import sqlite3
from backend.domain_foundation import initialize, ReconciliationDomain

def test_source_revision_releases_ledger_but_preserves_history(tmp_path):
    db=tmp_path/'revision.sqlite';initialize(db);d=ReconciliationDomain(db)
    row={'source_id':'bank1','transaction_id':'TX','date':'2026-01-02','description':'payment','amount_cents':-425,'currency':'USD'}
    d.ingest('u','bank','1',[row]);d.add_ledger_record('u','l1','2026-01-02','payment',-425,'USD',transaction_id='TX')
    assert d.reconcile('u')['matched']==1
    d.ingest('u','bank','2',[dict(row,amount_cents=-500)])
    assert d.reconcile('u')['matched']==0
    d.ingest('u','bank','3',[row])
    assert d.reconcile('u')['matched']==1
    with sqlite3.connect(db) as conn:
        statuses=conn.execute('SELECT status, count(*) FROM lr_matches GROUP BY status').fetchall()
    assert dict(statuses)=={'active':1,'stale':1}
