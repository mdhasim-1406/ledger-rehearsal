import json

import httpx

from investigation_agent import InvestigationAgent


class QueueTransport(httpx.BaseTransport):
    def __init__(self, bodies):
        self.bodies = iter(bodies)
        self.requests = []

    def handle_request(self, request):
        body = json.loads(request.content)
        self.requests.append(body)
        return httpx.Response(200, json=next(self.bodies))


def message(content=None, calls=None):
    msg = {"role": "assistant", "content": content}
    if calls is not None:
        msg["tool_calls"] = calls
    return {"choices": [{"message": msg}]}


def call(ids, name="get_evidence", call_id="c1"):
    return {"id": call_id, "type": "function", "function": {"name": name, "arguments": json.dumps({"ids": ids})}}


def configured(monkeypatch):
    monkeypatch.setenv("INVESTIGATION_LLM_BASE_URL", "https://provider.invalid/v1")
    monkeypatch.setenv("INVESTIGATION_LLM_MODEL", "test")
    monkeypatch.setenv("INVESTIGATION_LLM_API_KEY", "test-only")


def test_graph_entrypoint_returns_scoped_tool_evidence_and_final_refs(monkeypatch, tmp_path):
    configured(monkeypatch)
    transport = QueueTransport([
        message(calls=[call(["e2"])]),
        message(content=json.dumps({"case_id": "case", "status": "proposed", "hypotheses": [
            {"statement": "match", "evidence_ids": ["e2"], "confidence": 0.8}]})),
    ])
    result = InvestigationAgent(transport=transport, checkpoint_db=tmp_path / "graph.sqlite").investigate("case", [{"id": "e1", "v": "one"}, {"id": "e2", "v": "two"}])
    assert result.status == "proposed"
    assert len(transport.requests) == 2
    assert transport.requests[0]["tools"][0]["function"]["name"] == "get_evidence"
    second = transport.requests[1]["messages"][-1]
    assert second["role"] == "tool" and second["tool_call_id"] == "c1"
    assert json.loads(second["content"]) == [{"id": "e2", "v": "two"}]


def test_rejects_unknown_function_and_malformed_arguments(monkeypatch):
    configured(monkeypatch)
    import tempfile
    from pathlib import Path
    for tool in [call(["e1"], name="delete_records"), {"id": "c1", "type": "function", "function": {"name": "get_evidence", "arguments": "[]"}}]:
        transport = QueueTransport([message(calls=[tool])])
        result = InvestigationAgent(transport=transport, checkpoint_db=Path(tempfile.mktemp())).investigate("case", [{"id": "e1"}])
        assert result.status == "unavailable"
        assert len(transport.requests) == 1


def test_bounds_tool_chain_and_oversized_provider_response(monkeypatch):
    configured(monkeypatch)
    import tempfile
    from pathlib import Path
    chain = QueueTransport([message(calls=[call(["e1"], call_id=f"c{i}")]) for i in range(5)])
    result = InvestigationAgent(transport=chain, checkpoint_db=Path(tempfile.mktemp())).investigate("case", [{"id": "e1"}])
    assert result.status == "unavailable"
    assert len(chain.requests) <= 3

    huge = QueueTransport([message(content=" " * 200_000)])
    result = InvestigationAgent(transport=huge, checkpoint_db=Path(tempfile.mktemp())).investigate("case", [{"id": "e1"}])
    assert result.status == "unavailable"
    assert len(huge.requests) == 1
