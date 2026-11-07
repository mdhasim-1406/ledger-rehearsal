# LangGraph migration acceptance audit (stable pre-migration snapshot)

Scope: read-only review of `/home/mohamedhasim/.hermes/cache/scratch/ledger-before-graph-20261107-202728/backend`; this is baseline evidence, **not a review of the in-progress graph or its final implementation**. No source files were modified. Treat the following as executable acceptance requirements, not assumptions that the migrated code already passes.

## Preserve the domain boundary

- Graph nodes may investigate and propose only. They must not mutate reconciliation/matching state, apply a resolution, or bypass `ResolutionService.propose` validation. The baseline constrains suggested source and ledger evidence to the same non-empty transaction identity, then drafts through `ResolutionService`; invalid suggestion attempts are rejected while the investigation result can be stored.
- Before any persisted result, re-read the case and candidate ledger scope. Reject closed/missing cases and any mismatch in the ordered scoped evidence or its canonical SHA-256 hash. Recheck under the persistence transaction; a check before an external provider call alone is insufficient.
- Verify proposed hypothesis evidence IDs are limited to supplied evidence (the baseline `InvestigationAgent` is fail-closed; retain its schema/validation behavior). Preserve abstain/unavailable distinctions and don't turn provider failure into an abstention or successful completion.
- Acceptance test: mutate source revision, ledger candidate, case status, or candidate ordering/content after graph input is captured and before persistence; assert `stale`, no `lr_investigations` row, no resolution draft, and no matching-state mutation. Run a control case with unchanged evidence and assert one stored result and at most one validated draft.

## Durable queue and graph checkpoint are separate guarantees

- Queue retry is durable job state, not graph checkpoint persistence. An unavailable provider must fail/requeue the investigation queue job, preserve its input and retryability, and not mark the job done. Simulate process restart and provider recovery; assert the same evidence snapshot can resume and complete without replaying already completed reconciliation side effects.
- Distinct evidence snapshots must be distinct durable investigation jobs/checkpoints (baseline job key includes case ID plus evidence hash). A changed evidence hash cannot resume an old graph state as if it were current.
- Queue completion is generation-aware: when a newer payload arrives while an older lease is active, completing the old generation must leave the newer generation queued and claimable with its latest payload.

## Same-checkpoint concurrent ownership / fencing

- Start two workers against the *same* checkpoint/job identity. Assert only one can own/write the active lease; force lease expiry/reclaim and assert the old worker's token/generation cannot persist a result or complete/fail the new owner's job.
- Race an evidence change and lease reclaim against provider completion. The persistence transaction must check active lease token, running status, expiry, and `generation == claimed_generation`, then recheck evidence snapshot/case status. Assert no stale owner can commit even if it passed an earlier pre-provider check.
- Exercise heartbeat renewal, lease loss during provider latency, timeout/exception, and worker crash/restart. Confirm the new worker can retry without duplicate persisted result/proposal.

## Queue orchestration remains outside graph execution

- Keep queue claim/lease/heartbeat/retry/completion and outbox dispatch as durable worker responsibilities. Graph checkpointing alone does not replace these semantics. Ensure one explicit worker entry point owns retries; avoid nested legacy retry loops plus graph retries that multiply attempts or mark unavailable as complete.
- Retain reconciliation as deterministic domain work, then enqueue investigation by `(case_id, evidence_hash)`. Graph execution must not re-run reconciliation as an implicit retry side effect.
- Audit whether graph state/checkpointer is actually needed for this bounded investigation workflow. If no multi-step resume benefit is demonstrated, prefer the smallest runtime and avoid retaining both an old imperative investigation loop and a duplicate graph implementation.

## Baseline tests/callers and proof gaps

- `tests/test_durable_jobs.py` covers several queue generation/lease cases, including stale-token completion fencing. Keep those tests against the migrated queue/worker integration; queue unit tests alone do not prove graph persistence fencing.
- `tests/test_operational_pipeline.py::test_unavailable_investigation_is_retried_not_completed` is the baseline provider-unavailable acceptance point. Extend it through restart, provider recovery, same checkpoint ownership, and result persistence.
- `tests/test_investigation_reliability.py` uses an injected `SimpleNamespace(investigate=answer)` via `configure_investigation`; this proves an adapter-shaped seam, not real graph construction, checkpointer configuration, or competing callers. Preserve a direct `OperationalWorker(..., investigation_agent=...)` injection test and test configuration/injection through the actual production constructor/call path.
- Baseline has both constructor injection and mutable `configure_investigation` injection. Search all production call sites before removing the latter; test fakes are not proof it is a required production API. Avoid preserving both APIs/old orchestration merely for historical test fixture convenience.
- Verify whether historical investigation code branches have live callers before porting: the acceptance target is current exception evidence, investigation result, optional validated resolution draft, and durable retry—not every legacy proposal/abstention branch just because schemas/tests mention them.
- `requirements.txt` acceptance: LangGraph/checkpoint dependencies should be direct, minimal, and justified by exercised behavior; remove dependencies/imports for the retired loop only after full caller/test search. No dependency install or test run was performed in this bounded read-only audit.
