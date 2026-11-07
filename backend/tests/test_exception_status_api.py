from fastapi.testclient import TestClient
from backend.operational_api import create_app
from backend.operational_auth import OperationalAuth
from backend.domain_foundation import initialize
from backend.operational_pipeline import OperationalWorker

def test_exception_api_includes_authoritative_status(tmp_path):
    db=tmp_path/'api.sqlite'; initialize(db)
    auth=OperationalAuth('test-bootstrap-credential-123',database=str(db))
    app=create_app(db,auth=auth,start_worker=False)
    with TestClient(app) as client:
        h={'Authorization':'Bearer '+auth.bootstrap_token,'Origin':'http://localhost'}
        r=client.post('/api/import/bank',headers=h,json={'source':'bank','source_version':'v1','records':[{'source_id':'s','date':'2026-01-01','description':'x','amount':'1.00','currency':'USD','transaction_id':''}]})
        assert r.status_code==200,r.text
        worker=OperationalWorker(db);worker.dispatch_outbox();worker.run_one('w')
        cases=client.get('/api/exceptions',headers=h).json()
        assert cases[0]['status']=='open'
