# Operational handoff and release gates

## Modes are separate

`backend/main.py` is the legacy synthetic/demo API (default DB `backend/ledger-demo.sqlite3`, overridable with `LEDGER_DEMO_DB`). It is not the operational service and its records are not real financial data. `backend/operational_api_main.py` runs the secured operational API and requires both `OPERATIONAL_DB` and `OPERATIONAL_ADMIN_CREDENTIAL`; it defaults to loopback host and port 8765. Do not point the operational service at or convert the demo database. Preserve both stores independently.

Operational startup serves Vite's UI on loopback; its `/api` proxy forwards same-origin browser calls to `VITE_OPERATIONAL_API` (default `http://127.0.0.1:8765`). Set `OPERATIONAL_PORT` to match that target; `LEDGER_FRONTEND_PORT` selects UI port. `OPERATIONAL_ADMIN_CREDENTIAL` is an initial bootstrap credential, minimum 16 characters; auth issues bearer token `<token-id>.<secret>`. Keep it in a private process environment, not source control, shell history, logs or command-line arguments. The issued token is not interactively printed by the launcher; provision/enter it through a secure client workflow. The app does not provide a credential rotation workflow in this handoff.

## Setup and run

Linux/WSL: `./scripts/setup.sh`, then export `OPERATIONAL_ADMIN_CREDENTIAL` from a private secret manager/shell prompt, then `./start.sh`. Windows: `scripts\setup.bat`, then set that environment variable in a private PowerShell session (`$env:OPERATIONAL_ADMIN_CREDENTIAL = ...`) and run `start.bat`. Do not save real credentials in `.bat`, `.sh`, or `.env` files. Configure `OPERATIONAL_DB` to an absolute durable path (default `data/operational.sqlite3`). Back up and protect the file and its directory; do not share it across concurrent service instances. Start scripts do not stop unrelated processes. Linux launcher stops only its own child processes on exit; Windows API is a separate child console and must be stopped there.

The API `/health` endpoint is liveness only, not proof of readiness, reconciliation correctness, or production suitability. SQLite supports a local single-workspace deployment, not multi-user distributed/high-availability operation. The current configured pipeline uses local rule-based operations; this handoff makes no external bank, ERP, AI-provider or finance-system integration claim. Inspect external-provider requirements and security/recovery controls before enabling any such integration.

## Release blockers / acceptance gates

- Establish a supported real-client path to securely obtain/issue and rotate/revoke credentials; bootstrap is not a complete account lifecycle. Do not claim rotation is implemented.
- Review authorization model, bootstrap migration, token persistence, filesystem permissions, secret storage, auditability, CSRF/origin behavior and security threat model with the owning backend team.
- Obtain product/finance owner approval for source-of-truth, import mapping, currency/date semantics, duplicate handling, reconciliation rules, human approval, correction/rollback and audit retention using representative non-synthetic data.
- Establish tested backup/restore, retention, monitoring, incident response and upgrade/migration procedures; assess SQLite single-workspace limits against actual usage.
- Live model/accountant pilot remains blocked until a provider is deliberately configured and evidence handling is authorized. Provider output remains advisory; reviewers and the internal allocation safeguards control proposals.
- Configure and validate any required external providers using their verified documented environment-variable names and credentials. No provider-specific credentials are assumed or included here.
- Run full regression, dependency/security review, accessibility and deployment review. Passing local smoke checks does not authorize production release.

A smoke script for fresh isolated setup/start verifies only local process boot, health, authenticated record API access and same-origin proxy routing. It does not perform business acceptance or external integrations.

## Current implementation record (2026-11-07)

**Implemented:** authenticated operational UI; CSV source import with required-field mapping, exact decimal validation, row-level preview errors and explicit commit; immutable source versions; persisted LangGraph investigation diagnosis and evidence references in reviewer case rows; safe exact internal allocation proposal/rehearsal/approval/apply; explicit request-evidence and reviewed-unsupported dispositions that leave financial case status open; authenticated JSON/CSV evidence, resolution proposal, reviewer disposition, and audit exports with spreadsheet formula escaping; persisted-workspace evaluation counts with unmeasured effort, reviewer corrections, tokens and cost labeled unknown. External journal posting is not implemented.

**Verified in this work:** frontend production bundle builds (`npm run build`); focused worker/agent/resolution regressions and synthetic representative exact/date/amount/fee/duplicate/missing-counterpart/missing-identity/currency corpus pass (`backend/.venv/bin/python -m pytest -q backend/tests/test_operational_pipeline.py backend/tests/test_investigation_workflow.py backend/tests/test_investigation_reliability.py backend/tests/test_resolution.py backend/tests/test_agent_resolution_drafts.py backend/tests/test_executed_outcome_corpus.py backend/tests/test_operational_reviewer_workflows.py`: 35 passed). Python syntax compilation succeeds for the operational API and reviewer workflow test. Prior repository state reported 101 backend tests passing and the browser lifecycle replay passing; those results predate this change and are not a verification of it.

**Remaining verification/blockers:** this sandbox denied loopback socket creation while starting `scripts/verify_browser_lifecycle.py`; the canonical backend suite collected 102 tests, passed one, then stalled inside an unchanged demo API test request; the targeted operational HTTP test also stalled at `TestClient` startup, so full backend HTTP verification is unavailable. The four `INVESTIGATION_LLM_*` settings and bootstrap credential were unset; no live provider run occurred. Customer/accountant outcome quality, real-data provenance, Windows run, production deployment/security review and backup/restore remain unverified. Do not claim production readiness or customer problem resolution from local implementation/tests.
