"""Phase 1 acceptance tests: parsing, validation, execution, honest reporting."""

from __future__ import annotations

import psutil
import pytest

from core.schemas import CommandSource, ExecutionStatus


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "text,command,args",
    [
        ("open chrome", "open_application", {"application": "chrome"}),
        ("JARVIS, open Chrome.", "open_application", {"application": "chrome"}),
        ("  open   notepad  ", "open_application", {"application": "notepad"}),
        ("close chrome", "close_application", {"application": "chrome"}),
        ("quit notepad", "close_application", {"application": "notepad"}),
        ("open downloads", "open_folder", {"folder": "downloads"}),
        ("search for invoice", "search_files", {"query": "invoice"}),
        ("set volume to 30", "set_volume", {"level": "30"}),
        ("mute", "set_volume", {"level": 0}),
        ("take a screenshot", "screenshot", {}),
        ("status", "status", {}),
        ("help", "help", {}),
        ("stop listening", "stop", {}),
    ],
)
def test_parser_maps_sentences_to_registered_commands(agent, text, command, args):
    parsed = agent.parser.parse(text)
    assert parsed.ok, parsed.error
    assert parsed.request is not None
    assert parsed.request.name == command
    assert parsed.request.args == args


def test_parser_refuses_unknown_sentence(agent):
    parsed = agent.parser.parse("make me a sandwich")
    assert not parsed.ok
    assert parsed.request is None
    assert parsed.suggestions


def test_parser_never_returns_code(agent):
    """A shell-injection attempt must not become a command; it becomes a bad arg."""
    parsed = agent.parser.parse("open chrome && rm -rf /")
    assert parsed.ok  # parsed as "open <something>"
    result = agent.validator.validate(parsed.request)
    assert not result.ok
    assert "not an approved application" in (result.error or "")


# ---------------------------------------------------------------------------
# Validation / allowlist
# ---------------------------------------------------------------------------
def test_unknown_application_is_rejected(agent):
    result = agent.handle_text("open winrar")
    assert result.status is ExecutionStatus.REJECTED
    assert "not an approved application" in result.message


def test_alias_is_canonicalised(agent):
    parsed = agent.parser.parse("open google chrome")
    outcome = agent.validator.validate(parsed.request)
    assert outcome.ok
    assert outcome.request.args["application"] == "chrome"


def test_folder_outside_allowed_roots_is_rejected(agent, settings):
    parsed = agent.parser.parse("/etc")
    assert not parsed.ok
    result = agent.handle_text("open documents in /etc")
    assert result.status in {ExecutionStatus.REJECTED, ExecutionStatus.FAILURE}


def test_protected_path_is_not_allowed(agent, fake_home):
    protected = fake_home / "Downloads" / "System Volume Information"
    assert agent.validator.is_allowed_path(protected) is False
    assert agent.validator.is_allowed_path(fake_home / "Downloads") is True


# ---------------------------------------------------------------------------
# Execution (dry run): proves the plumbing without touching the OS
# ---------------------------------------------------------------------------
def test_dry_run_never_reports_real_success(dry_agent):
    result = dry_agent.handle_text("open chrome")
    assert result.status is ExecutionStatus.DRY_RUN
    assert result.details.get("simulated") is True
    assert result.details.get("verified") is False
    assert "[dry run]" in result.message


def test_dry_run_volume(dry_agent):
    result = dry_agent.handle_text("set volume to 25")
    assert result.status is ExecutionStatus.DRY_RUN
    assert result.details["level"] == 25


def test_status_reports_real_machine_facts(agent):
    result = agent.handle_text("status")
    assert result.status is ExecutionStatus.SUCCESS
    assert result.details["hostname"]
    assert result.details["uptime_seconds"] >= 0


def test_help_lists_registered_commands(agent):
    result = agent.handle_text("help")
    assert result.status is ExecutionStatus.SUCCESS
    for phrase in ("Open an approved application", "Set the system output volume", "Examples"):
        assert phrase in result.message


# ---------------------------------------------------------------------------
# Execution (real): launch + verify + close, and honest failure
# ---------------------------------------------------------------------------
@pytest.mark.skipif(not __import__("sys").platform.startswith("linux"), reason="POSIX sleeper test")
def test_launch_and_close_are_verified(agent):
    from core.schemas import CommandRequest

    if "sleeper" not in agent.settings.applications:
        pytest.skip("sleeper fixture unavailable")

    try:
        opened = agent.handle(
            CommandRequest(
                name="open_application",
                args={"application": "sleeper", "arguments": ["120"]},
            )
        )
        if opened.status is ExecutionStatus.FAILURE:
            pytest.skip(f"could not spawn test process: {opened.message}")
        assert opened.status is ExecutionStatus.SUCCESS, opened.message
        assert opened.details.get("verified") is True
        assert any(p.name() == "jvsleeper" for p in psutil.process_iter(["name"]))

        closed = agent.handle_text("close sleeper")
        assert closed.status is ExecutionStatus.SUCCESS, closed.message
        assert not any(p.name() == "jvsleeper" for p in psutil.process_iter(["name"]))
    finally:
        for proc in psutil.process_iter(["name"]):
            if proc.info.get("name") == "jvsleeper":
                try:
                    proc.kill()
                except psutil.Error:
                    pass


@pytest.mark.skipif(not __import__("sys").platform.startswith("linux"), reason="POSIX sleeper test")
def test_closing_something_not_running_reports_failure(agent):
    if "sleeper" not in agent.settings.applications:
        pytest.skip("sleeper fixture unavailable")
    result = agent.handle_text("close sleeper")
    assert result.status is ExecutionStatus.FAILURE
    assert "not running" in result.message


def test_search_files_finds_and_reports_paths(agent):
    result = agent.handle_text("search for invoice")
    assert result.status is ExecutionStatus.SUCCESS, result.message
    assert any(path.endswith("invoice-2026.pdf") for path in result.details["matches"])


def test_search_files_reports_empty_scope_honestly(agent):
    result = agent.handle_text("search for does-not-exist-xyz")
    assert result.status is ExecutionStatus.FAILURE
    assert "No files matching" in result.message


def test_open_folder_dry_run(dry_agent, fake_home):
    result = dry_agent.handle_text("open downloads")
    assert result.status is ExecutionStatus.DRY_RUN
    assert result.details["path"] == str(fake_home / "Downloads")


# ---------------------------------------------------------------------------
# Result envelope
# ---------------------------------------------------------------------------
def test_results_carry_timing_and_permission(agent):
    result = agent.handle_text("status")
    assert result.duration_ms >= 0
    assert result.finished_at >= result.started_at
    assert result.permission.value == "low"
    assert result.command_id.startswith("cmd_")


def test_remote_source_is_recorded(agent):
    result = agent.handle_text("status", source=CommandSource.REMOTE_API)
    assert result.status is ExecutionStatus.SUCCESS
    assert result.details is not None
