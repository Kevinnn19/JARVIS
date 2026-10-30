"""Logging + audit trail.

Two different things, deliberately separated:

* ``get_logger()``  — developer-facing console/file logging (debugging).
* ``AuditLogger``   — append-only JSONL record of every command JARVIS was
  asked to perform, and what happened. This is the file you would review if you
  ever suspected somebody else drove your laptop.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_CONFIGURED = False
_LOCK = threading.Lock()

SECRET_KEYS = {"password", "token", "access_token", "refresh_token", "secret", "authorization"}


def get_logger(name: str = "jarvis") -> logging.Logger:
    global _CONFIGURED
    with _LOCK:
        if not _CONFIGURED:
            level = os.environ.get("JARVIS_LOG_LEVEL", "INFO").upper()
            handler = logging.StreamHandler(stream=sys.stderr)
            handler.setFormatter(
                logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s",
                                  datefmt="%H:%M:%S")
            )
            root = logging.getLogger("jarvis")
            root.setLevel(getattr(logging, level, logging.INFO))
            root.addHandler(handler)
            root.propagate = False
            _CONFIGURED = True
    return logging.getLogger(f"jarvis.{name}")


def _redact(value: Any, depth: int = 0) -> Any:
    """Remove obvious secrets and truncate deep structures before writing."""
    if depth > 4:
        return "..."
    if isinstance(value, dict):
        return {
            k: ("***" if str(k).lower() in SECRET_KEYS else _redact(v, depth + 1))
            for k, v in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_redact(v, depth + 1) for v in value][:20]
    if isinstance(value, str):
        return value[:400]
    return value


class AuditLogger:
    """Append-only JSON Lines audit log."""

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self._lock = threading.Lock()
        self.log = get_logger("audit")

    def write(self, event: str, payload: dict[str, Any]) -> None:
        record = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "event": event,
            **_redact(payload),
        }
        line = json.dumps(record, ensure_ascii=False, default=str)
        try:
            with self._lock:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                with self.path.open("a", encoding="utf-8") as fh:
                    fh.write(line + "\n")
        except OSError as exc:  # never let logging break the assistant
            self.log.warning("audit write failed: %s", exc)

    def tail(self, count: int = 20) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        with self.path.open("r", encoding="utf-8") as fh:
            lines = fh.readlines()[-count:]
        out: list[dict[str, Any]] = []
        for line in lines:
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return out
