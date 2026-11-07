import json
import sqlite3

from backend.domain_foundation import initialize
from backend.operational_api import CsvPreviewBody, DispositionBody, _csv_cell, create_app
from backend.operational_auth import Actor, OperationalAuth


def test_csv_preview_commit_disposition_and_exports(tmp_path):
    path = tmp_path / 'review.sqlite'
    initialize(path)
    auth = OperationalAuth('test-bootstrap-credential-123', allowed_origins=frozenset({'http://testserver'}), database=str(path))
    app = create_app(path, auth=auth, start_worker=False)
    routes = {route.path: route.endpoint for route in app.routes if getattr(route, 'path', None)}
    actor = Actor('operator', 'operator')
    csv_text = 'ref,posted,payee,value,ccy,trace\nS-1,2026-01-02,Vendor,12.34,USD,T-1\n'
    mapping = {'source_id':'ref','date':'posted','description':'payee','amount':'value','currency':'ccy','transaction_id':'trace'}
    payload = {'source':'bank','source_version':'v1','csv_text':csv_text,'mapping':mapping}
    body = CsvPreviewBody(**payload)
    assert routes['/api/import/preview'](body, actor)['ready'] is True
    bad = CsvPreviewBody(**{**payload, 'csv_text': csv_text.replace('12.34','NaN')})
    invalid = routes['/api/import/preview'](bad, actor)
    assert invalid['ready'] is False and invalid['errors'][0]['row'] == 2
    assert routes['/api/records'](actor)['bank'] == []
    committed = routes['/api/import/commit'](body, actor)
    assert committed == {'inserted':1,'duplicates':0}
    assert routes['/api/import/commit'](body, actor) == {'inserted':0,'duplicates':1}
    ledger_payload = CsvPreviewBody(**{**payload, 'record_type':'ledger', 'source':'ledger', 'source_version':'ledger-v1'})
    assert routes['/api/import/commit'](ledger_payload, actor) == {'inserted':1,'duplicates':0}
    assert routes['/api/import/commit'](ledger_payload, actor) == {'inserted':0,'duplicates':1}
    routes['/api/exceptions'](actor)
    with sqlite3.connect(path) as db:
        db.execute("INSERT INTO lr_exceptions(id,outbox_id,user_id,reason,evidence_json,created_at,status) VALUES('local:bank:S-1','o','local','missing_ledger_record',?,'2026-01-01','open')", (json.dumps({'source_record_id':'source-id'}),))
        db.execute("INSERT INTO lr_investigations VALUES(?,?,?,?,?)", ('local:bank:S-1','local','digest',json.dumps({'case_id':'local:bank:S-1','status':'abstain','hypotheses':[],'abstain_reason':'no counterpart'}),'2026-01-02'))
        db.execute("INSERT INTO lr_resolution_proposals VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)", ('proposal-1','local','local:bank:S-1','reviewer','source-id','S-1','{}','{}','proposed',None,'2026-01-02',None,None))
        db.execute("INSERT INTO lr_resolution_audit VALUES(?,?,?,?,?,?,?)", ('audit-1','local','proposal-1','reviewer','proposed','{}','2026-01-02'))
    cases = routes['/api/exceptions'](actor)
    assert cases[0]['investigation']['abstain_reason'] == 'no counterpart'
    assert cases[0]['resolutions'][0]['status'] == 'proposed' and cases[0]['audit'][0]['action'] == 'proposed'
    disposition = routes['/api/exceptions/{case_id}/disposition']('local:bank:S-1', DispositionBody(disposition='request_evidence',note='Please provide the ledger export.'), Actor('reviewer','reviewer'))
    assert disposition['financially_resolved'] is False
    assert routes['/api/exceptions'](actor)[0]['status'] == 'open'
    exported = routes['/api/exports/exceptions.csv'](actor)
    assert exported.media_type == 'text/csv'
    json_export = routes['/api/exports/exceptions.json'](actor)
    assert json.loads(json_export.body)['cases'][0]['dispositions'][0]['disposition'] == 'request_evidence'
    assert _csv_cell('=2+2') == "'=2+2"
    report = routes['/api/evaluation'](actor)
    assert report['human_effort'].startswith('unknown') and report['tokens_and_cost'].startswith('unknown')
