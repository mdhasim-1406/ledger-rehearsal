import React from 'react';

// Decorative topology only. Illumination follows an actual case status and
// never represents a record read, evidence attachment, or an AI tool call.
export function LivingTopology({investigating}) {
  return <svg className={`living-topology ${investigating ? 'is-investigating' : ''}`} viewBox="0 0 1000 700" preserveAspectRatio="xMidYMid slice" aria-hidden="true" focusable="false">
    <path d="M60 470 L250 375 L430 420 L605 270 L890 325 M250 375 L300 190 L605 270 M430 420 L600 555 L890 325" />
    <g><circle cx="60" cy="470" r="3"/><circle cx="250" cy="375" r="3"/><circle cx="300" cy="190" r="3"/><circle cx="430" cy="420" r="3"/><circle cx="605" cy="270" r="3"/><circle cx="600" cy="555" r="3"/><circle cx="890" cy="325" r="3"/></g>
  </svg>;
}

export function ProposedFields({operation}) {
  if (!operation || typeof operation !== 'object') return null;
  const effects = operation.effects && typeof operation.effects === 'object' ? Object.entries(operation.effects) : [];
  const ids = Array.isArray(operation.record_ids) ? operation.record_ids : [];
  if (!effects.length && !ids.length) return null;
  return <section className="proposed-fields" aria-label="Structured proposed change">
    <div className="proposed-fields-head"><strong>Proposed fields</strong><span>Not yet applied</span></div>
    <p>Values supplied by the proposal. Previous values are not provided here.</p>
    {ids.length > 0 && <div className="proposed-target"><span>Affected records</span><code>{ids.join(', ')}</code></div>}
    {effects.map(([key, value]) => <div className="proposed-line" key={key}><b aria-hidden="true">+</b><code>{key}</code><span>{typeof value === 'object' ? JSON.stringify(value) : String(value ?? 'Not provided')}</span></div>)}
  </section>;
}
