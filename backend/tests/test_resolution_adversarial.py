import sqlite3
import pytest
from backend.domain_foundation import initialize,ReconciliationDomain
from backend.operational_pipeline import OperationalWorker
from backend.resolution import ResolutionService

def test_proposal_cannot_use_another_case_source(tmp_path):
 db=tmp_path/'s.sqlite';initialize(db);d=ReconciliationDomain(db);w=OperationalWorker(db)
 rows=[{'source_id':'a','transaction_id':'A','date':'2026-01-01','description':'a','amount_cents':100,'currency':'USD'},{'source_id':'b','transaction_id':'B','date':'2026-01-01','description':'b','amount_cents':200,'currency':'USD'}]
 d.ingest('u','bank','v1',rows);w.dispatch_outbox();w.run_one('w')
 d.add_ledger_record('u','ledger-b','2026-01-01','b',200,'USD',transaction_id='B')
 with sqlite3.connect(db) as c:
  case=c.execute("select id from lr_exceptions where id='u:bank:a'").fetchone()[0]
  source=c.execute("select id from lr_source_records where source_id='b'").fetchone()[0]
  ledger=c.execute("select id from lr_ledger_records where ledger_id='ledger-b'").fetchone()[0]
 with pytest.raises(ValueError):
  ResolutionService(db).propose('u',case,{'id':'reviewer','role':'reviewer'},{'source_record_id':source,'ledger_id':'ledger-b'})
