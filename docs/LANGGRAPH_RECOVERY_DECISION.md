# Superseded: pre-migration LangGraph recovery decision

This document records the earlier decision to retain the custom investigation runtime. That decision is superseded. LangGraph is now the sole investigation runtime; do not treat the historical no-migration recommendation below as current architecture guidance. Current implementation and release status are in [OPERATIONAL_HANDOFF.md](OPERATIONAL_HANDOFF.md).

Decision: retain the current production runtime. LangGraph improves checkpoint recovery in the isolated experiment, but reduction in application complexity was not demonstrated. The user's adoption condition requires both.

## Implemented and verified

- Worker renews fenced queue leases while processing. Lease ownership and generation are checked within the final investigation write transaction.
- Current source/candidate evidence is compared within BEGIN IMMEDIATE before creating a draft.
- Draft, proposed audit event, and investigation result share one SQLite transaction. Replaying the same case/evidence digest reads the existing result rather than creating another draft.
- ResolutionService.propose accepts an optional caller-owned connection while preserving its existing independently transactional API.

Regression evidence: four failing tests were reproduced before fixes (replay duplication, stale draft creation, missing heartbeat interface, lost-lease mutation). The original audit-hook fault test already passed because propose itself rolls back; it was strengthened to fail the investigation INSERT after successful draft creation with an SQLite trigger. The strengthened test proves draft and audit rollback, followed by one successful retry.

Final backend suite: 99 passed, two existing deprecation warnings. Browser lifecycle replay passed after changes: API ingest, automatic case, evidence, proposal, rehearsal, distinct approval, apply and resolved readback.

## Isolated recovery experiment

Environment: scratch-only virtualenv; langgraph 1.2.20, langgraph-checkpoint-sqlite 3.1.3. No project dependencies changed.

Script: /home/mohamedhasim/.hermes/cache/scratch/ledger-langgraph-experiment/recovery.py
Interpreter: /home/mohamedhasim/.hermes/cache/scratch/ledger-langgraph-experiment/bin/python

Two sequential synthetic read-only stages, model then tool. A separate process exits using os._exit(77) on the first tool attempt. A fresh process restarts or resumes the run. No actual model/provider called.

- Whole-job replay surrogate: model executed twice, tool completed once; restart succeeded.
- LangGraph with synchronous SQLite checkpoints: model executed once, tool completed once; resume succeeded.

This establishes checkpoint reuse of the completed first stage. It does not benchmark our full production worker or prove exactly-once arbitrary side effects. The custom branch represents current whole-investigation replay semantics, not an import of the application adapter.

## Complexity assessment

The graph introduces persistent checkpointer storage, thread identity, serialization and node boundaries. It does not remove transactional outbox dispatch, fenced leases, stale-evidence validation, atomic draft persistence, or authenticated human approval. Existing code has no intermediate-stage persistence implementation to delete. The experiment adds recovery capability, but demonstrates no net complexity reduction in the current bounded adapter. Physical function spans (custom 2 lines, graph 7) are not a meaningful maintainability benchmark and are not used as an adoption score.

Therefore no migration is justified under the stated two-part acceptance criterion. Revisit if multi-stage resumability becomes a product requirement, not merely because a framework exists.

## Limitations

Synthetic control-flow experiment only. No live LLM, economic/product-quality evaluation, exhaustive concurrent mutation stress test, or production LangGraph adapter. No performance/cost advantage claimed. No external data or financial mutations.
