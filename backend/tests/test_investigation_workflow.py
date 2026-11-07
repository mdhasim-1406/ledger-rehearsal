import json
import sqlite3
import pytest
import httpx
from backend.domain_foundation import ReconciliationDomain, initialize
from backend.operational_pipeline import OperationalWorker
from backend.investigation_agent import InvestigationAgent

def test_actual_worker_persists_investigation_and_stale_guard(tmp_path, monkeypatch):
    path=tmp_path/"db.sqlite"; initialize(path)
    domain=ReconciliationDomain(path)
    domain.ingest("u","bank","v1",[{"source_id":"s","transaction_id":"x","date":"2026-01-01","description":"Coffee","amount_cents":-100,"currency":"USD"}])
    worker=OperationalWorker(path)
    import os
    monkeypatch.setenv("INVESTIGATION_LLM_BASE_URL","https://mock.invalid/v1")
    monkeypatch.setenv("INVESTIGATION_LLM_MODEL","test-model")
    monkeypatch.setenv("INVESTIGATION_LLM_API_KEY","test-key")
    def mock_response(req):
        body=json.loads(req.content)
        assert body['messages'][0]['role'] == 'system'
        user_message = next(message for message in body['messages'] if message['role'] == 'user')
        evidence=json.loads(user_message['content'].split('EVIDENCE: ',1)[1])
        source=next(x for x in evidence if x.get('evidence_type')=='source'); ledger=next((x for x in evidence if x.get('evidence_type')=='ledger'),None)
        payload={"case_id":"u:bank:s","status":"proposed","hypotheses":[{"statement":"Date differs","evidence_ids":[source["id"]]+([ledger['id']] if ledger else []),"confidence":0.9}],"abstain_reason":None}
        if ledger: payload['suggestion']={"kind":"allocate","source_record_id":source['id'],"ledger_id":ledger['id'],"rationale":"Exact identity; date variance."}
        return httpx.Response(200,json={"choices":[{"message":{"content":json.dumps(payload)}}]})
    worker.investigation_agent=InvestigationAgent(transport=httpx.MockTransport(mock_response))
    worker.dispatch_outbox(); queued=worker.run_one("w")
    assert queued["investigation"]["status"] == "queued"
    result=worker.run_one("w")
    assert result["investigation"]["status"] == "proposed"
    with sqlite3.connect(path) as db:
        assert db.execute("select count(*) from lr_investigations").fetchone()[0] == 1
        row=db.execute("select result_json from lr_investigations").fetchone()
        assert "secret" not in row[0]


def test_worker_creates_proposed_draft_from_date_mismatch(tmp_path, monkeypatch):
    path=tmp_path/"draft.sqlite"; initialize(path); domain=ReconciliationDomain(path)
    domain.ingest("u","bank","v1",[{"source_id":"s","transaction_id":"x","date":"2026-01-01","description":"Coffee","amount_cents":-100,"currency":"USD"}])
    with sqlite3.connect(path) as db:
        db.execute("INSERT INTO lr_ledger_records VALUES(?,?,?,?,?,?,?,?)",("ledger-row","u","ledger-7","2026-01-02","Coffee",-100,"USD","x"))
    monkeypatch.setenv("INVESTIGATION_LLM_BASE_URL","https://mock.invalid/v1"); monkeypatch.setenv("INVESTIGATION_LLM_MODEL","test-model"); monkeypatch.setenv("INVESTIGATION_LLM_API_KEY","test-key")
    calls=[]
    def transport(req):
        calls.append(req)
        evidence=json.loads(next(m for m in json.loads(req.content)['messages'] if m['role']=='user')['content'].split('EVIDENCE: ',1)[1])
        source=next(x for x in evidence if x['evidence_type']=='source'); ledger=next(x for x in evidence if x['evidence_type']=='ledger')
        response={"case_id":"u:bank:s","status":"proposed","hypotheses":[{"statement":"Date differs","evidence_ids":[source['id'],ledger['id']],"confidence":0.95}],"abstain_reason":None,"suggestion":{"kind":"allocate","source_record_id":source['id'],"ledger_id":ledger['id'],"rationale":"Exact identity with date variance."}}
        return httpx.Response(200,json={"choices":[{"message":{"content":json.dumps(response)}}]})
    worker=OperationalWorker(path,investigation_agent=InvestigationAgent(transport=httpx.MockTransport(transport)))
    worker.dispatch_outbox(); reconcile=worker.run_one('worker'); assert reconcile['exceptions'][0]['reason']=='date_mismatch'
    result=worker.run_one('worker'); assert result['investigation']['status']=='proposed'
    proposal_id=result['investigation']['resolution_proposal_id']; assert proposal_id and len(calls)==1
    with sqlite3.connect(path) as db:
        source_internal=db.execute("SELECT id FROM lr_source_records WHERE user_id='u'").fetchone()[0]
        proposal=db.execute("SELECT source_id,ledger_id,status,approver,applied_at FROM lr_resolution_proposals WHERE id=?",(proposal_id,)).fetchone()
        assert proposal==(source_internal,"ledger-7","proposed",None,None)
        assert db.execute("SELECT count(*) FROM lr_matches").fetchone()[0]==0


def test_candidate_arrival_stales_old_job_and_requeues_updated_scope(tmp_path, monkeypatch):
    path=tmp_path/"arrival.sqlite"; initialize(path); domain=ReconciliationDomain(path)
    domain.ingest("u","bank","v1",[{"source_id":"s","transaction_id":"x","date":"2026-01-01","description":"Coffee","amount_cents":-100,"currency":"USD"}])
    worker=OperationalWorker(path); worker.dispatch_outbox(); worker.run_one('worker')
    with sqlite3.connect(path) as db:
        old=db.execute("SELECT payload FROM lrq_jobs WHERE job_key LIKE 'investigation:%'").fetchone()[0]
    old_payload=json.loads(old)
    with sqlite3.connect(path) as db:
        db.execute("INSERT INTO lr_ledger_records VALUES(?,?,?,?,?,?,?,?)",("ledger-row","u","ledger-7","2026-01-02","Coffee",-100,"USD","x"))
    assert worker._process_investigation(old_payload)=={"status":"stale","case_id":"u:bank:s"}
    # Reconciliation cycle observes the newly arrived candidate and queues a fresh bounded snapshot.
    domain.ingest("u","bank","v2",[{"source_id":"s2","transaction_id":"x","date":"2026-01-01","description":"Coffee","amount_cents":-100,"currency":"USD"}])
    worker.dispatch_outbox(); worker.run_one('worker')
    with sqlite3.connect(path) as db:
        jobs=db.execute("SELECT payload FROM lrq_jobs WHERE job_key LIKE 'investigation:%' ORDER BY created_at,job_key").fetchall()
    assert any(any(item.get('evidence_type')=='ledger' for item in json.loads(row[0])['evidence']) for row in jobs)


def test_amount_mismatch_suggestion_never_creates_draft(tmp_path, monkeypatch):
    path=tmp_path/"unsafe.sqlite"; initialize(path); domain=ReconciliationDomain(path)
    domain.ingest("u","bank","v1",[{"source_id":"s","transaction_id":"x","date":"2026-01-01","description":"Coffee","amount_cents":-100,"currency":"USD"}])
    with sqlite3.connect(path) as db: db.execute("INSERT INTO lr_ledger_records VALUES(?,?,?,?,?,?,?,?)",("ledger-row","u","ledger-7","2026-01-02","Coffee",-200,"USD","x"))
    monkeypatch.setenv("INVESTIGATION_LLM_BASE_URL","https://mock.invalid/v1"); monkeypatch.setenv("INVESTIGATION_LLM_MODEL","test-model"); monkeypatch.setenv("INVESTIGATION_LLM_API_KEY","test-key")
    def transport(req):
        evidence=json.loads(next(m for m in json.loads(req.content)['messages'] if m['role']=='user')['content'].split('EVIDENCE: ',1)[1]); source=evidence[0]; ledger=evidence[1]
        response={"case_id":"u:bank:s","status":"proposed","hypotheses":[{"statement":"Possible allocation","evidence_ids":[source['id'],ledger['id']],"confidence":0.9}],"abstain_reason":None,"suggestion":{"kind":"allocate","source_record_id":source['id'],"ledger_id":ledger['id'],"rationale":"Model suggestion."}}
        return httpx.Response(200,json={"choices":[{"message":{"content":json.dumps(response)}}]})
    worker=OperationalWorker(path,investigation_agent=InvestigationAgent(transport=httpx.MockTransport(transport)))
    worker.dispatch_outbox(); worker.run_one('worker'); result=worker.run_one('worker')
    assert result['investigation']['suggestion_rejected'] is True
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT count(*) FROM lr_resolution_proposals").fetchone()[0]==0
        assert db.execute("SELECT count(*) FROM lr_matches").fetchone()[0]==0


def test_revision_supersedes_old_case_evidence(tmp_path):
    path=tmp_path/"revisions.sqlite"; initialize(path); domain=ReconciliationDomain(path)
    domain.ingest("u","bank","v9",[{"source_id":"s","transaction_id":"x","date":"2026-01-01","description":"Coffee","amount_cents":-100,"currency":"USD"}])
    worker=OperationalWorker(path); worker.dispatch_outbox(); worker.run_one("w")

    domain.ingest("u","bank","v10",[{"source_id":"s","transaction_id":"x","date":"2026-01-01","description":"Coffee revised","amount_cents":-200,"currency":"USD"}])
    worker.dispatch_outbox(); worker.run_one("w")
    with sqlite3.connect(path) as db:
        row=db.execute("select status,evidence_json from lr_exceptions where id='u:bank:s'").fetchone()
        assert row[0] == "open" and json.loads(row[1])["source_version"] == "v10"
        assert db.execute("select count(*) from lr_exceptions where status='open'").fetchone()[0] == 1


def test_investigation_retries_recover_and_keep_audit_history(tmp_path, monkeypatch):
    monkeypatch.setenv('INVESTIGATION_LLM_API_KEY','test-only')
    monkeypatch.setenv('INVESTIGATION_LLM_BASE_URL','https://mock.invalid/v1')
    monkeypatch.setenv('INVESTIGATION_LLM_MODEL','test-model')
    path=tmp_path/"retry.sqlite"; initialize(path)
    domain=ReconciliationDomain(path)
    domain.ingest("u","bank","v1",[{"source_id":"s","transaction_id":"x","date":"2026-01-01","description":"Coffee","amount_cents":-100,"currency":"USD"}])
    worker=OperationalWorker(path); worker.dispatch_outbox(); worker.run_one("w")

    with sqlite3.connect(path) as db:
        queued=db.execute("select job_key,payload from lrq_jobs where job_key like 'investigation:%'").fetchone()
        assert queued is not None
        assert json.loads(queued[1])["evidence_hash"] in queued[0]
    # Provider failure is retried by the leased queue; a later configured worker recovers it.
    from backend.durable_jobs import DurableJobQueue
    queue=DurableJobQueue(str(path),base_retry_seconds=0)
    unavailable=OperationalWorker(path,queue=queue)
    unavailable.investigation_agent=None
    with pytest.raises(RuntimeError, match='unavailable'):
        unavailable.run_one("w")
    with sqlite3.connect(path) as db:
        assert db.execute("select count(*) from lr_investigations").fetchone()[0] == 0
    evidence=json.loads(queued[1])["evidence"]
    def response(req):
        payload={"case_id":"u:bank:s","status":"proposed","hypotheses":[{"statement":"Possible duplicate","evidence_ids":[evidence[0]["id"]],"confidence":0.7}],"abstain_reason":None}
        return httpx.Response(200,json={"choices":[{"message":{"content":json.dumps(payload)}}]})
    recovered=OperationalWorker(path,queue=DurableJobQueue(str(path),base_retry_seconds=0),investigation_agent=InvestigationAgent(transport=httpx.MockTransport(response)))
    recovered.run_one("w")
    recovered.run_one("w")
    with sqlite3.connect(path) as db:
        assert db.execute("select count(*) from lr_investigations").fetchone()[0] == 1


def test_missing_provider_does_not_auto_configure_from_unrelated_env(tmp_path, monkeypatch):
    monkeypatch.setenv("INVESTIGATION_LLM_API_KEY", "dummy")
    monkeypatch.setenv("INVESTIGATION_LLM_BASE_URL", "https://mock.invalid")
    monkeypatch.delenv("INVESTIGATION_API_KEY", raising=False)
    monkeypatch.delenv("INVESTIGATION_BASE_URL", raising=False)
    worker=OperationalWorker(tmp_path/"no-provider.sqlite")
    assert worker.investigation_agent is None
