"""Read-only file operations (Phase 1: search + open folder).

Destructive operations (delete/rename/move) arrive in Phase 3 together with the
confirmation manager; they are deliberately absent here so there is no code path
in v0.1 that can modify or remove a user file.

Every search is bounded three ways -- allowed roots, max depth, and a wall-clock
deadline -- so a vague query can never freeze the assistant on a large drive.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

from automation.result import OperationResult
from config import Settings
from utils.helpers import user_folder
from utils.logger import get_logger

log = get_logger("files")

SKIP_DIR_NAMES = {
    "$recycle.bin",
    "system volume information",
    "node_modules",
    ".git",
    "__pycache__",
    "appdata",
    "windows",
    "program files",
    "program files (x86)",
    "programdata",
    "venv",
    ".venv",
}


@dataclass
class SearchReport:
    query: str
    roots: list[str]
    matches: list[Path] = field(default_factory=list)
    truncated: bool = False
    timed_out: bool = False
    scanned_dirs: int = 0

    @property
    def count(self) -> int:
        return len(self.matches)


class FileManager:
    def __init__(self, settings: Settings, *, dry_run: bool | None = None) -> None:
        self.settings = settings
        self.dry_run = settings.dry_run if dry_run is None else dry_run
        self.policy = settings.path_policy

    # -- folder helpers -----------------------------------------------------
    def resolve_folder(self, folder: str) -> Path | None:
        """Map a friendly folder name to an existing path inside allowed roots.

        Accepts both "downloads" and an absolute path, provided the path is
        inside an allowed root. Returns None when unusable.
        """
        named = user_folder(folder, self.policy.home_dir)
        if named is not None:
            return named if self.is_allowed(named) else None

        candidate = Path(folder).expanduser()
        if candidate.exists() and self.is_allowed(candidate):
            return candidate
        return None

    def is_allowed(self, path: Path) -> bool:
        try:
            resolved = path.expanduser().resolve()
        except OSError:
            return False
        if self._is_protected(resolved):
            return False
        for root in self.policy.allowed_roots:
            try:
                root_resolved = root.expanduser().resolve()
            except OSError:
                continue
            if resolved == root_resolved or root_resolved in resolved.parents:
                return True
        return False

    def _is_protected(self, resolved: Path) -> bool:
        for protected in self.policy.protected_paths:
            try:
                p = protected.expanduser().resolve()
            except OSError:
                continue
            if resolved == p or p in resolved.parents:
                return True
        return False

    def open_folder(self, folder: str, opener) -> OperationResult:
        """``opener`` is injected (AppController.open_folder_path) so this module
        has no OS-launch code and stays trivially testable."""
        path = self.resolve_folder(folder)
        if path is None:
            return OperationResult.failure(
                f"I can't open '{folder}' -- it doesn't exist or is outside the "
                f"folders you allow me to use.",
                folder=folder,
            )
        return opener(path)

    # -- search -------------------------------------------------------------
    def search(
        self,
        query: str,
        root: str | None = None,
        limit: int = 10,
        time_budget_seconds: float = 8.0,
    ) -> SearchReport:
        needle = query.strip().lower()
        roots = self._search_roots(root)
        report = SearchReport(query=query, roots=[str(r) for r in roots])
        deadline = time.monotonic() + time_budget_seconds
        max_results = min(limit, self.policy.search_max_results) if limit else self.policy.search_max_results

        for base in roots:
            if report.truncated or report.timed_out:
                break
            for path in self._walk(base, deadline):
                report.scanned_dirs += 1
                if needle in path.name.lower():
                    report.matches.append(path)
                    if len(report.matches) >= max_results:
                        report.truncated = True
                        break
                if time.monotonic() > deadline:
                    report.timed_out = True
                    break
        return report

    def _search_roots(self, root: str | None) -> list[Path]:
        if root:
            named = self.resolve_folder(root)
            return [named] if named else []
        roots: list[Path] = []
        for candidate in self.policy.default_search_roots:
            path = candidate.expanduser()
            if path.exists() and self.is_allowed(path):
                roots.append(path)
        if not roots:  # fall back to the first allowed root that exists
            for candidate in self.policy.allowed_roots:
                path = candidate.expanduser()
                if path.exists() and self.is_allowed(path):
                    roots.append(path)
                    break
        return roots

    def _walk(self, base: Path, deadline: float) -> Iterable[Path]:
        max_depth = self.policy.search_max_depth
        base_depth = len(base.parts)
        stack: list[Path] = [base]
        while stack:
            if time.monotonic() > deadline:
                return
            current = stack.pop()
            try:
                for entry in current.iterdir():
                    if entry.is_symlink():
                        continue
                    if entry.is_dir():
                        if entry.name.lower() in SKIP_DIR_NAMES:
                            continue
                        if len(entry.parts) - base_depth >= max_depth:
                            continue
                        stack.append(entry)
                    else:
                        yield entry
            except (PermissionError, OSError):
                continue


__all__ = ["FileManager", "SearchReport"]
