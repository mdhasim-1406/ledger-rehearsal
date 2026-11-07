from fastapi.testclient import TestClient
from starlette.responses import JSONResponse
from backend.operational_api import MAX_BODY_BYTES, create_app
from backend.operational_auth import OperationalAuth


def test_body_limit_rejects_chunked_bytes_without_content_length(tmp_path):
    auth = OperationalAuth('test-bootstrap-credential-123')
    app = create_app(tmp_path / 'body.sqlite', auth=auth, start_worker=False)

    @app.post('/probe')
    async def probe(payload: dict):
        return JSONResponse({'received': True})

    body = b'{"x":"' + (b'a' * MAX_BODY_BYTES) + b'"}'
    with TestClient(app) as client:
        response = client.post('/probe', content=body, headers={'content-type': 'application/json', 'authorization': f'Bearer {auth.bootstrap_token}', 'transfer-encoding': 'chunked'})
    assert response.status_code == 413
