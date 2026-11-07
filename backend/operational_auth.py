"""Isolated authentication and origin controls for operational routers."""
from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import sqlite3
import threading
from dataclasses import dataclass
from typing import Mapping
from urllib.parse import urlsplit

from fastapi import HTTPException, Request

ADMIN_ENV = "OPERATIONAL_ADMIN_CREDENTIAL"
_ALLOWED_ROLES = frozenset({"admin", "operator", "reviewer", "viewer"})


class AuthConfigError(RuntimeError):
    """Required security configuration is absent or unsafe."""


@dataclass(frozen=True)
class Actor:
    name: str
    role: str


@dataclass(frozen=True)
class _Credential:
    actor: Actor
    salt: bytes
    digest: bytes


class OperationalAuth:
    """SQLite-backed bearer registry. Database access must be filesystem protected."""

    def __init__(self, bootstrap_credential: str, allowed_origins: frozenset[str] = frozenset({"http://localhost", "http://127.0.0.1"}), *, database: str = ":memory:", rotation_credential: str | None = None):
        if not isinstance(bootstrap_credential, str) or len(bootstrap_credential) < 16:
            raise AuthConfigError(f"{ADMIN_ENV} must be explicitly set to at least 16 characters")
        self.allowed_origins = frozenset(self._canonical_origin(o) for o in allowed_origins)
        self.database = database
        self._lock = threading.RLock()
        self._db = sqlite3.connect(database, check_same_thread=False)
        self._db.execute("CREATE TABLE IF NOT EXISTS credentials (id TEXT PRIMARY KEY, name TEXT NOT NULL, role TEXT NOT NULL, salt BLOB NOT NULL, digest BLOB NOT NULL, revoked INTEGER NOT NULL DEFAULT 0)")
        self._db.commit()
        try:
            self._ensure_bootstrap(bootstrap_credential)
            if rotation_credential is not None:
                if not isinstance(rotation_credential, str) or len(rotation_credential) < 16:
                    raise AuthConfigError("Replacement credential must contain at least 16 characters")
                salt = secrets.token_bytes(16)
                with self._lock, self._db:
                    self._db.execute("UPDATE credentials SET salt=?,digest=? WHERE id='bootstrap'", (salt,self._digest(rotation_credential,salt)))
                bootstrap_credential = rotation_credential
            self.bootstrap_token = self._bootstrap_identity(bootstrap_credential)
        except Exception:
            self._db.close()
            raise

    def close(self):
        with self._lock:
            self._db.close()

    def _ensure_bootstrap(self, secret):
        with self._lock:
            rows = self._db.execute("SELECT id,salt,digest,name,role,revoked FROM credentials WHERE id='bootstrap'").fetchall()
            if rows:
                _, salt, digest, name, role, revoked = rows[0]
                if name != 'admin' or role != 'admin' or revoked:
                    raise AuthConfigError("Persistent bootstrap identity is invalid or revoked")
                if not hmac.compare_digest(self._digest(secret, salt), digest):
                    raise AuthConfigError("Configured admin credential does not match persistent bootstrap credential")
            else:
                salt = secrets.token_bytes(16)
                self._db.execute("INSERT INTO credentials(id,name,role,salt,digest) VALUES('bootstrap','admin','admin',?,?)", (salt, self._digest(secret, salt)))
                self._db.commit()

    @staticmethod
    def _bootstrap_identity(secret):
        return "bootstrap." + secret

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None, allowed_origins=None):
        env = os.environ if environ is None else environ
        secret = env.get(ADMIN_ENV)
        if not secret:
            raise AuthConfigError(f"{ADMIN_ENV} must be configured; refusing insecure bootstrap")
        return cls(secret, frozenset(allowed_origins) if allowed_origins is not None else frozenset({"http://localhost", "http://127.0.0.1"}), database=env.get("OPERATIONAL_AUTH_DB", ":memory:"))

    @staticmethod
    def _canonical_origin(origin: str) -> str:
        try:
            parsed = urlsplit(origin)
            if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username or parsed.password or parsed.path not in ("", "/") or parsed.query or parsed.fragment:
                raise ValueError
            port = parsed.port
            host = parsed.hostname.lower()
            default = (parsed.scheme == "http" and port == 80) or (parsed.scheme == "https" and port == 443)
            return f"{parsed.scheme}://{host}" + (f":{port}" if port and not default else "")
        except (ValueError, TypeError):
            raise ValueError("Invalid origin") from None

    @staticmethod
    def _digest(token: str, salt: bytes) -> bytes:
        return hashlib.scrypt(token.encode(), salt=salt, n=2**14, r=8, p=1, dklen=32)

    def issue_token(self, name: str, role: str, *, credential: str | None = None) -> str:
        if role not in _ALLOWED_ROLES or not name or len(name) > 128:
            raise ValueError("Invalid actor name or role")
        token = credential if credential is not None else secrets.token_urlsafe(32)
        token_id = "bootstrap" if credential is not None else secrets.token_urlsafe(12)
        salt = secrets.token_bytes(16)
        with self._lock:
            if credential is None:
                self._db.execute("INSERT INTO credentials(id,name,role,salt,digest) VALUES(?,?,?,?,?)", (token_id, name, role, salt, self._digest(token, salt)))
                self._db.commit()
        # Token ID is public routing metadata; secret remains the bearer credential.
        return f"{token_id}.{token}"

    async def authenticate(self, request: Request, *, sse: bool = False) -> Actor:
        origin = request.headers.get("origin")
        if origin is not None:
            try:
                canonical = self._canonical_origin(origin)
            except ValueError:
                raise HTTPException(403, "Untrusted origin") from None
            if canonical not in self.allowed_origins:
                raise HTTPException(403, "Untrusted origin")
        if request.method.upper() not in {"GET", "HEAD", "OPTIONS"} and origin is None:
            raise HTTPException(403, "Origin required for browser-unsafe request")
        authorization = request.headers.get("authorization", "")
        scheme, sep, raw = authorization.partition(" ")
        if not sep or scheme.lower() != "bearer" or not raw or raw != raw.strip() or "." not in raw:
            raise HTTPException(401, "Bearer authentication required", headers={"WWW-Authenticate": "Bearer"})
        token_id, secret = raw.split(".", 1)
        with self._lock:
            row = self._db.execute("SELECT name,role,salt,digest,revoked FROM credentials WHERE id=?", (token_id,)).fetchone()
        if row is None or row[4] or not hmac.compare_digest(self._digest(secret, row[2]), row[3]):
            raise HTTPException(401, "Invalid bearer credential", headers={"WWW-Authenticate": "Bearer"})
        return Actor(row[0], row[1])

    def revoke_token(self, token_id: str) -> bool:
        if token_id == "bootstrap":
            raise ValueError("Bootstrap credential cannot be revoked")
        with self._lock:
            cursor = self._db.execute("UPDATE credentials SET revoked=1 WHERE id=? AND revoked=0", (token_id,))
            self._db.commit()
            return cursor.rowcount == 1

    def require_roles(self, *roles: str, sse: bool = False):
        if not roles or not set(roles) <= _ALLOWED_ROLES:
            raise ValueError("At least one valid role is required")
        async def dependency(request: Request) -> Actor:
            actor = await self.authenticate(request, sse=sse)
            if actor.role not in roles:
                raise HTTPException(403, "Insufficient role")
            return actor
        return dependency


def require_roles(auth: OperationalAuth, *roles: str, sse: bool = False):
    """Convenience dependency factory for route registration."""
    return auth.require_roles(*roles, sse=sse)
