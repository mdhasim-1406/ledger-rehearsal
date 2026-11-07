import os, sys, tempfile
from pathlib import Path
from fastapi.testclient import TestClient
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
_workspace=Path(os.environ.get('BH_AGENT_WORKSPACE',Path.home()/'.hermes/cache/scratch')); _workspace.mkdir(parents=True,exist_ok=True)
_tmp=tempfile.TemporaryDirectory(prefix='csv-import-test-',dir=_workspace)
os.environ['LEDGER_DEMO_DB']=str(Path(_tmp.name)/'db.sqlite3')
from main import app
client=TestClient(app)
HEADER='source_id,transaction_id,date,description,amount,currency\n'
def row(s,t,d='2025-01-02',desc='Example',amt='10.00',cur='USD'):
 return f'{s},{t},{d},{desc},{amt},{cur}\n'
def test_pair_detection_dedupe_persistence_and_isolation():
 bank=HEADER+row('bmatch','MATCH')+row('bmis','MIS',amt='15')+row('bdup1','DUP')+row('bdup2','DUP')+row('bmissing','ONLYBANK')
 ledger=HEADER+row('lmatch','MATCH')+row('lmis','MIS',amt='10')+row('ldup','DUP')+row('lmissing','ONLYLEDGER')
 payload={'bank_csv':bank,'ledger_csv':ledger,'user_id':'untrusted-caller-value'}
 first=client.post('/api/ingest/csv',json=payload); assert first.status_code==200,first.text
 data=first.json(); assert data['accepted']=={'bank':5,'ledger':4}
 cases={(x['transaction_id'],x['kind']):x for x in data['cases']}
 assert set(cases)=={('MIS','amount_mismatch'),('DUP','duplicate_source'),('ONLYBANK','missing_ledger'),('ONLYLEDGER','missing_bank')}
 assert cases['MIS','amount_mismatch']['record_ids']=='["bank:bmis", "ledger:lmis"]'
 assert cases['DUP','duplicate_source']['record_ids']=='["bank:bdup1", "bank:bdup2", "ledger:ldup"]'
 second=client.post('/api/ingest/csv',json=payload); assert second.status_code==200
 assert [x['id'] for x in second.json()['cases']]==[x['id'] for x in data['cases']]
 assert second.json()['accepted']==data['accepted']
 # Imported cases are in the unified list/detail/evidence path, but cannot create proposals.
 listed=client.get('/api/cases').json()['cases']; assert any(x['id']==cases['MIS','amount_mismatch']['id'] for x in listed)
 detail=client.get('/api/cases/'+cases['MIS','amount_mismatch']['id']).json()
 assert detail['proposal'] is None and detail['safe_investigation'] is False and detail['case']['provenance']['source']=='csv-import'
 assert len(detail['evidence'])==2
 assert client.post('/api/cases/'+cases['MIS','amount_mismatch']['id']+'/investigate').status_code==409
 # Imports accumulate: unrelated clean data must not erase unresolved evidence.
 clean=client.post('/api/ingest/csv',json={'bank_csv':HEADER+row('bmatch','MATCH'),'ledger_csv':HEADER+row('lmatch','MATCH')})
 assert clean.status_code==200
 assert client.get('/api/cases/'+cases['MIS','amount_mismatch']['id']).json()['case']['status']=='needs_review'
 # A missing side can be resolved when the matching counterparty arrives.
 missing=cases['ONLYBANK','missing_ledger']['id']
 result=client.post('/api/ingest/csv',json={'bank_csv':HEADER,'ledger_csv':HEADER+row('lnew','ONLYBANK')})
 assert result.status_code==200, result.text
 detail=client.get('/api/cases/'+missing).json()
 assert detail['case']['status']=='resolved_nonfinancial'
 assert any(e['type']=='resolved' for e in detail['events'])
 # Application lifecycle/reopen uses same persistent SQLite database.
 from main import connect
 with connect() as db: assert db.execute("select count(*) from imported_rows where user_id='local'").fetchone()[0]==10

def test_validation_conflict_and_no_injection():
 good={'user_id':'safe','bank_csv':HEADER+row('stable','T1'),'ledger_csv':HEADER}
 assert client.post('/api/ingest/csv',json=good).status_code==200
 changed={**good,'bank_csv':HEADER+row('stable','T1',desc="x'); DROP TABLE imported_rows;--")}
 assert client.post('/api/ingest/csv',json=changed).status_code==409
 bad={**good,'bank_csv':HEADER+row('s2','T2',amt='NaN')}
 assert client.post('/api/ingest/csv',json=bad).status_code==422
 bad={**good,'bank_csv':'source_id,transaction_id,amount\na,b,1\n'}
 assert client.post('/api/ingest/csv',json=bad).status_code==422
 # Caller-supplied identity is ignored; this is a local demo, not authenticated tenancy.
 ignored=client.post('/api/ingest/csv',json={**good,'user_id':'../unsafe'})
 assert ignored.status_code==200 and ignored.json()['user_id']=='local'
 assert client.post('/api/ingest/csv',json={**good,'bank_csv':'x'*2_000_001}).status_code==413
 from main import connect
 with connect() as db: assert db.execute("select count(*) from imported_rows where user_id='local' AND source_id='stable'").fetchone()[0]==1

if __name__ == '__main__':
 test_pair_detection_dedupe_persistence_and_isolation()
 test_validation_conflict_and_no_injection()
 print('2 CSV import integration tests passed')
