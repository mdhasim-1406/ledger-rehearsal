import asyncio
import sqlite3

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from backend.operational_auth import AuthConfigError, OperationalAuth


def request(token):
    return Request({"type": "http", "method": "GET", "headers": [(b"authorization", f"Bearer {token}".encode())], "scheme": "http", "server": ("test", 80), "path": "/", "query_string": b"", "client": ("test", 1), "http_version": "1.1"})


async def authenticate(auth, token):
    return await auth.authenticate(request(token))


def test_bootstrap_rotation_persists_and_old_secret_fails(tmp_path):
    db = str(tmp_path / "auth.sqlite")
    auth = OperationalAuth("first-bootstrap-secret-123", database=db)
    assert asyncio.run(authenticate(auth, auth.bootstrap_token)).name == "admin"
    auth.close()
    with pytest.raises(AuthConfigError):
        OperationalAuth("second-bootstrap-secret-456", database=db)
    rotated = OperationalAuth("first-bootstrap-secret-123", database=db, rotation_credential="second-bootstrap-secret-456")
    assert asyncio.run(authenticate(rotated, "bootstrap.second-bootstrap-secret-456")).role == "admin"
    with pytest.raises(HTTPException):
        asyncio.run(authenticate(rotated, "bootstrap.first-bootstrap-secret-123"))
    rotated.close()
    reopened = OperationalAuth("second-bootstrap-secret-456", database=db)
    assert asyncio.run(authenticate(reopened, "bootstrap.second-bootstrap-secret-456")).name == "admin"
    reopened.close()


def test_revoked_credential_stays_revoked_after_restart(tmp_path):
    db = str(tmp_path / "auth.sqlite")
    auth = OperationalAuth("stable-bootstrap-secret-123", database=db)
    token = auth.issue_token("worker", "operator")
    token_id = token.split(".", 1)[0]
    assert auth.revoke_token(token_id)
    auth.close()
    reopened = OperationalAuth("stable-bootstrap-secret-123", database=db)
    with pytest.raises(HTTPException):
        asyncio.run(authenticate(reopened, token))
    reopened.close()


def test_bootstrap_cannot_be_revoked_and_namespace_collision_is_rejected(tmp_path):
    db = str(tmp_path / "auth.sqlite")
    auth = OperationalAuth("stable-bootstrap-secret-123", database=db)
    with pytest.raises(ValueError):
        auth.revoke_token("bootstrap")
    # Corrupt/legacy databases must not silently adopt another actor's bootstrap id.
    auth._db.execute("UPDATE credentials SET name='intruder' WHERE id='bootstrap'")
    auth._db.commit()
    auth.close()
    with pytest.raises(AuthConfigError):
        OperationalAuth("stable-bootstrap-secret-123", database=db)


def test_issued_token_identifier_collision_does_not_overwrite(tmp_path, monkeypatch):
    auth = OperationalAuth("stable-bootstrap-secret-123", database=str(tmp_path / "auth.sqlite"))
    first = auth.issue_token("one", "viewer")
    collision_id = first.split(".", 1)[0]
    monkeypatch.setattr("backend.operational_auth.secrets.token_urlsafe", lambda n: collision_id)
    with pytest.raises((ValueError, sqlite3.IntegrityError)):
        auth.issue_token("two", "admin")
    row = auth._db.execute("SELECT name,role FROM credentials WHERE id=?", (collision_id,)).fetchone()
    assert row == ("one", "viewer")
    auth.close()
