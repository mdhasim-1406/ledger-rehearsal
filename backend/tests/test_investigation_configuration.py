from backend.domain_foundation import initialize
from backend.operational_pipeline import OperationalWorker

def test_worker_uses_documented_provider_settings(tmp_path,monkeypatch):
    for k in ('INVESTIGATION_API_KEY','INVESTIGATION_BASE_URL'): monkeypatch.delenv(k,raising=False)
    for k in ('INVESTIGATION_LLM_API_KEY','INVESTIGATION_LLM_BASE_URL','INVESTIGATION_LLM_MODEL'): monkeypatch.setenv(k,'test-only')
    db=tmp_path/'test.sqlite';initialize(db)
    assert OperationalWorker(db).investigation_agent is not None
