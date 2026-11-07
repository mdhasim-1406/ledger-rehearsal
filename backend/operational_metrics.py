"""Deterministic, truthful operational metrics over the durable SQLite journal."""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class OperationalMetrics:
    def __init__(self, database: str | Path):
        self.database = str(database)

    def snapshot(self, user_id: str, *, start: str | None = None, end: str | None = None) -> dict[str, Any]:
        with sqlite3.connect(self.database) as db:
            db.row_factory = sqlite3.Row
            source_rows = db.execute("""
                SELECT s.id FROM lr_source_records s
                WHERE s.user_id=? AND s.source_version=(
                    SELECT s2.source_version FROM lr_source_records s2
                    WHERE s2.user_id=s.user_id AND s2.source=s.source AND s2.source_id=s.source_id
                    ORDER BY s2.created_at DESC, s2.rowid DESC LIMIT 1)
            """, (user_id,)).fetchall()
            eligible_ids = {r['id'] for r in source_rows}
            matched_ids = {r[0] for r in db.execute("SELECT DISTINCT source_record_id FROM lr_matches WHERE user_id=? AND status='active'", (user_id,)) if r[0] in eligible_ids}
            exceptions = db.execute("SELECT reason,status FROM lr_exceptions WHERE user_id=?", (user_id,)).fetchall()
            event_exists = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='lr_events'").fetchone() is not None
            events = []
            if event_exists:
                clauses, params = ["user_id=?"], [user_id]
                if start is not None:
                    clauses.append("created_at>=?"); params.append(start)
                if end is not None:
                    clauses.append("created_at<?"); params.append(end)
                events = db.execute("SELECT event_type,created_at FROM lr_events WHERE " + " AND ".join(clauses) + " ORDER BY created_at,event_type", params).fetchall()
        by_category: dict[str, int] = {}
        by_state: dict[str, int] = {}
        for row in exceptions:
            by_category[row['reason']] = by_category.get(row['reason'], 0) + 1
            by_state[row['status']] = by_state.get(row['status'], 0) + 1
        buckets: dict[str, dict[str, int]] = {}
        for row in events:
            value = row['created_at']
            try:
                dt = datetime.fromisoformat(value.replace('Z', '+00:00'))
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                hour = dt.astimezone(timezone.utc).replace(minute=0, second=0, microsecond=0).isoformat()
            except (ValueError, AttributeError):
                continue
            types = buckets.setdefault(hour, {})
            types[row['event_type']] = types.get(row['event_type'], 0) + 1
        return {
            'health': {'eligible': len(eligible_ids), 'matched': len(matched_ids), 'unmatched': len(eligible_ids) - len(matched_ids)},
            'exceptions': {'total': len(exceptions), 'by_category': dict(sorted(by_category.items())), 'by_state': dict(sorted(by_state.items()))},
            'events': {
                'coverage': 'available' if event_exists else 'unavailable',
                'hourly': [{'hour': hour, 'total': sum(types.values()), 'by_type': dict(sorted(types.items()))} for hour, types in sorted(buckets.items())],
            },
        }
