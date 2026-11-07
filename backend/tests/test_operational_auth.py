import pytest
import sqlite3
from fastapi import FastAPI, Depends
from fastapi.testclient import TestClient

from backend.operational_auth import OperationalAuth, AuthConfigError, require_roles


def setup_app():
    auth = OperationalAuth.from_env({"OPERATIONAL_ADMIN_CREDENTIAL": "admin-secret-for-test"})
    app = FastAPI()
    @app.get("/private")
    def private(actor=Depends(auth.require_roles("admin", "viewer"))):
        return {"actor": actor.name, "role": actor.role}
    @app.post("/private")
    def unsafe(actor=Depends(auth.require_roles("admin"))):
        return {"actor": actor.name}
    @app.get("/events")
    def events(actor=Depends(auth.require_roles("viewer", sse=True))):
        return {"actor": actor.name}
    return auth, TestClient(app)

def test_initial_admin_and_bearer_role_auth():
    auth, client = setup_app()
    token = auth.bootstrap_token
    assert token and auth._db.execute("SELECT COUNT(*) FROM credentials").fetchone()[0] == 1
    assert client.get("/private", headers={"Authorization": "Bearer " + token}).json() == {"actor": "admin", "role": "admin"}

def test_no_auth_and_bad_token_rejected():
    _, client = setup_app()
    assert client.get("/private").status_code == 401
    assert client.get("/private", headers={"Authorization": "Bearer wrong"}).status_code == 401

def test_role_denial():
    auth, client = setup_app()
    token = auth.issue_token("read-only", "viewer")
    assert client.post("/private", headers={"Authorization": "Bearer " + token}).status_code == 403

def test_origin_and_csrf_rules():
    auth, client = setup_app()
    token = auth.bootstrap_token
    h = {"Authorization": "Bearer " + token}
    assert client.post("/private", headers=h).status_code == 403
    assert client.post("/private", headers={**h, "Origin": "https://evil.invalid"}).status_code == 403
    assert client.post("/private", headers={**h, "Origin": "http://localhost"}).status_code == 200
    assert client.get("/private", headers={**h, "Origin": "https://evil.invalid"}).status_code == 403

def test_machine_client_without_origin_allowed_but_sse_still_authenticates():
    auth, client = setup_app()
    token = auth.issue_token("robot", "viewer")
    assert client.get("/private", headers={"Authorization": "Bearer " + token}).status_code == 200
    assert client.get("/events").status_code == 401
    assert client.get("/events", headers={"Authorization": "Bearer " + token}).status_code == 200

def test_no_configuration_refuses_bootstrap():
    with pytest.raises(AuthConfigError):
        OperationalAuth.from_env({})

def test_restart_persists_bootstrap_and_issued_tokens_and_revocation(tmp_path):
    db = str(tmp_path / "auth.sqlite")
    env = {"OPERATIONAL_ADMIN_CREDENTIAL": "admin-secret-for-test", "OPERATIONAL_AUTH_DB": db}
    first = OperationalAuth.from_env(env)
    issued = first.issue_token("persisted", "viewer")
    first._db.close()
    second = OperationalAuth.from_env(env)
    assert second.bootstrap_token == "bootstrap.admin-secret-for-test"
    assert second._db.execute("SELECT COUNT(*) FROM credentials").fetchone()[0] == 2
    # persisted viewer can authenticate after process-local registry is replaced
    app = FastAPI()
    app.get("/private")(lambda actor=Depends(second.require_roles("viewer")): {"actor": actor.name})
    assert TestClient(app).get("/private", headers={"Authorization": "Bearer " + issued}).json() == {"actor": "persisted"}
    token_id = issued.split(".", 1)[0]
    assert second.revoke_token(token_id)
    assert TestClient(app).get("/private", headers={"Authorization": "Bearer " + issued}).status_code == 401
    with pytest.raises(AuthConfigError):
        OperationalAuth.from_env({**env, "OPERATIONAL_ADMIN_CREDENTIAL": "different-admin-secret"})

def test_persistent_database_contains_only_salted_hashes(tmp_path):
    db = str(tmp_path / "auth.sqlite")
    secret = "admin-secret-for-test"
    auth = OperationalAuth(secret, database=db)
    row = sqlite3.connect(db).execute("SELECT salt,digest FROM credentials WHERE id='bootstrap'").fetchone()
    assert row and row[0] != row[1] and secret.encode() not in row[0] + row[1]
