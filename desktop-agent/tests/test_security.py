"""Security-layer tests: the parts that must never regress.

Covers the five layers that exist in Phase 1:
  * registry purity (nothing runs that is not registered),
  * permission policy (levels, blocked commands, remote cap, lock/emergency stop),
  * confirmation gate (high/medium risk never runs unapproved),
  * argument validation (no arbitrary paths, no arbitrary apps),
  * audit trail (every attempt leaves a record).
"""

from __future__ import annotations

import dataclasses
import json

import pytest

from core.schemas import (
    CommandRequest,
    CommandSource,
    ExecutionStatus,
    PermissionLevel,
)
from core.task_executor import TaskExecutor
from core.task_registry import RegisteredCommand
from automation.result import OperationResult
from security.permission_manager import PermissionManager


# ---------------------------------------------------------------------------
# Registry purity
# ---------------------------------------------------------------------------
def test_registry_is_the_only_surface(agent):
    assert set(agent.registry.names()) == {
        "open_application",
        "close_application",
        "open_folder",
        "search_files",
        "set_volume",
        "screenshot",
        "status",
        "help",
        "stop",
    }


def test_unregistered_command_cannot_execute(agent):
    result = agent.handle(CommandRequest(name="execute_shell_command", args={"cmd": "rm -rf /"}))
    assert result.status is ExecutionStatus.REJECTED
    assert result.details.get("stage") == "validation"


def test_blocked_command_is_refused_with_reason(agent):
    decision = agent.permissions.evaluate(
        CommandRequest(name="execute_shell_command"), registered=True
    )
    assert decision.denied
    assert decision.level is PermissionLevel.BLOCKED
    assert "disabled by design" in (decision.reason or "")


def test_extras_in_args_are_rejected(agent):
    result = agent.handle(
        CommandRequest(name="open_application", args={"application": "chrome", "shell": "calc"})
    )
    assert result.status is ExecutionStatus.REJECTED


def test_overlong_or_empty_args_are_rejected(agent):
    assert agent.handle(CommandRequest(name="open_application", args={"application": ""})).status is ExecutionStatus.REJECTED
    assert agent.handle(CommandRequest(name="search_files", args={"query": "*"})).status is ExecutionStatus.REJECTED
    assert agent.handle(CommandRequest(name="set_volume", args={"level": 500})).status is ExecutionStatus.REJECTED


# ---------------------------------------------------------------------------
# Permission policy
# ---------------------------------------------------------------------------
def test_high_risk_requires_confirmation(settings):
    pm = PermissionManager(settings)
    decision = pm.evaluate(CommandRequest(name="delete_file", args={"path": "x"}), registered=True)
    assert decision.allowed
    assert decision.level is PermissionLevel.HIGH
    assert decision.requires_confirmation


def test_medium_remote_requires_confirmation(settings):
    """medium risk: fine locally, confirmed from the phone."""
    pm = PermissionManager(settings)
    local = pm.evaluate(CommandRequest(name="lock_workstation", source=CommandSource.LOCAL_TYPED), registered=True)
    remote = pm.evaluate(CommandRequest(name="lock_workstation", source=CommandSource.REMOTE_API), registered=True)
    assert local.requires_confirmation is False
    assert remote.requires_confirmation is True


def test_explicit_confirmation_flag_overrides_level(settings):
    """rename_file is medium but pinned to always-confirm in permissions.yaml."""
    pm = PermissionManager(settings)
    decision = pm.evaluate(CommandRequest(name="rename_file", source=CommandSource.LOCAL_TYPED), registered=True)
    assert decision.requires_confirmation is True


def test_remote_cannot_exceed_policy_ceiling(settings):
    perms = json.loads(json.dumps(settings.permissions_config))
    perms["policy"]["max_remote_permission"] = "low"
    tightened = dataclasses.replace(settings, permissions_config=perms)
    pm = PermissionManager(tightened)
    decision = pm.evaluate(
        CommandRequest(name="shutdown_system", source=CommandSource.REMOTE_API), registered=True
    )
    assert decision.denied
    assert "may not exceed" in (decision.reason or "")


def test_low_risk_does_not_need_confirmation(settings):
    pm = PermissionManager(settings)
    decision = pm.evaluate(CommandRequest(name="open_application"), registered=True)
    assert decision.allowed and not decision.requires_confirmation


# ---------------------------------------------------------------------------
# Emergency stop / locked mode
# ---------------------------------------------------------------------------
def test_locked_mode_blocks_everything_but_status_and_stop(agent):
    agent.lock("test")
    blocked = agent.handle_text("open chrome")
    allowed = agent.handle_text("status")
    stopped = agent.handle_text("stop")
    agent.unlock()

    assert blocked.status is ExecutionStatus.REJECTED
    assert "locked" in blocked.message.lower()
    assert allowed.status is ExecutionStatus.SUCCESS
    assert stopped.status is ExecutionStatus.SUCCESS


def test_lock_survives_parse_of_unrelated_commands(agent):
    agent.lock()
    try:
        for text in ("help", "set volume to 10", "search for invoice"):
            assert agent.handle_text(text).status is ExecutionStatus.REJECTED
    finally:
        agent.unlock()


# ---------------------------------------------------------------------------
# Confirmation gate
# ---------------------------------------------------------------------------
class _DenyAll:
    def ask(self, ticket):
        return False


class _ApproveAll:
    def ask(self, ticket):
        return True


def _executor_with(settings, agent, handler, confirmer):
    registry = agent.registry
    registry.register(
        RegisteredCommand(name="status", description="test", handler=handler)
    )
    return TaskExecutor(
        settings,
        registry,
        agent.permissions,
        agent.confirmations,
        audit=agent.audit,
        events=agent.events,
        confirmer=confirmer,
    )


def test_pending_confirmation_does_not_run_handler(settings, agent):
    from security.confirmation_manager import ConfirmationManager

    perms = json.loads(json.dumps(settings.permissions_config))
    perms["commands"]["status"] = {"permission": "high", "confirmation": True}
    strict = dataclasses.replace(settings, permissions_config=perms)
    called: list[int] = []

    registry = agent.registry
    registry.register(
        RegisteredCommand(
            name="status",
            description="test",
            handler=lambda args: (called.append(1), OperationResult.success("ran"))[1],
        )
    )
    executor = TaskExecutor(
        strict,
        registry,
        PermissionManager(strict),
        ConfirmationManager(30),
        audit=agent.audit,
        confirmer=_DenyAll(),
    )
    result = executor.execute(CommandRequest(name="status"))
    assert result.status is ExecutionStatus.PENDING_CONFIRMATION
    assert called == []


def test_timeout_is_reported_not_hung(settings, agent):
    import time

    slow_settings = dataclasses.replace(settings, command_timeout_seconds=0.2)
    executor = _executor_with(
        slow_settings,
        agent,
        lambda args: (time.sleep(1.5), OperationResult.success("late"))[1],
        None,
    )
    result = executor.execute(CommandRequest(name="status"))
    assert result.status is ExecutionStatus.TIMEOUT


def test_handler_exception_becomes_failure(settings, agent):
    def boom(args):
        raise RuntimeError("driver exploded")

    executor = _executor_with(settings, agent, boom, None)
    result = executor.execute(CommandRequest(name="status"))
    assert result.status is ExecutionStatus.FAILURE
    assert "driver exploded" in result.message


# ---------------------------------------------------------------------------
# Audit trail
# ---------------------------------------------------------------------------
def test_every_attempt_is_audited(agent, settings):
    agent.handle_text("open chrome")          # parsed, executed
    agent.handle_text("nonsense phrase")      # parse failure
    agent.handle_text("open winrar")          # validation failure

    records = agent.audit.tail(50)
    kinds = {record["event"] for record in records}
    assert {"command", "parse_failed", "validation_failed"} <= kinds
    assert settings.audit_path.exists()

    # no plaintext secret keys are ever written
    raw = settings.audit_path.read_text(encoding="utf-8")
    assert "password" not in raw.lower()
