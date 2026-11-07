import sqlite3
from fastapi.testclient import TestClient
from backend.operational_api import create_app
from backend.operational_auth import OperationalAuth

def test_jobs_endpoint_reads_actual_durable_queue(tmp_path):
    db=tmp_path/'api.sqlite'; auth=OperationalAuth('this-is-not-a-real-token-for-testing',database=str(db))
    app=create_app(db,auth=auth,start_worker=False)
    with TestClient(app,raise_server_exceptions=False) as c:
        response=c.get('/api/jobs',headers={'Authorization':'Bearer '+auth.bootstrap_token})
        assert response.status_code==200
        assert response.json()==[]

def test_exception_counts_exclude_resolved(tmp_path):
    db=tmp_path/'api.sqlite'; auth=OperationalAuth('this-is-not-a-real-token-for-testing',database=str(db))
    app=create_app(db,auth=auth,start_worker=False)
    with sqlite3.connect(db) as c:
        c.execute("INSERT INTO lr_exceptions(id,outbox_id,user_id,reason,evidence_json,created_at,status) VALUES('e','x','local','test','{}','2026','resolved')")
    with TestClient(app) as c:
        response=c.get('/api/overview',headers={'Authorization':'Bearer '+auth.bootstrap_token})
        assert response.json()['exceptions']==0
