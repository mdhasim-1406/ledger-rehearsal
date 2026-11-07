import React from 'react';
import './dashboard.css';

const text = value => value == null || value === '' ? '—' : String(value);
const date = value => {
  if (!value) return '—';
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? String(value) : parsed.toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' });
};
const titleCase = value => text(value).replace(/[_-]+/g, ' ').replace(/\b\w/g, c => c.toUpperCase());
const amount = item => {
  if (item.amount == null && item.amount_cents == null) return '—';
  const value = item.amount != null ? item.amount : item.amount_cents / 100;
  try { return new Intl.NumberFormat(undefined, { style: 'currency', currency: item.currency || 'USD' }).format(value); }
  catch { return `${Number(value).toFixed(2)} ${item.currency || ''}`.trim(); }
};

export default function Dashboard({ overview, cases, onChoose, onNavigate, onIngest, busy, health }) {
  const stats = overview?.stats || {};
  const rows = Array.isArray(cases) ? cases : [];
  const activity = Array.isArray(overview?.activity) ? overview.activity : [];
  const total = stats.total_cases ?? rows.length;
  const statuses = stats.by_status || {};
  const kinds = rows.reduce((out, item) => { const key = item.kind || 'unknown'; out[key] = [...(out[key] || []), item]; return out; }, {});
  const statusTotal = Object.values(statuses).reduce((sum, n) => sum + Number(n || 0), 0);
  const open = Object.entries(statuses).filter(([key]) => !['resolved','resolved_nonfinancial','closed','complete','completed'].includes(key.toLowerCase())).reduce((sum, [, count]) => sum + Number(count || 0), 0);
  const slices = Object.entries(statuses).reduce((out,[,v],i)=>{const start=out.offset;out.offset+=Number(v||0)/statusTotal*100;out.parts.push(`${['#42685f','#d1a66f','#b87355','#8897a2'][i%4]} ${start}% ${out.offset}%`);return out},{offset:0,parts:[]}).parts.join(', ');
  const recent = rows.slice(0, 6);
  return <main className="dash-shell">
    <header className="dash-header">
      <div><div className="dash-kicker">LEDGER REHEARSAL <span> / </span> OVERVIEW</div><h1>Workspace</h1><p className="dash-intro">Real case counts, case mix, and the latest events returned by this workspace.</p></div>
      <button className="dash-ingest" type="button" onClick={onIngest} disabled={!!busy}>{busy ? 'Working…' : '＋　Add records'}</button>
    </header>
    {health?.mode && <div className="dash-environment"><span className="dash-dot" />{health.mode === 'synthetic-demo' ? 'Local synthetic workspace' : 'Connected service'}{health.database ? <span className="dash-db">{titleCase(health.database)}</span> : null}</div>}
    <section className="dash-metrics" aria-label="Workspace counts">
      <article className="dash-metric"><span>Cases</span><strong>{total}</strong><small>All cases in this workspace</small></article>
      <article className="dash-metric"><span>Open cases</span><strong>{open ?? '—'}</strong><small>{open == null ? 'Status counts not supplied' : 'Based on current case statuses'}</small></article>
      <article className="dash-metric"><span>Records</span><strong>{stats.records ?? '—'}</strong><small>Source records available</small></article>
      <article className="dash-metric dash-metric-quiet"><span>Reconciliation rate</span><strong>Unavailable</strong><small>No rate is provided by the API</small></article>
    </section>
    <section className="dash-insights" aria-label="Case analytics">
      <article className="dash-panel dash-status-panel"><div className="dash-panel-head"><div><span className="dash-overline">LIVE CASE STATUS</span><h2>Status distribution</h2></div><span className="dash-chart-note">{statusTotal} counted cases</span></div>
        {statusTotal ? <div className="dash-status-chart" role="img" aria-label={`Case status distribution: ${Object.entries(statuses).map(([k,v]) => `${titleCase(k)} ${v}`).join(', ')}`}><div className="dash-ring" style={{'--dash-slices':slices}}><strong>{statusTotal}</strong><span>cases</span></div><ul>{Object.entries(statuses).map(([key,count],i)=><li key={key}><i style={{'--slice-color':['#42685f','#d1a66f','#b87355','#8897a2'][i%4]}}/><span>{titleCase(key)}</span><b>{count}</b></li>)}</ul></div> : <p className="dash-chart-empty">Status counts are not available.</p>}
      </article>
      <article className="dash-panel dash-kind-panel"><div className="dash-panel-head"><div><span className="dash-overline">CASE REGISTER</span><h2>Cases by type</h2></div></div>{Object.keys(kinds).length ? <ul className="dash-kind-list">{Object.entries(kinds).map(([kind,items])=><li key={kind}><span>{titleCase(kind)}</span><b>{items.length}</b><div>{items.slice(0,4).map(item=><button type="button" key={item.id} onClick={()=>item.id && onChoose?.(item.id)} disabled={!item.id} aria-label={`Open ${item.title || item.id || titleCase(kind)}`}>{text(item.title || item.id)}</button>)}</div></li>)}</ul> : <p className="dash-chart-empty">Case types are unavailable.</p>}<p className="dash-disclosure">Counts use the cases currently supplied to this view; type buttons open those actual cases.</p></article>
    </section>
    <p className="dash-unavailable">Monitoring coverage, agent performance, and historical trends: unavailable from the current API.</p>
    <div className="dash-columns">
      <section className="dash-panel dash-cases">
        <div className="dash-panel-head"><div><span className="dash-overline">CASE REGISTER</span><h2>Recent cases</h2></div><button className="dash-text-button" onClick={() => onNavigate?.('Cases')} type="button">View all <span aria-hidden="true">↗</span></button></div>
        {recent.length ? <div className="dash-table-wrap"><table className="dash-table"><thead><tr><th>Case</th><th>Type</th><th>Status</th><th>Amount</th><th>Updated</th><th aria-label="Open" /></tr></thead><tbody>{recent.map((item, i) => <tr key={item.id ?? `${item.title}-${i}`} onClick={() => onChoose?.(item.id)} tabIndex={item.id ? 0 : undefined} onKeyDown={e => { if (item.id && (e.key === 'Enter' || e.key === ' ')) { e.preventDefault(); onChoose?.(item.id); } }}>
          <td><strong>{text(item.title || item.id)}</strong><small>{item.id && item.title ? text(item.id) : text(item.summary)}</small></td><td>{titleCase(item.kind)}</td><td><span className={`dash-status dash-status-${text(item.status).toLowerCase().replace(/[^a-z0-9]+/g,'-')}`}>{titleCase(item.status)}</span></td><td className="dash-amount">{amount(item)}</td><td className="dash-date">{date(item.updated_at || item.created_at)}</td><td className="dash-arrow">›</td>
        </tr>)}</tbody></table></div> : <div className="dash-empty"><div className="dash-empty-mark">＋</div><h3>No cases yet</h3><p>Add source records to see cases appear here.</p><button type="button" onClick={onIngest} disabled={!!busy}>{busy ? 'Working…' : 'Add records'}</button></div>}
      </section>
      <aside className="dash-panel dash-activity"><div className="dash-panel-head"><div><span className="dash-overline">LATEST EVENTS</span><h2>Activity</h2><small className="dash-chart-note">Showing up to 8 of {activity.length} returned events (API limit: 20)</small></div></div>
        {activity.length ? <ol className="dash-activity-list">{activity.slice(0, 8).map((event, i) => <li key={event.id ?? i}><span className="dash-activity-rule" /><div><p>{text(event.message)}</p><div className="dash-event-meta">{event.case_id ? <button type="button" onClick={() => onChoose?.(event.case_id)}>{text(event.case_id)}</button> : <span>{titleCase(event.type)}</span>}<time>{date(event.created_at)}</time></div></div></li>)}</ol> : <p className="dash-activity-empty">Activity will appear here when the workspace has events.</p>}
      </aside>
    </div>
  </main>;
}
