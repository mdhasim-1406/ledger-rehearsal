# Ledger Rehearsal: project, problem, design and implementation report

Status snapshot: 6 November 2026. This document is a technical and product study of a local prototype, not a production-readiness certification. It describes what is present, what has been exercised, what is proposed, and what is unknown. Source paths are relative to the repository root unless otherwise stated.

## Executive summary

Ledger Rehearsal is a local-first prototype for reviewing bookkeeping exceptions and rehearsing a proposed response before a person explicitly approves it. The central design question is: **What requires attention, what evidence supports a proposed action, and what will change if the operator approves it?**

The problem being explored is a trust gap in accounting automation. A system that produces a confident result without making its evidence, uncertainty, proposed effects and human decision point inspectable can leave an operator unable to verify what happened. This is the product hypothesis, not proof that all existing accounting tools have this defect or that a customer has validated our solution.

Our direction is to treat each exception as a case, attach source evidence and an event history, produce a structured proposal, rehearse its checks, present the proposal to a human, and separate approval from application. An approval is associated with a particular proposal hash. The current system implements parts of this cycle using deterministic rules and local synthetic records. It does **not** currently run a model-driven accounting agent or post to a real accounting system.

### What exists today

- A React/Vite workspace and a FastAPI service backed by a local SQLite database.
- Synthetic fixture ingestion and multiple exception types, plus paired CSV import and read-only imported cases.
- Evidence, case investigation, a proposed action, sandbox checks, explicit proposal approval and a separate application step for supported synthetic workflows.
- A nonfinancial apply path that changes local synthetic record state and records events. This is not a real journal posting.
- A separate, narrowly scoped synthetic journal scenario exists in the backend tests; it must not be confused with a verified external accounting integration or a production-ready journal UI.
- A frontend navigation redesign using dark navigation, light warm surfaces, restrained accents, and a separate mobile queue/detail interaction.
- Automated tests and a browser exercise of a synthetic workflow, with important gaps listed below.

### What does not yet exist or has not been established

- Authentication, authorization and tenant isolation appropriate for real users or real financial information.
- Proven compliance, an independent security assessment, accountant sign-off, customer validation or production-readiness.
- A verified external bank, ERP or accounting-system write. CSV-derived cases are currently read-only.
- Mem0 and Graphify integration, a production agent, or evaluation of a real model-driven workflow. These are discussed as future directions, not shipped capabilities.
- A complete mutation-testing score, an isolated ZAP scan, or a verified end-to-end browser journey for every supported case and journal path.
- A completed visual acceptance review of the latest redesigned UI or an approved final advertising reel.

**Data warning:** the repository itself warns against using real customer data, credentials or secrets. Localhost and an approval hash do not provide user authentication or tenant isolation.

## How to read this report

The report uses three categories of evidence:

1. **Implemented / observed:** behavior visible in the current source, configuration or a directly observed run. Source code establishes intended behavior in the code; it does not by itself prove every possible execution.
2. **Tested:** a specific test or browser run with a stated scope. A passed case does not generalize to all case types, adversaries or deployments.
3. **Proposed / unvalidated:** design ideas, architectural plans, suspected product opportunities and future requirements. These are not claims of a working feature or proven market advantage.

The existing `frontend/UX.md`, older study PDF and plans are useful history but can drift from current source. In conflicts, current code and dated test results are described separately; the plan is not treated as execution evidence. Any model-generated art critique is a viewpoint on supplied images, not a substitute for user testing or visual verification of the entire application.

## Origin and framing

The project was inspired by the broader lesson drawn from public reporting on ScaleFactor: a claimed or expected automation experience and the operational service delivered to customers may diverge. The current repository does not preserve enough independently verified primary evidence to support a detailed causal history of that company. Therefore this report does not claim that reconciliation was the sole reason for its failure, does not infer the conduct of its staff, and does not portray its reported history as customer validation for this prototype.

The actionable design question is narrower: can an operator see the evidence and proposed consequences before permitting a bookkeeping-related change, and later inspect what happened? The project explores that question through a synthetic, local workflow. The hypothesis needs validation with working accountants and real operational constraints before it becomes a claim about customer value.

## Problem decomposition

A bookkeeping exception is not just a number with an alert next to it. A useful resolution may need:

1. Source identity: which records and imports are involved?
2. Context: why was a mismatch, duplicate, missing side or fee discrepancy detected?
3. Evidence: which source facts support the diagnosis, and which facts are missing?
4. Proposal: what concrete operation is contemplated, and against which records?
5. Rehearsal: what checks were performed before requesting permission?
6. Decision: who is authorized to review and approve which exact action?
7. Execution: is the application still permitted under current evidence and state?
8. Verification: what actually changed, and was that result nonfinancial or a real posting?
9. Audit: can an operator reconstruct the sequence without relying on memory or promotional claims?

The current prototype demonstrates aspects of that structure. It does not prove accounting correctness, completeness of evidence, real-user identity or production-grade transaction handling.

## Design decision: a case-centered working desk

A case is the proposed unit of work. Rather than placing a conversational agent at the center, the interface exposes a queue and a selected case. In the intended experience, an operator can orient themselves, inspect facts and make an explicit decision. The reviewed case, evidence and proposal should remain more important than charts or decorative summaries.

The architecture separates several ideas that are easy to conflate:

- Detection is not a conclusion that a financial change is correct.
- A proposal is not an approval.
- An approval is not execution.
- A sandbox result is not an external ledger entry.
- A displayed hash is an integrity aid, not a user identity or authorization boundary.
- A local event history is not, without further controls, an immutable compliance-grade audit trail.

These distinctions are critical because an attractive UI can otherwise make an unsafe prototype appear more mature than it is.

## System at a glance

```text
Synthetic fixtures or paired local CSV data
                  |
                  v
       FastAPI ingestion and detection
                  |
                  v
       SQLite records, cases and events
                  |
          +-------+--------------------+
          |                            |
   Synthetic case                Imported CSV case
          |                         read-only
          v                            |
 Investigation and evidence             v
          |                       case and evidence
 Structured proposal                   display
 and sandbox checks
          |
 Explicit human approval of
 current proposal hash
          |
 Separate application request
          |
 Synthetic nonfinancial state change
 and local audit/event history
```

This diagram is conceptual and intentionally omits implementation details and exception handling. It does not imply authentication, actual model inference, a production ledger connection or external posting. See `backend/main.py` and the technical analysis below for the actual scope.

---


---

# Product problem, design, solution rationale, UX, and progress

## Evidence boundary and reading guide

This section separates (1) **observed implementation** in the current React UI and local README, (2) **documented intent** in project plans and UX notes, and (3) **unvalidated hypotheses / unresolved questions**. A plan is not proof that a feature exists; a screenshot or video script is not proof of a functioning production workflow. Source references below are repository-relative unless a path is absolute. External URLs are included only where named in the project documents; their presence is not independent validation of the claims.

## Product problem and user need

### Intended user and job

**Documented intent:** Ledger Rehearsal is framed as a finance-operator workspace for resolving bookkeeping exceptions, not as an AI chat window or a metric-first dashboard. The UX plan’s central question is: “What needs my attention, and what will change if I allow it?” The product-workflow plan describes a sequence from source/event ingestion through evidence gathering, a typed proposal, isolated rehearsal, accountant review and exact approval, controlled application, and read-back/audit. The case record is intended as the unit of work. Sources: `frontend/UX.md` (“Product direction”, “Information architecture”); `.hermes/plans/product-workflow-architecture.md` (“Mission and decisions”, “User workflow”).

**User need the design attempts to serve:** make exceptions actionable while preserving the operator’s ability to understand provenance, uncertainty, proposed impact, and the boundary between review and a write. The queue should help triage; the selected case should explain the evidence and next action; approval should be informed and scoped to a specific change. This is a rationale encoded in the project’s design documents, not validated evidence of customer demand.

### Problem framing and why caution is part of the product

The plans explicitly reject a simplistic “all mismatches are errors” model. Missing bank records may reflect timing or settlement; duplicate-looking items can be legitimate; matching needs temporal and currency context. The architecture proposal names multiple possible exception families—missing/duplicate imports, payment/invoice mismatches, fees/refunds, ambiguous matches, inconsistent categorisation—and says each needs defined inputs, actions, safeguards, and acceptance tests. It also calls for comparing an agent with deterministic rules and existing human/manual workflows, and says not to claim that an AI system would have prevented a historical company failure. Source: `.hermes/plans/product-workflow-architecture.md` (“User workflow”, “Delivery and verification”, “UX and communication”); `antagonist.md`.

**Evidence gap:** first customer/accountant, jurisdiction and accounting standards, target accounting system, deployment model, source-of-truth ownership per client, acceptance thresholds, willingness to pay, and measured present-day pain remain unresolved in the plan. Thus the current work supports a product thesis and a local rehearsal demonstration, not proven demand, market size, or an ROI claim. Source: `.hermes/plans/product-workflow-architecture.md` (“Unresolved”).

## Proposed solution and rationale

### The safety-shaped workflow

The documented target workflow is:

1. Ingest source records/events with stable identity and provenance.
2. Create a case and gather supporting evidence.
3. Produce a typed, exact candidate operation rather than an unbounded instruction.
4. Replay it against an isolated snapshot and run deterministic accounting/policy checks.
5. Present evidence, proposed changes, and test results for human review.
6. Bind approval to the exact proposal and relevant versions/scope.
7. Revalidate authorization and source versions before controlled apply.
8. Read back the result and preserve an audit trail; surface rejection, uncertainty, and failures rather than masking them.

Rationale: accounting changes can be consequential and model output alone cannot certify correctness. The plans require deterministic checks and human control, and call for idempotency, version/precondition checks, explicit unknown-outcome handling, traceable corrections rather than silent history edits, and no live write without explicit scoped approval. These are design requirements, not evidence that all production-grade protections are implemented. Source: `.hermes/plans/product-workflow-architecture.md` (“User workflow”, “Sandbox”, “Approval and application”); `.hermes/plans/sdlc-execution.md`.

### Boundaries and data architecture

The README describes the current application as a **local synthetic accounting rehearsal demo** backed by persistent SQLite on the local machine, explicitly not a financial posting system; it warns against real customer data, credentials, or secrets. It documents separate local frontend/API ports and manual dependency setup. Source: `README.md`, `start_command.md`.

The architecture plan proposes PostgreSQL and tenant controls only for a later multi-user need, and distinguishes a first-party demo ledger from an ERP-connected mode where the ERP remains authoritative. It also emphasizes that a database/event/audit workflow is the financial source of truth; optional semantic memory and developer code maps are not transactional truth. The research amendment records a user-selected Mem0 + Graphify direction, but states integration is not implemented; it says Mem0 would be supplementary scoped memory and Graphify a developer codebase map. None of these future architecture decisions should be described as current capabilities. Sources: `.hermes/plans/product-workflow-architecture.md` (“Architecture”, “Scale and operations”); `.hermes/plans/memory-architecture-research.md`.

**Rationale:** keep exact records, evidence IDs, proposal versions, decisions, and audit in a structured persistent store with provenance; consider semantic retrieval only if a measured source-linked database baseline proves insufficient. This is a planned decision, not an implemented memory feature. The research amendment’s existing external references are: Mem0 source/docs (`https://github.com/mem0ai/mem0`, `https://docs.mem0.ai/platform/platform-vs-oss`), OpenViking (`https://github.com/volcengine/OpenViking`), and Graphify (`https://github.com/Graphify-Labs/graphify`). The plan itself cautions about OpenViking’s stated AGPLv3 license and says to verify obligations with counsel; no independent license or vendor comparison is asserted here.

## Observed UI and design system

### What the frontend code establishes

The application is a React single-page workspace (`frontend/src/main.jsx`) with client-side page state for **Overview**, cases, and records, API-driven loading, search, case selection/detail, error and notice state, investigation/steering/confirmation controls, and paired bank/ledger file selection/import state. Its API base defaults to `/api` and can be overridden with `VITE_API_BASE`. The code includes request/fetch and action paths; the source is densely minified, so exact state transitions should be confirmed against running behavior/tests before relying on every path as a shipped workflow. The README and UX contract say the UI should reflect backend health and synthetic/demo facts and should not invent external ledger connectivity.

The visual direction documented in `frontend/UX.md` is a quiet ledger-room aesthetic: warm paper canvas, ink/navy text, deep teal primary actions, restrained amber waiting states, red for error/risk, green for confirmed outcomes; editorial serif display paired with legible sans UI and tabular money numerals. It calls for thin rules, compact rows, generous detail panels, restrained status markers, and no gradients, glow, fake terminal, decorative charts, fabricated metrics, logos, or illustrations. These are stated design specifications; review of the very compressed `frontend/src/style.css` is insufficient alone to establish every visual detail or conformance.

### Information architecture and primary UX

The UX plan specifies:

- **Overview/work queue:** backend-provided counts/activity only, connection and refresh state, actionable cases with state, kind, amount, and plain-language summary.
- **Cases:** searchable/filterable queue plus selected detail; a progressive case path of Activity → Investigation → Sandbox → Review → Applied/Attention; evidence and event history remain accessible.
- **Proposal review:** render the proposal payload as provided, show evidence references and any available before/after operation or sandbox/check results, expose the proposal hash, and bind approval to that exact hash. Approval and application are distinct deliberate actions; the client must not invent proposals.
- **Records:** inspect API-returned records and searchable fields, with raw details disclosed readably; do not imply an external database connection.
- **Synthetic ingest:** label demo ingestion clearly, require explicit confirmation, report backend result and visible errors; do not imply CSV/database integration beyond the actual backend contract.

These are product-specific answers to the operator’s core questions: what is active, what evidence supports it, what the system proposes, what will change, and what decision is being requested. Source: `frontend/UX.md` (“Information architecture”, “Interaction and safety”).

### Interaction, safety, and accessibility intent

The design calls for explicit investigation start, steering only while work is active, and reporting a posted operator message only after API success followed by authoritative refresh. It rejects optimistic success; exact API errors should remain visible. Actions should be disabled where state/hash prerequisites are absent, approval/apply should prompt for confirmation, and outcomes should be announced accessibly. Health is connection/mode information—not evidence of an external ledger connection. Source: `frontend/UX.md`.

Accessibility requirements include semantic landmarks, skip link, labeled controls, visible focus, keyboard-operable navigation/dialogs, status announcements, contrast-safe labels that do not rely on color alone, reduced-motion support, and useful loading/stale/disconnected/error/empty states. These are documented requirements and should not be reported as fully tested solely from the source. Source: `frontend/UX.md` (“Accessibility and responsive behavior”).

### Mobile navigation and responsive behavior

The UX plan’s intended mobile model is a compact navigation and a **separate queue and selected-detail state**, rather than forcing a desktop master/detail arrangement into one long mobile page. Queue/detail should stack as states; evidence and safety disclosures must remain available; tables should scroll within a labeled region or transform into labeled cards; no horizontal page overflow. A project-specific skill note further prescribes an explicit working “Back to cases” control on mobile, hiding the empty detail when returning to the queue, and testing selection/detail/back on a narrow viewport after asynchronous loading.

Historical visual review in `ledger-rehearsal-videos/ui-review/ui-art-review.md` reports duplicated breadcrumbs/navigation context, repeated activity/card text, low-contrast metadata, compressed horizontal workflow steps, and a mobile layout that stacked the full queue above selected case detail. It recommends isolating the mobile queue and dedicated case view. Treat this as a **historical critique of the reviewed artifact**, not proof that every issue persists in current code; it does indicate concrete risks to verify against current screenshots and a live narrow viewport. No claim is made here that those critiques were fixed.

## UX trade-offs and why this is not a chat-first product

The documented design makes the case, evidence, proposed operation, and approval boundary the primary interface rather than treating free-form conversation as the work product. This suits an auditable workflow: dialogue can clarify or steer, but the operator’s decision should be grounded in structured state and a reviewable exact change. The queue supports triage; the case page supports investigation; a distinct proposal review reduces ambiguity about what approval covers; post-action read-back closes the loop. This is the project’s design rationale, not comparative usability research.

The most important trade-off is friction versus reversibility and comprehension. Confirmation, hash/version checks, and explicit approve-then-apply add steps; the plans accept that friction to avoid accidental or stale financial actions. Another trade-off is broad automation versus abstention: ambiguity should lead to request for evidence/escalation, not a confident guessed match. These requirements are stated in the architecture and UX plans; their effectiveness needs accountant/operator testing.

## Research, alternatives, and open hypotheses

`antagonist.md` asks reviewers to identify the user, workflow, harm and evidence, test simpler rules/current accounting software/manual review, and challenge architecture, dependency, security, metrics, cost, and failure assumptions. The architecture plan incorporates this adversarial stance and names risks such as cross-tenant access, stale approvals, unknown external commit, misleading sandbox isolation, duplicate events, history rewriting, and rubber-stamping. It explicitly says requirements above do not prove safety and recommends re-evaluating against ordinary software and manual workflows.

The product hypothesis is that a persistent case workflow with evidence-linked proposals and controlled rehearsal can make exception handling more legible and safer than a chat-only or upload-and-check tool. **Not established:** superiority to accounting products/rules/manual processes; willingness to adopt; measured reduction in review time/error; acceptable false-positive/false-negative rates; or any realized business outcome. No competitor comparison is included because the inspected materials do not provide documented competitor research adequate to support one.

## Project progress and historical artifacts

### Current status from plans and repository artifacts

- `.hermes/plans/sdlc-execution.md` labels the SDLC **IN PROGRESS** and explicitly states that local-demo completion is not enterprise readiness.
- The README provides local setup/run instructions and accurately scopes the current product as synthetic and local.
- The frontend contains a React workspace, UI source, screenshot artifacts, and browser-flow test files. The presence of tests/artifacts is not itself evidence of a passing current end-to-end test run; the SDLC plan says imported-case browser flow and journal UI have not passed end-to-end verification.
- The plan records future release gates: accountant review, customer validation, security/privacy testing, operational economics, and production integration evidence. It says multi-user authentication/isolation remain absent.
- The plans describe future deliverables and safeguards (multiple seeded case families, protected answer keys, deterministic validation, sandbox, exact approval, controlled apply, read-back, adversarial tests). These must remain **planned** unless directly verified in implementation and test results.

### Screenshots and video/reel history

Repository screenshot artifacts include `artifacts/overview-desktop.png`, `artifacts/records-desktop.png`, `artifacts/case-proposal-desktop.png`, and `artifacts/case-mobile.png` (also copied under `frontend/artifacts/`). They document design snapshots, not production integration or proof of current state.

The video workspace contains a production script and successive creative/review notes. `reel-production/production-script.md` is explicitly a script/edit blueprint, not a finished video. It describes a **staged, nonfinancial** desktop example and a **read-only CSV** mobile example, forbidding claims of live posting, autonomous inference, or financial outcomes. Its own limitations say no video was rendered, source action timestamps were not all visually verified, and the vision inspection endpoint was unavailable. `grounded-editorial-notes.md` likewise confirms metadata/durations but says approval-modal and apply-result states were not independently verified; suggested edit times are estimates. A later `reel-production/v4-script.md` remains a script and labels source sequences as staged/nonfinancial and CSV/read-only, with no claimed action/result. These artifacts demonstrate careful claim-boundary work, not a shipped marketing asset or validated workflow proof.

The historical `ui-review/ui-art-review.md` gives a detailed critique of a prior UI snapshot: positive notes on editorial typography, warm paper/white cards, queue scannability and modular evidence blocks; concerns about redundant navigation/copy, metadata contrast, mobile queue-detail stacking, and cramped stepper labels. Because it is an artifact-specific critique, current status should be checked rather than inferred.

## Evidence-based summary

**Observed / documented now:** a locally run synthetic SQLite-backed demo; a React workspace with overview/cases/records and import-related frontend state; explicit README safety boundaries; a product design that centers a case queue, evidence, proposal, review, and controlled action; local screenshots and test files; plans that mark work in progress and name unverified release gates.

**Intended:** a durable multi-exception accounting workflow with independent sandboxing, deterministic checks, hash/version-scoped approvals, apply/read-back/audit, accessible mobile-first case navigation, and optionally scoped supplementary memory.

**Not demonstrated by the inspected materials:** production/live accounting integration, multi-tenant auth/isolation, enterprise readiness or certification, accountant/customer validation, proven agent advantage, verified action success in the promotional footage, a visually approved final reel, or measured savings/accuracy. The product’s strongest current rationale is its proposed human-controlled, evidence-first rehearsal boundary; whether that solves a sufficiently important user problem remains an open validation question.

## Local source index

- `README.md`, `start_command.md` — current local-demo scope and setup.
- `frontend/src/main.jsx`, `frontend/src/style.css` — current frontend implementation sources.
- `frontend/UX.md` — intended IA, interaction, design, accessibility, contract assumptions.
- `.hermes/plans/product-workflow-architecture.md` — product thesis, workflow, architecture, risks, and unresolved choices.
- `.hermes/plans/sdlc-execution.md` — progress, verification/security status, and release gates.
- `.hermes/plans/memory-architecture-research.md` — memory/tool research decision and implementation status.
- `antagonist.md` — challenge criteria and safety questions.
- `artifacts/` and `frontend/artifacts/` — UI screenshots.
- `/home/mohamedhasim/ledger-rehearsal-videos/ui-review/ui-art-review.md` — historical visual critique.
- `/home/mohamedhasim/ledger-rehearsal-videos/reel-production/production-script.md`, `grounded-editorial-notes.md`, `v4-script.md` — reel scripts and evidence/claim limitations.


---

## Technical architecture, implementation status, and assurance

### Scope and runtime

Ledger Rehearsal is a local synthetic accounting rehearsal demo, not an accounting integration or production financial-posting service. `README.md` explicitly says it persists to a local SQLite database and warns against entering real customer data, credentials, or secrets. `backend/main.py:8-10` selects `LEDGER_DEMO_DB` when set (otherwise `backend/ledger-demo.sqlite3`) and creates a FastAPI application titled “Local Synthetic Accounting Demo.” Its `/api/health` response (`backend/main.py:45-46`) explicitly labels operation `synthetic-demo`, storage `sqlite-persistent-local`, inference `deterministic-rules`, and writes as non-financial synthetic sandbox only/no financial posting. No external ledger, bank, payment rail, or accounting-system connector is implemented in the reviewed backend.

The database initialization (`backend/main.py:18-31`) establishes tables for source records, cases, events, applied proposal hashes, internal journal entries and lines, plus CSV import rows/cases/provenance. SQLite connections enable foreign keys, WAL mode, a 15-second busy timeout, and autocommit (`backend/main.py:13-17`). The app calls `init()` at module import (`backend/main.py:31`), so startup creates/updates the local DB. This persistence is local machine storage, not a separately managed or tenant-isolated database service.

`start_command.md` documents manually preparing the Python virtual environment and frontend dependencies; the launchers do not install dependencies and do not stop existing services. `start.sh`/`start.bat` start the local API/UI on documented loopback ports (API 28751, UI 28752 per README). This is a local demo launch path, not deployment hardening or a managed production service.

### Implemented backend surface

The FastAPI routes in `backend/main.py` expose:

- `GET /api/health` — explicit mode, storage, inference, and write capability disclosure (`:45-46`).
- `GET /api/overview` — case counts by status, record count, and the latest 20 events (`:47-51`).
- `GET /api/cases` and `GET /api/cases/{case_id}` — case summaries, with detail including evidence, events and current proposal; CSV-import cases have provenance and are surfaced without a proposal (`:52-69`).
- `GET /api/records` — source record list (`:58-60`).
- `POST /api/ingest/demo` — idempotent synthetic fixtures covering six named example categories, including mismatches and matched payments (`:70-90`).
- `POST /api/ingest/csv` — paired bank/ledger CSV snapshot import and exception detection, explicitly detect-only (`:92 onward`).
- `POST /api/cases/{case_id}/steer` — persists operator steering text and an event (route at `:208`; implementation immediately following).
- `POST /api/cases/{case_id}/investigate` — starts a daemon-thread investigation run, with a run ID and durable phases (`:170 onward`, route `:217 onward`).
- `POST /api/cases/{case_id}/approve` — requires the exact current proposal hash, checks digest and evidence/case versions, then stores approval (`:227-237`).
- `POST /api/cases/{case_id}/apply` — applies only the approved unchanged proposal in a SQLite transaction and reports `financial_posting: false` (`:238 onward`).

CSV validation is stricter than a raw import: `ingest_csv` rejects text over 2 MB and more than 10,000 rows, requires exactly six headers (`source_id`, `transaction_id`, `date`, `description`, `amount`, `currency`), validates uniqueness/field lengths/date/three-letter currency/decimal amount, and bounds the amount (`backend/main.py:96-117`). The importer compares bank and ledger rows, identifies exceptions, persists imported rows/cases and local source records, and returns a statement that it performs no journal or external writes (`:118-169`). Imported cases are read-only for investigation: the investigation endpoint rejects them with HTTP 409 (`:217 onward`). CSV import currently hardcodes `user_id='local'` (`:95`); this is not authentication or user separation.

### Data lifecycle and approval boundary

The demonstrated flow is: seed synthetic or import paired CSV rows → persist records and detected cases → inspect evidence/events → optionally steer → investigate → create a proposal or pause for review → human approves the exact proposal hash → apply an internal sandbox state change. Investigation is asynchronous: each worker phase uses its own durable transaction, checks its run ID/status, and can respond to steering (`backend/main.py:170 onward`). The implementation is explicitly rule-based; it should not be described as an AI/LLM agent or model-driven reasoning system.

`proposal_digest` hashes canonical JSON (sorted keys and compact separators) after excluding mutable status/hash metadata (`backend/main.py:33-35`). Approval refuses a missing, stale, mismatched, or modified proposal and checks current source record and case versions (`:227-237`). Apply takes an immediate transaction, enforces idempotency by proposal hash, confirms the approved/current hash and digest, verifies case and evidence versions/statuses, and checks journal debit/credit balance and line validity before writing local journal entries/lines and synthetic record status (`:238 onward`, especially `:241-255`). This is a meaningful demo-level stale-state and exact-approval safeguard. It is not independent identity proof: there is no authentication/authorization mechanism in the reviewed API, and the “approver” is not bound to an authenticated person. The proposal hash is an integrity/freshness check within the application, not a digital signature, external audit attestation, or guarantee against a privileged local DB/process modification.

The word “journal” needs qualification: local journal-entry/line rows can be created by the sandbox apply workflow, but `/api/health`, `case_dict`, and the apply response state that financial posting is unsupported. This is not a real general ledger, external posting, money movement, or verified write to a third-party accounting system. The current tests describe the resulting case as `resolved_nonfinancial` and record status as `reviewed` (`backend/tests/test_api.py:34-40`).

### Tests and actual execution evidence

The backend tests use FastAPI `TestClient` and set `LEDGER_DEMO_DB` to a temporary isolated path before importing `main` (`backend/tests/test_api.py:1-10`; `backend/tests/test_csv_ingest.py:1-9`). Test helper `wait_for` polls asynchronous case state rather than assuming immediate completion (`test_api.py:12-19`). The named test cases cover:

- `test_demo_workflow_and_exact_approval`: synthetic ingest, detection, investigation, rejection of bad hash, exact-hash approval/apply, reviewed record state, and idempotent repeated apply (`test_api.py:21-40`).
- `test_steering_persists_as_run_input_and_events_pollable`: manual-review steering pauses the investigation without a proposal and records an event (`test_api.py:42-49`).
- `test_balanced_journal_cases_and_ambiguity_fail_closed`: expected journal-oriented case handling and ambiguity fail-closed assertions (`test_api.py:51 onward`).
- `test_pair_detection_dedupe_persistence_and_isolation`: paired CSV exception classification, repeated-import idempotency, unified case/detail/evidence behavior, and restrictions (`test_csv_ingest.py:13 onward`).
- Additional API tests in `test_api.py` exercise proposal tampering, stale evidence/version rejection and duplicate-apply behavior (`:93-119 onward`); the CSV tests exercise input validation/error cases in the remaining test body.

I executed `./.venv/bin/pytest -q` from `backend/`: **6 passed**, with one Starlette deprecation warning concerning use of `httpx` with `starlette.testclient` and a recommendation to use `httpx2`. This is evidence for this backend test suite in the current environment only. It is not evidence of frontend end-to-end coverage, live integration, concurrency/load resilience, production security, or real financial correctness.

### Security posture and limitations

The report in `.hermes/security/README.md` records static/dependency-scan evidence and limitations. Bandit 1.9.4 exited 1 with 57 findings: four medium B608 findings for string-based SQL construction in `backend/main.py`, and 53 low B101 findings (assertions in tests); it records no high-severity finding. The B608 hits merit contextual review: several queries interpolate internally generated placeholder counts/column names, while user values are passed as bound parameters, but the static scan itself is not proof of exploitability or safety. `pip-audit` checked 27 requirements and exited 1 for two duplicate advisory records for the same pytest issue (PYSEC-2026-1845 / CVE-2025-71176 / GHSA-6w46-j5rx-g56g), marked fixed in pytest 9.0.3 by that report. `npm audit` in the copied frontend reported zero vulnerabilities from the configured registry. A ZAP baseline was **not run**: the security note cites lack of an established isolated Docker network policy while unrelated containers were running. Therefore there is no dynamic ZAP scan result.

Security boundaries that remain absent or unverified in the inspected backend include API authentication and role-based authorization, tenant isolation, CSRF/CORS policy review, TLS/network exposure controls, request rate limiting, retention/backup/encryption-at-rest policy, production-grade secrets handling, hardened schema migration strategy, and external posting safeguards. The local CSV parser has size/row/field validation, but the endpoint is not a secure authenticated upload service. Events provide application-level history but are not a tamper-evident external audit log. Thread-per-investigation is a simple local demo mechanism, not a durable task queue or demonstrated scale-safe worker design. Local SQLite persistence means the demo’s records survive restarts, but does not itself provide backup, recovery, multi-user consistency, or deployment guarantees.

### Planned architecture versus delivered behavior

`.hermes/plans/product-workflow-architecture.md` explicitly labels itself a discussion proposal, not implementation or evidence of enterprise readiness. It describes a broader intended lifecycle including sources/event streams, typed proposals, isolated sandbox replay, deterministic checks, accountant review, controlled posting, read-back verification, and visible exception handling. The plan also records unresolved choices: initial customer/accountant, jurisdiction/standards, target accounting system, deployment model, acceptance metrics, and authoritative-book decision. These should remain identified as unresolved design intent—not claimed as implemented capabilities.

The plan’s “real product trajectory” and future integrations do not change the actual scope: the reviewed implementation offers synthetic fixtures, local paired CSV import, deterministic investigation, exact-hash human approval, and non-financial local state changes. No real bank feed, external ledger API, real posting, live reconciliation, authentication, or AI inference was found in the reviewed backend. Security scan notes are historical scan records for the stated snapshot/copy and must not be represented as a current full penetration test or readiness certification.



---

## Verification log and interpretation

### Backend: direct run for this report

On 6 November 2026, from the `backend` directory, the project interpreter ran `./.venv/bin/pytest -q`. The observed result was **6 passed, 1 warning in 1.92 seconds**. The warning was a Starlette deprecation warning about the `httpx` TestClient integration. These tests exercise specific synthetic cases; six passing tests are not a measure of total correctness or coverage. The test files create temporary databases under the configured scratch workspace, not a production accounting database.

### Browser behavior: dated evidence from the work session

An isolated local instance on ports 38761 and 38762, using a scratch SQLite database, was seeded using the synthetic demo endpoint. The existing Playwright scenario exercised the Fee Discrepancy path and observed evidence, proposal approval, nonfinancial application, the resulting API status, and records. Its report stated no mobile horizontal overflow. That complete workflow ran before the final mobile queue/detail changes.

After those navigation changes, a separate Playwright check on a 390 × 844 viewport waited for case detail to load, verified that the queue was hidden while detail was selected, verified that the Back to cases button returned to the queue and hid the detail, and checked that the document did not overflow horizontally. The frontend production build also passed after the changes. The complete approval/apply journey was not rerun after the final navigation edit. These are targeted checks, not exhaustive accessibility or cross-browser testing.

The current preview port is a temporary development process, not a deployment commitment. It may not remain available after the session. See `start_command.md` for the supported local launch instructions, port options and prerequisites.

### Security review: findings and scope

A previous isolated adversarial review reproduced access to local API routes from requests bearing an untrusted `Origin` and observed acceptance of a CSV row containing an extra field. The important conclusion is not that every browser attack path was exhaustively demonstrated: the local API does not currently provide an authenticated user or tenant authorization boundary. CORS, loopback binding and hashes are not substitutes for authorization. Local threat exposure depends on deployment and browser behavior and requires a dedicated review.

The saved historical scanning snapshot reported four Bandit medium B608 warnings concerning SQL construction and low-severity test assertion warnings; the specific reviewed dynamic `IN` usage employed placeholders for values, but that observation does not clear every SQL path. A dependency scan reported a pytest advisory in its tested environment, and a frontend lockfile audit reported zero advisories at that time. These are dated snapshots, not current guarantees. The planned ZAP baseline was not run safely, and there is no established mutation score. Do not extrapolate any of these observations to a security certification.

### UI art direction: evidence and limits

The recorded visual review of desktop and mobile screenshots recommended revision, calling out duplicate navigation and the previous mobile queue/detail stacking. Those two issues were subsequently changed and the targeted navigation behavior was exercised. The AI review response ended because of its length limit, so it is incomplete; model observations are not independent proof of usability. The newest UI has not been comprehensively reviewed through normal-speed interaction by a human art director or representative finance operator.

## Product decision log

### Why not start with autonomous posting?

External writes carry a much higher impact than synthetic review annotations. The prototype first explores evidence and approval boundaries without connecting a live ledger. This reduces the scope of a demonstration but also limits what it proves. Before any external posting, the project needs explicit user authorization, real identity and role permissions, an accounting-system contract, an independently reviewed transaction strategy, safe retry/idempotency behavior, read-back verification, failure recovery and accountant validation.

### Why make proposals structured?

A structured proposal allows an operator and implementation to inspect an operation, its target records and validation results. The hash can bind an approval to a particular proposal. It is not a substitute for understanding the operation and does not establish that the approver is authorized. A future change in the evidence or proposal must be handled deliberately, not hidden behind an old approval.

### Why retain event history?

An investigation may move through detection, review, approval and application. Recording transitions can make the local sequence easier to reconstruct and debug. Current events should not be described as tamper-evident, independently retained, legally sufficient or immutable. A production audit design would need actor identity, access control, retention, tamper-resistance and operational ownership.

### Why are CSV cases read-only?

CSV imports supply local evidence and demonstrate exception detection without pretending that a CSV file is a connected accounting system. The current imported-case boundary prevents investigation/approval/apply through the synthetic write workflow. Future support for any write would need explicit source ownership, identity mapping, schema contracts, permissioning and reconciliation semantics.

### Why keep financial records out of the memory layer?

The selected direction, Mem0 plus Graphify, is recorded as an architectural research choice rather than an installed feature. Financial facts and transaction state must remain authoritative in the database and source systems. Any future memory retrieval should be supplementary, bounded by permissions, traceable, and unable to authorize a change by itself. The project must first demonstrate a concrete need, a safe local deployment and measurable value over simpler approaches.

## Remaining work, ordered by dependency

1. **Safety before data:** establish authentication, authorization, origin/request defenses, safe local deployment and input validation; reproduce and address known adversarial findings. Continue to exclude real customer data until these gates are met.
2. **Accounting semantics:** have a qualified practitioner review case definitions, proposals, journal examples, currency handling, duplicate logic and failure recovery. Expand synthetic fixtures and withheld-answer evaluation before claiming accuracy.
3. **Workflow correctness:** add tests across all supported statuses, stale evidence, changed proposal hashes, repeated approvals/applications, concurrent requests, partial failures and recovery. Distinguish nonfinancial annotations from journal scenarios in code and UX.
4. **Import reliability:** validate CSV schemas strictly, reject malformed rows, define conflicting imports and resolution rules, test cumulative evidence and idempotency, and maintain the read-only boundary until a separate write design is approved.
5. **Usability:** review the latest desktop and mobile interface with representative users; test keyboard-only interaction, screen readers, focus management, empty/loading/error states, responsive layouts and relevant browsers. Re-run the full workflow following the final navigation change.
6. **Security assurance:** reproduce current static/dependency scans in a controlled environment; remediate verified vulnerabilities, then run safely isolated dynamic and mutation testing. Preserve raw results and their scope.
7. **Product validation:** interview practitioners about the proposed workflow, alternatives and actual decision bottlenecks. Avoid positioning the idea as unique until competitor and customer evidence supports that claim.
8. **Memory and agent experiments:** prototype Mem0 and Graphify only after a specific retrieval use case and security boundary are agreed. Any model-driven system must be evaluated separately and never be allowed to silently approve or post.
9. **Documentation and launch:** keep this report, README, architecture and existing study PDF synchronized with implemented behavior. Verify native Windows startup on Windows before claiming support has been tested.
10. **Demonstration and communication:** re-record after the UI changes, verify visible states and the exact source timestamps, inspect audio and full-speed motion, preserve the full critique, and obtain approval before publishing.

## Open questions for an accountant or product owner

- Which exception type causes the most operational pain, and what evidence is needed to make a decision?
- Which cases should never be automated, even with a human approval step?
- Who is responsible for preparing, approving, applying and correcting a change?
- What should happen if source evidence changes while a proposal is awaiting approval?
- How should reversals, partial failures, stale imports and duplicate external transactions be handled?
- Which currencies, accounting methods, tax rules and jurisdictions are actually in scope?
- What level of explanation and audit evidence is useful without overwhelming the operator?
- How would the organization connect, authorize, and verify a real accounting-system action?
- What evidence would demonstrate that rehearsal reduces errors or saves time compared with current practice?

Until these questions are answered, the product remains an exploration rather than a validated accounting workflow.

## Reproducibility and evidence index

- Current backend implementation: `backend/main.py`.
- Backend tests: `backend/tests/test_api.py` and `backend/tests/test_csv_ingest.py`.
- Frontend implementation and palette: `frontend/src/main.jsx`, `frontend/src/style.css`.
- Browser scenario: `frontend/tests/investor-flow.spec.cjs`; note that it expects a seeded synthetic demo service and its default ports can be overridden through environment variables.
- Scope and setup: `README.md`, `start_command.md`, `start.sh`, `start.bat`.
- Product intent: `frontend/UX.md`, `.hermes/plans/product-workflow-architecture.md`.
- SDLC and open gates: `.hermes/plans/sdlc-execution.md`.
- Memory research: `.hermes/plans/memory-architecture-research.md`.
- Historical static-scan summary: `.hermes/security/README.md`.
- Visual and reel artifacts, outside the repository: `/home/mohamedhasim/ledger-rehearsal-videos/`.

The repository was untracked when inspected for this report. This report was written locally, and no commit, push, or publication was performed.
