# Operational frontend E2E

Validated against a fresh SQLite database and loopback API/Vite servers (API 28753, Vite 28754). The reproducible harness lives in the isolated scratch snapshot at `/home/mohamedhasim/.hermes/cache/scratch/ledger-supervision-20261107-181549/run-front-e2e.sh`; Playwright test: `frontend/tests/operational-e2e.cjs`.

Command: `/home/mohamedhasim/.hermes/cache/scratch/ledger-supervision-20261107-181549/run-front-e2e.sh`

Passed: operational entry is asserted, invalid bearer rejected, generated in-memory bootstrap bearer accepted, API-backed overview loaded, desktop and mobile horizontal overflow absent, no page errors. `npm run build` passes. Screenshot (no credential field) is in scratch snapshot as `frontend-authenticated.png`.

Not yet exercised: synthetic bank/ledger ingestion, automatic case visibility, evidence selection and proposal/rehearsal/approval/apply; current harness verifies login and overview only. Frontend workflow still uses its own stale shape assumption in case-detail/proposal matching; backend scope remained read-only.
