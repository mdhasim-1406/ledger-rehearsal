import sqlite3
from backend.domain_foundation import initialize,ReconciliationDomain
from backend.operational_pipeline import OperationalWorker

def test_unmatched_case_resolves_after_counterpart_arrives(tmp_path):
    db=tmp_path/'lifecycle.sqlite';initialize(db);d=ReconciliationDomain(db);w=OperationalWorker(db)
    d.ingest('u','bank','v1',[{'source_id':'s1','transaction_id':'T','date':'2026-01-01','description':'entry','amount_cents':100,'currency':'USD'}])
    w.dispatch_outbox();w.run_one('w')
    with sqlite3.connect(db) as c:
        assert c.execute('select count(*) from lr_exceptions').fetchone()[0] > 0
    d.add_ledger_record('u','l1','2026-01-01','entry',100,'USD',transaction_id='T')
    w.dispatch_outbox()
    while w.run_one('w'): pass
    with sqlite3.connect(db) as c:
        assert c.execute("select count(*) from lr_matches where status='active'").fetchone()[0] == 1
        assert c.execute("select count(*) from lr_exceptions where status='open'").fetchone()[0] == 0
