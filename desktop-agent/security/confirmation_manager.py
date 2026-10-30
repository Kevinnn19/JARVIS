"""Layer 3 — confirmation prompts (medium/high risk commands).

Phase 1 registers no medium/high handlers, so this module mostly exists to
define the contract the executor already speaks: when policy says
``requires_confirmation`` the executor returns ``PENDING_CONFIRMATION`` rather
than executing. Phase 3 plugs the Windows toast prompt and the Android approval
sheet into ``Confirmer`` implementations below.

Keeping the interface now means the executor never needs to change later, and
there is no risk of someone "temporarily" auto-approving high-risk actions.
"""

from __future__ import annotations

import secrets
import time
from dataclasses import dataclass, field
from typing import Protocol

from core.schemas import CommandRequest
from utils.logger import get_logger

log = get_logger("confirmation")


@dataclass
class ConfirmationTicket:
    ticket_id: str
    command_id: str
    command_name: str
    summary: str
    created_at: float = field(default_factory=time.time)
    expires_at: float = 0.0
    approved: bool | None = None  # None = still pending

    @property
    def expired(self) -> bool:
        return time.time() > self.expires_at


class Confirmer(Protocol):
    """Something that can ask a human for a yes/no."""

    def ask(self, ticket: ConfirmationTicket) -> bool | None: ...


class ConsoleConfirmer:
    """Local-terminal confirmer used by the Phase 1 CLI (local sources only)."""

    def ask(self, ticket: ConfirmationTicket) -> bool | None:
        answer = input(f"  Confirm '{ticket.summary}'? [y/N] ").strip().lower()
        if answer in {"y", "yes"}:
            return True
        if answer in {"n", "no", ""}:
            return False
        return None


class AutoDenyConfirmer:
    """Safe default for unattended/remote requests until Phase 3 ships the UI."""

    def ask(self, ticket: ConfirmationTicket) -> bool | None:
        log.warning("auto-denying confirmation for %s (no approver wired up)", ticket.command_name)
        return False


class ConfirmationManager:
    def __init__(self, timeout_seconds: float = 30.0) -> None:
        self.timeout_seconds = timeout_seconds
        self._tickets: dict[str, ConfirmationTicket] = {}

    def request(self, request: CommandRequest, summary: str) -> ConfirmationTicket:
        ticket = ConfirmationTicket(
            ticket_id=f"cfm_{secrets.token_hex(6)}",
            command_id=request.command_id,
            command_name=request.name,
            summary=summary,
            expires_at=time.time() + self.timeout_seconds,
        )
        self._tickets[ticket.ticket_id] = ticket
        return ticket

    def resolve(self, ticket_id: str, approved: bool) -> ConfirmationTicket | None:
        ticket = self._tickets.get(ticket_id)
        if ticket is None or ticket.expired:
            return None
        ticket.approved = approved
        return ticket

    def pending(self) -> list[ConfirmationTicket]:
        return [t for t in self._tickets.values() if t.approved is None and not t.expired]
