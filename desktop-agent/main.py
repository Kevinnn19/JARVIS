"""JARVIS desktop agent — Phase 1 CLI (typed commands).

Run on Windows 11:

    cd JARVIS\\desktop-agent
    .\\venv\\Scripts\\Activate.ps1
    python main.py                # interactive
    python main.py --dry-run      # nothing is launched; safe rehearsal
    python main.py --once "open chrome"

Run anywhere (Linux/macOS sandbox, CI):

    python main.py --dry-run --once "open downloads"

Voice (Phase 2) will call the same JarvisAgent.handle_text(); this file stays the
only place that knows about a terminal.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Make `python main.py` work from any cwd (packages import as top-level modules).
sys.path.insert(0, str(Path(__file__).resolve().parent))

from config import ConfigError, load_settings  # noqa: E402
from core.agent import JarvisAgent  # noqa: E402
from core.schemas import ExecutionStatus  # noqa: E402
from security.confirmation_manager import ConsoleConfirmer  # noqa: E402
from utils.logger import get_logger  # noqa: E402

log = get_logger("main")

BANNER = r"""
   ____   _    ____  __     __ ___  ____
  |  _ \ / \  |  _ \ \ \   / /|_ _|/ ___|
  | |_) / _ \ | |_) | \ \ / /  | | \___ \
  |  __/ ___ \|  _ <   \ V /   | |  ___) |
  |_| /_/   \_\_| \_\   \_/   |___||____/
  Phase 1 — local typed commands (Windows 11 laptop agent)
"""

HELP = """\
Commands you can type (natural language, no punctuation needed):
  open chrome              open notepad            open downloads
  close chrome             search for invoice      find report in downloads
  set volume to 30         mute                    take a screenshot
  status                   help

CLI extras:
  :lock        emergency stop  (only status/stop allowed until :unlock)
  :unlock      resume normal operation
  :audit [n]   show the last n audit records (default 10)
  :commands    list registered commands
  :quit        exit
"""


def build_agent(args: argparse.Namespace) -> JarvisAgent:
    settings = load_settings(args.config_dir, dry_run=args.dry_run)
    confirmer = None if args.no_prompt else ConsoleConfirmer()
    return JarvisAgent(settings, dry_run=args.dry_run, confirmer=confirmer, speak=args.speak)


def print_result(result, as_json: bool, agent: JarvisAgent) -> None:
    if as_json:
        print(json.dumps(result.model_dump(mode="json"), indent=2))
        return
    print(agent.responses.respond(result))


def handle_meta(line: str, agent: JarvisAgent, as_json: bool) -> bool:
    """Handle ':cmd' CLI extras. Returns False when the loop should exit."""
    command, _, rest = line[1:].partition(" ")
    command = command.lower()

    if command in {"quit", "exit", "q"}:
        return False
    if command == "help":
        print(HELP)
    elif command == "lock":
        agent.lock("operator command")
        print("⛔ Locked. Only 'status' and 'stop' will be accepted. Use :unlock to resume.")
    elif command == "unlock":
        agent.unlock()
        print("✔ Unlocked.")
    elif command == "audit":
        count = int(rest) if rest.strip().isdigit() else 10
        records = agent.audit.tail(count)
        if not records:
            print("(no audit records yet)")
        for record in records:
            print(json.dumps(record, ensure_ascii=False))
    elif command == "commands":
        print(agent.registry.help_text())
    else:
        print(f"Unknown CLI command ':{command}'. Type :help.")
    return True


def repl(agent: JarvisAgent, as_json: bool) -> int:
    print(BANNER)
    state = "DRY RUN — no real actions will be taken" if agent.dry_run else "LIVE"
    print(f"State: {state} | Platform: {agent.settings.platform} | "
          f"Audit: {agent.settings.audit_path}")
    print(f"{len(agent.registry.names())} commands registered. Type :help for help, :quit to exit.\n")

    while True:
        try:
            line = input("you> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if not line:
            continue
        if line.lower() in {"quit", "exit", "bye", "q"}:
            return 0
        if line.startswith(":"):
            if not handle_meta(line, agent, as_json):
                return 0
            continue

        result = agent.handle_text(line)
        print_result(result, as_json, agent)
        if result.status is ExecutionStatus.REJECTED and "locked" in result.message.lower():
            print("   (type :unlock to resume)")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="jarvis", description="JARVIS desktop agent (Phase 1: typed commands)"
    )
    parser.add_argument("--once", metavar="TEXT", help="run a single command and exit")
    parser.add_argument("--dry-run", action="store_true",
                        help="simulate: never launch, close or capture anything")
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    parser.add_argument("--config-dir", default=None, help="path to the config/ folder")
    parser.add_argument("--speak", action="store_true", help="also speak responses (needs pyttsx3)")
    parser.add_argument("--no-prompt", action="store_true",
                        help="never ask for confirmation (declines instead)")
    parser.add_argument("--self-test", action="store_true",
                        help="parse a handful of sentences and exit (no OS actions)")
    args = parser.parse_args(argv)

    if args.json:
        # keep stdout clean JSON; logs already go to stderr
        pass

    try:
        agent = build_agent(args)
    except ConfigError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 2

    if args.self_test:
        samples = [
            "JARVIS, open Chrome.",
            " open notepad ",
            "open downloads",
            "close chrome",
            "search for invoice",
            "find report in downloads",
            "set volume to 30",
            "mute",
            "take a screenshot",
            "status",
            "help",
            "delete everything",
        ]
        for sample in samples:
            parsed = agent.parser.parse(sample)
            if parsed.ok and parsed.request:
                valid = agent.validator.validate(parsed.request)
                state = "ok" if valid.ok else f"rejected: {valid.error}"
                print(f"{sample!r:32} -> {parsed.request.name:<18} args={parsed.request.args} [{state}]")
            else:
                print(f"{sample!r:32} -> unparsed ({parsed.error})")
        return 0

    if args.once:
        result = agent.handle_text(args.once)
        print_result(result, args.json, agent)
        return 0 if result.ok or result.status is ExecutionStatus.PENDING_CONFIRMATION else 1

    return repl(agent, args.json)


if __name__ == "__main__":
    raise SystemExit(main())
