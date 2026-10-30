# database/ — Phase 3 (not implemented yet)

Phase 1 writes an append-only JSONL audit log (`utils/logger.py` →
`~/.jarvis/logs/audit.jsonl`) instead of a database, so the schema can settle
while the phone UI does not yet exist.

When command history needs paging/searching on the phone, add:

* `database.py` — SQLite connection + migrations (schema version table)
* `models.py` — `commands`, `devices`, `sessions`, `confirmations`
* `repository.py` — write-behind from the audit log; the agent keeps writing
  JSONL as the source of truth even after SQLite exists
