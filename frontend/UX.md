# Ledger Rehearsal — UX plan

## Product direction
A working desk for a finance operator, not an AI chat window or metric-led dashboard. The central question is “What needs my attention, and what will change if I allow it?” Treat the case record as the unit of work; keep monitoring, source records, and review reachable without burying active work.

## Information architecture
- **Work queue / Overview:** backend-provided case counts and activity only; connection/last-refresh state; actionable cases listed with state, kind, amount and a plain-language summary. No synthesized activity or guessed health.
- **Cases:** searchable/filterable queue and a selected case detail. Detail follows Activity → Investigation → Sandbox → Review → Applied/Attention. Evidence and event history remain available alongside status.
- **Exact proposal review:** show proposal payload as provided, evidence references, before/after or operation details if present, sandbox/check results if present, and proposal hash. Approval is explicitly bound to this hash; applying is a separate deliberate action after approval. Never create a proposal client-side.
- **Records:** inspect records returned by API with field search and readable raw-detail disclosure; never imply a connection to an external database.
- **Ingest sample:** clearly labeled synthetic demo ingestion, with explicit confirmation and backend result; errors remain visible. No CSV/database import claim absent contract.

## Interaction and safety
Use a persistent navigation rail on desktop and compact navigation on narrow screens. Poll overview/case detail while the workspace is open (and more frequently while investigation is active); display polling/refresh/error states. Start investigation only by explicit action. While running, permit an operator message through the steer endpoint; show the posted message only after API success, and refresh authoritative case/events. Distinguish approval from application. Disable actions whose prerequisites are not established by returned state/hash; ask for confirmation before approval/apply and announce results accessibly. Preserve exact API errors and avoid optimistic success.

## Visual system
Quiet ledger-room aesthetic: warm paper canvas, ink/navy text, deep teal primary action, amber for waiting, red only for error/risk, green for confirmed outcomes. Editorial serif display headings paired with a highly legible sans UI; tabular numerals for money. Thin rules, compact table rows, generous detail panels, small restrained status markers. No gradients, glow, fake terminal, decorative charts, fabricated metrics, logos or illustrations.

## Accessibility and responsive behavior
Semantic landmarks, skip link, labeled controls, visible focus, keyboard-operable navigation and dialogs, status announcements, contrast-safe state labels (not color alone), reduced-motion support. Queue/detail stack on mobile; tables scroll within their own labeled region or transform into labeled cards. Avoid horizontal page overflow. Empty, loading, stale, disconnected, and error states have useful plain-language next steps.

## Contract assumptions to confirm
Case/detail/event/proposal shapes are only partially specified. UI will defensively render unknown JSON fields and will not infer readiness from absent fields. Hash may be supplied in proposal or case. Backend must define status vocabulary, evidence schema, event ordering/timestamps, activity shape, sandbox outcomes, and authoritative apply response. GET /api/health informs connection/mode only; it is not a claim of external ledger connectivity. No local fake data fallback.
