"""Launching, verifying and closing applications.

Design rules that make this module safe and honest:

1. Only applications present in ``config/applications.yaml`` can be touched.
   The caller passes an allowlist *key*, never a raw command line.
2. Launch is verified: after spawning we poll the process table until a process
   from ``process_names`` appears, then we report success. If it never appears
   we report failure -- JARVIS never says "Chrome is open" because it sent a
   spawn request.
3. Close is graceful-then-forceful and also verified.
4. ``dry_run`` short-circuits before any spawn and says so explicitly.
"""

from __future__ import annotations

import os
import shlex
import subprocess
import time
from pathlib import Path
from typing import Callable, Iterable

import psutil

from automation.result import OperationResult
from config import AppSpec, Settings
from utils.helpers import is_windows, open_with_os, spawn_detached, which
from utils.logger import get_logger

log = get_logger("apps")


class AppController:
    def __init__(
        self,
        settings: Settings,
        *,
        dry_run: bool | None = None,
        platform: str | None = None,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        verify_timeout: float = 6.0,
        poll_interval: float = 0.25,
    ) -> None:
        self.settings = settings
        self.dry_run = settings.dry_run if dry_run is None else dry_run
        self.platform = platform or settings.platform
        self._clock = clock
        self._sleep = sleep
        self.verify_timeout = verify_timeout
        self.poll_interval = poll_interval
        self._alias_index = settings.alias_index()

    # -- allowlist ----------------------------------------------------------
    def resolve(self, application: str) -> AppSpec | None:
        """Map user text ("google chrome") to an allowlisted AppSpec."""
        key = " ".join(application.strip().lower().split())
        if key in self._alias_index:
            return self._alias_index[key]
        # tolerate a trailing ".exe" and plural/"app" suffixes
        for suffix in (".exe", " app", " application"):
            if key.endswith(suffix):
                trimmed = key[: -len(suffix)].strip()
                if trimmed in self._alias_index:
                    return self._alias_index[trimmed]
        return None

    def known_applications(self) -> list[AppSpec]:
        return sorted(self.settings.applications.values(), key=lambda a: a.display_name)

    # -- process inspection -------------------------------------------------
    def _process_names(self, spec: AppSpec) -> set[str]:
        names = {n.lower() for n in spec.processes_for(self.platform)}
        names.add(f"{spec.key.lower()}.exe")
        return names

    def running_processes(self, spec: AppSpec) -> list[psutil.Process]:
        wanted = self._process_names(spec)
        found: list[psutil.Process] = []
        for proc in psutil.process_iter(["name", "status"]):
            try:
                name = (proc.info.get("name") or "").lower()
                status = proc.info.get("status")
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
            # A terminated child whose parent has not reaped it shows up as a
            # zombie. It is not running, so it must not count as "still open".
            if status == psutil.STATUS_ZOMBIE:
                continue
            if name in wanted or name in {w.replace(".exe", "") for w in wanted}:
                found.append(proc)
        return found

    def is_running(self, spec: AppSpec) -> bool:
        return bool(self.running_processes(spec))

    def _wait_for(self, predicate: Callable[[], bool], timeout: float) -> bool:
        deadline = self._clock() + timeout
        while self._clock() < deadline:
            if predicate():
                return True
            self._sleep(self.poll_interval)
        return predicate()

    @staticmethod
    def _reap(pid: int) -> None:
        """Reap a child we spawned so it does not linger as a zombie."""
        if is_windows():
            return
        try:
            os.waitpid(pid, os.WNOHANG)
        except (ChildProcessError, OSError):
            pass

    # -- launching ----------------------------------------------------------
    def _candidate_argv(self, spec: AppSpec) -> list[list[str]]:
        """Turn config candidates into argv lists, most specific first."""
        out: list[list[str]] = []
        for raw in spec.launchers_for(self.platform):
            expanded = os.path.expandvars(os.path.expanduser(raw))
            if os.path.isfile(expanded):
                out.append([expanded])
                continue
            resolved = which(expanded)
            if resolved:
                out.append([resolved])
                continue
            head, _, tail = expanded.partition(" ")
            head_resolved = which(head) if head else None
            if head_resolved and tail:
                try:
                    out.append([head_resolved, *shlex.split(tail)])
                except ValueError:
                    out.append([head_resolved, tail])
                continue
            if head_resolved:
                out.append([head_resolved])
        return out

    def launch(self, spec: AppSpec, extra_args: Iterable[str] = ()) -> OperationResult:
        display = spec.display_name
        argv_candidates = self._candidate_argv(spec)

        if self.dry_run:
            if self.is_running(spec):
                return OperationResult.simulated_result(
                    f"{display} is already running (dry run: nothing to do)",
                    already_running=True,
                )
            return OperationResult.simulated_result(
                f"[dry run] Would launch {display}",
                would_launch=argv_candidates,
                platform=self.platform,
            )

        if self.is_running(spec):
            return OperationResult.success(
                f"{display} is already running.", already_running=True
            )

        if not argv_candidates:
            return OperationResult.failure(
                f"I don't know how to launch {display} on this computer. "
                f"Add a launcher path for '{spec.key}' in config/applications.yaml.",
                tried=list(spec.launchers_for(self.platform)),
            )

        errors: list[str] = []
        for argv in argv_candidates:
            full = [*argv, *extra_args]
            try:
                spawn_detached(full)
            except OSError as exc:
                errors.append(f"{argv[0]}: {exc}")
                continue

            if self._wait_for(lambda: self.is_running(spec), self.verify_timeout):
                return OperationResult.success(
                    f"{display} is now open.",
                    launched_with=full,
                    processes=[p.pid for p in self.running_processes(spec)],
                )
            errors.append(f"{argv[0]}: launched but no {display} process appeared")

        return OperationResult.failure(
            f"I tried to start {display} but it did not come up. {errors[-1] if errors else ''}".strip(),
            attempts=errors,
        )

    # -- closing ------------------------------------------------------------
    def close(self, spec: AppSpec) -> OperationResult:
        display = spec.display_name
        processes = self.running_processes(spec)

        if self.dry_run:
            if not processes:
                return OperationResult.simulated_result(
                    f"[dry run] {display} is not running; would report that honestly",
                    running=0,
                )
            return OperationResult.simulated_result(
                f"[dry run] Would close {display} ({len(processes)} process(es))",
                running=len(processes),
            )

        if not processes:
            return OperationResult.failure(
                f"{display} is not running, so there was nothing to close.",
                running=0,
            )

        terminated: list[int] = []
        denied: list[int] = []
        for proc in processes:
            try:
                proc.terminate()  # graceful: lets the app save state
                terminated.append(proc.pid)
            except psutil.AccessDenied:
                denied.append(proc.pid)
            except psutil.NoSuchProcess:
                pass

        def gone() -> bool:
            for pid in terminated:
                self._reap(pid)
            return not self.running_processes(spec)

        if not self._wait_for(gone, 5.0):
            # escalate only for processes we are allowed to touch
            for proc in self.running_processes(spec):
                try:
                    proc.kill()
                except (psutil.AccessDenied, psutil.NoSuchProcess):
                    pass
            self._wait_for(gone, 3.0)

        if gone():
            return OperationResult.success(
                f"{display} is closed.",
                pids=terminated,
            )
        return OperationResult.failure(
            f"{display} is still running; Windows refused to close it "
            f"(access denied for pid(s) {denied or 'unknown'}).",
            pids=terminated,
        )

    # -- folders ------------------------------------------------------------
    def open_folder_path(self, path: Path) -> OperationResult:
        if self.dry_run:
            return OperationResult.simulated_result(
                f"[dry run] Would open folder {path}", path=str(path)
            )
        if not path.exists():
            return OperationResult.failure(f"The folder {path} does not exist.", path=str(path))
        try:
            open_with_os(path)
        except OSError as exc:
            return OperationResult.failure(
                f"I could not open {path}: {exc}", path=str(path)
            )
        return OperationResult.success(f"Opened {path.name}.", path=str(path), verified=False)


__all__ = ["AppController", "OperationResult", "is_windows", "subprocess"]
