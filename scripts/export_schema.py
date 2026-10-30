"""Export the shared command/result JSON Schema for the phone & API layers.

    python scripts/export_schema.py

Writes shared/command-schema.json from the Pydantic models, so the React Native
client and the FastAPI server in later phases validate against exactly the same
contract the desktop agent uses. Run it after changing core/schemas.py.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "desktop-agent"))

from core import schemas  # noqa: E402


def build() -> dict:
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "https://jarvis.local/schemas/command-schema.json",
        "title": "JARVIS command protocol (v1)",
        "description": (
            "Shared contract between the Android app, the FastAPI server and the "
            "Windows desktop agent. A command is a typed request, never code."
        ),
        "$defs": {
            "CommandRequest": schemas.CommandRequest.model_json_schema(),
            "CommandResult": schemas.CommandResult.model_json_schema(),
            "ParseResult": schemas.ParseResult.model_json_schema(),
            "CommandSource": {
                "type": "string",
                "enum": [s.value for s in schemas.CommandSource],
            },
            "ExecutionStatus": {"type": "string", "enum": [s.value for s in schemas.ExecutionStatus]},
            "PermissionLevel": {"type": "string", "enum": [s.value for s in schemas.PermissionLevel]},
            "commands": {
                "description": "name -> argument schema. args are validated before any handler runs.",
                "type": "object",
                "properties": {
                    name: model.model_json_schema() for name, model in schemas.ARGS_MODELS.items()
                },
                "additionalProperties": False,
            },
        },
    }


def main() -> int:
    target = REPO_ROOT / "shared" / "command-schema.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(build(), indent=2) + "\n", encoding="utf-8")
    print(f"wrote {target.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
