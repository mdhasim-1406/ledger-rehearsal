"""Execute representative safe and abstain outcomes through the real SQLite domain/worker."""
import sqlite3

import pytest

from backend.domain_foundation import ReconciliationDomain, initialize
from backend.operational_pipeline import OperationalWorker


@pytest.mark.parametrize(('case','source','ledgers','expected'), [
    ('unique_exact', {'date':'2026-01-01','amount_cents':1234,'currency':'USD','transaction_id':'T1'}, [('2026-01-01',1234,'USD','T1')], 'matched'),
    ('date_difference', {'date':'2026-01-01','amount_cents':1234,'currency':'USD','transaction_id':'T2'}, [('2026-01-02',1234,'USD','T2')], 'date_mismatch'),
    ('amount_or_fee_difference', {'date':'2026-01-01','amount_cents':1234,'currency':'USD','transaction_id':'T3'}, [('2026-01-01',1300,'USD','T3')], 'amount_mismatch'),
    ('duplicate_candidates', {'date':'2026-01-01','amount_cents':1234,'currency':'USD','transaction_id':'T4'}, [('2026-01-01',1234,'USD','T4'),('2026-01-01',1234,'USD','T4')], 'ambiguous_candidate'),
    ('missing_ledger_counterpart', {'date':'2026-01-01','amount_cents':1234,'currency':'USD','transaction_id':'T5'}, [], 'missing_ledger_record'),
    ('missing_transaction_identity', {'date':'2026-01-01','amount_cents':1234,'currency':'USD','transaction_id':''}, [], 'missing_transaction_identity'),
    ('currency_difference', {'date':'2026-01-01','amount_cents':1234,'currency':'USD','transaction_id':'T6'}, [('2026-01-01',1234,'EUR','T6')], 'currency_mismatch'),
])
def test_representative_outcomes_execute_through_domain_and_worker(tmp_path, case, source, ledgers, expected):
    database=tmp_path/f'{case}.sqlite'; initialize(database); domain=ReconciliationDomain(database)
    domain.ingest('local','bank','v1',[{'source_id':'source-1','transaction_id':source['transaction_id'],'date':source['date'],'description':case,'amount_cents':source['amount_cents'],'currency':source['currency']}])
    for index,(day,cents,currency,txid) in enumerate(ledgers):
        domain.add_ledger_record('local',f'ledger-{index}',day,case,cents,currency,txid)
    worker=OperationalWorker(database); worker.dispatch_outbox(); result=worker.run_one('corpus-worker')
    with sqlite3.connect(database) as db:
        matched=db.execute("SELECT count(*) FROM lr_matches WHERE user_id='local' AND status='active'").fetchone()[0]
        exceptions=db.execute("SELECT reason FROM lr_exceptions WHERE user_id='local' AND status='open'").fetchall()
    if expected=='matched':
        assert result['matched']['matched']==1 and matched==1 and exceptions==[]
    else:
        assert matched==0
        assert [row[0] for row in exceptions]==[expected]
