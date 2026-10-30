"""Shared return type for every automation primitive.

An ``OperationResult`` is the ONLY way a controller reports back. ``ok`` must be
the truth about the world after the call, not the truth about the call being
accepted -- that distinction is the whole point of `verified`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class OperationResult:
    ok: bool
    message: str
    details: dict[str, Any] = field(default_factory=dict)
    verified: bool = False
    simulated: bool = False

    @classmethod
    def success(cls, message: str, **details: Any) -> "OperationResult":
        return cls(True, message, details, verified=True)

    @classmethod
    def simulated_result(cls, message: str, **details: Any) -> "OperationResult":
        return cls(True, message, details, verified=False, simulated=True)

    @classmethod
    def failure(cls, message: str, **details: Any) -> "OperationResult":
        return cls(False, message, details, verified=False)
