import sqlite3
from fastapi.testclient import TestClient
from backend.domain_foundation import initialize, ReconciliationDomain
from backend.operational_api import create_app
from backend.operational_auth import OperationalAuth

def test_authenticated_resolution_lifecycle_no_caller_actor(tmp_path):
    path=tmp_path/'db.sqlite'; initialize(path)
    auth=OperationalAuth('bootstrap-test-credential-123',database=str(path))
    reviewer=auth.issue_token('maker','reviewer'); admin=auth.issue_token('approver','admin')
    app=create_app(path,auth=auth,start_worker=False)
    domain=ReconciliationDomain(path)
    domain.ingest('local','bank','1',[{'source_id':'source','date':'2026-01-01','description':'bank entry','amount_cents':1200,'currency':'USD','transaction_id':'txn'}])
    domain.add_ledger_record('local','ledger','2026-01-01','ledger entry',1200,'USD','txn')
    with sqlite3.connect(path) as db:
        src=db.execute("select id from lr_source_records where source_id='source'").fetchone()[0]
        db.execute("insert into lr_exceptions(id,outbox_id,user_id,reason,evidence_json,created_at,status) values('case','outbox','local','unmatched',?, '2026-01-02','open')",('{'+'"source_record_id":"'+src+'"}',))
    with TestClient(app) as c:
        h={'Authorization':'Bearer '+reviewer,'Origin':'http://localhost'}
        assert c.post('/api/resolutions/proposals',headers=h,json={'case_id':'case','source_record_id':src,'ledger_id':'ledger','actor':'admin'}).status_code==422
        response=c.post('/api/resolutions/proposals',headers=h,json={'case_id':'case','source_record_id':src,'ledger_id':'ledger'})
        assert response.status_code==200,response.text
        pid=response.json()['id']
        assert c.post(f'/api/resolutions/proposals/{pid}/rehearse',headers=h).json()['no_changes'] is True
        assert c.post(f'/api/resolutions/proposals/{pid}/approve',headers=h).status_code==403
        ah={'Authorization':'Bearer '+admin,'Origin':'http://localhost'}
        assert c.post(f'/api/resolutions/proposals/{pid}/approve',headers=ah).status_code==200
        applied=c.post(f'/api/resolutions/proposals/{pid}/apply',headers={**ah,'Idempotency-Key':'apply-once'})
        assert applied.status_code==200,applied.text
        assert c.get(f'/api/resolutions/proposals/{pid}',headers=ah).json()['status']=='applied'
        again=c.post(f'/api/resolutions/proposals/{pid}/apply',headers={**ah,'Idempotency-Key':'apply-once'})
        assert again.status_code==200 and again.json()==applied.json()
        assert c.get(f'/api/resolutions/proposals/{pid}').status_code==401