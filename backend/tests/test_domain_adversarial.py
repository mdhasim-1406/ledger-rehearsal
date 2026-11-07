"""Adversarial cross-record regressions for the nascent reconciliation domain."""
import sqlite3
import pytest
from backend.domain_foundation import initialize,ReconciliationDomain

def bank(sid,amount=-425,version='T'):
    return {'source_id':sid,'transaction_id':version,'date':'2026-01-02','description':'entry','amount_cents':amount,'currency':'USD'}

def test_same_version_conflicting_content_is_never_silently_deduplicated(tmp_path):
    path=tmp_path/'test.sqlite';initialize(path);d=ReconciliationDomain(path)
    d.ingest('u','bank','v1',[bank('1')])
    with pytest.raises(ValueError):
        d.ingest('u','bank','v1',[bank('1',-999)])

def test_duplicate_bank_candidates_never_match_one_ledger(tmp_path):
    path=tmp_path/'test.sqlite';initialize(path);d=ReconciliationDomain(path)
    d.ingest('u','bank','v1',[bank('1'),bank('2')])
    d.add_ledger_record('u','l1','2026-01-02','entry',-425,'USD',transaction_id='T')
    assert d.reconcile('u')['matched']==0

def test_replaced_version_not_available_as_candidate(tmp_path):
    path=tmp_path/'test.sqlite';initialize(path);d=ReconciliationDomain(path)
    d.ingest('u','bank','v1',[bank('1',-425)])
    d.ingest('u','bank','v2',[bank('1',-999)])
    d.add_ledger_record('u','l1','2026-01-02','entry',-425,'USD',transaction_id='T')
    assert d.reconcile('u')['matched']==0
