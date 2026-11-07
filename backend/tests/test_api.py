import os, sys, tempfile, time
from pathlib import Path
from fastapi.testclient import TestClient
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
_workspace = Path(os.environ.get('BH_AGENT_WORKSPACE', Path.home() / '.hermes/cache/scratch'))
_workspace.mkdir(parents=True, exist_ok=True)
_db = tempfile.TemporaryDirectory(prefix='ledger-test-', dir=_workspace)
os.environ['LEDGER_DEMO_DB'] = str(Path(_db.name) / 'isolated.sqlite3')
from main import app
client = TestClient(app)

def wait_for(case_id, statuses, timeout=5):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        state = client.get(f'/api/cases/{case_id}').json()['case']['status']
        if state in statuses:
            return client.get(f'/api/cases/{case_id}').json()
        time.sleep(.02)
    raise AssertionError(f'case {case_id} did not reach {statuses}; last state {state}')

def test_demo_workflow_and_exact_approval():
    client.post('/api/ingest/demo')
    cases = client.get('/api/cases').json()['cases']
    assert len(cases) >= 3 and len({c['id'] for c in cases}) == len(cases)
    case_id = next(c['id'] for c in cases if c['status'] == 'detected' and c['kind'] == 'invoice_without_payment')
    if client.get(f'/api/cases/{case_id}').json()['case']['status'] != 'detected':
        client.post('/api/ingest/demo')
        cases = client.get('/api/cases').json()['cases']
        case_id = next(c['id'] for c in cases if c['status'] == 'detected' and c['kind'] == 'invoice_without_payment')
    client.post(f'/api/cases/{case_id}/investigate')
    detail = wait_for(case_id, {'awaiting_approval','needs_review'})
    h = detail['proposal']['hash']
    assert client.post(f'/api/cases/{case_id}/approve', json={'proposal_hash':'bad'}).status_code == 409
    assert client.post(f'/api/cases/{case_id}/approve', json={'proposal_hash':h}).status_code == 200
    assert client.post(f'/api/cases/{case_id}/apply', json={'proposal_hash':'bad'}).status_code == 409
    before = client.get('/api/records').json()['records']
    assert client.post(f'/api/cases/{case_id}/apply', json={'proposal_hash':h}).json()['case']['status'] == 'resolved_nonfinancial'
    after = client.get('/api/records').json()['records']
    assert next(r for r in after if r['id'] in detail['proposal']['operation']['record_ids'])['status'] == 'reviewed'
    assert client.post(f'/api/cases/{case_id}/apply', json={'proposal_hash':h}).json()['idempotent'] is True

def test_steering_persists_as_run_input_and_events_pollable():
    client.post('/api/ingest/demo')
    case_id = next(c['id'] for c in client.get('/api/cases').json()['cases'] if c['status'] == 'detected')
    assert client.post(f'/api/cases/{case_id}/steer', json={'message':'Do not auto-match; require manual review'}).status_code == 200
    assert client.post(f'/api/cases/{case_id}/investigate').status_code == 200
    detail = wait_for(case_id, {'needs_review'})
    assert detail['case']['status'] == 'needs_review' and detail['proposal'] is None
    assert any(e['type'] == 'investigation_paused' for e in detail['events'])

def test_balanced_journal_cases_and_ambiguity_fail_closed():
    global _db, client
    client.close()
    _db.cleanup()
    _db = tempfile.TemporaryDirectory(prefix='ledger-test-', dir=_workspace)
    os.environ['LEDGER_DEMO_DB'] = str(Path(_db.name) / 'isolated.sqlite3')
    import main
    main.DB_PATH = Path(os.environ['LEDGER_DEMO_DB'])
    main.init()
    client = TestClient(app)
    client.post('/api/ingest/demo')
    cases = client.get('/api/cases').json()['cases']
    expected = {
      'matched_customer_payment': [('Cash','debit',24000),('Sales Revenue','credit',24000)],
      'matched_vendor_payment': [('Operating Expense','debit',8750),('Cash','credit',8750)],
    }
    for kind, lines in expected.items():
        case = next(c for c in cases if c['kind'] == kind)
        assert client.post(f"/api/cases/{case['id']}/investigate").status_code == 200
        d = wait_for(case['id'], {'awaiting_approval','needs_review'})
        assert d['case']['status']=='awaiting_approval', d
        p=d['proposal']; assert p['operation']['journal']
        j=p['operation']['journal']
        assert [(x['account'],x['side'],x['amount_cents']) for x in j['lines']] == lines
        assert sum(x['amount_cents'] for x in j['lines'] if x['side']=='debit') == sum(x['amount_cents'] for x in j['lines'] if x['side']=='credit')
        assert p['accounting_assumptions']
        h=p['hash']; assert client.post(f"/api/cases/{case['id']}/approve",json={'proposal_hash':h}).status_code==200
        assert client.post(f"/api/cases/{case['id']}/apply",json={'proposal_hash':h}).json()['financial_posting'] is False
        got=client.get(f"/api/cases/{case['id']}/journal").json()['entries']
        assert len(got)==1
        assert [(x['account'],x['side'],x['amount_cents']) for x in got[0]['lines']] == lines
        assert client.post(f"/api/cases/{case['id']}/apply",json={'proposal_hash':h}).json()['idempotent'] is True
    ambiguous=next(c for c in cases if c['kind']=='invoice_without_payment')
    client.post(f"/api/cases/{ambiguous['id']}/investigate")
    d=wait_for(ambiguous['id'], {'awaiting_approval','needs_review'})
    assert d['proposal']['operation']['journal'] is None
    assert client.get(f"/api/cases/{ambiguous['id']}/journal").json()['entries']==[]
    assert client.get('/api/health').json()['writes'].find('no financial posting') >= 0

def test_tampered_proposal_stale_record_and_duplicate_apply_fail_closed():
    global _db, client
    client.close(); _db.cleanup()
    _db = tempfile.TemporaryDirectory(prefix='ledger-test-', dir=_workspace)
    os.environ['LEDGER_DEMO_DB'] = str(Path(_db.name) / 'isolated.sqlite3')
    import main
    main.DB_PATH = Path(os.environ['LEDGER_DEMO_DB']); main.init(); client = TestClient(app)
    client.post('/api/ingest/demo')
    case = next(x for x in client.get('/api/cases').json()['cases'] if x['kind']=='matched_customer_payment')
    client.post(f"/api/cases/{case['id']}/investigate")
    d=wait_for(case['id'], {'awaiting_approval'}); h=d['proposal']['hash']
    with main.connect() as c:
        p=__import__('json').loads(c.execute('SELECT proposal FROM cases WHERE id=?',(case['id'],)).fetchone()[0])
        p['operation']['journal']['lines'][0]['amount_cents'] += 1
        c.execute('UPDATE cases SET proposal=? WHERE id=?',(__import__('json').dumps(p),case['id']))
    assert client.post(f"/api/cases/{case['id']}/approve",json={'proposal_hash':h}).status_code==409
    with main.connect() as c:
        p=__import__('json').loads(c.execute('SELECT proposal FROM cases WHERE id=?',(case['id'],)).fetchone()[0])
        p['operation']['journal']['lines'][0]['amount_cents'] -= 1
        c.execute('UPDATE cases SET proposal=? WHERE id=?',(__import__('json').dumps(p),case['id']))
        rid=p['operation']['record_ids'][0]
        c.execute('UPDATE records SET version=version+1 WHERE id=?',(rid,))
    assert client.post(f"/api/cases/{case['id']}/approve",json={'proposal_hash':h}).status_code==409

    # Separate DB for stale-record and duplicate-apply checks.
    client.close(); _db.cleanup()
    _db = tempfile.TemporaryDirectory(prefix='ledger-test-', dir=_workspace)
    os.environ['LEDGER_DEMO_DB'] = str(Path(_db.name) / 'isolated.sqlite3')
    main.DB_PATH = Path(os.environ['LEDGER_DEMO_DB']); main.init(); client = TestClient(app)
    client.post('/api/ingest/demo')
    case=next(x for x in client.get('/api/cases').json()['cases'] if x['kind']=='matched_vendor_payment')
    client.post(f"/api/cases/{case['id']}/investigate"); d=wait_for(case['id'], {'awaiting_approval'}); h=d['proposal']['hash']
    assert client.post(f"/api/cases/{case['id']}/approve",json={'proposal_hash':h}).status_code==200
    with main.connect() as c: c.execute('UPDATE records SET version=version+1 WHERE id=?',(d['proposal']['operation']['record_ids'][0],))
    assert client.post(f"/api/cases/{case['id']}/apply",json={'proposal_hash':h}).status_code==409

    client.close(); _db.cleanup()
    _db = tempfile.TemporaryDirectory(prefix='ledger-test-', dir=_workspace)
    os.environ['LEDGER_DEMO_DB'] = str(Path(_db.name) / 'isolated.sqlite3')
    main.DB_PATH = Path(os.environ['LEDGER_DEMO_DB']); main.init(); client = TestClient(app)
    client.post('/api/ingest/demo')
    case=next(x for x in client.get('/api/cases').json()['cases'] if x['kind']=='matched_vendor_payment')
    client.post(f"/api/cases/{case['id']}/investigate"); d=wait_for(case['id'], {'awaiting_approval'}); h=d['proposal']['hash']
    assert client.post(f"/api/cases/{case['id']}/approve",json={'proposal_hash':h}).status_code==200
    assert client.post(f"/api/cases/{case['id']}/apply",json={'proposal_hash':h}).status_code==200
    assert client.post(f"/api/cases/{case['id']}/apply",json={'proposal_hash':h}).json()['idempotent'] is True

if __name__ == '__main__':
    test_demo_workflow_and_exact_approval()
    test_steering_persists_as_run_input_and_events_pollable()
    test_balanced_journal_cases_and_ambiguity_fail_closed()
    test_tampered_proposal_stale_record_and_duplicate_apply_fail_closed()
    print('4 backend behavior tests passed')
