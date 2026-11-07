import sqlite3

from fastapi.testclient import TestClient

from backend.domain_foundation import ReconciliationDomain, initialize
from backend.operational_api import create_app
from backend.operational_auth import OperationalAuth
from backend.operational_pipeline import OperationalWorker


def _setup(path):
    initialize(path)
    auth = OperationalAuth("bootstrap-test-credential-123", database=str(path))
    maker = auth.issue_token("maker", "reviewer")
    approver = auth.issue_token("approver", "admin")
    return auth, maker, approver, ReconciliationDomain(path), OperationalWorker(path)


def _latest_source(path):
    with sqlite3.connect(path) as db:
        return db.execute("SELECT id FROM lr_source_records WHERE source_id='bank-1' ORDER BY rowid DESC LIMIT 1").fetchone()[0]


def test_revised_source_exact_match_resolves_old_case_without_new_case(tmp_path):
    path = tmp_path / "exact-revision.sqlite"
    _, _, _, domain, worker = _setup(path)
    domain.ingest("local", "bank", "rev-1", [{
        "source_id": "bank-1", "transaction_id": "", "date": "2026-02-03",
        "description": "Test merchant", "amount_cents": 2345, "currency": "USD",
    }])
    assert worker.dispatch_outbox() == 1
    assert worker.run_one("acceptance-worker")["abstained"] is True
    with sqlite3.connect(path) as db:
        case_id = db.execute("SELECT id FROM lr_exceptions WHERE user_id='local' AND status='open'").fetchone()[0]

    domain.add_ledger_record("local", "ledger-1", "2026-02-03", "Test merchant", 2345, "USD", "txn-2345")
    domain.ingest("local", "bank", "rev-2", [{
        "source_id": "bank-1", "transaction_id": "txn-2345", "date": "2026-02-03",
        "description": "Test merchant", "amount_cents": 2345, "currency": "USD",
    }])
    assert worker.dispatch_outbox() == 1
    result = worker.run_one("acceptance-worker")
    source_id = _latest_source(path)
    assert result["abstained"] is False
    with sqlite3.connect(path) as db:
        ledger_record_id = db.execute("SELECT id FROM lr_ledger_records WHERE user_id='local' AND ledger_id='ledger-1'").fetchone()[0]
        assert db.execute("SELECT source_record_id,ledger_record_id,status FROM lr_matches WHERE status='active'").fetchone() == (source_id, ledger_record_id, "active")
        assert db.execute("SELECT status FROM lr_exceptions WHERE id=?", (case_id,)).fetchone()[0] == "resolved"
        assert db.execute("SELECT count(*) FROM lr_exceptions WHERE user_id='local' AND status='open'").fetchone()[0] == 0
        assert db.execute("SELECT count(*) FROM lr_exceptions WHERE id=?", (case_id,)).fetchone()[0] == 1


def test_date_difference_case_requires_evidence_human_approval_and_readback(tmp_path):
    path = tmp_path / "date-exception.sqlite"
    auth, maker, approver, domain, worker = _setup(path)
    domain.add_ledger_record("local", "ledger-1", "2026-02-04", "Test merchant", 2345, "USD", "txn-2345")
    domain.ingest("local", "bank", "rev-1", [{
        "source_id": "bank-1", "transaction_id": "txn-2345", "date": "2026-02-03",
        "description": "Test merchant", "amount_cents": 2345, "currency": "USD",
    }])
    assert worker.dispatch_outbox() == 1
    result = worker.run_one("acceptance-worker")
    assert result["abstained"] is True
    assert result["reason"] == "date_mismatch"
    source_id = _latest_source(path)
    with sqlite3.connect(path) as db:
        case_id, evidence_json, status = db.execute("SELECT id,evidence_json,status FROM lr_exceptions WHERE user_id='local'").fetchone()
        ledger_record_id = db.execute("SELECT id FROM lr_ledger_records WHERE user_id='local' AND ledger_id='ledger-1'").fetchone()[0]
        assert status == "open"
        evidence = __import__("json").loads(evidence_json)
        assert evidence["source_record_id"] == source_id

    app = create_app(path, auth=auth, start_worker=False)
    with TestClient(app) as client:
        mh = {"Authorization": f"Bearer {maker}", "Origin": "http://localhost"}
        ah = {"Authorization": f"Bearer {approver}", "Origin": "http://localhost"}
        proposal = client.post("/api/resolutions/proposals", headers=mh, json={
            "case_id": case_id, "source_record_id": source_id, "ledger_id": "ledger-1",
        })
        assert proposal.status_code == 200, proposal.text
        proposal_id = proposal.json()["id"]
        rehearsal = client.post(f"/api/resolutions/proposals/{proposal_id}/rehearse", headers=mh)
        assert rehearsal.status_code == 200, rehearsal.text
        assert rehearsal.json()["would_match"] is True
        assert rehearsal.json()["no_changes"] is True
        with sqlite3.connect(path) as db:
            assert db.execute("SELECT count(*) FROM lr_matches").fetchone()[0] == 0
        approval = client.post(f"/api/resolutions/proposals/{proposal_id}/approve", headers=ah)
        assert approval.status_code == 200, approval.text
        applied = client.post(f"/api/resolutions/proposals/{proposal_id}/apply", headers={**ah, "Idempotency-Key": "date-exception-apply"})
        assert applied.status_code == 200, applied.text
        assert applied.json()["external_posted"] is False
        readback = client.get(f"/api/resolutions/proposals/{proposal_id}", headers=ah)
        assert readback.status_code == 200, readback.text
        assert readback.json()["status"] == "applied"
        records = client.get("/api/records", headers=ah)
        assert records.status_code == 200, records.text
        with sqlite3.connect(path) as db:
            assert db.execute("SELECT source_record_id,ledger_record_id,status FROM lr_matches").fetchone() == (source_id, ledger_record_id, "active")
            assert db.execute("SELECT status FROM lr_exceptions WHERE id=?", (case_id,)).fetchone()[0] == "resolved"
            assert db.execute("SELECT count(*) FROM lr_ledger_records").fetchone()[0] == 1
            assert db.execute("SELECT count(*) FROM lr_source_records").fetchone()[0] == 1
