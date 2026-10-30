"""Runs an authorized command and reports the truth about the outcome.

Responsibilities, in order:

1. refuse anything not in the registry,
2. ask the PermissionManager for a decision (denied -> REJECTED, no handler runs),
3. honour confirmation requirements (-> PENDING_CONFIRMATION),
4. run the handler under a hard timeout,
5. translate the handler's ``OperationResult`` into a ``CommandResult`` whose
   status distinguishes real success from dry-run simulation,
6. publish events and write the audit record.
"""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from datetime import datetime, timezone
from typing import Any

from automation.result import OperationResult
from config import Settings
from core.event_bus import EventBus
from core.schemas import (
    CommandRequest,
    CommandResult,
    ExecutionStatus,
    PermissionLevel,
)
from core.task_registry import TaskRegistry
from security.confirmation_manager import ConfirmationManager, Confirmer
from security.permission_manager import PermissionManager
from utils.logger import AuditLogger, get_logger

log = get_logger("executor")


class TaskExecutor:
    def __init__(
        self,
        settings: Settings,
        registry: TaskRegistry,
        permissions: PermissionManager,
        confirmations: ConfirmationManager | None = None,
        *,
        audit: AuditLogger | None = None,
        events: EventBus | None = None,
        confirmer: Confirmer | None = None,
    ) -> None:
        self.settings = settings
        self.registry = registry
        self.permissions = permissions
        self.confirmations = confirmations or ConfirmationManager(
            settings.confirm_timeout_seconds
        )
        self.audit = audit
        self.events = events or EventBus()
        self.confirmer = confirmer
        self._pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="jarvis-task")

    # -- public -------------------------------------------------------------
    def execute(self, request: CommandRequest) -> CommandResult:
        started_wall = datetime.now(timezone.utc)
        started = time.perf_counter()
        registered = request.name in self.registry
        decision = self.permissions.evaluate(request, registered=registered)

        if decision.denied:
            return self._finish(
                request,
                started_wall,
                started,
                status=ExecutionStatus.REJECTED,
                message=decision.reason or "This command is not permitted.",
                permission=decision.level,
                details={"policy": "denied"},
            )

        if decision.requires_confirmation:
            ticket = self.confirmations.request(
                request, summary=_summarise(request.name, request.args)
            )
            approved = None
            if self.confirmer is not None and request.source.is_local:
                approved = self.confirmer.ask(ticket)
                self.confirmations.resolve(ticket.ticket_id, bool(approved))
            if approved is not True:
                reason = (
                    "Confirmation was declined."
                    if approved is False
                    else "This action needs your confirmation before I run it."
                )
                return self._finish(
                    request,
                    started_wall,
                    started,
                    status=ExecutionStatus.PENDING_CONFIRMATION,
                    message=reason,
                    permission=decision.level,
                    details={"ticket_id": ticket.ticket_id, "approved": approved},
                )

        command = self.registry.get(request.name)
        if command is None:  # pragma: no cover - guarded by `registered`
            return self._finish(
                request, started_wall, started,
                status=ExecutionStatus.REJECTED,
                message="Unknown command.",
                permission=PermissionLevel.BLOCKED,
            )

        future = self._pool.submit(command.handler, request.args)
        try:
            outcome: OperationResult = future.result(timeout=self.settings.command_timeout_seconds)
        except FutureTimeout:
            future.cancel()
            return self._finish(
                request, started_wall, started,
                status=ExecutionStatus.TIMEOUT,
                message=(
                    f"{request.name} did not finish within "
                    f"{self.settings.command_timeout_seconds:.0f}s; I stopped waiting."
                ),
                permission=decision.level,
                details={"timeout_seconds": self.settings.command_timeout_seconds},
            )
        except Exception as exc:  # handler bug -> report, never crash the agent
            log.exception("handler for %s raised", request.name)
            return self._finish(
                request, started_wall, started,
                status=ExecutionStatus.FAILURE,
                message=f"{request.name} failed: {type(exc).__name__}: {exc}",
                permission=decision.level,
                details={"exception": type(exc).__name__},
            )

        status = _status_from(outcome)
        return self._finish(
            request,
            started_wall,
            started,
            status=status,
            message=outcome.message,
            permission=decision.level,
            details={**outcome.details, "verified": outcome.verified, "simulated": outcome.simulated},
        )

    # -- internals ----------------------------------------------------------
    def _finish(
        self,
        request: CommandRequest,
        started_wall: datetime,
        started: float,
        *,
        status: ExecutionStatus,
        message: str,
        permission: PermissionLevel,
        details: dict[str, Any] | None = None,
    ) -> CommandResult:
        finished = datetime.now(timezone.utc)
        result = CommandResult(
            command_id=request.command_id,
            name=request.name,
            status=status,
            message=message,
            permission=permission,
            details=details or {},
            started_at=started_wall,
            finished_at=finished,
            duration_ms=int((time.perf_counter() - started) * 1000),
        )
        if self.audit is not None:
            self.audit.write(
                "command",
                {
                    "command_id": result.command_id,
                    "name": result.name,
                    "args": request.args,
                    "raw_text": request.raw_text,
                    "source": request.source.value,
                    "status": result.status.value,
                    "permission": result.permission.value,
                    "message": result.message,
                    "duration_ms": result.duration_ms,
                    "details": result.details,
                },
            )
        self.events.publish(
            "command.finished",
            command_id=result.command_id,
            name=result.name,
            status=result.status.value,
            message=result.message,
        )
        return result


def _status_from(outcome: OperationResult) -> ExecutionStatus:
    if outcome.simulated:
        return ExecutionStatus.DRY_RUN
    return ExecutionStatus.SUCCESS if outcome.ok else ExecutionStatus.FAILURE


def _summarise(name: str, args: dict[str, Any]) -> str:
    if not args:
        return name.replace("_", " ")
    pairs = ", ".join(f"{k}={v}" for k, v in args.items())
    return f"{name.replace('_', ' ')} ({pairs})"
