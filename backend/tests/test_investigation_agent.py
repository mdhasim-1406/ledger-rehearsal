import json
import sqlite3
from pathlib import Path
import httpx
from backend.investigation_agent import InvestigationAgent, InvestigationResult


def test_runner():
    pass


def response(content):
    return httpx.Response(200, json={"choices":[{"message":{"content":json.dumps(content)}}]})


def test_valid_hypothesis_and_scoped_read_only_tools(monkeypatch):
    requests=[]
    def handler(req):
        body=json.loads(req.content); requests.append(body)
        return response({"case_id":"c1","status":"proposed","hypotheses":[{"statement":"Possible duplicate","evidence_ids":["e1"],"confidence":0.6}],"abstain_reason":None})
    monkeypatch.setenv("INVESTIGATION_LLM_BASE_URL","https://llm.test/v1")
    monkeypatch.setenv("INVESTIGATION_LLM_MODEL","model-x")
    monkeypatch.setenv("INVESTIGATION_LLM_API_KEY","secret-test")
    agent=InvestigationAgent(transport=httpx.MockTransport(handler), checkpoint_db=Path('/tmp')/f"investigation-{__import__('uuid').uuid4().hex}.sqlite")
    result=agent.investigate("c1", [{"id":"e1","description":"Coffee"}])
    assert isinstance(result, InvestigationResult)
    assert result.hypotheses[0].evidence_ids == ["e1"]
    assert "secret-test" not in repr(result)
    assert "untrusted" in requests[0]["messages"][0]["content"].lower()


def test_missing_config_is_unavailable(monkeypatch):
    for k in ("INVESTIGATION_LLM_BASE_URL","INVESTIGATION_LLM_MODEL","INVESTIGATION_LLM_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    assert InvestigationAgent().investigate("c", []).status == "unavailable"


def test_abstain_and_bad_scope_fail_closed(monkeypatch):
    monkeypatch.setenv("INVESTIGATION_LLM_BASE_URL","https://llm.test/v1")
    monkeypatch.setenv("INVESTIGATION_LLM_MODEL","m")
    monkeypatch.setenv("INVESTIGATION_LLM_API_KEY","secret")
    def run(payload):
        import tempfile
        with tempfile.TemporaryDirectory() as checkpoint_dir:
            return InvestigationAgent(transport=httpx.MockTransport(lambda r: response(payload)), checkpoint_db=Path(checkpoint_dir)/"state.sqlite").investigate("c", [{"id":"e1"}])
    abstain=run({"case_id":"c","status":"abstain","hypotheses":[],"abstain_reason":"insufficient evidence"})
    assert abstain.status == "abstain"
    assert run({"case_id":"c","status":"proposed","hypotheses":[{"statement":"x","evidence_ids":["other"],"confidence":0.5}],"abstain_reason":None}).status == "unavailable"
    assert run({"case_id":"c","status":"proposed","hypotheses":[],"abstain_reason":None,"write":"bad"}).status == "unavailable"


def test_timeout_and_http_error_unavailable(monkeypatch):
    monkeypatch.setenv("INVESTIGATION_LLM_BASE_URL","https://llm.test/v1")
    monkeypatch.setenv("INVESTIGATION_LLM_MODEL","m")
    monkeypatch.setenv("INVESTIGATION_LLM_API_KEY","secret")
    a=InvestigationAgent(transport=httpx.MockTransport(lambda r: httpx.Response(503)))
    assert a.investigate("c", []).status == "unavailable"
    b=InvestigationAgent(transport=httpx.MockTransport(lambda r: (_ for _ in ()).throw(httpx.TimeoutException("late"))))
    assert b.investigate("c", []).status == "unavailable"
