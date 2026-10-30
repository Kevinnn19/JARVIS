"""Rule-based natural-language -> structured command.

Deliberately NOT an LLM. For v1 the mapping from sentence to registry command is
a small, ordered list of regexes defined in ``config/commands.yaml``. Benefits:

* deterministic and offline (no API keys, no latency, no cost),
* auditable -- you can read every sentence pattern JARVIS understands,
* incapable of inventing a command that does not exist,
* identical input always produces identical output, which makes tests useful.

Phase 6 can add an LLM *in front of* this parser to rewrite loose phrasing into
one of these canonical sentences, but the registry and validator still decide
what may actually happen.
"""

from __future__ import annotations

import re
import string
from dataclasses import dataclass
from typing import Any

from config import Settings
from core.schemas import CommandRequest, CommandSource, ParseResult
from utils.logger import get_logger

log = get_logger("parser")

WAKE_PREFIXES = (
    "hey jarvis",
    "ok jarvis",
    "okay jarvis",
    "jarvis",
)

FALLBACK_SUGGESTIONS = [
    "open chrome",
    "close chrome",
    "open downloads",
    "search for invoice",
    "set volume to 30",
    "take a screenshot",
    "status",
    "help",
]


@dataclass(frozen=True)
class PatternRule:
    command: str
    regex: re.Pattern[str]
    fixed_args: dict[str, Any]


def normalise(text: str) -> str:
    """Lowercase, strip a wake word, collapse whitespace, drop trailing punctuation."""
    cleaned = " ".join(text.strip().lower().split())
    for prefix in WAKE_PREFIXES:
        if cleaned == prefix:
            continue
        if cleaned.startswith(prefix + " ") or cleaned.startswith(prefix + ","):
            cleaned = cleaned[len(prefix):].lstrip(" ,.")
            break
    cleaned = cleaned.strip(string.whitespace + string.punctuation + "!?.,")
    return cleaned


class CommandParser:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.rules = self._compile_rules(settings.commands_config)

    def _compile_rules(self, config: dict[str, Any]) -> list[PatternRule]:
        patterns = config.get("patterns") or {}
        order = config.get("command_order") or list(patterns)
        rules: list[PatternRule] = []
        for command in order:
            for entry in patterns.get(command) or []:
                if isinstance(entry, str):
                    pattern, fixed = entry, {}
                elif isinstance(entry, dict):
                    pattern = entry.get("pattern")
                    fixed = dict(entry.get("args") or {})
                else:  # pragma: no cover - config error
                    continue
                if not pattern:
                    continue
                rules.append(
                    PatternRule(
                        command=str(command),
                        regex=re.compile(pattern, re.IGNORECASE),
                        fixed_args=fixed,
                    )
                )
        if not rules:
            raise ValueError("commands.yaml defines no usable patterns")
        return rules

    # -- public API ---------------------------------------------------------
    def parse(self, text: str, source: CommandSource = CommandSource.LOCAL_TYPED) -> ParseResult:
        cleaned = normalise(text or "")
        if not cleaned:
            return ParseResult(ok=False, error="I didn't catch a command.", suggestions=[])

        for rule in self.rules:
            match = rule.regex.match(cleaned)
            if not match:
                continue
            args: dict[str, Any] = dict(rule.fixed_args)
            for key, value in match.groupdict().items():
                if value is not None:
                    args[key] = str(value).strip()
            if args.get("root") in (None, ""):
                args.pop("root", None)
            return ParseResult(
                ok=True,
                request=CommandRequest(
                    name=rule.command,
                    args=args,
                    raw_text=text,
                    source=source,
                ),
            )

        return ParseResult(
            ok=False,
            error=f"I don't have a command for '{cleaned}'.",
            suggestions=self.suggest(cleaned),
        )

    def suggest(self, text: str, limit: int = 4) -> list[str]:
        """Cheap nearest-neighbour suggestions so failures are actionable."""
        words = {w for w in re.split(r"\W+", text) if w}
        scored: list[tuple[int, str]] = []
        for example in FALLBACK_SUGGESTIONS:
            score = len(words & set(example.split()))
            if score:
                scored.append((score, example))
        scored.sort(key=lambda item: -item[0])
        picks = [example for _, example in scored[:limit]]
        if len(picks) < limit:
            for example in FALLBACK_SUGGESTIONS:
                if example not in picks:
                    picks.append(example)
                if len(picks) >= limit:
                    break
        return picks
