"""SQLite-backed durable work queue with fenced, expiring worker leases."""
from __future__ import annotations

import json
import sqlite3
import time
import uuid
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Job:
    id: int
    key: str
    payload: Any
    status: str
    generation: int
    attempts: int
    lease_token: str | None
    lease_until: float | None
    available_at: float
    last_error: str | None


class DurableJobQueue:
    """A generic queue; each instance owns its SQLite connections."""

    def __init__(self, database: str, *, max_attempts: int = 5,
                 base_retry_seconds: float = 1.0, busy_timeout: float = 30.0):
        if max_attempts < 1 or base_retry_seconds < 0:
            raise ValueError("max_attempts must be positive and retry delay nonnegative")
        self.database = database
        self.max_attempts = max_attempts
        self.base_retry_seconds = base_retry_seconds
        self.busy_timeout = busy_timeout
        with self._connect() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS lrq_jobs (
                id INTEGER PRIMARY KEY, job_key TEXT NOT NULL UNIQUE, payload TEXT NOT NULL,
                status TEXT NOT NULL CHECK(status IN ('queued','running','done','dead')),
                generation INTEGER NOT NULL, completed_generation INTEGER NOT NULL DEFAULT 0,
                claimed_generation INTEGER NOT NULL DEFAULT 0,
                attempts INTEGER NOT NULL DEFAULT 0, lease_token TEXT, lease_until REAL,
                available_at REAL NOT NULL, last_error TEXT, created_at REAL NOT NULL,
                updated_at REAL NOT NULL)""")
            db.execute("CREATE INDEX IF NOT EXISTS lrq_ready ON lrq_jobs(status, available_at)")
            columns = {row["name"] for row in db.execute("PRAGMA table_info(lrq_jobs)")}
            if "claimed_generation" not in columns:
                db.execute("ALTER TABLE lrq_jobs ADD COLUMN claimed_generation INTEGER NOT NULL DEFAULT 0")

    def _connect(self):
        db = sqlite3.connect(self.database, timeout=self.busy_timeout, isolation_level=None)
        db.row_factory = sqlite3.Row
        db.execute(f"PRAGMA busy_timeout={int(self.busy_timeout * 1000)}")
        return db

    @staticmethod
    def _job(row):
        if row is None:
            return None
        return Job(row["id"], row["job_key"], json.loads(row["payload"]), row["status"],
                   row["generation"], row["attempts"], row["lease_token"], row["lease_until"],
                   row["available_at"], row["last_error"])

    def enqueue(self, key: str, payload: Any) -> Job:
        if not key:
            raise ValueError("key must be nonempty")
        encoded = json.dumps(payload, separators=(",", ":"), sort_keys=True)
        now = time.time()
        db = self._connect()
        try:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM lrq_jobs WHERE job_key=?", (key,)).fetchone()
            if row is None:
                db.execute("INSERT INTO lrq_jobs(job_key,payload,status,generation,available_at,created_at,updated_at) VALUES(?,?,'queued',1,?,?,?)", (key, encoded, now, now, now))
            elif json.dumps(json.loads(row["payload"]), separators=(",", ":"), sort_keys=True) != encoded:
                status = "queued" if row["status"] in ("done", "dead") else row["status"]
                reset = row["status"] == "dead"
                db.execute("UPDATE lrq_jobs SET payload=?,generation=generation+1,status=?,attempts=CASE WHEN ? THEN 0 ELSE attempts END,lease_token=CASE WHEN ? THEN NULL ELSE lease_token END,lease_until=CASE WHEN ? THEN NULL ELSE lease_until END,available_at=?,updated_at=? WHERE id=?", (encoded, status, reset, reset, reset, now, now, row["id"]))
            result = db.execute("SELECT * FROM lrq_jobs WHERE job_key=?", (key,)).fetchone()
            db.commit()
            return self._job(result)
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def claim(self, worker: str, *, lease_seconds: float = 60.0) -> Job | None:
        if lease_seconds <= 0:
            raise ValueError("lease_seconds must be positive")
        now, token = time.time(), uuid.uuid4().hex
        db = self._connect()
        try:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM lrq_jobs WHERE (status='queued' AND available_at<=?) OR (status='running' AND lease_until<=?) ORDER BY CASE WHEN job_key LIKE 'reconcile:%' THEN 0 ELSE 1 END, available_at,id LIMIT 1", (now, now)).fetchone()
            if row:
                if row["attempts"] >= self.max_attempts:
                    db.execute("UPDATE lrq_jobs SET status='dead',lease_token=NULL,lease_until=NULL,last_error=COALESCE(last_error,'lease expired'),updated_at=? WHERE id=?", (now, row["id"]))
                    db.commit()
                    return None
                db.execute("UPDATE lrq_jobs SET status='running',attempts=attempts+1,claimed_generation=generation,lease_token=?,lease_until=?,updated_at=? WHERE id=?", (token, now + lease_seconds, now, row["id"]))
                row = db.execute("SELECT * FROM lrq_jobs WHERE id=?", (row["id"],)).fetchone()
            db.commit()
            return self._job(row)
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def get(self, job_id: int) -> Job | None:
        with self._connect() as db:
            return self._job(db.execute("SELECT * FROM lrq_jobs WHERE id=?", (job_id,)).fetchone())

    def _fenced_update(self, sql, args):
        with self._connect() as db:
            cur = db.execute(sql, args)
            return cur.rowcount == 1

    def renew(self, job_id: int, lease_token: str, *, lease_seconds: float = 60.0) -> bool:
        if lease_seconds <= 0:
            raise ValueError("lease_seconds must be positive")
        now = time.time()
        return self._fenced_update("UPDATE lrq_jobs SET lease_until=?,updated_at=? WHERE id=? AND status='running' AND lease_token=? AND lease_until>?", (now + lease_seconds, now, job_id, lease_token, now))

    def complete(self, job_id: int, lease_token: str) -> bool:
        now = time.time()
        db = self._connect()
        try:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM lrq_jobs WHERE id=? AND status='running' AND lease_token=? AND lease_until>?", (job_id, lease_token, now)).fetchone()
            if not row:
                db.rollback()
                return False
            if row["generation"] > row["claimed_generation"]:
                db.execute("UPDATE lrq_jobs SET status='queued',completed_generation=generation,attempts=0,lease_token=NULL,lease_until=NULL,available_at=?,updated_at=? WHERE id=?", (now, now, job_id))
            else:
                db.execute("UPDATE lrq_jobs SET status='done',completed_generation=claimed_generation,lease_token=NULL,lease_until=NULL,updated_at=? WHERE id=?", (now, job_id))
            db.commit()
            return True
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def fail(self, job_id: int, lease_token: str, error: str) -> bool:
        now = time.time()
        db = self._connect()
        try:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM lrq_jobs WHERE id=? AND status='running' AND lease_token=? AND lease_until>?", (job_id, lease_token, now)).fetchone()
            if not row:
                db.rollback()
                return False
            dead = row["attempts"] >= self.max_attempts
            if row["generation"] > row["claimed_generation"]:
                dead = False
                db.execute("UPDATE lrq_jobs SET attempts=0 WHERE id=?", (job_id,))
            delay = self.base_retry_seconds * (2 ** max(0, row["attempts"] - 1))
            db.execute("UPDATE lrq_jobs SET status=?,available_at=?,lease_token=NULL,lease_until=NULL,last_error=?,updated_at=? WHERE id=?", ("dead" if dead else "queued", now + delay, error, now, job_id))
            db.commit()
            return True
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()
