# Investigation orchestration ownership

LangGraph is the sole investigation execution runtime. InvestigationAgent is its entrypoint, not an alternate agent loop.

Graph: initialize scoped evidence/messages -> one model request -> conditional read-only tools/model or final validation. Checkpoints hold messages, counters and execution progress only. No graph retry policy: the durable worker owns dispatch failure/backoff; a retry resumes the failed graph node. A crash during an uncommitted request may repeat that request. Completed synchronous checkpoints are reused.

Domain SQLite remains authoritative for evidence, financial data, proposals, approvals, audit and applied outcomes. The worker checks evidence before invoking/resuming and again under BEGIN IMMEDIATE before atomically persisting draft and result. Lease heartbeat/fencing is retained. Graph checkpoints never authorize mutation.

Checkpoint storage: worker defaults to <domain-database>.investigations.sqlite, separate from domain writes. Identity hashes workspace-qualified case, canonical evidence, provider endpoint and model. API keys are not persisted. Different evidence starts a different graph thread; stale old outputs cannot pass final validation. Checkpoints contain sensitive evidence and need the same filesystem protections and retention policy as source data.

Same-thread advancement is serialized across processes by OS-backed filelock, not a second custom lease registry. Locks are released on process exit. Domain queue leases still control job dispatch and final write ownership. No distributed-worker deployment is claimed by this local SQLite design.

Verification: 101 backend tests passed. Production graph subprocess tests terminate after committed tool state and resume in a fresh process; completed initial model work is not repeated. Two concurrent subprocesses produce one shared execution. Existing bounded scope/tool/request tests, stale-evidence tests and atomic draft/replay/lease tests pass. Browser API ingest -> automatic case -> manual proposal -> rehearsal -> distinct approval -> apply -> resolved readback passed. Missing provider causes dispatch retries and logged unavailable iterations, not successful investigations.

Removed: manual range-based model/tool loop, mutable configure_investigation setter, process-local lock registry, checkpoint test hook, and worker-side unavailable-result retry branch. Graph edges own branching; LangGraph owns checkpoint serialization/resumption. Existing HTTP transport and typed result models remain necessary provider/domain boundaries.

Limitations: model HTTP responses are mocked in graph tests; no live provider configured. This proves execution recovery and safeguards, not model accuracy or startup/customer economics. OS-lock behavior verified on local Linux processes, not Windows/network filesystems. No frontend redesign or financial service rewrite.
