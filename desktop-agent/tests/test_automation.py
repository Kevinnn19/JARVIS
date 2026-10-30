"""Automation-module tests: allowlist resolution, path policy, search bounds."""

from __future__ import annotations

from pathlib import Path

import pytest

from automation.app_controller import AppController
from automation.file_manager import FileManager


def test_alias_resolution_and_suffixes(settings):
    apps = AppController(settings, dry_run=True)
    assert apps.resolve("chrome").key == "chrome"
    assert apps.resolve("google chrome").key == "chrome"
    assert apps.resolve("Chrome.exe").key == "chrome"
    assert apps.resolve("chrome app").key == "chrome"
    assert apps.resolve("winrar") is None


def test_unknown_launcher_reports_failure_not_silence(settings):
    """'Files' (explorer) has no launcher on Linux; it must fail loudly."""
    apps = AppController(settings, dry_run=False, platform="linux")
    spec = settings.applications["file_explorer"]
    result = apps.launch(spec)
    if result.ok:  # a real nautilus exists on this machine
        apps.close(spec)
        pytest.skip("an explorer-equivalent is installed here")
    assert not result.ok
    assert result.verified is False


def test_dry_run_launch_reports_simulation(settings):
    apps = AppController(settings, dry_run=True)
    result = apps.launch(settings.applications["chrome"])
    assert result.simulated and not result.verified
    assert "[dry run]" in result.message


def test_file_manager_refuses_protected_path(settings, fake_home):
    files = FileManager(settings)
    assert files.is_allowed(fake_home / "Downloads") is True
    assert files.is_allowed(fake_home / "Downloads" / "System Volume Information") is False
    assert files.is_allowed(Path("/etc")) is False


def test_file_manager_rejects_unknown_folder(settings):
    files = FileManager(settings)
    assert files.resolve_folder("downloads") is not None
    assert files.resolve_folder("rm -rf /") is None


def test_search_respects_depth_and_skips_noise(settings, fake_home):
    deep = fake_home / "Documents" / "a" / "b" / "c" / "d" / "e" / "f" / "g"
    deep.mkdir(parents=True)
    (deep / "deep-needle.txt").write_text("x", encoding="utf-8")
    (fake_home / "Documents" / "node_modules").mkdir(exist_ok=True)
    (fake_home / "Documents" / "node_modules" / "needle-in-noise.txt").write_text("x", encoding="utf-8")

    files = FileManager(settings)
    report = files.search("needle", limit=10)
    names = {p.name for p in report.matches}
    assert "needle-in-noise.txt" not in names  # skipped noise directory
    assert "deep-needle.txt" not in names or report.truncated  # depth limited


def test_search_limit_is_enforced(settings, fake_home):
    for i in range(12):
        (fake_home / "Downloads" / f"sample-{i}.txt").write_text("x", encoding="utf-8")
    files = FileManager(settings)
    report = files.search("sample", limit=5)
    assert report.count == 5
    assert report.truncated is True
