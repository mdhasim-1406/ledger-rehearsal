"""Additive SQLite foundation for source ingestion and conservative reconciliation."""
from __future__ import annotations
import json, re, sqlite3, uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping


def _now() -> str: return datetime.now(timezone.utc).isoformat()
def _currency(v: str) -> str:
    if not isinstance(v,str) or not re.fullmatch(r"[A-Z]{3}",v): raise ValueError("currency must be a three-letter uppercase code")
    return v
def _cents(v: Any) -> int:
    if isinstance(v,bool) or not isinstance(v,int): raise ValueError("amount_cents must be an integer")
    return v

def initialize(database: str | Path) -> None:
    Path(database).parent.mkdir(parents=True,exist_ok=True)
    with sqlite3.connect(str(database)) as db:
        db.execute("PRAGMA foreign_keys=ON")
        db.executescript('''
        CREATE TABLE IF NOT EXISTS lr_source_records(id TEXT PRIMARY KEY,user_id TEXT NOT NULL,source TEXT NOT NULL,source_id TEXT NOT NULL,source_version TEXT NOT NULL,transaction_date TEXT NOT NULL,description TEXT NOT NULL,amount_cents INTEGER NOT NULL,currency TEXT NOT NULL,transaction_id TEXT NOT NULL DEFAULT '',raw_json TEXT NOT NULL,created_at TEXT NOT NULL,UNIQUE(user_id,source,source_id,source_version));
        CREATE TABLE IF NOT EXISTS lr_ledger_records(id TEXT PRIMARY KEY,user_id TEXT NOT NULL,ledger_id TEXT NOT NULL,transaction_date TEXT NOT NULL,description TEXT NOT NULL,amount_cents INTEGER NOT NULL,currency TEXT NOT NULL,transaction_id TEXT NOT NULL DEFAULT '',UNIQUE(user_id,ledger_id));
        CREATE TABLE IF NOT EXISTS lr_matches(id TEXT PRIMARY KEY,user_id TEXT NOT NULL,source_record_id TEXT NOT NULL REFERENCES lr_source_records(id),ledger_record_id TEXT NOT NULL REFERENCES lr_ledger_records(id),created_at TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active','stale')));
        CREATE TABLE IF NOT EXISTS lr_events(id TEXT PRIMARY KEY,user_id TEXT NOT NULL,event_type TEXT NOT NULL,data_json TEXT NOT NULL,created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS lr_jobs(id TEXT PRIMARY KEY,user_id TEXT NOT NULL,job_type TEXT NOT NULL,payload_json TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'queued',created_at TEXT NOT NULL,lease_until TEXT,UNIQUE(job_type,payload_json));
        ''')
        cols={r[1] for r in db.execute('PRAGMA table_info(lr_matches)')}
        if 'status' not in cols: db.execute("ALTER TABLE lr_matches ADD COLUMN status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active','stale'))")
        # Legacy unique constraints cannot be dropped in place; rebuild without losing audit rows.
        indexes=list(db.execute("PRAGMA index_list(lr_matches)"))
        unique_auto=[r[1] for r in indexes if r[2] and r[3]=='u']
        if unique_auto:
            db.execute('ALTER TABLE lr_matches RENAME TO lr_matches_old')
            db.execute('''CREATE TABLE lr_matches(id TEXT PRIMARY KEY,user_id TEXT NOT NULL,source_record_id TEXT NOT NULL REFERENCES lr_source_records(id),ledger_record_id TEXT NOT NULL REFERENCES lr_ledger_records(id),created_at TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active','stale')))''')
            db.execute('INSERT INTO lr_matches SELECT id,user_id,source_record_id,ledger_record_id,created_at,status FROM lr_matches_old')
            db.execute('DROP TABLE lr_matches_old')
        db.execute("CREATE UNIQUE INDEX IF NOT EXISTS lr_matches_active_source ON lr_matches(source_record_id) WHERE status='active'")
        db.execute("CREATE UNIQUE INDEX IF NOT EXISTS lr_matches_active_ledger ON lr_matches(ledger_record_id) WHERE status='active'")
        for table in ('lr_source_records','lr_ledger_records'):
            if 'transaction_id' not in {r[1] for r in db.execute(f'PRAGMA table_info({table})')}: db.execute(f"ALTER TABLE {table} ADD COLUMN transaction_id TEXT NOT NULL DEFAULT ''")

class ReconciliationDomain:
    def __init__(self,database: str | Path): self.database=str(database)
    def _connect(self):
        db=sqlite3.connect(self.database,timeout=15,isolation_level=None); db.row_factory=sqlite3.Row; db.execute('PRAGMA foreign_keys=ON'); db.execute('PRAGMA busy_timeout=15000'); return db
    def _queue(self,db,user_id):
        payload=json.dumps({'user_id':user_id},sort_keys=True)
        db.execute("INSERT INTO lr_jobs(id,user_id,job_type,payload_json,created_at) VALUES(?,?,?,?,?) ON CONFLICT(job_type,payload_json) DO UPDATE SET status='queued',lease_until=NULL",(str(uuid.uuid4()),user_id,'reconcile',payload,_now()))
    def ingest(self,user_id: str,source: str,source_version: str,records: Iterable[Mapping[str,Any]]) -> dict[str,int]:
        inserted=duplicates=0; db=self._connect()
        try:
            db.execute('BEGIN IMMEDIATE')
            for row in records:
                sid=row.get('source_id'); date=row.get('date'); desc=row.get('description'); cents=_cents(row.get('amount_cents')); currency=_currency(row.get('currency')); txid=row.get('transaction_id','')
                if not all(isinstance(v,str) and v for v in (user_id,source,source_version,sid,date,desc)): raise ValueError('user, source identity/version, date and description are required')
                raw=json.dumps(dict(row),sort_keys=True,separators=(',',':'),ensure_ascii=False)
                existing=db.execute('SELECT raw_json FROM lr_source_records WHERE user_id=? AND source=? AND source_id=? AND source_version=?',(user_id,source,sid,source_version)).fetchone()
                if existing:
                    if existing['raw_json'] != raw: raise ValueError('conflicting content for existing source version')
                    duplicates+=1; continue
                cur=db.execute('INSERT INTO lr_source_records(id,user_id,source,source_id,source_version,transaction_date,description,amount_cents,currency,transaction_id,raw_json,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',(str(uuid.uuid4()),user_id,source,sid,source_version,date,desc,cents,currency,txid,raw,_now()))
                if cur.rowcount:
                    inserted+=1; rec=db.execute('SELECT id FROM lr_source_records WHERE user_id=? AND source=? AND source_id=? AND source_version=?',(user_id,source,sid,source_version)).fetchone()[0]
                    db.execute("UPDATE lr_matches SET status='stale' WHERE status='active' AND source_record_id IN (SELECT id FROM lr_source_records WHERE user_id=? AND source=? AND source_id=? AND id<>?)",(user_id,source,sid,rec))
                    db.execute('INSERT INTO lr_events VALUES(?,?,?,?,?)',(str(uuid.uuid4()),user_id,'source.ingested',json.dumps({'record_id':rec,'source':source,'source_id':sid}),_now())); self._queue(db,user_id)
                else: duplicates+=1
            db.commit()
        except Exception: db.rollback(); raise
        finally: db.close()
        return {'inserted':inserted,'duplicates':duplicates}
    def add_ledger_record(self,user_id,ledger_id,date,description,amount_cents,currency,transaction_id=''):
        cents=_cents(amount_cents); currency=_currency(currency)
        if not all(isinstance(v,str) and v for v in (user_id,ledger_id,date,description)): raise ValueError('ledger identity, date and description are required')
        db=self._connect()
        try:
            db.execute('BEGIN IMMEDIATE'); db.execute('INSERT INTO lr_ledger_records(id,user_id,ledger_id,transaction_date,description,amount_cents,currency,transaction_id) VALUES(?,?,?,?,?,?,?,?)',(str(uuid.uuid4()),user_id,ledger_id,date,description,cents,currency,transaction_id)); db.execute('INSERT INTO lr_events VALUES(?,?,?,?,?)',(str(uuid.uuid4()),user_id,'ledger.added',json.dumps({'ledger_id':ledger_id}),_now())); self._queue(db,user_id); db.commit()
        except Exception: db.rollback(); raise
        finally: db.close()
    def reconcile(self,user_id):
        db=self._connect(); matched=unmatched=0
        try:
            db.execute('BEGIN IMMEDIATE')
            sources=db.execute('''SELECT s.* FROM lr_source_records s WHERE user_id=? AND NOT EXISTS(SELECT 1 FROM lr_source_records newer WHERE newer.user_id=s.user_id AND newer.source=s.source AND newer.source_id=s.source_id AND (newer.created_at>s.created_at OR (newer.created_at=s.created_at AND newer.rowid>s.rowid))) AND NOT EXISTS(SELECT 1 FROM lr_matches m WHERE m.source_record_id=s.id AND m.status='active')''',(user_id,)).fetchall()
            ledgers=db.execute("SELECT l.* FROM lr_ledger_records l WHERE user_id=? AND NOT EXISTS(SELECT 1 FROM lr_matches m WHERE m.ledger_record_id=l.id AND m.status='active')",(user_id,)).fetchall()
            candidates={s['id']:[l for l in ledgers if s['transaction_id'] and l['transaction_id']==s['transaction_id'] and l['transaction_date']==s['transaction_date'] and l['amount_cents']==s['amount_cents'] and l['currency']==s['currency']] for s in sources}
            reverse={l['id']:[s for s in sources if l in candidates[s['id']]] for l in ledgers}
            for s in sources:
                c=candidates[s['id']]
                if len(c)==1 and len(reverse[c[0]['id']])==1:
                    l=c[0]; db.execute('INSERT INTO lr_matches(id,user_id,source_record_id,ledger_record_id,created_at,status) VALUES(?,?,?,?,?,?)',(str(uuid.uuid4()),user_id,s['id'],l['id'],_now(),'active')); db.execute('INSERT INTO lr_events VALUES(?,?,?,?,?)',(str(uuid.uuid4()),user_id,'records.matched',json.dumps({'source_record_id':s['id'],'ledger_record_id':l['id']}),_now())); matched+=1
                else: unmatched+=1
            db.execute("UPDATE lr_jobs SET status='completed' WHERE user_id=? AND job_type='reconcile' AND status='queued'",(user_id,)); db.commit()
        except Exception: db.rollback(); raise
        finally: db.close()
        return {'matched':matched,'unmatched':unmatched}
