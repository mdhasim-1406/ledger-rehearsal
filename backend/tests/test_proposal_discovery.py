from fastapi.testclient import TestClient
from backend.operational_api import create_app
from backend.operational_auth import OperationalAuth

def test_authenticated_identity_and_proposal_discovery(tmp_path):
    path=tmp_path/'discovery.sqlite'
    auth=OperationalAuth('isolated-test-secret-only',database=str(path))
    app=create_app(path,auth=auth,start_worker=False)
    token=auth.issue_token('reviewer-one','reviewer')
    with TestClient(app) as client:
        assert client.get('/api/me').status_code==401
        headers={'Authorization':'Bearer '+token}
        assert client.get('/api/me',headers=headers).json()=={'name':'reviewer-one','role':'reviewer','workspace':'local'}
        assert client.get('/api/resolutions/proposals',headers=headers).json()==[]
