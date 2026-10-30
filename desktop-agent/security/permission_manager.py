"""Layer 3 — command authorization.

This decides, for every request, three things:

* Is the command registered at all?  (unregistered => reject, always)
* What permission level does policy assign to it?
* Does this particular request, from this particular source, need a
  confirmation from the human before it may run?

Nothing else in the codebase is allowed to answer those questions, so there is
exactly one place to audit -- and exactly one place to change policy.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from config import Settings
from core.schemas import CommandRequest, CommandSource, PermissionLevel
from utils.logger import get_logger

log = get_logger("permissions")


@dataclass(frozen=True)
class PermissionDecision:
    allowed: bool
    level: PermissionLevel
    requires_confirmation: bool = False
    reason: str | None = None

    @property
    def denied(self) -> bool:
        return not self.allowed


class PermissionManager:
    """Policy engine backed by config/permissions.yaml."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        config: dict[str, Any] = settings.permissions_config or {}
        self._commands: dict[str, dict[str, Any]] = {
            str(k): dict(v or {}) for k, v in (config.get("commands") or {}).items()
        }
        policy = config.get("policy") or {}
        self._trusted_local = {
            CommandSource(str(s)) for s in (policy.get("trusted_local_sources") or [])
        }
        self._max_remote = PermissionLevel(str(policy.get("max_remote_permission") or "high"))
        self._confirm_high_always = bool(policy.get("confirm_high_always", True))
        self._confirm_medium_locally = bool(policy.get("confirm_medium_locally", False))
        self._locked_allow = {str(c) for c in (policy.get("allow_only_when_locked") or [])}
        self._locked = False  # emergency stop flag
        self._lock_reason = ""

    # -- emergency stop -----------------------------------------------------
    def lock(self, reason: str = "emergency stop") -> None:
        self._locked = True
        self._lock_reason = reason
        log.warning("agent locked: %s", reason)

    def unlock(self) -> None:
        self._locked = False
        self._lock_reason = ""

    @property
    def is_locked(self) -> bool:
        return self._locked

    # -- policy -------------------------------------------------------------
    def is_registered(self, command_name: str) -> bool:
        return command_name in self._commands

    def level_for(self, command_name: str) -> PermissionLevel:
        entry = self._commands.get(command_name) or {}
        try:
            return PermissionLevel(str(entry.get("permission") or "blocked"))
        except ValueError:
            return PermissionLevel.BLOCKED

    def evaluate(self, request: CommandRequest, *, registered: bool) -> PermissionDecision:
        name = request.name
        level = self.level_for(name)

        if not registered:
            return PermissionDecision(
                allowed=False,
                level=PermissionLevel.BLOCKED,
                reason=f"'{name}' is not a registered command.",
            )

        if level is PermissionLevel.BLOCKED:
            entry = self._commands.get(name) or {}
            return PermissionDecision(
                allowed=False,
                level=level,
                reason=str(
                    entry.get("reason")
                    or f"'{name}' is permanently blocked by policy."
                ),
            )

        if self._locked and name not in self._locked_allow:
            return PermissionDecision(
                allowed=False,
                level=level,
                reason=(
                    f"JARVIS is in locked mode ({self._lock_reason or 'emergency stop'}). "
                    "Only status and stop are allowed."
                ),
            )

        if not request.source.is_local and level.rank > self._max_remote.rank:
            return PermissionDecision(
                allowed=False,
                level=level,
                reason=(
                    f"Remote requests may not exceed '{self._max_remote.value}' "
                    f"permission; '{name}' is '{level.value}'."
                ),
            )

        requires_confirmation = self._needs_confirmation(name, level, request.source)
        return PermissionDecision(
            allowed=True, level=level, requires_confirmation=requires_confirmation
        )

    def _needs_confirmation(
        self, name: str, level: PermissionLevel, source: CommandSource
    ) -> bool:
        entry = self._commands.get(name) or {}
        explicit = entry.get("confirmation")
        if explicit is not None:
            return bool(explicit)
        if level is PermissionLevel.HIGH:
            return self._confirm_high_always
        if level is PermissionLevel.MEDIUM:
            if source not in self._trusted_local:
                return True
            return self._confirm_medium_locally
        return False
