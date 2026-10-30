"""Shared pytest fixtures.

Tests run against a throwaway copy of the real config/ directory, with two
changes:

* allowed roots / search roots point at a temp "home" so the sandbox's real
  folders are never touched,
* one extra application ("sleeper") is registered that maps to a copy of
  /bin/sleep, so launch/verify/close can be exercised for real (not just in
  dry-run) on Linux CI.
"""

from __future__ import annotations

import shutil
import stat
import sys
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
REAL_CONFIG_DIR = REPO_ROOT / "config"
CONFIG_FILES = ("applications.yaml", "commands.yaml", "permissions.yaml", "settings.yaml")


@pytest.fixture
def fake_home(tmp_path: Path) -> Path:
    home = tmp_path / "home"
    (home / "Downloads").mkdir(parents=True)
    (home / "Documents").mkdir()
    (home / "Desktop").mkdir()
    (home / "Pictures").mkdir()
    (home / "Downloads" / "invoice-2026.pdf").write_text("pdf", encoding="utf-8")
    (home / "Documents" / "report-final.docx").write_text("docx", encoding="utf-8")
    (home / "Documents" / "notes.txt").write_text("notes", encoding="utf-8")
    (home / "Downloads" / "System Volume Information").mkdir()
    return home


@pytest.fixture
def sleeper_binary(tmp_path: Path) -> Path | None:
    """A uniquely-named copy of /bin/sleep so process matching is unambiguous."""
    source = Path("/bin/sleep")
    if not source.exists():
        return None
    target = tmp_path / "bin" / "jvsleeper"
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)
    target.chmod(target.stat().st_mode | stat.S_IEXEC)
    return target


@pytest.fixture
def config_dir(tmp_path: Path, fake_home: Path, sleeper_binary: Path | None) -> Path:
    dst = tmp_path / "config"
    dst.mkdir()
    for name in CONFIG_FILES:
        shutil.copy2(REAL_CONFIG_DIR / name, dst / name)

    settings = yaml.safe_load((dst / "settings.yaml").read_text(encoding="utf-8"))
    settings["paths"]["home"] = str(fake_home)
    settings["paths"]["allowed_roots"] = [str(fake_home), str(fake_home / "Downloads")]
    settings["paths"]["default_search_roots"] = [
        str(fake_home / "Downloads"),
        str(fake_home / "Documents"),
    ]
    settings["paths"]["protected_paths"] = [
        str(fake_home / "Downloads" / "System Volume Information"),
        "/etc",
        "/bin",
    ]
    settings["logging"]["log_dir"] = str(tmp_path / "logs")
    settings["agent"]["command_timeout_seconds"] = 20
    (dst / "settings.yaml").write_text(yaml.safe_dump(settings), encoding="utf-8")

    apps = yaml.safe_load((dst / "applications.yaml").read_text(encoding="utf-8"))
    if sleeper_binary is not None and sys.platform.startswith("linux"):
        apps["applications"]["sleeper"] = {
            "display_name": "Test Sleeper",
            "aliases": ["sleeper", "test sleeper"],
            "process_names": {"linux": ["jvsleeper"], "windows": ["jvsleeper.exe"]},
            "linux": {"launch": [str(sleeper_binary)]},
            "windows": {"launch": [str(sleeper_binary)]},
        }
    (dst / "applications.yaml").write_text(yaml.safe_dump(apps), encoding="utf-8")
    return dst


@pytest.fixture
def settings(config_dir: Path):
    from config import load_settings

    return load_settings(config_dir)


@pytest.fixture
def agent(settings):
    from core.agent import JarvisAgent

    return JarvisAgent(settings, dry_run=False)


@pytest.fixture
def dry_agent(settings):
    from core.agent import JarvisAgent

    return JarvisAgent(settings, dry_run=True)
