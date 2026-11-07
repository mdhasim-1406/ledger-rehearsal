import json
import sqlite3
import httpx

from fastapi.testclient import TestClient

from backend.domain_foundation import initialize
from backend.operational_api import create_app
from backend.operational_auth import OperationalAuth
from backend.operational_pipeline import OperationalWorker


def app_for(tmp_path):
    path = tmp_path / 'ops.sqlite'
    initialize(path)
    auth = OperationalAuth('test-bootstrap-credential-123', database=str(path))
    return create_app(path, auth=auth, start_worker=False), auth, path


def test_metrics_requires_auth_and_returns_authoritative_snapshot(tmp_path):
    app, auth, path = app_for(tmp_path)
    with TestClient(app) as client:
        assert client.get('/api/metrics').status_code == 401
        headers = {'Authorization': f'Bearer {auth.bootstrap_token}'}
        result = client.get('/api/metrics', headers=headers)
        assert result.status_code == 200
        assert result.json()['bank_records'] == 0
        assert result.json()['open_exceptions'] == 0
        assert client.get('/api/overview', headers=headers).json()['bank_records'] == 0


def test_event_replay_after_cursor_is_ordered_and_authenticated(tmp_path):
    import asyncio

    app, auth, path = app_for(tmp_path)
    with sqlite3.connect(path) as db:
        for event_id, kind in [(1, 'first'), (2, 'second'), (3, 'latest')]:
            db.execute('INSERT INTO lr_events VALUES(?,?,?,?,?)', (event_id, 'local', kind, '{}', '2026-01-01T00:00:00+00:00'))

    # Exercise the actual endpoint generator with bounded consumption.
    from starlette.requests import Request
    from starlette.responses import StreamingResponse
    endpoint = next(route.endpoint for route in app.routes if getattr(route, 'path', None) == '/api/events')
    scope = {'type': 'http', 'method': 'GET', 'path': '/api/events', 'headers': [(b'last-event-id', b'1')], 'query_string': b'', 'server': ('testserver', 80), 'client': ('testclient', 1), 'scheme': 'http'}
    async def receive():
        return {'type': 'http.request', 'body': b'', 'more_body': False}
    request = Request(scope, receive)
    async def exercise_stream():
        response = await endpoint(request, actor='local')
        assert isinstance(response, StreamingResponse)
        chunks = []
        iterator = response.body_iterator
        iterator = response.body_iterator
        try:
            async for chunk in iterator:
                chunks.append(chunk.decode() if isinstance(chunk, bytes) else chunk)
                if sum(line.startswith('data: ') for line in ''.join(chunks).splitlines()) == 2:
                    break
        finally:
            await iterator.aclose()
        payloads = [json.loads(line[6:]) for line in ''.join(chunks).splitlines() if line.startswith('data: ')]
        assert [item['type'] for item in payloads] == ['second', 'latest']
        assert [item['event_id'] for item in payloads] == ['2', '3']
    asyncio.run(asyncio.wait_for(exercise_stream(), timeout=2))

    # Verify auth at the real HTTP boundary using a finite response timeout;
    # unauthorized requests terminate without entering the infinite SSE stream.
    with TestClient(app) as client:
        assert client.get('/api/events', timeout=2).status_code == 401
