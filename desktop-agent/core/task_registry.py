"""The command registry — the complete list of things JARVIS can do.

Every entry binds a *command name* to one plain Python function. There is no
dynamic dispatch on user text, no ``eval``, no shell string and no plugin
loading. If a capability is not registered here, it does not exist.

This is the direct implementation of the rule from the blueprint:

    "JARVIS should never be able to do something that isn't explicitly
     registered and authorized."
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from automation.app_controller import AppController
from automation.file_manager import FileManager
from automation.result import OperationResult
from automation.system_controller import SystemController
from config import Settings
from core.schemas import ARGS_MODELS
from utils.logger import get_logger

log = get_logger("registry")

Handler = Callable[[dict[str, Any]], OperationResult]


@dataclass(frozen=True)
class RegisteredCommand:
    name: str
    description: str
    handler: Handler
    examples: list[str] = field(default_factory=list)
    phase: int = 1


class TaskRegistry:
    def __init__(
        self,
        settings: Settings,
        apps: AppController,
        files: FileManager,
        system: SystemController,
    ) -> None:
        self.settings = settings
        self.apps = apps
        self.files = files
        self.system = system
        self._commands: dict[str, RegisteredCommand] = {}
        self._register_all()

    # -- registration -------------------------------------------------------
    def register(self, command: RegisteredCommand) -> None:
        if command.name not in ARGS_MODELS:
            raise ValueError(f"'{command.name}' has no argument schema in schemas.py")
        self._commands[command.name] = command

    def _register_all(self) -> None:
        self.register(
            RegisteredCommand(
                name="open_application",
                description="Open an approved application (Chrome, Notepad, VS Code, ...).",
                handler=self._open_application,
                examples=["open chrome", "launch notepad", "start vs code"],
            )
        )
        self.register(
            RegisteredCommand(
                name="close_application",
                description="Close a running application.",
                handler=self._close_application,
                examples=["close chrome", "quit notepad"],
            )
        )
        self.register(
            RegisteredCommand(
                name="open_folder",
                description="Open a user folder (Downloads, Documents, Desktop, ...).",
                handler=self._open_folder,
                examples=["open downloads", "show documents"],
            )
        )
        self.register(
            RegisteredCommand(
                name="search_files",
                description="Search for files by name inside your allowed folders.",
                handler=self._search_files,
                examples=["search for invoice", "find report in downloads"],
            )
        )
        self.register(
            RegisteredCommand(
                name="set_volume",
                description="Set the system output volume to a percentage.",
                handler=self._set_volume,
                examples=["set volume to 30", "mute"],
            )
        )
        self.register(
            RegisteredCommand(
                name="screenshot",
                description="Take a screenshot and save it to Pictures/JARVIS-Screenshots.",
                handler=lambda args: self.system.screenshot(),
                examples=["take a screenshot"],
            )
        )
        self.register(
            RegisteredCommand(
                name="status",
                description="Report the health and uptime of this machine.",
                handler=lambda args: self.system.status(),
                examples=["status", "are you there"],
            )
        )
        self.register(
            RegisteredCommand(
                name="help",
                description="List everything JARVIS can currently do.",
                handler=lambda args: OperationResult.success(self.help_text()),
                examples=["help", "what can you do"],
            )
        )
        self.register(
            RegisteredCommand(
                name="stop",
                description="Stop the current activity / go back to sleep.",
                handler=lambda args: OperationResult.success(
                    "Stopping. Say or type my name when you need me."
                ),
                examples=["stop", "never mind"],
            )
        )

    # -- handlers -----------------------------------------------------------
    def _spec(self, key: str):
        spec = self.settings.applications.get(key)
        if spec is None:  # validator guarantees this, but defence in depth
            raise KeyError(f"application '{key}' is not allowlisted")
        return spec

    def _open_application(self, args: dict[str, Any]) -> OperationResult:
        spec = self._spec(str(args["application"]))
        return self.apps.launch(spec, extra_args=args.get("arguments") or ())

    def _close_application(self, args: dict[str, Any]) -> OperationResult:
        spec = self._spec(str(args["application"]))
        return self.apps.close(spec)

    def _open_folder(self, args: dict[str, Any]) -> OperationResult:
        return self.apps.open_folder_path(Path(str(args["folder"])))

    def _search_files(self, args: dict[str, Any]) -> OperationResult:
        report = self.files.search(
            query=str(args["query"]),
            root=args.get("root"),
            limit=int(args.get("limit") or 10),
        )
        if report.count == 0:
            scope = ", ".join(Path(p).name for p in report.roots) or "your folders"
            note = " (search stopped early)" if report.timed_out else ""
            return OperationResult.failure(
                f"No files matching '{report.query}' in {scope}{note}.",
                query=report.query,
                roots=report.roots,
                scanned_dirs=report.scanned_dirs,
            )
        names = [p.name for p in report.matches[:5]]
        more = "" if report.count <= 5 else f" (+{report.count - 5} more)"
        return OperationResult.success(
            f"Found {report.count} file(s) matching '{report.query}': "
            + ", ".join(names)
            + more,
            query=report.query,
            matches=[str(p) for p in report.matches],
            truncated=report.truncated or report.timed_out,
        )

    def _set_volume(self, args: dict[str, Any]) -> OperationResult:
        return self.system.set_volume(int(args["level"]))

    # -- introspection ------------------------------------------------------
    def get(self, name: str) -> RegisteredCommand | None:
        return self._commands.get(name)

    def names(self) -> list[str]:
        return sorted(self._commands)

    def __contains__(self, name: object) -> bool:
        return name in self._commands

    def examples(self) -> list[str]:
        out: list[str] = []
        for command in self._commands.values():
            out.extend(command.examples)
        return out

    def help_text(self) -> str:
        lines = [f"{self.settings.agent_name} can do the following right now:"]
        for command in sorted(self._commands.values(), key=lambda c: c.name):
            lines.append(f"  - {command.description}")
        lines.append("Examples: " + "; ".join(self.examples()[:8]))
        return "\n".join(lines)

