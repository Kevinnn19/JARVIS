"""The agent: the one object every interface talks to.

    text/command -> CommandParser -> CommandValidator -> TaskExecutor
                                                         |
                                              TaskRegistry -> automation.*

``JarvisAgent`` is deliberately UI-agnostic. Phase 1 drives it from a terminal
loop; Phase 2 will drive it from the microphone, and Phase 4 from FastAPI -- all
through the same ``handle_text`` / ``handle`` methods. That is what keeps the
remote-control server from needing its own copy of the security logic.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from automation.app_controller import AppController
from automation.file_manager import FileManager
from automation.system_controller import SystemController
from config import Settings, load_settings
from core.command_parser import CommandParser
from core.event_bus import EventBus
from core.response_engine import ResponseEngine
from core.schemas import (
    CommandRequest,
    CommandResult,
    CommandSource,
    ExecutionStatus,
    PermissionLevel,
)
from core.task_executor import TaskExecutor
from core.task_registry import TaskRegistry
from security.command_validator import CommandValidator
from security.confirmation_manager import ConfirmationManager, Confirmer
from security.permission_manager import PermissionManager
from utils.logger import AuditLogger, get_logger

log = get_logger("agent")


@dataclass
class AgentSnapshot:
    name: str
    locked: bool
    dry_run: bool
    platform: str
    uptime_note: str
    commands: list[str]

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "locked": self.locked,
            "dry_run": self.dry_run,
            "platform": self.platform,
            "commands": self.commands,
        }


class JarvisAgent:
    def __init__(
        self,
        settings: Settings | None = None,
        *,
        config_dir: str | None = None,
        dry_run: bool | None = None,
        confirmer: Confirmer | None = None,
        speak: bool = False,
    ) -> None:
        if settings is None:
            settings = load_settings(config_dir, dry_run=bool(dry_run))
        self.settings = settings
        self.dry_run = settings.dry_run if dry_run is None else dry_run

        self.events = EventBus()
        self.audit = AuditLogger(settings.audit_path)
        self.apps = AppController(settings, dry_run=self.dry_run)
        self.files = FileManager(settings, dry_run=self.dry_run)
        self.system = SystemController(settings, dry_run=self.dry_run)

        self.registry = TaskRegistry(settings, self.apps, self.files, self.system)
        self.parser = CommandParser(settings)
        self.validator = CommandValidator(settings)
        self.permissions = PermissionManager(settings)
        self.confirmations = ConfirmationManager(settings.confirm_timeout_seconds)
        self.responses = ResponseEngine(agent_name=settings.agent_name, speak=speak)
        self.executor = TaskExecutor(
            settings,
            self.registry,
            self.permissions,
            self.confirmations,
            audit=self.audit,
            events=self.events,
            confirmer=confirmer,
        )
        self.audit.write(
            "agent.start",
            {
                "platform": settings.platform,
                "dry_run": self.dry_run,
                "commands": self.registry.names(),
                "config_dir": str(settings.config_dir),
            },
        )

    # -- entry points -------------------------------------------------------
    def handle_text(
        self,
        text: str,
        source: CommandSource = CommandSource.LOCAL_TYPED,
    ) -> CommandResult:
        parsed = self.parser.parse(text, source)
        if not parsed.ok or parsed.request is None:
            suggestions = "; ".join(parsed.suggestions[:3])
            message = parsed.error or "I didn't understand that."
            if suggestions:
                message = f"{message} Try: {suggestions}"
            self.audit.write(
                "parse_failed", {"text": text, "source": source.value, "error": parsed.error}
            )
            self.events.publish("command.parse_failed", text=text, error=parsed.error)
            return CommandResult(
                command_id="cmd_unparsed",
                name="<unparsed>",
                status=ExecutionStatus.PARSE_ERROR,
                message=message,
                permission=PermissionLevel.BLOCKED,
                details={"suggestions": parsed.suggestions, "raw_text": text},
            )

        validated = self.validator.validate(parsed.request)
        if not validated.ok or validated.request is None:
            self.audit.write(
                "validation_failed",
                {
                    "text": text,
                    "name": parsed.request.name,
                    "args": parsed.request.args,
                    "error": validated.error,
                },
            )
            return CommandResult(
                command_id=parsed.request.command_id,
                name=parsed.request.name,
                status=ExecutionStatus.REJECTED,
                message=validated.error or "That command's arguments were not valid.",
                permission=self.permissions.level_for(parsed.request.name),
                details={"stage": "validation"},
            )

        return self.executor.execute(validated.request)

    def handle(self, request: CommandRequest) -> CommandResult:
        """Entry point for non-text interfaces (voice, HTTP) once they exist."""
        validated = self.validator.validate(request)
        if not validated.ok or validated.request is None:
            return CommandResult(
                command_id=request.command_id,
                name=request.name,
                status=ExecutionStatus.REJECTED,
                message=validated.error or "Invalid command.",
                permission=self.permissions.level_for(request.name),
                details={"stage": "validation"},
            )
        return self.executor.execute(validated.request)

    # -- control ------------------------------------------------------------
    def lock(self, reason: str = "emergency stop") -> None:
        self.permissions.lock(reason)
        self.audit.write("agent.locked", {"reason": reason})
        self.events.publish("agent.locked", reason=reason)

    def unlock(self) -> None:
        self.permissions.unlock()
        self.audit.write("agent.unlocked", {})
        self.events.publish("agent.unlocked")

    def snapshot(self) -> AgentSnapshot:
        return AgentSnapshot(
            name=self.settings.agent_name,
            locked=self.permissions.is_locked,
            dry_run=self.dry_run,
            platform=self.settings.platform,
            uptime_note=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            commands=self.registry.names(),
        )
