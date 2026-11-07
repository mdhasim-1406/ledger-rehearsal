# Operational acceptance status — 2026-11-07

This status reflects current source, not older test counts. Focused backend regression: `backend/.venv/bin/python -m pytest -q backend/tests/test_operational_pipeline.py backend/tests/test_investigation_workflow.py backend/tests/test_investigation_reliability.py backend/tests/test_resolution.py backend/tests/test_agent_resolution_drafts.py backend/tests/test_executed_outcome_corpus.py backend/tests/test_operational_reviewer_workflows.py` — 35 passed. The 7 executed corpus cases cover local synthetic safety behavior only. The full implementation record and startup guidance live in [the operational handoff](../docs/OPERATIONAL_HANDOFF.md).

| Capability | Current status | Evidence / limit |
|---|---|---|
| Protected operational UI and bearer auth | Implemented | Operational UI uses the issued `<token-id>.<secret>` bearer token in memory. Auth boundaries remain server enforced. |
| Bank and ledger CSV import | Implemented | Operator maps source ID, date, description, decimal amount, currency and optional transaction ID; validation preview reports row errors; explicit commit preserves bank revisions and rejects conflicting ledger IDs. |
| Persisted investigation display | Implemented | Exception API returns latest persisted LangGraph result, hypotheses, evidence references, uncertainty/abstention, and linked proposal ID when present. Provider configuration is not present in this environment. |
| Supported resolution | Narrowly supported | Exact identity internal allocation can be proposed, rehearsed, separately approved, applied, and read back. No external financial journal posting. |
| Unsupported/ambiguous cases | Reviewer disposition implemented | Request evidence or record reviewed-unsupported with actor/time/note. Case remains financially open; disposition does not imply resolution. |
| Evidence and audit export | Implemented | Authenticated JSON and CSV exports include evidence, persisted diagnosis, proposals, dispositions, and resolution audit; CSV formula-leading cells are escaped. Semantics state internal-only/no external posting. |
| Evaluation | Implemented, data-limited | UI/API report reads persisted local events/investigations/proposals/dispositions. Reviewer corrections, effort, token use and cost are explicitly unknown because they are not measured. Workspace data provenance is not independently verified. |
| LangGraph runtime | Sole investigation runtime | Current `backend/investigation_agent.py` uses LangGraph SQLite checkpoints; historical no-migration decision is marked superseded. Database remains domain truth; worker dispatch and fenced leases remain outside the graph. |
| Automated verification after current change | Blocked in this sandbox | `npm run build` succeeded. Canonical suite collected 102 tests, passed `test_agent_resolution_drafts.py`, then stalled in unchanged `test_api.py::test_demo_workflow_and_exact_approval` at its POST (`TestClient.handle_request`); the targeted operational workflow test separately stalled during `TestClient` startup. Browser replay cannot create loopback sockets (`PermissionError`). Do not reuse prior 101-pass result as current verification. |
| Live provider / accountant pilot | Blocked | `INVESTIGATION_LLM_API_KEY`, `INVESTIGATION_LLM_BASE_URL`, `INVESTIGATION_LLM_MODEL` unset; no live call or evidence transmission occurred. |
| Production readiness | Not established | Single-workspace SQLite, credential lifecycle, backup/restore, deployment/security review, real-data policy approval and Windows flow remain outstanding. |

No test corpus outcome, mock provider result, or local event count is presented as production telemetry or customer value evidence.
