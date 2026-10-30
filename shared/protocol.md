# JARVIS wire protocol (v1) — contract for Phases 4–5

Phase 1 has no network layer. This document fixes the contract *now* so the
FastAPI server (Phase 4) and the Android app (Phase 5) are built against the
same shapes the desktop agent already produces, and so the agent never needs a
"network version" of its security logic.

Machine-readable schemas: [`command-schema.json`](command-schema.json)
(regenerate with `python scripts/export_schema.py` after editing
`desktop-agent/core/schemas.py`).

## Transport

* HTTPS + WSS only, reachable **only** over Tailscale (no port forwarding, no
  public DNS name).
* Bind address: `0.0.0.0:<JARVIS_PORT>` on the laptop so the Tailscale interface
  can reach it; the Windows firewall rule must be scoped to the Tailscale
  adapter, not "any network".
* The FastAPI process talks to the desktop agent over a loopback-only,
  shared-secret-authenticated channel. The agent's automation never listens on
  the network directly.

## Envelope: command request

```json
{
  "command_id": "cmd_9f2c1a7b3d4e",
  "name": "open_application",
  "args": { "application": "chrome" },
  "raw_text": "open chrome",
  "source": "remote_voice",
  "created_at": "2026-10-30T06:30:00Z"
}
```

Rules:

* `name` **must** exist in the registry; the server does not transform it.
* `args` is validated by the per-command model (`extra="forbid"`). Unknown
  fields are a client bug and produce `rejected`, not a crash.
* `source` is set by the server, never trusted from the client body. A phone
  request is `remote_api` / `remote_voice`, which lowers the trust level and can
  require confirmation for medium/high commands.

## Envelope: result

```json
{
  "command_id": "cmd_9f2c1a7b3d4e",
  "name": "open_application",
  "status": "success",
  "message": "Google Chrome is now open.",
  "permission": "low",
  "details": { "verified": true, "simulated": false, "pids": [4820] },
  "started_at": "2026-10-30T06:30:00Z",
  "finished_at": "2026-10-30T06:30:01Z",
  "duration_ms": 812
}
```

`status` ∈ `success | dry_run | failure | rejected | pending_confirmation |
timeout | parse_error`.

The phone must render `dry_run` differently from `success`, and must never infer
success from the HTTP 200 alone — an accepted command is not a completed one.

## REST endpoints (Phase 4)

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/auth/login` | password (+ later WebAuthn) → access + refresh token |
| `POST` | `/auth/refresh` | rotate refresh token |
| `POST` | `/auth/logout` | revoke the current device session |
| `GET` | `/device/status` | hostname, uptime, battery, locked state, dry_run |
| `POST` | `/commands` | submit a `CommandRequest` → `CommandResult` (202 + id if async) |
| `GET` | `/commands/{id}` | result lookup / polling fallback |
| `GET` | `/commands?limit=n` | activity history (Phase 3 SQLite) |
| `POST` | `/security/lock` | engage emergency stop |
| `POST` | `/security/unlock` | resume (requires password re-auth) |
| `POST` | `/confirmations/{ticket_id}` | approve/deny a `pending_confirmation` |

## WebSocket

`WSS /ws?token=<access_token>` — one multiplexed stream, JSON frames.

Client → server:

```json
{ "type": "command", "payload": { "name": "status", "args": {}, "raw_text": "status" } }
{ "type": "ping" }
{ "type": "confirm", "payload": { "ticket_id": "cfm_ab12cd", "approved": true } }
```

Server → client:

```json
{ "type": "result",  "payload": { /* CommandResult */ } }
{ "type": "event",   "payload": { "topic": "agent.locked", "reason": "phone request" } }
{ "type": "status",  "payload": { "online": true, "locked": false, "last_seen": "..." } }
{ "type": "confirmation_required", "payload": { "ticket_id": "cfm_ab12cd", "summary": "delete file (path=…)", "expires_in": 30 } }
{ "type": "pong" }
```

## Notes the phone must respect

1. Phone speech is converted to **text on the device** (Android STT) and sent as
   `source: remote_voice`. No raw audio is streamed in v1.
2. High-risk commands are never executed on request; they return
   `pending_confirmation` and wait for an explicit approval frame (or a prompt on
   the laptop), then expire.
3. A `pending_confirmation` ticket is bound to the requesting `command_id` and
   cannot be replayed against a different command.
4. If `/device/status` reports the laptop asleep or the agent offline, the UI
   must show "unavailable" rather than queue commands silently.
