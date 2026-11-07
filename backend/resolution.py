"""Narrow, auditable nonfinancial allocation proposals. No external posting."""
from __future__ import annotations
import hashlib, json, sqlite3, uuid
from datetime import datetime, timezone, date
from pathlib import Path


def _now(): return datetime.now(timezone.utc).isoformat()
def _hash(value): return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':')).encode()).hexdigest()

class ResolutionService:
    """Trusted-library actor attribution; callers must pass authenticated actor identity and role."""
    def __init__(self, database: str | Path): self.database=str(database)
    def _db(self):
        db=sqlite3.connect(self.database,timeout=20,isolation_level=None); db.row_factory=sqlite3.Row; db.execute('PRAGMA foreign_keys=ON'); db.execute('PRAGMA busy_timeout=20000'); return db
    def _schema(self,db):
        # Deliberately execute statements individually: executescript commits active transactions.
        db.execute('CREATE TABLE IF NOT EXISTS lr_resolution_proposals(id TEXT PRIMARY KEY,user_id TEXT NOT NULL,case_id TEXT NOT NULL,actor TEXT NOT NULL,source_id TEXT NOT NULL,ledger_id TEXT NOT NULL,snapshot TEXT NOT NULL,case_snapshot TEXT NOT NULL,status TEXT NOT NULL,approver TEXT,created_at TEXT NOT NULL,applied_at TEXT, rehearsal_hash TEXT)')
        db.execute('CREATE TABLE IF NOT EXISTS lr_resolution_idempotency(user_id TEXT NOT NULL,proposal_id TEXT NOT NULL,key TEXT NOT NULL,result TEXT NOT NULL,PRIMARY KEY(user_id,proposal_id,key))')
        db.execute('CREATE TABLE IF NOT EXISTS lr_resolution_audit(id TEXT PRIMARY KEY,user_id TEXT NOT NULL,proposal_id TEXT NOT NULL,actor TEXT NOT NULL,action TEXT NOT NULL,data TEXT NOT NULL,created_at TEXT NOT NULL)')
        cols={r['name'] for r in db.execute('PRAGMA table_info(lr_resolution_proposals)')}
        if 'rehearsal_hash' not in cols: db.execute('ALTER TABLE lr_resolution_proposals ADD COLUMN rehearsal_hash TEXT')
    def _ensure_schema(self):
        db=self._db()
        try: self._schema(db)
        finally: db.close()
    @staticmethod
    def _role(actor, allowed):
        if not isinstance(actor,dict) or not actor.get('id') or actor.get('role') not in allowed: raise ValueError('actor role not permitted')
    def _evidence(self,db,user,case,source,ledger):
        ex=db.execute('SELECT * FROM lr_exceptions WHERE id=? AND user_id=?',(case,user)).fetchone()
        if not ex or ex['status']!='open': raise ValueError('case missing or not open')
        s=db.execute('SELECT * FROM lr_source_records WHERE id=? AND user_id=?',(source,user)).fetchone()
        l=db.execute('SELECT * FROM lr_ledger_records WHERE ledger_id=? AND user_id=?',(ledger,user)).fetchone()
        if not s or not l: raise ValueError('evidence missing or outside user scope')
        # Exceptions carry provenance in evidence_json; source records have no outbox column.
        try: case_evidence=json.loads(ex['evidence_json'])
        except (TypeError, ValueError): raise ValueError('case evidence is invalid')
        if case_evidence.get('source_record_id') != s['id']: raise ValueError('source evidence is not linked to this case')
        latest=db.execute('SELECT id FROM lr_source_records WHERE user_id=? AND source=? AND source_id=? ORDER BY created_at DESC LIMIT 1',(user,s['source'],s['source_id'])).fetchone()
        if not latest or latest['id'] != s['id']: raise ValueError('source evidence is not the latest revision')
        if not s['amount_cents'] or s['amount_cents']!=l['amount_cents'] or s['currency']!=l['currency'] or not s['transaction_id'] or s['transaction_id']!=l['transaction_id']: raise ValueError('evidence does not establish exact allocation identity')
        sc=db.execute('SELECT count(*) FROM lr_ledger_records WHERE user_id=? AND amount_cents=? AND currency=? AND transaction_id=?',(user,s['amount_cents'],s['currency'],s['transaction_id'])).fetchone()[0]
        lc=db.execute('SELECT count(*) FROM lr_source_records WHERE user_id=? AND amount_cents=? AND currency=? AND transaction_id=?',(user,l['amount_cents'],l['currency'],l['transaction_id'])).fetchone()[0]
        if sc!=1 or lc!=1: raise ValueError('ambiguous duplicate evidence')
        for table,col,val in [('lr_matches','source_record_id',s['id']),('lr_matches','ledger_record_id',l['id'])]:
            if db.execute(f"SELECT 1 FROM {table} WHERE {col}=? AND status='active'",(val,)).fetchone(): raise ValueError('evidence already allocated')
        snap={'source':dict(s),'ledger':dict(l)}
        return ex,snap
    def propose(self,user_id,case_id,actor,evidence,*,connection=None):
        self._role(actor,{'admin','reviewer'})
        if connection is None: self._ensure_schema()
        db=connection if connection is not None else self._db()
        owned=connection is None
        try:
            if owned: db.execute('BEGIN IMMEDIATE')
            ex,snap=self._evidence(db,user_id,case_id,evidence['source_record_id'],evidence['ledger_id'])
            case_snapshot={k:ex[k] for k in ex.keys()}; ident=str(uuid.uuid4()); now=_now()
            db.execute("INSERT INTO lr_resolution_proposals(id,user_id,case_id,actor,source_id,ledger_id,snapshot,case_snapshot,status,approver,created_at,applied_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,NULL)",(ident,user_id,case_id,actor['id'],snap['source']['id'],snap['ledger']['ledger_id'],_hash(snap),_hash(case_snapshot),'proposed',None,now))
            self._audit(db,user_id,ident,actor['id'],'proposed',{'evidence_hash':_hash(snap),'case_hash':_hash(case_snapshot)})
            if owned: db.commit()
            return {'id':ident,'status':'proposed','evidence_hash':_hash(snap)}
        except:
            if owned: db.rollback()
            raise
        finally:
            if owned: db.close()
    def _audit(self,db,user,pid,actor,action,data): db.execute('INSERT INTO lr_resolution_audit VALUES(?,?,?,?,?,?,?)',(str(uuid.uuid4()),user,pid,actor,action,json.dumps(data,sort_keys=True),_now()))
    def _load(self,db,user,pid):
        p=db.execute('SELECT * FROM lr_resolution_proposals WHERE id=? AND user_id=?',(pid,user)).fetchone()
        if not p: raise ValueError('proposal not found in user scope')
        return p
    def rehearse(self,user_id,proposal_id,actor):
        self._role(actor,{'admin','reviewer'}); self._ensure_schema(); db=self._db()
        try:
            db.execute('BEGIN IMMEDIATE'); p=self._load(db,user_id,proposal_id)
            if p['status'] not in ('proposed','approved'): raise ValueError('proposal is not in a rehearsable state')
            try: ex,snap=self._evidence(db,user_id,p['case_id'],p['source_id'],p['ledger_id'])
            except ValueError:
                db.commit()
                return {'proposal_id':proposal_id,'would_match':False,'before':{'active_match':False},'after':{'active_match':False},'no_changes':True}
            valid=_hash(snap)==p['snapshot'] and _hash({k:ex[k] for k in ex.keys()})==p['case_snapshot']
            if valid: db.execute('UPDATE lr_resolution_proposals SET rehearsal_hash=? WHERE id=?',(p['snapshot'],proposal_id))
            else: db.execute('UPDATE lr_resolution_proposals SET rehearsal_hash=NULL WHERE id=?',(proposal_id,))
            db.commit()
            return {'proposal_id':proposal_id,'would_match':bool(valid),'before':{'active_match':False},'after':{'active_match':bool(valid)},'no_changes':True}
        except: db.rollback(); raise
        finally: db.close()
    def approve(self,user_id,proposal_id,actor):
        self._role(actor,{'admin'}); self._ensure_schema(); db=self._db()
        try:
            db.execute('BEGIN IMMEDIATE'); p=self._load(db,user_id,proposal_id)
            if p['status']!='proposed' or p['actor']==actor['id']: raise ValueError('approval requires a different admin and proposed state')
            if not p['rehearsal_hash'] or p['rehearsal_hash']!=p['snapshot']: raise ValueError('current successful rehearsal required')
            ex,snap=self._evidence(db,user_id,p['case_id'],p['source_id'],p['ledger_id'])
            if _hash(snap)!=p['snapshot'] or _hash({k:ex[k] for k in ex.keys()})!=p['case_snapshot']: raise ValueError('evidence or case changed')
            db.execute("UPDATE lr_resolution_proposals SET status='approved',approver=? WHERE id=?",(actor['id'],proposal_id)); self._audit(db,user_id,proposal_id,actor['id'],'approved',{}); db.commit(); return {'id':proposal_id,'status':'approved'}
        except: db.rollback(); raise
        finally: db.close()
    def apply(self,user_id,proposal_id,actor,idempotency_key):
        self._role(actor,{'admin'});
        if not isinstance(idempotency_key,str) or not idempotency_key: raise ValueError('idempotency key required')
        self._ensure_schema(); db=self._db()
        try:
            db.execute('BEGIN IMMEDIATE'); p=self._load(db,user_id,proposal_id)
            prior=db.execute('SELECT result FROM lr_resolution_idempotency WHERE user_id=? AND proposal_id=? AND key=?',(user_id,proposal_id,idempotency_key)).fetchone()
            if prior: db.commit(); return json.loads(prior['result'])
            if p['status']!='approved' or p['approver']!=actor['id']: raise ValueError('proposal not approved by applying admin')
            if not p['rehearsal_hash'] or p['rehearsal_hash']!=p['snapshot']: raise ValueError('current successful rehearsal required')
            ex,snap=self._evidence(db,user_id,p['case_id'],p['source_id'],p['ledger_id'])
            if _hash(snap)!=p['snapshot'] or _hash({k:ex[k] for k in ex.keys()})!=p['case_snapshot']: raise ValueError('evidence or case changed')
            mid=str(uuid.uuid4()); now=_now(); db.execute("INSERT INTO lr_matches(id,user_id,source_record_id,ledger_record_id,created_at,status) VALUES(?,?,?,?,?,'active')",(mid,user_id,p['source_id'],snap['ledger']['id'],now))
            db.execute("UPDATE lr_exceptions SET status='resolved' WHERE id=? AND user_id=? AND status='open'",(p['case_id'],user_id))
            db.execute("INSERT INTO lr_events VALUES(?,?,?,?,?)",(str(uuid.uuid4()),user_id,'records.matched',json.dumps({'match_id':mid,'source_record_id':p['source_id'],'ledger_record_id':snap['ledger']['id'],'case_id':p['case_id']}),now))
            db.execute("UPDATE lr_resolution_proposals SET status='applied',applied_at=? WHERE id=?",(now,proposal_id))
            result={'id':proposal_id,'status':'applied','match_id':mid,'external_posted':False}
            self._audit(db,user_id,proposal_id,actor['id'],'applied',result); db.execute('INSERT INTO lr_resolution_idempotency VALUES(?,?,?,?)',(user_id,proposal_id,idempotency_key,json.dumps(result,sort_keys=True)))
            db.commit()
            with self._db() as check:
                row=check.execute('SELECT status FROM lr_resolution_proposals WHERE id=? AND user_id=?',(proposal_id,user_id)).fetchone()
                match=check.execute("SELECT status FROM lr_matches WHERE id=? AND user_id=? AND source_record_id=? AND ledger_record_id=?",(mid,user_id,p['source_id'],snap['ledger']['id'])).fetchone()
                case=check.execute('SELECT status FROM lr_exceptions WHERE id=? AND user_id=?',(p['case_id'],user_id)).fetchone()
                if not row or row['status']!='applied' or not match or match['status']!='active' or not case or case['status']!='resolved': raise RuntimeError('apply read-back failed')
            return result
        except: db.rollback(); raise
        finally: db.close()
