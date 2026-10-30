# JARVIS

A secure, remote-controllable desktop assistant for **Windows 11 + Android**.

Phase 1 is complete: a Windows desktop agent that accepts **typed** commands,
executes them through an allowlisted command registry, and reports what actually
happened. Voice (Phase 2), authentication (Phase 3), the FastAPI/Tailscale
transport (Phase 4) and the React Native app (Phase 5) build on top of this same
core without being redesigned around it.

```
              ┌──────────────────────── Phase 1 (this code) ────────────────────────┐
  you ──text──▶ CommandParser ──▶ CommandValidator ──▶ PermissionManager ──▶ Executor
                     │                    │                    │                 │
              config/commands.yaml  allowlists            permissions.yaml  TaskRegistry
                                                                                │
                                                   AppController · FileManager · SystemController
                                                                                │
                                                                     verified result + audit log
```

---

## What works right now

| Capability | Command examples | Status |
|---|---|---|
| Open an allowlisted app | `open chrome`, `open notepad`, `launch vs code` | ✅ verified launch |
| Close an app | `close chrome`, `quit notepad` | ✅ verified close |
| Open a user folder | `open downloads`, `show documents` | ✅ |
| Search files by name | `search for invoice`, `find report in downloads` | ✅ bounded search |
| Set system volume | `set volume to 30`, `mute` | ✅ Windows (pycaw) |
| Screenshot | `take a screenshot` | ✅ Windows (pyautogui) |
| Machine status | `status` | ✅ |
| Help / stop | `help`, `stop` | ✅ |
| Remove / move / rename a file | — | 🚫 Phase 3 (with confirmation) |
| Shutdown / restart / shell | — | 🚫 blocked by policy |

Verified means JARVIS polls the process table (or the filesystem) after acting
and reports the real outcome. It never says "Chrome is open" because it sent a
spawn request. `--dry-run` results are labelled `dry_run`, never `success`.

---

## Quick start — Windows 11

```powershell
# from the repo root
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\scripts\setup_windows.ps1          # venv + deps + tests
.\scripts\start_jarvis.ps1           # interactive
```

Or manually:

```powershell
cd desktop-agent
py -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
python main.py
```

Boring-but-important: always try `--dry-run` first. It simulates every action and
touches nothing.

```powershell
python main.py --dry-run
python main.py --once "open chrome"       # single command, exit
python main.py --json --once "status"     # machine-readable, for scripts
```

## Quick start — any OS (Linux/macOS, CI, this sandbox)

```bash
cd desktop-agent
python -m pytest tests -q          # 53 tests, no Windows required
python main.py --self-test         # show how sentences map to commands
python main.py --dry-run           # interactive rehearsal
```

Application launching, volume and screenshots are Windows-targeted; on Linux the
agent tells you so instead of pretending. Parsing, validation, permissions,
search, audit and the whole command pipeline are fully cross-platform.

---

## Sample session (real output, `--dry-run`)

```
you> open chrome
◌ [dry run] Would launch Google Chrome
you> open downloads
◌ [dry run] Would open folder /home/user/Downloads
you> search for invoice
✔ Found 1 file(s) matching 'invoice': invoice-2026.pdf
you> open winrar
⛔ 'winrar' is not an approved application. Known: Calculator, File Explorer,
   Google Chrome, Notepad, Spotify, Visual Studio Code
you> make me a sandwich
… I don't have a command for 'make me a sandwich'. Try: open chrome; status; help
```

---

## Security model (what exists in Phase 1)

| Layer | Mechanism | State |
|---|---|---|
| 1. Phone authentication | password + biometric + token rotation | Phase 3 |
| 2. Private network | Tailscale, no port forwarding | Phase 4 |
| 3. Command authorization | `permissions.yaml` levels + confirmation gate + lock/emergency-stop | ✅ |
| 4. Voice security | wake word, push-to-talk, speaker verification later | Phase 2 |
| 5. Safe execution | command registry, Pydantic args, path allowlist, timeouts, audit | ✅ |

Three rules the code enforces, not just documents:

1. **Nothing runs that is not registered.** `core/task_registry.py` is the only
   place a capability can be added, and every entry binds a plain Python
   function to a command name. There is no `eval`, no `exec`, no shell string.
2. **Natural language never becomes code.** The parser emits a `CommandRequest`
   whose `args` must validate against a per-command Pydantic model with
   `extra="forbid"`; `open chrome && rm -rf /` becomes the *argument*
   `"chrome && rm -rf /"`, which is then rejected as an unknown application.
3. **Reports are truthful.** Every handler returns an `OperationResult` carrying
   `verified`/`simulated` flags; the executor maps them to
   `success / dry_run / failure / rejected / pending_confirmation / timeout`.

Details and threat model: [`docs/security.md`](docs/security.md).

---

## Repository map

```
JARVIS/
├── desktop-agent/          # the Windows agent (Phase 1 complete)
│   ├── main.py             # CLI: REPL, --once, --dry-run, --json, --self-test
│   ├── config.py           # loads + validates config/*.yaml into frozen Settings
│   ├── core/
│   │   ├── schemas.py       # CommandRequest/CommandResult + per-command arg models
│   │   ├── command_parser.py# regexes (config/commands.yaml) -> structured command
│   │   ├── task_registry.py # THE allowlist of capabilities
│   │   ├── task_executor.py # permission check, timeout, honest status, audit
│   │   ├── agent.py         # JarvisAgent: the one facade every UI talks to
│   │   ├── response_engine.py
│   │   └── event_bus.py
│   ├── automation/          # app_controller, file_manager, system_controller
│   ├── security/            # permission_manager, command_validator, confirmation_manager
│   ├── utils/               # logging + append-only JSONL audit, OS helpers
│   └── tests/               # 53 tests: parsing, security, automation
├── config/                  # applications.yaml, commands.yaml, permissions.yaml, settings.yaml
├── shared/                  # command-schema.json (exported) + protocol.md
├── scripts/                 # setup_windows.ps1, start_jarvis.ps1, install_autostart.ps1
├── docs/                    # architecture.md, security.md, commands.md
├── backend/                 # Phase 4 — FastAPI + WebSocket (empty by design)
└── mobile-app/              # Phase 5 — React Native + Expo (empty by design)
```

The agent is intentionally dependency-light: `pydantic`, `PyYAML`, `psutil`
(+ `pycaw`/`pyautogui` on Windows). No framework is installed before the phase
that needs it.

---

## Extending it

* **New application:** add an entry to `config/applications.yaml` (aliases +
  process names + launcher paths). No code change.
* **New sentence pattern:** add a regex to `config/commands.yaml` under the
  command name. No code change.
* **New capability:** add an arg model in `core/schemas.py`, a `RegisteredCommand`
  in `core/task_registry.py`, a level in `config/permissions.yaml`, and a test.
  See [`docs/commands.md`](docs/commands.md).

## Roadmap

| Phase | Deliverable | State |
|---|---|---|
| 1 | Typed commands control Windows (open/close/search/volume/screenshot/status) | ✅ done |
| 2 | Voice: faster-whisper STT, pyttsx3 TTS, push-to-talk, wake word | next |
| 3 | Auth, sessions, confirmation prompts, safe deletion, activity log UI | |
| 4 | FastAPI + WebSocket + device status, Tailscale, emergency stop over network | |
| 5 | React Native (Expo) app: login, biometrics, push-to-talk, dashboard, history | |
| 6 | End-to-end tests, screen-off operation, autostart, hardening | |

## Tests

```bash
cd desktop-agent && python -m pytest tests -q
```

53 tests covering: sentence → command mapping, allowlist rejection, path policy,
permission levels, remote cap, locked mode, confirmation gate, handler timeouts,
verified launch/close of a real process, bounded search, and the audit trail.

## License

MIT — see [`LICENSE`](LICENSE).
