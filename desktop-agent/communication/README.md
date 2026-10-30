# communication/ — Phase 4 (not implemented yet)

The FastAPI server lives in `/backend`. This package holds the *laptop side* of
the local IPC bridge:

* `local_ipc.py` — loopback-only HTTP/WS client the FastAPI process uses to hand
  a `CommandRequest` to this agent, authenticated with a shared secret stored in
  Windows Credential Manager (never in the repo).
* `websocket_server.py` — pushes `EventBus` events (command results, lock state)
  to the backend for fan-out to the phone.

Constraints that must not be relaxed:
* never bind the agent's automation surface to a non-loopback interface;
* `source` on remote requests is set by the backend, not by the client;
* remote requests respect `max_remote_permission` and require confirmation for
  medium/high risk.
