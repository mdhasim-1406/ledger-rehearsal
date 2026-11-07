# Operational database recovery

The operational API uses SQLite. Keep backups outside the repository and restrict
filesystem permissions to the service operator; the database contains operational
records and authentication state. Never put credentials, tokens, or database contents
in a backup filename, command transcript, or support ticket.

## Create a consistent backup

Stop writes if you need a quiescent handoff. The helper uses SQLite's online backup
API, which gives a consistent snapshot even while the database is open and includes
committed WAL data. It validates the result with `PRAGMA quick_check` and refuses to
overwrite an existing destination.

```sh
backend/.venv/bin/python scripts/backup_operational.py /path/to/operational.sqlite /secure/backups/operational-YYYYMMDD.sqlite
```

Keep the original database untouched. Transfer the resulting file using your approved
secure channel and access controls. Do not copy only the main `.sqlite` file while a
live WAL database is active.

## Restore as a separate file

Restore by copying the backup to a **new** path, never over the active database. For
example, after securely transferring the backup to the recovery host:

```sh
cp --no-clobber /secure/backups/operational-YYYYMMDD.sqlite /secure/recovery/operational-restored.sqlite
backend/.venv/bin/python -c 'import sqlite3,sys; c=sqlite3.connect(sys.argv[1]); print(c.execute("PRAGMA integrity_check").fetchone()[0]); c.close()' /secure/recovery/operational-restored.sqlite
```

Proceed only when integrity check reports `ok`. Configure a separately reviewed
service instance with `OPERATIONAL_DB` pointing at the restored file and the required
`OPERATIONAL_ADMIN_CREDENTIAL` supplied through your secret manager; do not put secrets
in shell history or this document. Verify `/health`, authenticated reads, and expected
record/event counts before routing traffic. Preserve the original database and backup
until recovery is accepted. This procedure does not configure services, copy secrets,
or authorize replacing production data.

## Handoff checks

- Record source/backup paths, UTC timestamp, operator, and integrity-check outcome in
a restricted recovery log; never log database contents or secret values.
- Retain backups according to the organization's encryption, access, and retention
policies. The helper does not encrypt the output itself.
- Exercise restore periodically into a new isolated file and validate representative
records and events before declaring the handoff complete.
