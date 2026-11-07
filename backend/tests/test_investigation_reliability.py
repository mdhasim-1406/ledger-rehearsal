import json
import sqlite3
import threading
import time
from types import SimpleNamespace

import pytest
from backend.domain_foundation import initialize, ReconciliationDomain
from backend.operational_pipeline import OperationalWorker
from backend.investigation_agent import InvestigationResult, Hypothesis, ResolutionSuggestion
from backend.resolution import ResolutionService


def setup_case(tmp_path):
    path=tmp_path/'reliability.sqlite'; initialize(path)
    domain=ReconciliationDomain(path)
    domain.add_ledger_record('u','l','2026-01-02','ledger',100,'USD','x')
    domain.ingest('u','bank','1',[{'source_id':'s','date':'2026-01-01','description':'bank','amount_cents':100,'currency':'USD','transaction_id':'x'}])
    worker=OperationalWorker(path); worker.dispatch_outbox(); worker.run_one('setup')
    with sqlite3.connect(path) as db:
        payload=json.loads(db.execute("SELECT payload FROM lrq_jobs WHERE job_key LIKE 'investigation:%'").fetchone()[0])
    ResolutionService(path)._ensure_schema()
    return path,domain,worker,payload


def answer(case,evidence):
    return InvestigationResult(case_id=case,status='proposed',hypotheses=[Hypothesis(statement='date mismatch',evidence_ids=[e['id'] for e in evidence],confidence=.8)],suggestion=ResolutionSuggestion(kind='allocate',source_record_id=evidence[0]['id'],ledger_id=evidence[1]['id'],rationale='Exact identity'))


def counts(path):
    with sqlite3.connect(path) as db:
        return (db.execute('SELECT count(*) FROM lr_resolution_proposals').fetchone()[0],db.execute('SELECT count(*) FROM lr_investigations').fetchone()[0])


def test_replay_creates_one_draft(tmp_path):
    path,domain,worker,payload=setup_case(tmp_path)
    worker.investigation_agent=SimpleNamespace(investigate=answer)
    first=worker._process_investigation(payload)
    second=worker._process_investigation(payload)
    assert first['resolution_proposal_id']==second['resolution_proposal_id']
    assert counts(path)==(1,1)


def test_failure_after_draft_rolls_back(tmp_path,monkeypatch):
    path,domain,worker,payload=setup_case(tmp_path)
    worker.investigation_agent=SimpleNamespace(investigate=answer)
    with sqlite3.connect(path) as db:
        db.execute("CREATE TRIGGER injected_failure BEFORE INSERT ON lr_investigations BEGIN SELECT RAISE(ABORT,'injected crash after draft insert'); END")
    with pytest.raises(sqlite3.IntegrityError,match='injected crash'):
        worker._process_investigation(payload)
    assert counts(path)==(0,0)
    with sqlite3.connect(path) as db:
        assert db.execute('SELECT count(*) FROM lr_resolution_audit').fetchone()[0]==0
        db.execute('DROP TRIGGER injected_failure')
    worker._process_investigation(payload)
    assert counts(path)==(1,1)


def test_candidate_changed_during_inference_leaves_no_draft(tmp_path):
    path,domain,worker,payload=setup_case(tmp_path)
    def mutate(case,evidence):
        # A differing-amount candidate changes the full snapshot but not allocation uniqueness.
        domain.add_ledger_record('u','new','2026-01-03','new',200,'USD','x')
        return answer(case,evidence)
    worker.investigation_agent=SimpleNamespace(investigate=mutate)
    assert worker._process_investigation(payload)['status']=='stale'
    assert counts(path)==(0,0)


def test_short_lease_is_renewed_while_inference_runs(tmp_path):
    path,domain,worker,payload=setup_case(tmp_path)
    entered=threading.Event(); results=[]
    def slow(case,evidence):
        entered.set();time.sleep(.55);return answer(case,evidence)
    worker.investigation_agent=SimpleNamespace(investigate=slow)
    thread=threading.Thread(target=lambda:results.append(worker.run_one('slow',lease_seconds=.2)))
    thread.start(); assert entered.wait(2)
    time.sleep(.3)
    assert worker.queue.claim('competitor',lease_seconds=1) is None
    thread.join(3);assert not thread.is_alive()
    assert counts(path)==(1,1)


def test_lost_lease_cannot_create_draft(tmp_path,monkeypatch):
    path,domain,worker,payload=setup_case(tmp_path)
    def steal(case,evidence):
        with sqlite3.connect(path) as db:
            db.execute("UPDATE lrq_jobs SET lease_token='stolen' WHERE job_key LIKE 'investigation:%'")
        return answer(case,evidence)
    worker.investigation_agent=SimpleNamespace(investigate=steal)
    with pytest.raises(RuntimeError,match='lease lost'):
        worker.run_one('owner')
    assert counts(path)==(0,0)
