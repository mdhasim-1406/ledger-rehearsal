import json
import sqlite3

import pytest

from backend.domain_foundation import ReconciliationDomain, initialize


def _row(source_id="bank-1", txid="shared-1", **overrides):
    row = {"source_id": source_id, "transaction_id": txid, "date": "2026-01-02", "description": "Coffee", "amount_cents": -425, "currency": "USD"}
    row.update(overrides)
    return row


def test_legacy_events_table_is_preserved_and_lr_tables_migrate(tmp_path):
    db = tmp_path / "legacy.sqlite"
    with sqlite3.connect(db) as conn:
        conn.execute("CREATE TABLE events (legacy_id TEXT PRIMARY KEY, payload BLOB NOT NULL)")
        conn.execute("INSERT INTO events VALUES ('e1', X'01')")
    initialize(db)
    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT legacy_id,payload FROM events").fetchall() == [('e1', b'\x01')]
        names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert {'lr_source_records','lr_ledger_records','lr_matches','lr_events','lr_jobs'} <= names
    domain = ReconciliationDomain(db)
    assert domain.ingest('u','bank','v1',[_row()])['inserted'] == 1


def test_changed_source_content_appends_immutable_version_and_unmatches_stale_result(tmp_path):
    db = tmp_path / "versions.sqlite"
    initialize(db); d = ReconciliationDomain(db)
    d.ingest('u','bank','v1',[_row()])
    d.add_ledger_record('u','ledger-1','2026-01-02','Coffee',-425,'USD')
    assert d.reconcile('u')['matched'] == 0
    changed = _row(amount_cents=-500, description='Corrected Coffee')
    assert d.ingest('u','bank','v2',[changed])['inserted'] == 1
    with sqlite3.connect(db) as conn:
        rows = conn.execute('SELECT source_version,amount_cents FROM lr_source_records ORDER BY created_at').fetchall()
        assert rows == [('v1',-425),('v2',-500)]
        assert conn.execute('SELECT count(*) FROM lr_matches').fetchone()[0] == 0


def test_historical_match_stales_and_ledger_can_be_reused(tmp_path):
    db=tmp_path/'revision.sqlite'; initialize(db); d=ReconciliationDomain(db)
    d.ingest('u','bank','v1',[_row()]); d.add_ledger_record('u','ledger','2026-01-02','Coffee',-425,'USD','shared-1')
    assert d.reconcile('u')['matched']==1
    d.ingest('u','bank','v2',[_row(amount_cents=-500)])
    with sqlite3.connect(db) as conn:
        assert conn.execute('SELECT status FROM lr_matches').fetchone()[0]=='stale'
        assert conn.execute('SELECT COUNT(*) FROM lr_matches').fetchone()[0]==1
    assert d.reconcile('u')['matched']==0
    d.ingest('u','bank','v3',[_row()])
    assert d.reconcile('u')['matched']==1
    with sqlite3.connect(db) as conn:
        assert sorted(r[0] for r in conn.execute('SELECT status FROM lr_matches').fetchall())==['active','stale']


def test_active_allocation_conflicts_are_not_silently_overwritten(tmp_path):
    db=tmp_path/'conflict.sqlite'; initialize(db); d=ReconciliationDomain(db)
    d.ingest('u','bank','v1',[_row()]); d.add_ledger_record('u','ledger','2026-01-02','Coffee',-425,'USD','shared-1')
    assert d.reconcile('u')['matched']==1
    d.ingest('u','bank','v2',[_row(amount_cents=-500)])
    d.ingest('u','bank','v3',[_row(amount_cents=-425)])
    assert d.reconcile('u')['matched']==1
    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT COUNT(*) FROM lr_matches WHERE status='active'").fetchone()[0]==1
        assert conn.execute('SELECT COUNT(*) FROM lr_matches').fetchone()[0]==2


def test_no_match_without_same_explicit_transaction_identity(tmp_path):
    db=tmp_path/'identity.sqlite'; initialize(db); d=ReconciliationDomain(db)
    d.ingest('u','bank','v1',[_row(txid='bank-ref')])
    d.add_ledger_record('u','ledger','2026-01-02','Coffee',-425,'USD')
    assert d.reconcile('u')['matched'] == 0
    db2=tmp_path/'missing.sqlite'; initialize(db2); d2=ReconciliationDomain(db2)
    d2.ingest('u','bank','v1',[_row(txid='')])
    d2.add_ledger_record('u','ledger','2026-01-02','Coffee',-425,'USD')
    assert d2.reconcile('u')['matched'] == 0


def test_completed_job_does_not_block_later_ingestion(tmp_path):
    db=tmp_path/'jobs.sqlite'; initialize(db); d=ReconciliationDomain(db)
    d.ingest('u','bank','v1',[_row()])
    d.reconcile('u')
    d.ingest('u','bank','v1',[_row('bank-2', 'shared-2', amount_cents=-100)])
    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT count(*) FROM lr_jobs WHERE status='queued'").fetchone()[0] >= 1


def test_identical_reingestion_is_idempotent(tmp_path):
    db=tmp_path/'idem.sqlite'; initialize(db); d=ReconciliationDomain(db)
    assert d.ingest('u','bank','v1',[_row()]) == {'inserted':1,'duplicates':0}
    assert d.ingest('u','bank','v1',[_row()]) == {'inserted':0,'duplicates':1}
