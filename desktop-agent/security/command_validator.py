"""Argument validation and path guarding.

Runs between the parser and the executor. It turns loose parser output into a
*canonical* argument set:

* every command's args are validated against its Pydantic model,
* application names are resolved against the allowlist (aliases -> canonical key),
* folder names are resolved to real directories inside the allowed roots,
* anything pointing at a protected/out-of-scope path is refused here, before an
  automation module ever sees it.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import ValidationError

from config import Settings
from core.schemas import ARGS_MODELS, CommandRequest
from utils.helpers import user_folder
from utils.logger import get_logger

log = get_logger("validator")

FRIENDLY_FOLDERS = {
    "home",
    "downloads",
    "documents",
    "desktop",
    "pictures",
    "music",
    "videos",
}


class ValidationOutcome:
    def __init__(self, ok: bool, request: CommandRequest | None = None, error: str | None = None):
        self.ok = ok
        self.request = request
        self.error = error

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"ValidationOutcome(ok={self.ok}, error={self.error!r})"


class CommandValidator:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._alias_index = settings.alias_index()

    # -- applications -------------------------------------------------------
    def resolve_application(self, application: str) -> str | None:
        key = " ".join(application.strip().lower().split())
        if key in self._alias_index:
            return self._alias_index[key].key
        for suffix in (".exe", " app", " application"):
            if key.endswith(suffix):
                trimmed = key[: -len(suffix)].strip()
                if trimmed in self._alias_index:
                    return self._alias_index[trimmed].key
        return None

    def known_application_names(self) -> list[str]:
        return sorted({spec.display_name for spec in self._alias_index.values()})

    # -- paths --------------------------------------------------------------
    def resolve_folder(self, folder: str) -> Path | None:
        if folder.strip().lower() in FRIENDLY_FOLDERS:
            path = user_folder(folder, self.settings.path_policy.home_dir)
            return path if path is not None else None
        candidate = Path(folder).expanduser()
        if candidate.exists() and candidate.is_dir() and self.is_allowed_path(candidate):
            return candidate
        return None

    def is_allowed_path(self, path: Path) -> bool:
        try:
            resolved = path.expanduser().resolve()
        except OSError:
            return False
        policy = self.settings.path_policy
        for protected in policy.protected_paths:
            try:
                p = protected.expanduser().resolve()
            except OSError:
                continue
            if resolved == p or p in resolved.parents:
                return False
        for root in policy.allowed_roots:
            try:
                r = root.expanduser().resolve()
            except OSError:
                continue
            if resolved == r or r in resolved.parents:
                return True
        return False

    # -- main entry point ---------------------------------------------------
    def validate(self, request: CommandRequest) -> ValidationOutcome:
        model = ARGS_MODELS.get(request.name)
        if model is None:
            return ValidationOutcome(False, error=f"No argument schema for '{request.name}'.")

        try:
            args_model = model.model_validate(request.args)
        except ValidationError as exc:
            first = exc.errors()[0]
            field = ".".join(str(p) for p in first.get("loc", ())) or "arguments"
            return ValidationOutcome(
                False, error=f"Invalid {field}: {first.get('msg', 'bad value')}"
            )

        args: dict[str, Any] = args_model.model_dump()

        # --- canonicalise applications ---
        for field_name in ("application",):
            if field_name in args:
                canonical = self.resolve_application(str(args[field_name]))
                if canonical is None:
                    return ValidationOutcome(
                        False,
                        error=(
                            f"'{args[field_name]}' is not an approved application. "
                            f"Known: {', '.join(self.known_application_names())}"
                        ),
                    )
                args[field_name] = canonical

        # --- canonicalise folders / search roots ---
        if request.name == "open_folder":
            path = self.resolve_folder(str(args["folder"]))
            if path is None:
                return ValidationOutcome(
                    False,
                    error=(
                        f"I can't reach '{args['folder']}'. It doesn't exist or it is "
                        "outside the folders I'm allowed to use."
                    ),
                )
            args["folder"] = str(path)

        if request.name == "search_files" and args.get("root"):
            path = self.resolve_folder(str(args["root"]))
            if path is None:
                return ValidationOutcome(
                    False,
                    error=f"I'm not allowed to search '{args['root']}'.",
                )
            args["root"] = str(path)

        canonical = request.model_copy(update={"args": args})
        return ValidationOutcome(True, request=canonical)
