# Security

The real risk is not "someone opens Chrome". It is unauthorized access that
deletes files, shuts the laptop down, or drives your applications while you are
away. This document states what the current code actually guarantees, and what
it does not yet.

## Five layers

| Layer | Purpose | Phase 1 status |
|---|---|---|
| 1. Phone authentication | password/PIN, Android biometrics, device registration, short-lived access tokens, refresh rotation, revoke-device | **not built** (Phase 3) |
| 2. Private network | Tailscale-only reachability, no port forwarding, deny-by-default grants | **not built** (Phase 4) |
| 3. Command authorization | permission levels, blocked commands, confirmation gate, emergency stop | **implemented** |
| 4. Voice security | wake word, push-to-talk, speaker verification later, confirmation for sensitive ops | **not built** (Phase 2) |
| 5. Safe execution | registry-only capabilities, typed args, path allowlist, timeouts, audit log | **implemented** |

Because layers 1, 2 and 4 do not exist yet, **Phase 1 must not be exposed to a
network**. It has no listener at all: it only reads from your terminal, and every
request is treated as `local_typed` unless a future transport labels it
otherwise. That is the correct posture until Phase 3/4 land.

## What the code enforces today

### 1. Registry-only capabilities

`core/task_registry.py` contains nine commands. Each binds a plain Python
function; nothing else in the codebase can be reached from user input. There is
no `eval`, no `exec`, no `subprocess` call built from a sentence, and no plugin
loading. A command that is not registered cannot execute at two independent
levels: the validator has no argument schema for it, and the executor refuses
anything the registry does not contain.

`execute_shell_command` and `modify_security_settings` are declared in
`permissions.yaml` as `blocked`, so even a future parser that produced them
would be refused with a stated reason rather than silently failing.

### 2. Natural language never becomes code

The parser emits a structured request:

```json
{ "name": "open_application", "args": { "application": "chrome" } }
```

Arguments are validated against a per-command Pydantic model with
`extra="forbid"`, length bounds, and range checks (`set_volume.level` is
0–100). Consequences, all covered by tests:

* `open chrome && rm -rf /` → the application argument becomes
  `"chrome && rm -rf /"` → rejected as not allowlisted.
* `open_application` with an extra `shell` argument → rejected (extra field).
* `search_files` with query `*` → rejected (too broad).
* `open winrar` → rejected with the list of approved applications.

### 3. Allowlists, not guesses

Applications come from `config/applications.yaml` (aliases, process names,
launcher paths). Folders come from a fixed set of friendly names, or an absolute
path **inside** an allowed root. `search_files` cannot be pointed at `C:\Windows`,
`/etc`, or `..`: the root is resolved and checked before the search runs, and
the walker itself skips system/noise directories.

### 4. Permission levels and the remote ceiling

`config/permissions.yaml` assigns `low | medium | high | blocked`. Policy also
declares:

* `trusted_local_sources` — what counts as "the owner at the keyboard";
* `max_remote_permission` — a hard ceiling for anything that arrives remotely;
* `confirm_high_always` — high risk is never auto-approved;
* `allow_only_when_locked` — if the emergency stop is engaged, only `status` and
  `stop` are accepted.

The emergency stop is real: `agent.lock()` flips the policy engine, so parsed
`help`, `set_volume`, `search_files`, ... all come back `rejected` until
`unlock()`. Tests assert this.

### 5. Confirmation gate

If policy says a request needs confirmation, the executor asks a `Confirmer`
and, unless it gets an explicit `yes`, returns `pending_confirmation` **without
running the handler** (tested by asserting the handler was never called). For
remote or unattended sources the default is `AutoDenyConfirmer` — the safe
failure mode. Phase 3 replaces it with a Windows toast and an Android approval
sheet; the executor does not change.

### 6. Timeouts, locking down the blast radius

* Every command has a hard timeout (default 20 s) → `timeout` status.
* Search has a wall-clock budget, max depth, max results, and skips noise.
* App close is graceful (`terminate`) then forceful (`kill`), verified.
* A handler exception is caught and reported as `failure` with the exception
  type — the agent never crashes mid-command.

### 7. Audit trail

Every attempt writes one JSON Lines record to `~/.jarvis/logs/audit.jsonl`:

```json
{"ts":"2026-10-30T06:30:00+00:00","event":"command","command_id":"cmd_1f3…",
 "name":"open_application","args":{"application":"chrome"},"raw_text":"open chrome",
 "source":"local_typed","status":"success","permission":"low",
 "message":"Google Chrome is now open.","duration_ms":812,"details":{...}}
```

Also recorded: `agent.start`, `agent.locked`, `agent.unlocked`, `parse_failed`,
`validation_failed`. Keys named like secrets (`password`, `token`, …) are
redacted before writing. Review with `:audit 20` in the CLI.

## Threat model for Phase 1

| Threat | Mitigation | Residual risk |
|---|---|---|
| Malicious sentence trying to reach the shell | registry + typed args | none known; no shell path exists |
| Prompt-injecting text (e.g. from a copied web page) | parser only maps to registered commands; unknown → refusal | low |
| Path traversal / system-directory operations | allowed roots + protected paths; destructive ops not implemented | low |
| Someone at the keyboard | out of scope — local physical access is trusted by design | accepted |
| Network attacker | no listener exists in Phase 1 | none until Phase 4 |
| Runaway/hung automation | timeouts, bounded search | a stuck thread can linger (documented) |
| Silent wrong answers ("deleted" when not) | `verified`/`simulated` flags, dry-run status, real post-checks | low |

## Non-negotiable rules for later phases

1. Never open the FastAPI port to the internet; Tailscale only, deny-by-default
   grants (Android → laptop:JARVIS_PORT).
2. Never store passwords or refresh tokens in plaintext. Android Keystore-backed
   secure storage; hashed password (`argon2`/`bcrypt`) server-side.
3. Access tokens short-lived; refresh tokens rotated and revocable per device.
4. Voice is never an authentication factor by itself. A recording or a cloned
   voice must not be able to delete files or shut the machine down.
5. High-risk commands always require an explicit confirmation, from a different
   channel than the one that requested them.
6. Keep `execute_shell_command` blocked. If a real need appears, add a specific
   registered command for it — never a general shell.
7. Keep the audit log append-only, and keep `dry_run` distinct from `success` in
   every new handler.
