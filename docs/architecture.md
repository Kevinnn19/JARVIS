# Architecture

## The one decision that shapes everything

The **FastAPI communication server** and the **desktop executor** are separate
processes, and the executor lives in your *interactive* Windows session.

A Windows service runs in session 0, which has no access to your visible
desktop: mouse/keyboard automation, window management and screenshots either
fail or target an invisible desktop. So:

```
  Phone (Phase 5)                     Laptop
  ┌───────────┐   Tailscale+HTTPS  ┌──────────────────────────────┐
  │ Android   │ ─────────────────▶ │ FastAPI server (Phase 4)      │
  │ app       │ ◀───────────────── │ auth · routing · WebSocket    │
  └───────────┘                    └───────────────┬──────────────┘
                                                   │ restricted local IPC
                                                   │ (HTTP/WS on 127.0.0.1
                                                   │  + shared-secret header)
                                   ┌───────────────▼──────────────┐
                                   │ Desktop agent (this code)    │
                                   │ runs in YOUR logon session   │
                                   │ parser→validator→permissions│
                                   │ →executor→automation         │
                                   └──────────────────────────────┘
```

Phase 1 ships the bottom box. It is already structured so the box above can be
added without touching security or automation logic: `JarvisAgent.handle()` takes
a `CommandRequest` from *any* transport, and `CommandSource` records whether the
request was local or remote so policy can differ.

## Phase 1 internals

```
text ──▶ CommandParser ──▶ CommandValidator ──▶ TaskExecutor ──▶ TaskRegistry
          (regex rules     (Pydantic args,       (permission,     (one Python
           from config)     allowlists, paths)    timeout, audit)  fn per command)
                                                        │
                                                        ▼
                                        AppController · FileManager · SystemController
                                                        │
                                                        ▼
                                            OperationResult(ok, verified, simulated)
                                                        │
                                                        ▼
                                     CommandResult(status, message, details, duration)
```

### Module responsibilities

| Module | Responsibility | Never does |
|---|---|---|
| `core/command_parser.py` | sentence → `CommandRequest` using ordered regexes from `commands.yaml` | execute, validate paths, know about OS |
| `security/command_validator.py` | typed args, canonicalise app aliases/folders, enforce path allowlist | run anything |
| `security/permission_manager.py` | level lookup, blocked commands, remote ceiling, locked mode, confirmation requirement | talk to the OS |
| `security/confirmation_manager.py` | ticket lifecycle for medium/high risk approvals | auto-approve |
| `core/task_executor.py` | orchestrate the above, enforce timeout, produce the honest `CommandResult`, publish events, write audit | contain automation logic |
| `core/task_registry.py` | the complete capability list; binds names to functions | dynamically dispatch on user text |
| `automation/*` | talk to Windows; verify the result | decide whether it is allowed |
| `core/agent.py` | the facade every UI (CLI now, voice later, HTTP later) uses | know about argparse or FastAPI |
| `utils/logger.py` | human logs + append-only JSONL audit | store secrets |

### Why a rule-based parser instead of an LLM in Phase 1

* **Determinism** — same sentence, same command; tests are meaningful.
* **Offline and free** — no API key, no latency, no data leaves the laptop.
* **Bounded** — it cannot invent `execute_shell_command`; if no regex matches,
  the answer is "I don't have a command for that", plus suggestions.
* **Auditable** — every sentence pattern JARVIS understands is 40 lines of YAML.

An LLM can later sit *in front* of this parser to rewrite sloppy phrasing into a
canonical sentence, but the registry and validator still decide what happens.

### Why verification is in the automation layer

`AppController.launch()` polls `psutil` for a process from the app's
`process_names` after spawning. `close()` waits for the process to actually
disappear (escalating from `terminate` to `kill`). Screenshots confirm the file
exists and is non-empty. This is what makes the acceptance criterion
"JARVIS must not say a file was deleted just because it received the request"
achievable at every layer, not just as an afterthought.

### Concurrency and timeouts

Handlers run in a small thread pool with a hard `command_timeout_seconds`
(default 20 s). A hung automation call becomes a `timeout` result instead of a
frozen assistant. Note that a Python thread cannot be forcibly killed — the
executor stops *waiting* and reports; that is why handlers must also keep their
own internal bounds (search has a wall-clock deadline, close has a 5 s grace).

### Data contracts

`core/schemas.py` is the single source of truth. `scripts/export_schema.py`
generates `shared/command-schema.json`, which the FastAPI server and the React
Native client will consume — so the phone and the laptop cannot drift apart on
what a command looks like.

## Planned additions (and where they plug in)

| Phase | Addition | Plugs into |
|---|---|---|
| 2 | microphone, faster-whisper, pyttsx3, wake word | new `voice/` package; calls `agent.handle_text(text, LOCAL_VOICE)`; `ResponseEngine.speak` already exists |
| 3 | login, tokens, device registration, confirmation UI | `backend/` + `Confirmer` implementations (console → toast → phone prompt) |
| 4 | FastAPI + WebSocket, device status, remote lock | `communication/` + `agent.handle(request)` with `source=REMOTE_*` |
| 5 | Expo app: login, push-to-talk (Android STT), dashboard, history | consumes `shared/command-schema.json` + WS events |
| 6 | screen-off operation, autostart, end-to-end tests | `scripts/`, `docs/` |

### SQLite arrives in Phase 3, deliberately

Phase 1 writes an append-only JSONL audit log (`~/.jarvis/logs/audit.jsonl`) —
enough to prove what happened, with zero migration risk while the schema is
still moving. When the phone needs to page through command history and query
"what ran yesterday", the repository layer in `database/` will move that data
into SQLite.
