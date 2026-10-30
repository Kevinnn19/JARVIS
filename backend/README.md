# backend/ — Phase 4 (not implemented yet)

FastAPI communication server: authentication, command routing, WebSocket fan-out,
device status. Runs as a **separate process** from the desktop agent (see
`docs/architecture.md` for why).

Planned layout: `api/{auth,commands,devices,websocket}.py`, `schemas/`,
`services/`, `security/`, `tests/`.

Endpoints are already specified in `../shared/protocol.md`. Nothing here may be
exposed beyond Tailscale, and the public port must never be forwarded.
