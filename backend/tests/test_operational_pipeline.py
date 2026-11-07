import sqlite3
import time

import pytest

from backend.domain_foundation import ReconciliationDomain, initialize
from backend.operational_pipeline import OperationalWorker


def test_dispatch_outbox_and_worker_processes_deterministically(tmp_path):
    path = tmp_path / "db.sqlite"
    initialize(path)
    domain = ReconciliationDomain(path)
    domain.ingest("u", "bank", "v1", [{"source_id":"s", "transaction_id":"", "date":"2026-01-01", "description":"Coffee", "amount_cents":-100, "currency":"USD"}])
    worker = OperationalWorker(str(path))
    assert worker.dispatch_outbox() == 1
    assert worker.dispatch_outbox() == 0
    result = worker.run_one("worker")
    assert result["abstained"] is True
    assert result["reason"] == "missing_transaction_identity"
    with sqlite3.connect(path) as db:
        assert db.execute("select status from lr_jobs").fetchone()[0] == "completed"
        assert db.execute("select count(*) from lr_exceptions").fetchone()[0] == 1
        assert db.execute("select count(*) from lrq_jobs where status='done'").fetchone()[0] == 1


def test_retry_after_failure_keeps_outbox_for_redelivery(tmp_path, monkeypatch):
    path = tmp_path / "retry.sqlite"
    initialize(path)
    ReconciliationDomain(path).ingest("u", "bank", "v1", [{"source_id":"s", "transaction_id":"x", "date":"2026-01-01", "description":"Coffee", "amount_cents":-100, "currency":"USD"}])
    worker = OperationalWorker(str(path))
    worker.dispatch_outbox()
    monkeypatch.setattr(worker, "_process", lambda payload: (_ for _ in ()).throw(RuntimeError("temporary")))
    with pytest.raises(RuntimeError):
        worker.run_one("worker")
    with sqlite3.connect(path) as db:
        assert db.execute("select status from lr_jobs").fetchone()[0] == "completed"
        assert db.execute("select status from lrq_jobs").fetchone()[0] == "queued"
    monkeypatch.undo()
    with sqlite3.connect(path) as db:
        db.execute("update lrq_jobs set available_at=?", (time.time(),))
    assert worker.run_one("worker") is not None


def test_dispatch_is_atomic_and_deduplicates_same_outbox(tmp_path, monkeypatch):
    path = tmp_path / "atomic.sqlite"
    initialize(path)
    ReconciliationDomain(path).ingest("u", "bank", "v1", [{"source_id":"a", "transaction_id":"a", "date":"2026-01-01", "description":"A", "amount_cents":-1, "currency":"USD"}])
    worker = OperationalWorker(str(path))
    original = worker.queue.enqueue
    monkeypatch.setattr(worker.queue, "enqueue", lambda *a, **kw: (_ for _ in ()).throw(AssertionError("external enqueue must not be used")))
    assert worker.dispatch_outbox() == 1
    assert worker.dispatch_outbox() == 0
    monkeypatch.setattr(worker.queue, "enqueue", original)
    with sqlite3.connect(path) as db:
        assert db.execute("select status from lr_jobs").fetchone()[0] == "completed"
        assert db.execute("select count(*) from lrq_jobs").fetchone()[0] == 1


def test_missing_identity_is_per_record_and_does_not_hide_matchable_records(tmp_path):
    path = tmp_path / "records.sqlite"
    initialize(path)
    domain = ReconciliationDomain(path)
    domain.ingest("u", "bank", "v1", [
        {"source_id":"bad", "transaction_id":"", "date":"2026-01-01", "description":"Bad", "amount_cents":-1, "currency":"USD"},
        {"source_id":"good", "transaction_id":"x", "date":"2026-01-01", "description":"Good", "amount_cents":-2, "currency":"USD"},
    ])
    worker = OperationalWorker(str(path))
    worker.dispatch_outbox()
    result = worker.run_one("worker")
    assert result["abstained"] is True
    assert result["reason"] == "missing_transaction_identity"
    with sqlite3.connect(path) as db:
        assert db.execute("select count(*) from lr_exceptions where reason='missing_transaction_identity'").fetchone()[0] == 1
        assert db.execute("select count(*) from lr_exceptions where reason='missing_ledger_record'").fetchone()[0] == 1


def test_dispatch_generation_stable_until_new_source_revision(tmp_path):
    path=tmp_path/"revision.sqlite"; initialize(path); domain=ReconciliationDomain(path)
    domain.ingest("u","bank","v9",[{"source_id":"s","transaction_id":"x","date":"2026-01-01","description":"Coffee","amount_cents":-100,"currency":"USD"}])
    worker=OperationalWorker(path); assert worker.dispatch_outbox()==1
    with sqlite3.connect(path) as db: first=db.execute("select generation from lrq_jobs").fetchone()[0]
    assert worker.dispatch_outbox()==0
    with sqlite3.connect(path) as db: assert db.execute("select generation from lrq_jobs").fetchone()[0] == first
    domain.ingest("u","bank","v10",[{"source_id":"s","transaction_id":"x","date":"2026-01-01","description":"Coffee revised","amount_cents":-200,"currency":"USD"}])
    assert worker.dispatch_outbox()==1
    with sqlite3.connect(path) as db:
        generation=db.execute("select generation from lrq_jobs").fetchone()[0]
        assert generation > first


def test_unavailable_investigation_is_retried_not_completed(tmp_path):
    path=tmp_path/"investigation-retry.sqlite"; initialize(path)
    domain=ReconciliationDomain(path)
    domain.ingest('u','bank','v1',[{'source_id':'s','transaction_id':'x','date':'2026-01-01','description':'entry','amount_cents':100,'currency':'USD'}])
    worker=OperationalWorker(path); worker.investigation_agent=None
    worker.dispatch_outbox(); worker.run_one('worker')
    import pytest
    with pytest.raises(RuntimeError, match='unavailable'):
        worker.run_one('worker')
    with sqlite3.connect(path) as db:
        assert db.execute("select status from lrq_jobs where job_key like 'investigation:%'").fetchone()[0] == 'queued'
