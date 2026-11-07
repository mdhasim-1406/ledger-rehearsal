import React, {useState} from 'react';
import './case.css';

const titleCase = value => String(value || '').replace(/[_-]+/g, ' ').replace(/\b\w/g, c => c.toUpperCase());
const money = (amount, currency = 'USD') => {
  if (amount == null || !Number.isFinite(Number(amount))) return 'Unavailable';
  return new Intl.NumberFormat(undefined, { style: 'currency', currency: currency || 'USD' }).format(Number(amount));
};
const dateTime = value => value ? new Date(value).toLocaleString() : 'Unavailable';
const field = (row, keys) => {
  for (const key of keys) if (row?.[key] != null && row[key] !== '') return row[key];
  return null;
};

function EvidenceCard({ item, index, currency }) {
  const id = field(item, ['id', 'source_id', 'transaction_id']);
  const amountCents = item?.amount_cents;
  const amount = amountCents != null ? Number(amountCents) / 100 : item?.amount;
  const kind = field(item, ['kind', 'source', 'type']);
  const status = field(item, ['status']);
  const date = field(item, ['created_at', 'date', 'posted_at', 'occurred_at']);
  const description = field(item, ['description', 'memo', 'name']);
  return <article className="cw-evidence-card">
    <div className="cw-evidence-top"><span className="cw-index">{String(index + 1).padStart(2, '0')}</span><span className="cw-kind">{titleCase(kind) || 'Evidence'}</span>{status && <span className="cw-tag">{titleCase(status)}</span>}</div>
    <h3>{description || id || 'Evidence record'}</h3>
    <dl className="cw-fields">
      <div><dt>Record</dt><dd>{id || 'Unavailable'}</dd></div>
      <div><dt>Amount</dt><dd>{money(amount, field(item, ['currency']) || currency)}</dd></div>
      <div><dt>Source reference</dt><dd>{field(item, ['source_ref', 'transaction_id', 'external_id']) ?? 'Unavailable'}</dd></div>
      <div><dt>Recorded</dt><dd>{dateTime(date)}</dd></div>
      {item?.version != null && <div><dt>Version</dt><dd>{item.version}</dd></div>}
    </dl>
  </article>;
}

function Sandbox({ proposal }) {
  const sandbox = proposal?.sandbox;
  if (!sandbox) return null;
  const checks = sandbox.checks || {};
  const before = Array.isArray(sandbox.before) ? sandbox.before : [];
  const after = Array.isArray(sandbox.after) ? sandbox.after : [];
  const beforeById = new Map(before.map(row => [Array.isArray(row) ? row[0] : row?.id, row]));
  const afterById = new Map(after.map(row => [Array.isArray(row) ? row[0] : row?.id, row]));
  const ids = [...new Set([...beforeById.keys(), ...afterById.keys()])].filter(Boolean);
  const showFields = (row) => {
    if (!row) return 'Unavailable';
    if (Array.isArray(row)) return row.map(value => String(value ?? 'Unavailable')).join(' · ');
    return Object.entries(row).map(([key, value]) => `${titleCase(key)}: ${value ?? 'Unavailable'}`).join(' · ');
  };
  return <section className="cw-section cw-sandbox">
    <div className="cw-section-heading"><div><p className="cw-kicker">Simulation</p><h2>Sandbox validation</h2></div><span className="cw-count">{Object.values(checks).filter(Boolean).length}/{Object.keys(checks).length} passed</span></div>
    <div className="cw-check-grid">{Object.entries(checks).map(([name, passed]) => <div className={`cw-check ${passed ? 'is-pass' : 'is-fail'}`} key={name}><span className="cw-check-mark" aria-hidden="true">{passed ? 'PASS' : 'FAIL'}</span><span>{titleCase(name)}</span></div>)}</div>
    {ids.length > 0 && <div className="cw-before-after">{ids.map(id => <div className="cw-diff-row" key={id}><strong>{id}</strong><span><small>Before</small>{showFields(beforeById.get(id))}</span><span><small>After</small>{showFields(afterById.get(id))}</span></div>)}</div>}
  </section>;
}

export default function CaseWorkspace({ detail, onBack, onInvestigate, onSteer, onApprove, onApply, busy }) {
  const [steering,setSteering] = useState('');
  const c = detail?.case || {};
  const proposal = detail?.proposal;
  const evidence = Array.isArray(detail?.evidence) ? detail.evidence : [];
  const events = Array.isArray(detail?.events) ? detail.events : [];
  const imported = Boolean(c.provenance);
  const operation = proposal?.operation || {};
  const eligible = !imported && c.status === 'detected';
  const investigating = c.status === 'investigating';
  const canApprove = !imported && c.status === 'awaiting_approval' && Boolean(proposal?.hash || proposal?.proposal_hash || detail?.proposal_hash);
  const canApply = !imported && c.status === 'approved';
  const noOp = () => {};
  const steer = event => setSteering(event.currentTarget.value);

  if (!detail?.case) return <main className="cw-workspace"><button className="cw-back" onClick={onBack}>← Back to cases</button><div className="cw-empty">Case details are unavailable.</div></main>;

  return <main className="cw-workspace">
    <header className="cw-header">
      <button className="cw-back" onClick={onBack}>← <span>All cases</span></button>
      <div className="cw-heading-row"><div><div className="cw-meta"><span>{titleCase(c.kind) || 'Case'}</span><span>Case {c.id || '—'}</span></div><h1>{c.title || 'Untitled case'}</h1></div><span className={`cw-status cw-status-${String(c.status || 'unknown').replace(/[^a-z0-9_-]/gi, '-')}`}>{titleCase(c.status) || 'Unknown'}</span></div>
      <p className="cw-summary">{c.summary || 'No case summary provided.'}</p>
      <div className="cw-case-facts"><div><span>Case amount</span><strong>{money(c.amount, c.currency)}</strong></div><div><span>Case version</span><strong>{c.version ?? 'Unavailable'}</strong></div><div><span>Updated</span><strong>{dateTime(c.updated_at)}</strong></div>{c.phase && <div><span>Phase</span><strong>{titleCase(c.phase)}</strong></div>}</div>
      {imported && <aside className="cw-readonly"><strong>Imported evidence · read-only</strong><span>This case has external provenance. Investigation, approval and sandbox application are unavailable.</span><dl>{Object.entries(c.provenance || {}).map(([key, value]) => <div key={key}><dt>{titleCase(key)}</dt><dd>{typeof value === 'object' ? JSON.stringify(value) : String(value)}</dd></div>)}</dl></aside>}
    </header>

    <section className="cw-section">
      <div className="cw-section-heading"><div><p className="cw-kicker">Source records</p><h2>Evidence</h2></div><span className="cw-count">{evidence.length} {evidence.length === 1 ? 'record' : 'records'}</span></div>
      {evidence.length ? <div className="cw-evidence-grid">{evidence.map((item, i) => <EvidenceCard key={item.id || item.source_id || i} item={item} index={i} currency={c.currency} />)}</div> : <p className="cw-muted">No evidence records are attached to this case.</p>}
    </section>

    {!imported && <section className="cw-section cw-actions-section">
      <div className="cw-section-heading"><div><p className="cw-kicker">Review controls</p><h2>Investigation &amp; decision</h2></div></div>
      <label className="cw-steer-label" htmlFor="cw-steering">Investigation guidance <span>Optional</span></label>
      <textarea id="cw-steering" className="cw-steering" defaultValue={c.steering || ''} onChange={steer} placeholder="Add context or a question for the investigation" disabled={Boolean(busy) || !investigating} rows={3} />
      {investigating && <button className="cw-button" disabled={!steering.trim()||Boolean(busy)} onClick={()=>onSteer?.(steering)}>Send direction</button>}
      {investigating && <p className="cw-notice">Investigation is running{c.phase ? ` · ${titleCase(c.phase)}` : ''}. Refresh case details to see its latest result.</p>}
      {c.status === 'needs_review' && <p className="cw-notice">The sandbox checks did not pass. Review the evidence before investigating again.</p>}
      <div className="cw-actions">
        {eligible && <button className="cw-button cw-button-primary" disabled={Boolean(busy)} onClick={onInvestigate || noOp}>{busy ? 'Working…' : 'Investigate'}</button>}
        {canApprove && <button className="cw-button cw-button-primary" disabled={Boolean(busy)} onClick={() => onApprove?.(proposal?.proposal_hash || detail?.proposal_hash)}>{busy ? 'Working…' : 'Approve proposal'}</button>}
        {canApply && <button className="cw-button cw-button-primary" disabled={Boolean(busy)} onClick={onApply || noOp}>{busy ? 'Working…' : 'Apply to sandbox'}</button>}
      </div>
    </section>}

    {proposal && <section className="cw-section cw-proposal">
      {(proposal.hash||proposal.proposal_hash) && <p className="cw-hash"><span>Proposal hash</span><code>{proposal.hash||proposal.proposal_hash}</code></p>}
      <div className="cw-section-heading"><div><p className="cw-kicker">Proposed change</p><h2>{titleCase(operation.type) || 'Proposal'}</h2></div><span className="cw-tag">{titleCase(c.status)}</span></div>
      {operation.record_ids?.length > 0 && <p className="cw-operation">Records: {operation.record_ids.join(', ')}</p>}
      {operation.type && <p className="cw-operation">Operation: <strong>{titleCase(operation.type)}</strong></p>}
      {proposal.proposal_hash && <p className="cw-hash"><span>Proposal hash</span><code>{proposal.proposal_hash}</code></p>}
      <div className="cw-assumptions"><h3>Accounting assumptions</h3>{proposal.accounting_assumptions?.length ? <ul>{proposal.accounting_assumptions.map((item, i) => <li key={i}>{item}</li>)}</ul> : <p className="cw-muted">No assumptions supplied.</p>}</div>
      {proposal.financial_posting === false && <p className="cw-safety">Sandbox-only state change; no financial posting.</p>}
      <Sandbox proposal={proposal} />
    </section>}

    <section className="cw-section cw-timeline">
      <div className="cw-section-heading"><div><p className="cw-kicker">Audit trail</p><h2>Case events</h2></div><span className="cw-count">{events.length}</span></div>
      {events.length ? <ol className="cw-event-list">{events.map((event, i) => <li key={event.id ?? i}><span className="cw-event-dot"/><div><div className="cw-event-title"><strong>{titleCase(event.type) || 'Event'}</strong><time>{dateTime(event.created_at)}</time></div><p>{event.message || 'No event details.'}</p>{event.data && Object.keys(event.data).length > 0 && <details><summary>Event data</summary><pre>{JSON.stringify(event.data, null, 2)}</pre></details>}</div></li>)}</ol> : <p className="cw-muted">No events recorded.</p>}
    </section>
  </main>;
}
