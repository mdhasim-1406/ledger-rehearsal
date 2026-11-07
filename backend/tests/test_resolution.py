import sqlite3
import pytest
from backend.domain_foundation import initialize, ReconciliationDomain
from backend.operational_pipeline import OperationalWorker
from backend.resolution import ResolutionService

REVIEWER={'id':'reviewer','role':'reviewer'}
ADMIN={'id':'admin','role':'admin'}
@pytest.fixture
def service(tmp_path):
    db=tmp_path/'db.sqlite'; initialize(db); OperationalWorker(db)
    d=ReconciliationDomain(db)
    d.ingest('u','bank','v1',[{'source_id':'s','date':'2026-01-01','description':'payment','amount_cents':500,'currency':'USD','transaction_id':'tx'}])
    d.add_ledger_record('u','l','2026-01-01','payment',500,'USD','tx')
    with sqlite3.connect(db) as c:
        source_id=c.execute('select id from lr_source_records').fetchone()[0]
        import json
        c.execute("insert into lr_exceptions(id,outbox_id,user_id,reason,evidence_json,created_at,status) values('case','o','u','test',?, 'now','open')",(json.dumps({'source_record_id':source_id}),))
    return ResolutionService(db), db

def source(db):
    with sqlite3.connect(db) as c: return c.execute('select id from lr_source_records').fetchone()[0]
def propose(s,db): return s.propose('u','case',REVIEWER,{'source_record_id':source(db),'ledger_id':'l'})
def test_propose_rehearse_approve_apply_is_idempotent(service):
    s,db=service; p=propose(s,db)
    assert s.rehearse('u',p['id'],REVIEWER)['would_match']
    assert s.approve('u',p['id'],ADMIN)['status']=='approved'
    result=s.apply('u',p['id'],ADMIN,'key1'); assert result['status']=='applied' and result['external_posted'] is False
    assert s.apply('u',p['id'],ADMIN,'key1')==result
    with sqlite3.connect(db) as c: assert c.execute("select count(*) from lr_matches where status='active'").fetchone()[0]==1

def test_approval_requires_successful_current_rehearsal(service):
    s,db=service; p=propose(s,db)
    with pytest.raises(ValueError): s.approve('u',p['id'],ADMIN)
    assert s.rehearse('u',p['id'],REVIEWER)['would_match']
    with sqlite3.connect(db) as c: c.execute("update lr_ledger_records set description='changed'")
    with pytest.raises(ValueError): s.approve('u',p['id'],ADMIN)

def test_proposal_case_and_source_revision_are_bound(service):
    s,db=service; p=propose(s,db)
    with sqlite3.connect(db) as c:
        c.execute("insert into lr_exceptions(id,outbox_id,user_id,reason,evidence_json,created_at,status) values('other','o','u','test','{}','now','open')")
        c.execute("update lr_source_records set description='changed'")
    assert s.rehearse('u',p['id'],REVIEWER)['would_match'] is False
    with pytest.raises(ValueError):
        s.propose('u','other',REVIEWER,{'source_record_id':source(db),'ledger_id':'l'})

def test_apply_readback_includes_match_and_closed_case(service):
    s,db=service; p=propose(s,db); s.rehearse('u',p['id'],REVIEWER); s.approve('u',p['id'],ADMIN)
    result=s.apply('u',p['id'],ADMIN,'key')
    with sqlite3.connect(db) as c:
        assert c.execute('select status from lr_matches where id=?',(result['match_id'],)).fetchone()==('active',)
        assert c.execute("select status from lr_exceptions where id='case'").fetchone()==('resolved',)

def test_rehearsal_is_read_only_and_stale_evidence_blocks_apply(service):
    s,db=service; p=propose(s,db); s.rehearse('u',p['id'],REVIEWER); s.approve('u',p['id'],ADMIN)
    assert s.rehearse('u',p['id'],REVIEWER)['no_changes']
    with sqlite3.connect(db) as c: c.execute("update lr_ledger_records set description='changed'")
    with pytest.raises(ValueError): s.apply('u',p['id'],ADMIN,'key')

def test_duplicate_candidate_and_cross_case_rejected(service):
    s,db=service; ReconciliationDomain(db).add_ledger_record('u','l2','2026-01-01','same',500,'USD','tx')
    with pytest.raises(ValueError): propose(s,db)
    p=propose_after_removing_duplicate(s,db)
    with pytest.raises(ValueError): s.rehearse('other',p['id'],REVIEWER)
def propose_after_removing_duplicate(s,db):
    with sqlite3.connect(db) as c: c.execute("delete from lr_ledger_records where ledger_id='l2'")
    return propose(s,db)
def test_role_and_separation_of_duties(service):
    s,db=service; p=propose(s,db)
    with pytest.raises(ValueError): s.approve('u',p['id'],REVIEWER)
    with pytest.raises(ValueError): s.approve('u',p['id'],{'id':'reviewer','role':'admin'})
    with pytest.raises(ValueError): s.apply('u',p['id'],ADMIN,'')

def test_case_status_change_invalidates_proposal(service):
    s,db=service; p=propose(s,db); s.rehearse('u',p['id'],REVIEWER); s.approve('u',p['id'],ADMIN)
    with sqlite3.connect(db) as c: c.execute("update lr_exceptions set status='closed' where id='case'")
    with pytest.raises(ValueError): s.apply('u',p['id'],ADMIN,'key')
