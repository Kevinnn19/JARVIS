"""Small cross-platform helpers shared by the automation modules.

Nothing here decides *whether* an action is allowed — that belongs to the
security layer. These helpers only make "how do I talk to this OS" boring.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

from config import expand


def is_windows() -> bool:
    return sys.platform.startswith("win")


def is_macos() -> bool:
    return sys.platform == "darwin"


def is_linux() -> bool:
    return sys.platform.startswith("linux")


def which(command: str) -> str | None:
    """shutil.which that tolerates an absolute path that already exists."""
    if not command:
        return None
    if os.path.isabs(command) and Path(command).exists():
        return command
    return shutil.which(command)


def spawn_detached(argv: list[str]) -> subprocess.Popen | None:
    """Start a GUI program without blocking the agent."""
    kwargs: dict[str, object] = {
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
        "close_fds": True,
    }
    if is_windows():
        # DETACHED_PROCESS so the child survives the parent and does not spawn
        # a console window.
        kwargs["creationflags"] = 0x00000008 | 0x00000200
    else:
        kwargs["start_new_session"] = True
    return subprocess.Popen(argv, **kwargs)


def open_with_os(path: Path) -> None:
    """Ask the desktop shell to open a file/folder (Explorer on Windows)."""
    target = str(path)
    if is_windows():
        os.startfile(target)  # type: ignore[attr-defined]
    elif is_macos():
        subprocess.Popen(["open", target])
    else:
        subprocess.Popen(
            ["xdg-open", target],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )


def user_folder(folder: str, home: Path | None = None) -> Path | None:
    """Resolve a friendly folder name to a real path under the user profile.

    ``home`` comes from config (``paths.home``) rather than being hardcoded to
    Path.home(): that keeps the agent testable and lets a user relocate the
    scope without touching code. Returns None when the folder does not exist, so
    callers can report "not found" honestly instead of opening the wrong place.
    """
    mapping = {
        "home": "~",
        "downloads": "~/Downloads",
        "documents": "~/Documents",
        "desktop": "~/Desktop",
        "pictures": "~/Pictures",
        "music": "~/Music",
        "videos": "~/Videos",
    }
    key = folder.strip().lower().replace(" ", "")
    template = mapping.get(key)
    if template is None:
        return None
    if home is not None:
        suffix = template[2:] if template.startswith("~/") else ""
        path = home / suffix if suffix else home
    else:
        path = expand(template)
    return path if path.exists() else None


def human_duration(ms: float) -> str:
    if ms < 1000:
        return f"{int(ms)} ms"
    return f"{ms / 1000:.1f} s"
