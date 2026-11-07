from __future__ import annotations

import concurrent.futures
from contextlib import contextmanager
import os
import socket
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.domain_foundation import initialize
from backend.operational_api import create_app
from backend.resolution import ResolutionService
from backend.operational_auth import OperationalAuth
from scripts.backup_operational import backup

ROOT = Path(__file__).resolve().parents[2]
PYTHON = ROOT / "backend" / ".venv" / "bin" / "python"


def _port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _wait_health(url, process, timeout=20):
    import urllib.error
    import urllib.request

    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise AssertionError(f"API process exited early ({process.returncode})")
        try:
            with urllib.request.urlopen(url + "/health", timeout=0.5) as response:
                if response.status == 200:
                    return
        except (OSError, urllib.error.URLError) as exc:
            last = exc
        time.sleep(0.1)
    raise AssertionError(f"API did not become healthy: {last}")


def _stop(process):
    if process.poll() is None:
        process.terminate()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def test_real_api_process_restart_preserves_ingested_and_reconciled_state(tmp_path):
    if not PYTHON.is_file():
        pytest.skip(f"repository virtualenv missing: {PYTHON}")
    db = tmp_path / "operational.sqlite"
    credential = "process-recovery-admin-credential"
    port = _port()
    env = os.environ.copy()
    env.update({"OPERATIONAL_DB": str(db), "OPERATIONAL_ADMIN_CREDENTIAL": credential,
                "OPERATIONAL_HOST": "127.0.0.1", "OPERATIONAL_PORT": str(port),
                "PYTHONPATH": str(ROOT)})
    url = f"http://127.0.0.1:{port}"
    process = subprocess.Popen([str(PYTHON), "-m", "backend.operational_api_main"],
                               cwd=ROOT, env=env, stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL)
    try:
        _wait_health(url, process)
        auth = OperationalAuth(credential, database=str(db))
        token = auth.bootstrap_token
        headers = {"Authorization": f"Bearer {token}", "Origin": "http://localhost"}
        import urllib.request
        payload = (b'{"source":"bank","source_version":"v1","records":[{"source_id":"src-restart",'
                   b'"date":"2026-02-03","description":"Coffee","amount":"12.50",'
                   b'"currency":"USD","transaction_id":"txn-restart"}]}')
        request = urllib.request.Request(url + "/api/import/bank", data=payload, headers={**headers,
            "Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(request, timeout=5) as response:
            assert response.status == 200
        with sqlite3.connect(db) as conn:
            row = conn.execute("SELECT id FROM lr_source_records WHERE source_id='src-restart'").fetchone()
        assert row
        source_id = row[0]
        # Make the real worker reconcile after restart; no in-process worker or mock.
        request = urllib.request.Request(url + "/api/ledger", data=(
            b'{"ledger_id":"ledger-restart","date":"2026-02-03","description":"Coffee",'
            b'"amount":"12.50","currency":"USD","transaction_id":"txn-restart"}'),
            headers={**headers, "Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(request, timeout=5) as response:
            assert response.status == 200
        _stop(process)  # terminate the owned Uvicorn OS process after committed ingestion
        process = None

        process = subprocess.Popen([str(PYTHON), "-m", "backend.operational_api_main"],
                                   cwd=ROOT, env=env, stdout=subprocess.DEVNULL,
                                   stderr=subprocess.DEVNULL)
        _wait_health(url, process)
        deadline = time.monotonic() + 15
        with sqlite3.connect(db) as conn:
            while time.monotonic() < deadline:
                matches = conn.execute("SELECT source_record_id,ledger_record_id,status FROM lr_matches").fetchall()
                if matches:
                    break
                time.sleep(0.1)
            assert len(matches) == 1
            assert matches[0][0] == source_id
            assert matches[0][2] == "active"
            assert conn.execute("SELECT COUNT(*) FROM lr_events WHERE event_type='records.matched'").fetchone()[0] == 1
        request = urllib.request.Request(url + "/api/records", headers=headers)
        with urllib.request.urlopen(request, timeout=5) as response:
            assert response.status == 200
            records = response.read().decode()
        assert "src-restart" in records and "ledger-restart" in records
    finally:
        if process is not None:
            _stop(process)


@contextmanager
def _resolution_fixture(tmp_path):
    db = tmp_path / "resolution.sqlite"
    initialize(db)
    auth = OperationalAuth("resolution-recovery-test-credential", database=str(db))
    maker = auth.issue_token("maker", "reviewer")
    approver = auth.issue_token("approver", "admin")
    other_approver = auth.issue_token("other", "admin")
    app = create_app(db, auth=auth, start_worker=False)
    with TestClient(app) as client:
        source = client.post("/api/import/bank", headers={"Authorization": f"Bearer {auth.bootstrap_token}", "Origin": "http://localhost"}, json={
            "source": "bank", "source_version": "1", "records": [{"source_id": "resolution-source", "date": "2026-02-03", "description": "Coffee", "amount": "12.50", "currency": "USD", "transaction_id": "resolution-txn"}]})
        assert source.status_code == 200, source.text
        with sqlite3.connect(db) as conn:
            source_id = conn.execute("SELECT id FROM lr_source_records WHERE source_id='resolution-source'").fetchone()[0]
            conn.execute("INSERT INTO lr_ledger_records(id,user_id,ledger_id,transaction_date,description,amount_cents,currency,transaction_id) VALUES('ledger-row','local','ledger-resolution','2026-02-03','Coffee',1250,'USD','resolution-txn')")
            conn.execute("INSERT INTO lr_exceptions(id,outbox_id,user_id,reason,evidence_json,created_at,status) VALUES('resolution-case','outbox','local','unmatched',?,'2026-02-04','open')", (f'{{"source_record_id":"{source_id}"}}',))
        maker_headers = {"Authorization": f"Bearer {maker}", "Origin": "http://localhost"}
        body = {"case_id": "resolution-case", "source_record_id": source_id, "ledger_id": "ledger-resolution"}
        proposal = client.post("/api/resolutions/proposals", headers=maker_headers, json=body)
        assert proposal.status_code == 200, proposal.text
        pid = proposal.json()["id"]
        assert client.post(f"/api/resolutions/proposals/{pid}/rehearse", headers=maker_headers).status_code == 200
        approving_headers = {"Authorization": f"Bearer {approver}", "Origin": "http://localhost"}
        other_headers = {"Authorization": f"Bearer {other_approver}", "Origin": "http://localhost"}
        assert client.post(f"/api/resolutions/proposals/{pid}/approve", headers=maker_headers).status_code == 403
        assert client.post(f"/api/resolutions/proposals/{pid}/approve", headers=approving_headers).status_code == 200
        yield db, client, pid, approving_headers, other_headers


def test_concurrent_apply_is_exactly_once_and_requires_approver_identity(tmp_path):
    with _resolution_fixture(tmp_path) as (db, client, pid, headers, other_headers):
        def apply(index):
            return client.post(f"/api/resolutions/proposals/{pid}/apply", headers={**headers, "Idempotency-Key": f"parallel-{index}"})
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            responses = list(pool.map(apply, range(8)))
        # The first request applies; concurrent different keys are correctly rejected
        # once the proposal is no longer approved. Replaying its key is idempotent.
        succeeded = [r for r in responses if r.status_code == 200]
        rejected = [r for r in responses if r.status_code == 409]
        assert len(succeeded) == 1 and len(rejected) == 7, [(r.status_code, r.text) for r in responses]
        successful_index = next(i for i, r in enumerate(responses) if r.status_code == 200)
        assert all(r.json() == succeeded[0].json() for r in succeeded)
        replay = client.post(f"/api/resolutions/proposals/{pid}/apply", headers={**headers, "Idempotency-Key": f"parallel-{successful_index}"})
        assert replay.status_code == 200 and replay.json() == succeeded[0].json()
        assert client.post(f"/api/resolutions/proposals/{pid}/apply", headers={**other_headers, "Idempotency-Key": "wrong-admin"}).status_code == 409
        with sqlite3.connect(db) as conn:
            assert conn.execute("SELECT COUNT(*) FROM lr_matches WHERE status='active'").fetchone()[0] == 1
            assert conn.execute("SELECT COUNT(*) FROM lr_events WHERE event_type='records.matched'").fetchone()[0] == 1
            assert conn.execute("SELECT COUNT(*) FROM lr_resolution_audit WHERE proposal_id=? AND action='applied'", (pid,)).fetchone()[0] == 1
            assert conn.execute("SELECT COUNT(*) FROM lr_resolution_idempotency WHERE proposal_id=?", (pid,)).fetchone()[0] == 1


def test_stale_resolution_source_cannot_be_applied(tmp_path):
    with _resolution_fixture(tmp_path) as (db, client, pid, headers, _):
        with sqlite3.connect(db) as conn:
            conn.execute("UPDATE lr_source_records SET description='changed after approval' WHERE source_id='resolution-source'")
        response = client.post(f"/api/resolutions/proposals/{pid}/apply", headers={**headers, "Idempotency-Key": "stale-attempt"})
        assert response.status_code == 409, response.text
        with sqlite3.connect(db) as conn:
            assert conn.execute("SELECT COUNT(*) FROM lr_matches WHERE status='active'").fetchone()[0] == 0


def test_sqlite_backup_restores_into_new_file_without_overwrite(tmp_path):
    source = tmp_path / "live.sqlite"
    initialize(source)
    with sqlite3.connect(source) as conn:
        conn.execute("INSERT INTO lr_events VALUES('event-1','local','recovery.test','{\"safe\":true}','2026-01-01T00:00:00Z')")
    # Hold a WAL transaction open while backing up; committed state must survive.
    with sqlite3.connect(source) as writer:
        writer.execute("PRAGMA journal_mode=WAL")
        writer.execute("INSERT INTO lr_events VALUES('event-2','local','recovery.test','{\"safe\":false}','2026-01-02T00:00:00Z')")
        writer.commit()
        snapshot = tmp_path / "backup.sqlite"
        backup(source, snapshot)
    restored = tmp_path / "restored.sqlite"
    import shutil
    shutil.copyfile(snapshot, restored)
    assert restored != source and source.exists()
    with sqlite3.connect(restored) as conn:
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert conn.execute("SELECT id FROM lr_events ORDER BY id").fetchall() == [("event-1",), ("event-2",)]
    original = snapshot.read_bytes()
    with pytest.raises(FileExistsError):
        backup(source, snapshot)
    assert snapshot.read_bytes() == original
    with pytest.raises(ValueError):
        backup(source, source)
