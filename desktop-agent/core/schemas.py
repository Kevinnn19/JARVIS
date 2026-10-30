"""Structured data contracts for the JARVIS desktop agent.

The single most important security property of this project lives in this
file: a *command* is a typed object (``CommandRequest``) whose ``name`` must
exist in the registry and whose ``args`` must validate against a Pydantic
model. There is no field anywhere in this schema that can carry executable
code or a raw shell string into a handler.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class CommandSource(str, Enum):
    """Where a command came from. Drives the trust level in the policy engine."""

    LOCAL_TYPED = "local_typed"
    LOCAL_VOICE = "local_voice"
    REMOTE_API = "remote_api"
    REMOTE_VOICE = "remote_voice"

    @property
    def is_local(self) -> bool:
        return self in (CommandSource.LOCAL_TYPED, CommandSource.LOCAL_VOICE)


class PermissionLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    BLOCKED = "blocked"

    @property
    def rank(self) -> int:
        return {"low": 0, "medium": 1, "high": 2, "blocked": 3}[self.value]


class ExecutionStatus(str, Enum):
    """Outcome of a command. ``dry_run`` is deliberately distinct from
    ``success`` so that nothing can claim work that was not actually done."""

    SUCCESS = "success"
    DRY_RUN = "dry_run"
    FAILURE = "failure"
    REJECTED = "rejected"
    PENDING_CONFIRMATION = "pending_confirmation"
    TIMEOUT = "timeout"
    PARSE_ERROR = "parse_error"


# ---------------------------------------------------------------------------
# Request / result envelopes (mirrored to shared/command-schema.json)
# ---------------------------------------------------------------------------


class CommandRequest(BaseModel):
    """A validated intent. Produced by the parser, consumed by the executor."""

    model_config = ConfigDict(extra="forbid")

    command_id: str = Field(default_factory=lambda: new_id("cmd"))
    name: str = Field(min_length=1, max_length=64)
    args: dict[str, Any] = Field(default_factory=dict)
    raw_text: str = ""
    source: CommandSource = CommandSource.LOCAL_TYPED
    created_at: datetime = Field(default_factory=utcnow)


class CommandResult(BaseModel):
    """What actually happened. Always produced by the executor, never by the
    parser, so the reported status reflects the real world."""

    model_config = ConfigDict(extra="forbid")

    command_id: str
    name: str
    status: ExecutionStatus
    message: str
    permission: PermissionLevel = PermissionLevel.LOW
    details: dict[str, Any] = Field(default_factory=dict)
    started_at: datetime = Field(default_factory=utcnow)
    finished_at: datetime = Field(default_factory=utcnow)
    duration_ms: int = 0

    @property
    def ok(self) -> bool:
        return self.status in (ExecutionStatus.SUCCESS, ExecutionStatus.DRY_RUN)


class ParseResult(BaseModel):
    """Parser output. Either a request or a human-readable reason + suggestions."""

    model_config = ConfigDict(extra="forbid")

    ok: bool
    request: CommandRequest | None = None
    error: str | None = None
    suggestions: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Per-command argument models.
# Using one Pydantic model per command is what makes "natural language never
# reaches an API boundary unvalidated" true in practice.
# ---------------------------------------------------------------------------


class _StrictArgs(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class OpenApplicationArgs(_StrictArgs):
    application: str = Field(min_length=1, max_length=80)
    arguments: list[str] = Field(default_factory=list, max_length=8)


class CloseApplicationArgs(_StrictArgs):
    application: str = Field(min_length=1, max_length=80)


class OpenFolderArgs(_StrictArgs):
    folder: str = Field(min_length=1, max_length=80)


class SearchFilesArgs(_StrictArgs):
    query: str = Field(min_length=1, max_length=120)
    root: str | None = Field(default=None, max_length=260)
    limit: int = Field(default=10, ge=1, le=100)

    @field_validator("query")
    @classmethod
    def _no_glob_abuse(cls, value: str) -> str:
        if value.strip() in {"*", ".*", "%", "_"}:
            raise ValueError("query is too broad; be more specific")
        return value


class SetVolumeArgs(_StrictArgs):
    level: int = Field(ge=0, le=100)


class NoArgs(_StrictArgs):
    """Commands that take no parameters (status, help, stop, screenshot)."""


# Registry of command name -> argument model. Kept here (not in the registry)
# so that tests can validate the contract without importing automation code.
ARGS_MODELS: dict[str, type[BaseModel]] = {
    "open_application": OpenApplicationArgs,
    "close_application": CloseApplicationArgs,
    "open_folder": OpenFolderArgs,
    "search_files": SearchFilesArgs,
    "set_volume": SetVolumeArgs,
    "screenshot": NoArgs,
    "status": NoArgs,
    "help": NoArgs,
    "stop": NoArgs,
}
