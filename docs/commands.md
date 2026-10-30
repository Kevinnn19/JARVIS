# Command library (Phase 1)

Nine commands, each mapped to one tested Python function. This is deliberately
small: reliability first, breadth later.

| Command | Permission | Args (validated) | Example sentences | Handler |
|---|---|---|---|---|
| `open_application` | low | `application` (allowlisted key), `arguments` (≤8 strings) | "open chrome", "launch notepad", "start vs code" | `AppController.launch` → verified via process table |
| `close_application` | low | `application` | "close chrome", "quit notepad" | `AppController.close` → verified |
| `open_folder` | low | `folder` (friendly name or allowed path) | "open downloads", "show documents" | `AppController.open_folder_path` |
| `search_files` | low | `query` (1–120), `root` (optional), `limit` (1–100) | "search for invoice", "find report in downloads" | `FileManager.search` → bounded walk |
| `set_volume` | low | `level` (0–100) | "set volume to 30", "mute" | `SystemController.set_volume` (pycaw) |
| `screenshot` | low | — | "take a screenshot" | `SystemController.screenshot` → file verified |
| `status` | low | — | "status", "are you there" | `SystemController.status` (psutil) |
| `help` | low | — | "help", "what can you do" | `TaskRegistry.help_text` |
| `stop` | low | — | "stop", "never mind" | no-op ack; also accepts CLI `:lock` |

Declared but **not executed** in Phase 1 (they exist so policy is reviewable and
Phase 3 has nothing to invent):

| Command | Permission | Confirmation | Notes |
|---|---|---|---|
| `rename_file` | medium | always | Phase 3 |
| `move_file` | medium | always | Phase 3 |
| `delete_file` | high | always | Recycle Bin first, never `shutil.rmtree` |
| `empty_recycle_bin` | high | always | |
| `shutdown_system` / `restart_system` | high | always | |
| `lock_workstation` | medium | remote only | |
| `execute_shell_command` | **blocked** | — | never |
| `modify_security_settings` | **blocked** | — | requires manual action |

## How a sentence becomes an action

```
"JARVIS, open Chrome."
  → normalise            "open chrome"
  → commands.yaml rule   open_application, application="chrome"
  → CommandValidator     alias "chrome" → allowlist key "chrome"
  → PermissionManager    low, no confirmation
  → TaskRegistry         AppController.launch(spec)
  → AppController        resolve launcher → spawn → poll psutil ≤6s
  → OperationResult      ok=True, verified=True, pids=[…]
  → CommandResult        status=success, "Google Chrome is now open."
  → audit + event bus
```

## Adding a sentence pattern (no code)

```yaml
# config/commands.yaml
patterns:
  open_application:
    - '^(?:jarvis[,\s]+)?(?:can\s+you\s+|please\s+)?(?:open|launch|start|run)\s+(?:the\s+|my\s+)?(?P<application>.+)$'
    - '^(?:jarvis[,\s]+)?(?:fire\s+up)\s+(?P<application>.+)$'   # new phrasing
```

Named groups become command arguments. Rules are tried in `command_order`
sequence, so the first match wins — keep the more specific commands above the
general ones (that is why `open_folder` precedes `open_application`).

## Adding an application (no code)

```yaml
# config/applications.yaml
applications:
  slack:
    display_name: Slack
    aliases: [slack]
    process_names:
      windows: [slack.exe]
    windows:
      launch:
        - "${LocalAppData}\\slack\\slack.exe"
```

`process_names` is what makes verification possible — omit it and JARVIS can
launch the app but cannot honestly confirm it started.

## Adding a new capability (code + tests)

1. **Arg model** — `core/schemas.py`:

   ```python
   class OpenUrlArgs(_StrictArgs):
       url: str = Field(min_length=1, max_length=2048)
   ARGS_MODELS["open_url"] = OpenUrlArgs
   ```

2. **Handler** — the automation module that owns the risk (here
   `automation/browser_controller.py`), returning `OperationResult` and setting
   `verified=True` only if it checked the outcome. Treat the URL as untrusted:
   allow `https` only, reject `file://`, `javascript:`.

3. **Registration** — `core/task_registry.py`:

   ```python
   self.register(RegisteredCommand(
       name="open_url",
       description="Open a website in the default browser.",
       handler=lambda args: self.browser.open_url(args["url"]),
       examples=["open github.com"],
   ))
   ```

4. **Permission** — `config/permissions.yaml`:

   ```yaml
   open_url: { permission: low }
   ```

5. **Pattern** — `config/commands.yaml` (add to `command_order` too).

6. **Tests** — happy path, rejection path, and one test proving no side effect
   happens when validation fails.

7. **Docs** — add a row to the table above. A command that is not documented is
   not finished.
