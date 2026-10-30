"""Configuration loading for the JARVIS desktop agent.

Everything the agent considers "configuration" (allowlists, permissions, paths,
timeouts) is loaded here once and handed to the modules that need it. Nothing
in the codebase hardcodes an application path, a permission level or a folder
root -- those decisions live in ``config/*.yaml`` so they are reviewable and
diff-able.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

AGENT_DIR = Path(__file__).resolve().parent
REPO_ROOT = AGENT_DIR.parent
DEFAULT_CONFIG_DIR = REPO_ROOT / "config"


class ConfigError(RuntimeError):
    """Raised when a configuration file is missing or malformed."""


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise ConfigError(f"Missing configuration file: {path}")
    try:
        with path.open("r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}
    except yaml.YAMLError as exc:  # pragma: no cover - defensive
        raise ConfigError(f"Invalid YAML in {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ConfigError(f"Expected a mapping at the top level of {path}")
    return data


def expand(value: str | os.PathLike[str]) -> Path:
    """Expand ~ and environment variables into an absolute path."""
    raw = os.path.expandvars(os.path.expanduser(str(value)))
    return Path(raw)


@dataclass(frozen=True)
class AppSpec:
    """One entry from applications.yaml."""

    key: str
    display_name: str
    aliases: tuple[str, ...]
    process_names: dict[str, tuple[str, ...]]
    launchers: dict[str, tuple[str, ...]]

    def processes_for(self, platform: str) -> tuple[str, ...]:
        return self.process_names.get(platform, ())

    def launchers_for(self, platform: str) -> tuple[str, ...]:
        return self.launchers.get(platform, ())


@dataclass(frozen=True)
class PathPolicy:
    home_dir: Path
    allowed_roots: tuple[Path, ...]
    protected_paths: tuple[Path, ...]
    default_search_roots: tuple[Path, ...]
    search_max_depth: int
    search_max_results: int


@dataclass(frozen=True)
class Settings:
    """Resolved, immutable view of every config file."""

    config_dir: Path
    agent_name: str = "JARVIS"
    command_timeout_seconds: float = 20.0
    confirm_timeout_seconds: float = 30.0
    log_dir: Path = field(default_factory=lambda: expand("~/.jarvis/logs"))
    audit_filename: str = "audit.jsonl"
    log_level: str = "INFO"
    dry_run: bool = False
    platform: str = field(default_factory=lambda: current_platform())
    applications: dict[str, AppSpec] = field(default_factory=dict)
    commands_config: dict[str, Any] = field(default_factory=dict)
    permissions_config: dict[str, Any] = field(default_factory=dict)
    path_policy: PathPolicy = field(
        default_factory=lambda: PathPolicy(expand("~"), (), (), (), 4, 10)
    )
    voice_config: dict[str, Any] = field(default_factory=dict)
    settings_raw: dict[str, Any] = field(default_factory=dict)

    # -- derived helpers -----------------------------------------------------
    @property
    def audit_path(self) -> Path:
        return self.log_dir / self.audit_filename

    def alias_index(self) -> dict[str, AppSpec]:
        """Map every alias (and canonical key) -> AppSpec, lowercase."""
        index: dict[str, AppSpec] = {}
        for spec in self.applications.values():
            index[spec.key.lower()] = spec
            for alias in spec.aliases:
                index[alias.lower()] = spec
        return index


def current_platform() -> str:
    """Return 'windows' | 'linux' | 'darwin' (the only OS keys we use)."""
    if sys.platform.startswith("win"):
        return "windows"
    if sys.platform == "darwin":
        return "darwin"
    return "linux"


def _parse_applications(raw: dict[str, Any]) -> dict[str, AppSpec]:
    apps: dict[str, AppSpec] = {}
    for key, entry in (raw.get("applications") or {}).items():
        if not isinstance(entry, dict):
            raise ConfigError(f"Application '{key}' must be a mapping")
        proc = entry.get("process_names") or {}
        launches: dict[str, tuple[str, ...]] = {}
        for os_name in ("windows", "linux", "darwin"):
            block = entry.get(os_name) or {}
            candidates = list(block.get("launch") or [])
            if block.get("uri"):
                candidates.append(str(block["uri"]))
            launches[os_name] = tuple(str(c) for c in candidates)
        apps[str(key)] = AppSpec(
            key=str(key),
            display_name=str(entry.get("display_name") or key),
            aliases=tuple(str(a).lower() for a in (entry.get("aliases") or [])),
            process_names={
                os_name: tuple(str(n) for n in names or ())
                for os_name, names in proc.items()
            },
            launchers=launches,
        )
    if not apps:
        raise ConfigError("applications.yaml defines no applications")
    return apps


def _parse_path_policy(raw: dict[str, Any]) -> PathPolicy:
    paths = raw.get("paths") or {}
    return PathPolicy(
        home_dir=expand(paths.get("home") or "~"),
        allowed_roots=tuple(expand(p) for p in paths.get("allowed_roots") or ("~",)),
        protected_paths=tuple(expand(p) for p in paths.get("protected_paths") or ()),
        default_search_roots=tuple(
            expand(p) for p in paths.get("default_search_roots") or ("~",)
        ),
        search_max_depth=int(paths.get("search_max_depth") or 6),
        search_max_results=int(paths.get("search_max_results") or 25),
    )


def load_settings(
    config_dir: str | os.PathLike[str] | None = None,
    *,
    dry_run: bool = False,
) -> Settings:
    """Load every YAML file in ``config_dir`` (default: <repo>/config)."""
    directory = Path(config_dir) if config_dir else DEFAULT_CONFIG_DIR
    apps_raw = _load_yaml(directory / "applications.yaml")
    commands_raw = _load_yaml(directory / "commands.yaml")
    perms_raw = _load_yaml(directory / "permissions.yaml")
    settings_raw = _load_yaml(directory / "settings.yaml")

    agent_cfg = settings_raw.get("agent") or {}
    logging_cfg = settings_raw.get("logging") or {}

    return Settings(
        config_dir=directory,
        agent_name=str(agent_cfg.get("name") or "JARVIS"),
        command_timeout_seconds=float(
            agent_cfg.get("command_timeout_seconds") or 20.0
        ),
        confirm_timeout_seconds=float(agent_cfg.get("confirm_timeout_seconds") or 30.0),
        log_dir=expand(logging_cfg.get("log_dir") or "~/.jarvis/logs"),
        audit_filename=str(logging_cfg.get("audit_file") or "audit.jsonl"),
        log_level=str(logging_cfg.get("level") or "INFO").upper(),
        dry_run=dry_run,
        platform=current_platform(),
        applications=_parse_applications(apps_raw),
        commands_config=commands_raw,
        permissions_config=perms_raw,
        path_policy=_parse_path_policy(settings_raw),
        voice_config=settings_raw.get("voice") or {},
        settings_raw=settings_raw,
    )
