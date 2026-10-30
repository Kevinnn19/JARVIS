"""Turns a CommandResult into words (and, from Phase 2, into speech).

Phase 1 prints text. The TTS class below is already wired to pyttsx3 but stays
disabled until the voice phase enables it in settings.yaml -- so nothing in the
command path has to change when voice arrives.
"""

from __future__ import annotations

from core.schemas import CommandResult, ExecutionStatus

ICONS = {
    ExecutionStatus.SUCCESS: "✔",
    ExecutionStatus.DRY_RUN: "◌",
    ExecutionStatus.FAILURE: "✖",
    ExecutionStatus.REJECTED: "⛔",
    ExecutionStatus.PENDING_CONFIRMATION: "❓",
    ExecutionStatus.TIMEOUT: "⏱",
    ExecutionStatus.PARSE_ERROR: "…",
}


class ResponseEngine:
    def __init__(self, *, agent_name: str = "JARVIS", speak: bool = False, rate: int = 180) -> None:
        self.agent_name = agent_name
        self.speak_enabled = speak
        self.rate = rate
        self._engine = None

    # -- rendering ----------------------------------------------------------
    def render(self, result: CommandResult) -> str:
        icon = ICONS.get(result.status, "•")
        suffix = f" ({result.duration_ms} ms)" if result.duration_ms >= 200 else ""
        return f"{icon} {result.message}{suffix}"

    def render_compact(self, result: CommandResult) -> str:
        """One-line form used by the WebSocket feed later on."""
        return f"{result.status.value}: {result.message}"

    # -- speech (Phase 2) ---------------------------------------------------
    def speak(self, text: str) -> None:
        if not self.speak_enabled:
            return
        try:  # imported lazily: Windows-only dependency
            import pyttsx3  # type: ignore
        except ImportError:
            self.speak_enabled = False
            return
        if self._engine is None:
            self._engine = pyttsx3.init()
            self._engine.setProperty("rate", self.rate)
        self._engine.say(text)
        self._engine.runAndWait()

    def respond(self, result: CommandResult, *, speech_text: str | None = None) -> str:
        rendered = self.render(result)
        self.speak(speech_text or result.message)
        return rendered
