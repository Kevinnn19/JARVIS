"""System-level operations: volume, screenshots, machine status.

Phase 1 intentionally implements only non-destructive system actions. Shutdown,
restart and lock are declared in permissions.yaml but have no handler yet -- the
executor reports "not implemented" rather than doing something risky.

Optional dependencies (pycaw for real Windows volume control, pyautogui for
screenshots) are imported lazily. If they are missing the controller returns an
honest failure with an install hint instead of pretending it worked.
"""

from __future__ import annotations

import platform
import shutil
import socket
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import psutil

from automation.result import OperationResult
from config import Settings
from utils.logger import get_logger

log = get_logger("system")


class SystemController:
    def __init__(self, settings: Settings, *, dry_run: bool | None = None) -> None:
        self.settings = settings
        self.dry_run = settings.dry_run if dry_run is None else dry_run
        self._volume_before: int | None = None

    # -- volume -------------------------------------------------------------
    def set_volume(self, level: int) -> OperationResult:
        level = max(0, min(100, int(level)))
        if self.dry_run:
            return OperationResult.simulated_result(
                f"[dry run] Would set the volume to {level}%", level=level
            )

        if self.settings.platform != "windows":
            return OperationResult.failure(
                "Volume control is implemented for Windows only in Phase 1 "
                f"(this machine reports '{self.settings.platform}').",
                level=level,
            )

        try:
            from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume  # type: ignore
            from comtypes import CLSCTX_ALL  # type: ignore
        except ImportError:
            return OperationResult.failure(
                "Volume control needs the 'pycaw' package. Install it with: "
                "pip install pycaw comtypes",
                level=level,
            )

        try:
            devices = AudioUtilities.GetSpeakers()
            interface = devices.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
            volume = interface.QueryInterface(IAudioEndpointVolume)
            self._volume_before = int(round(volume.GetMasterVolumeLevelScalar() * 100))
            volume.SetMasterVolumeLevelScalar(level / 100.0, None)
            actual = int(round(volume.GetMasterVolumeLevelScalar() * 100))
        except Exception as exc:  # pragma: no cover - Windows-only path
            return OperationResult.failure(f"Windows refused the volume change: {exc}")

        if abs(actual - level) > 2:
            return OperationResult.failure(
                f"I asked for {level}% but the mixer reports {actual}%.", level=actual
            )
        return OperationResult.success(
            f"Volume set to {actual}%.", level=actual, previous=self._volume_before
        )

    def get_volume(self) -> int | None:  # pragma: no cover - Windows-only path
        if self.settings.platform != "windows":
            return None
        try:
            from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume  # type: ignore
            from comtypes import CLSCTX_ALL  # type: ignore

            devices = AudioUtilities.GetSpeakers()
            interface = devices.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
            volume = interface.QueryInterface(IAudioEndpointVolume)
            return int(round(volume.GetMasterVolumeLevelScalar() * 100))
        except Exception:
            return None

    # -- screenshot ---------------------------------------------------------
    def screenshot(self) -> OperationResult:
        target_dir = Path.home() / "Pictures" / "JARVIS-Screenshots"
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        target = target_dir / f"jarvis-{stamp}.png"

        if self.dry_run:
            return OperationResult.simulated_result(
                f"[dry run] Would save a screenshot to {target}", path=str(target)
            )

        try:
            import pyautogui  # type: ignore
        except Exception:
            return OperationResult.failure(
                "Screenshots need 'pyautogui' (and Pillow). Install with: "
                "pip install pyautogui pillow",
            )

        try:
            target_dir.mkdir(parents=True, exist_ok=True)
            image = pyautogui.screenshot()
            image.save(target)
        except Exception as exc:
            return OperationResult.failure(
                f"The screen capture failed: {exc} "
                "(on a locked or headless session Windows blocks capture)."
            )

        if not target.exists() or target.stat().st_size == 0:
            return OperationResult.failure("The screenshot file was not written.")
        return OperationResult.success(
            f"Screenshot saved to {target.name}.",
            path=str(target),
            bytes=target.stat().st_size,
        )

    # -- status -------------------------------------------------------------
    def status(self) -> OperationResult:
        boot = psutil.boot_time()
        uptime_seconds = max(0.0, time.time() - boot)
        battery = psutil.sensors_battery()
        details = {
            "hostname": socket.gethostname(),
            "os": f"{platform.system()} {platform.release()}",
            "platform": self.settings.platform,
            "python": platform.python_version(),
            "uptime_seconds": int(uptime_seconds),
            "uptime_human": _humanise(uptime_seconds),
            "cpu_percent": psutil.cpu_percent(interval=0.15),
            "memory_percent": psutil.virtual_memory().percent,
            "disk_free_gb": round(shutil.disk_usage(Path.home()).free / 1e9, 1),
            "battery_percent": int(battery.percent) if battery else None,
            "on_ac_power": bool(battery.power_plugged) if battery else None,
            "dry_run": self.dry_run,
            "audit_log": str(self.settings.audit_path),
        }
        summary = (
            f"{details['hostname']} is up {details['uptime_human']}, "
            f"CPU {details['cpu_percent']}%, memory {details['memory_percent']}%"
        )
        if details["battery_percent"] is not None:
            summary += (
                f", battery {details['battery_percent']}%"
                f" ({'charging' if details['on_ac_power'] else 'on battery'})"
            )
        return OperationResult.success(summary + ".", **details)


def _humanise(seconds: float) -> str:
    seconds = int(seconds)
    days, rem = divmod(seconds, 86400)
    hours, rem = divmod(rem, 3600)
    minutes = rem // 60
    parts = []
    if days:
        parts.append(f"{days}d")
    if hours:
        parts.append(f"{hours}h")
    parts.append(f"{minutes}m")
    return " ".join(parts)


@dataclass(frozen=True)
class PowerState:
    """Placeholder for the Phase 6 power-management work (screen-off support)."""

    on_ac: bool | None
    battery_percent: int | None
