import json
import sqlite3

from backend.domain_foundation import initialize
from backend.operational_metrics import OperationalMetrics


def make_db(path):
    initialize(path)
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE lr_exceptions(id TEXT PRIMARY KEY,outbox_id TEXT,user_id TEXT,reason TEXT,evidence_json TEXT,created_at TEXT,status TEXT)")
        db.execute("INSERT INTO lr_source_records VALUES('s1','u','bank','x','v1','2025-01-01','old',100,'USD','','{}','2025-01-01T00:00:00+00:00')")
        db.execute("INSERT INTO lr_source_records VALUES('s2','u','bank','x','v2','2025-01-02','new',100,'USD','','{}','2025-01-02T00:00:00+00:00')")
        db.execute("INSERT INTO lr_source_records VALUES('s3','u','bank','y','v1','2025-01-02','y',200,'USD','','{}','2025-01-02T01:00:00+00:00')")
        db.execute("INSERT INTO lr_ledger_records VALUES('l1','u','l1','2025-01-02','new',100,'USD','')")
        db.execute("INSERT INTO lr_matches VALUES('m1','u','s1','l1','2025-01-02T00:00:00+00:00','stale')")
        db.execute("INSERT INTO lr_matches VALUES('m2','u','s2','l1','2025-01-02T01:00:00+00:00','active')")
        db.execute("INSERT INTO lr_exceptions(id,outbox_id,user_id,reason,evidence_json,created_at,status) VALUES('e','o','u','ambiguous','{}','2025-01-02T02:00:00+00:00','open')")
        for i, (typ, stamp) in enumerate([('source.ingested','2025-01-02T01:10:00+00:00'), ('records.matched','2025-01-02T01:35:00+00:00')]):
            db.execute('INSERT INTO lr_events VALUES(?,?,?,?,?)',(str(i),'u',typ,json.dumps({}),stamp))


def test_latest_eligible_counts_exception_breakdown_and_hourly_events(tmp_path):
    db = tmp_path / 'metrics.sqlite'
    make_db(db)
    result = OperationalMetrics(db).snapshot('u', start='2025-01-02T00:00:00+00:00', end='2025-01-02T03:00:00+00:00')
    assert result['health'] == {'eligible': 2, 'matched': 1, 'unmatched': 1}
    assert result['exceptions'] == {'total': 1, 'by_category': {'ambiguous': 1}, 'by_state': {'open': 1}}
    assert result['events']['coverage'] == 'available'
    assert result['events']['hourly'] == [
        {'hour': '2025-01-02T01:00:00+00:00', 'total': 2, 'by_type': {'records.matched': 1, 'source.ingested': 1}}
    ]


def test_zero_data_returns_zeroes_and_explicit_event_coverage(tmp_path):
    db = tmp_path / 'empty.sqlite'
    initialize(db)
    with sqlite3.connect(db) as conn:
        conn.execute("CREATE TABLE lr_exceptions(id TEXT PRIMARY KEY,outbox_id TEXT,user_id TEXT,reason TEXT,evidence_json TEXT,created_at TEXT,status TEXT)")
    result = OperationalMetrics(db).snapshot('u')
    assert result['health'] == {'eligible': 0, 'matched': 0, 'unmatched': 0}
    assert result['exceptions'] == {'total': 0, 'by_category': {}, 'by_state': {}}
    assert result['events'] == {'coverage': 'available', 'hourly': []}
