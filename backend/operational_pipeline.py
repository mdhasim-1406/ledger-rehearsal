"""Minimal idempotent bridge from foundation outbox to leased jobs."""
from __future__ import annotations
import hashlib, json, sqlite3, time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from backend.durable_jobs import DurableJobQueue
from backend.domain_foundation import ReconciliationDomain
from backend.investigation_agent import InvestigationAgent, InvestigationResult
from backend.resolution import ResolutionService

def _now() -> str: return datetime.now(timezone.utc).isoformat()

class OperationalWorker:
    def __init__(self, database: str | Path, *, queue: DurableJobQueue | None = None, investigation_agent: InvestigationAgent | None = None):
        import os, threading
        self._lease_context=threading.local()
        self.database=str(database); self.domain=ReconciliationDomain(database); self.queue=queue or DurableJobQueue(self.database); self.investigation_agent=investigation_agent
        if self.investigation_agent is None and all(os.environ.get(key) for key in ("INVESTIGATION_LLM_API_KEY", "INVESTIGATION_LLM_BASE_URL", "INVESTIGATION_LLM_MODEL")):
            self.investigation_agent=InvestigationAgent()
        with sqlite3.connect(self.database) as db:
            db.execute("""CREATE TABLE IF NOT EXISTS lr_exceptions(id TEXT PRIMARY KEY,outbox_id TEXT NOT NULL,user_id TEXT NOT NULL,reason TEXT NOT NULL,evidence_json TEXT NOT NULL,created_at TEXT NOT NULL,UNIQUE(outbox_id,id))""")
            cols={r[1] for r in db.execute("PRAGMA table_info(lr_exceptions)")}
            if "status" not in cols: db.execute("ALTER TABLE lr_exceptions ADD COLUMN status TEXT NOT NULL DEFAULT 'open'")
            db.execute("""CREATE TABLE IF NOT EXISTS lr_investigations(case_id TEXT NOT NULL,user_id TEXT NOT NULL,evidence_hash TEXT NOT NULL,result_json TEXT NOT NULL,created_at TEXT NOT NULL,PRIMARY KEY(case_id,evidence_hash))""")
            cols={r[1] for r in db.execute("PRAGMA table_info(lr_investigations)")}
            if "case_id" in cols and not next((r for r in db.execute("PRAGMA table_info(lr_investigations)") if r[1]=="case_id"),[None,None,None,None,0])[5]:
                db.execute("ALTER TABLE lr_investigations RENAME TO lr_investigations_legacy")
                db.execute("""CREATE TABLE lr_investigations(case_id TEXT NOT NULL,user_id TEXT NOT NULL,evidence_hash TEXT NOT NULL,result_json TEXT NOT NULL,created_at TEXT NOT NULL,PRIMARY KEY(case_id,evidence_hash))""")
                db.execute("INSERT OR IGNORE INTO lr_investigations SELECT case_id,user_id,evidence_hash,result_json,created_at FROM lr_investigations_legacy")
                db.execute("DROP TABLE lr_investigations_legacy")


    def dispatch_outbox(self) -> int:
        count=0
        with sqlite3.connect(self.database,timeout=30,isolation_level=None) as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                rows=db.execute("SELECT id,user_id,payload_json FROM lr_jobs WHERE job_type='reconcile' AND status='queued' ORDER BY created_at,id").fetchall()
                now=time.time()
                for oid,uid,raw in rows:
                    key=f"reconcile:{oid}"
                    payload={"outbox_id":oid,"user_id":uid,**json.loads(raw)}
                    old=db.execute("SELECT generation,payload,status FROM lrq_jobs WHERE job_key=?",(key,)).fetchone()
                    generation=1 if old is None else old[0]+1
                    payload["generation"]=generation
                    encoded=json.dumps(payload,separators=(",",":"),sort_keys=True)
                    if old is None:
                        db.execute("INSERT INTO lrq_jobs(job_key,payload,status,generation,available_at,created_at,updated_at) VALUES(?,?,'queued',1,?,?,?)",(key,encoded,now,now,now))
                    else:
                        db.execute("UPDATE lrq_jobs SET payload=?,generation=?,status=CASE WHEN status IN ('done','dead') THEN 'queued' ELSE status END,attempts=CASE WHEN status='dead' THEN 0 ELSE attempts END,lease_token=CASE WHEN status='dead' THEN NULL ELSE lease_token END,lease_until=CASE WHEN status='dead' THEN NULL ELSE lease_until END,available_at=?,updated_at=? WHERE job_key=?",(encoded,generation,now,now,key))
                    db.execute("UPDATE lr_jobs SET status='completed',lease_until=NULL WHERE id=? AND status='queued'",(oid,))
                    count+=1
                db.commit()
            except BaseException: db.rollback(); raise
        return count

    def _process(self,payload:dict[str,Any])->dict[str,Any]:
        if isinstance(payload,str):
            payload=json.loads(payload)
        if payload.get("kind")=="investigation":
            return {"investigation":self._process_investigation(payload)}
        user_id,outbox_id=payload["user_id"],payload["outbox_id"]; matched=self.domain.reconcile(user_id)
        with sqlite3.connect(self.database) as db:
            rows=db.execute("""SELECT s.id,s.transaction_id,s.source,s.source_id,s.source_version,s.transaction_date,s.amount_cents,s.currency FROM lr_source_records s WHERE s.user_id=? AND NOT EXISTS(SELECT 1 FROM lr_source_records newer WHERE newer.user_id=s.user_id AND newer.source=s.source AND newer.source_id=s.source_id AND (newer.created_at>s.created_at OR (newer.created_at=s.created_at AND newer.rowid>s.rowid))) AND NOT EXISTS(SELECT 1 FROM lr_matches m WHERE m.source_record_id=s.id AND m.status='active') ORDER BY s.id""",(user_id,)).fetchall(); exceptions=[]
            for rid,tx,source,sid,version,date,cents,currency in rows:
                key=f"{user_id}:{source}:{sid}"
                ledgers=db.execute("SELECT transaction_id,transaction_date,amount_cents,currency FROM lr_ledger_records WHERE user_id=?",(user_id,)).fetchall()
                reason=("missing_transaction_identity" if not tx else
                        "ambiguous_candidate" if any(l[0]==tx and l[1]==date and l[2]==cents and l[3]==currency for l in ledgers) else
                        "currency_mismatch" if any(l[0]==tx and l[2]==cents and l[3]!=currency for l in ledgers) else
                        "amount_mismatch" if any(l[0]==tx and l[3]==currency and l[2]!=cents for l in ledgers) else
                        "date_mismatch" if any(l[0]==tx and l[2]==cents and l[3]==currency and l[1]!=date for l in ledgers) else
                        "missing_ledger_record")
                key=f"{user_id}:{source}:{sid}"; ev={"id":f"source:{rid}","evidence_type":"source","source_record_id":rid,"record_id":rid,"source":source,"source_id":sid,"source_version":version,"transaction_id":tx,"date":date,"amount_cents":cents,"currency":currency}; evj=json.dumps(ev,sort_keys=True)
                candidate_rows=db.execute("SELECT id,ledger_id,transaction_id,transaction_date,amount_cents,currency FROM lr_ledger_records WHERE user_id=? AND transaction_id=? ORDER BY ledger_id LIMIT 50",(user_id,tx)).fetchall() if tx else []
                candidate_evidence=[{"id":f"ledger:{l[0]}","evidence_type":"ledger","ledger_record_id":l[0],"ledger_id":l[1],"transaction_id":l[2],"date":l[3],"amount_cents":l[4],"currency":l[5]} for l in candidate_rows]
                scoped_evidence=[ev,*candidate_evidence]; digest=hashlib.sha256(json.dumps(scoped_evidence,sort_keys=True,separators=(",",":")).encode()).hexdigest()
                # Resolve an existing case when any revision of its source is now matched.
                db.execute("""UPDATE lr_exceptions SET status='resolved'
                    WHERE user_id=? AND id=? AND status='open'
                    AND EXISTS (SELECT 1 FROM lr_source_records current
                        JOIN lr_matches m ON m.source_record_id=current.id AND m.status='active'
                        WHERE current.user_id=lr_exceptions.user_id
                        AND current.source=? AND current.source_id=?)""",(user_id,key,source,sid))
                db.execute("INSERT INTO lr_exceptions(id,outbox_id,user_id,reason,evidence_json,created_at,status) VALUES(?,?,?,?,?,?,'open') ON CONFLICT(id) DO UPDATE SET outbox_id=excluded.outbox_id,reason=excluded.reason,evidence_json=excluded.evidence_json,status=CASE WHEN lr_exceptions.status='resolved' THEN 'resolved' ELSE 'open' END",(key,outbox_id,user_id,reason,evj,_now())); exceptions.append({"case_id":key,"reason":reason,"evidence":ev,"scoped_evidence":scoped_evidence,"evidence_hash":digest})
            db.execute("UPDATE lr_exceptions SET status='resolved' WHERE user_id=? AND status='open' AND NOT EXISTS(SELECT 1 FROM lr_source_records s WHERE s.user_id=lr_exceptions.user_id AND lr_exceptions.id=(s.user_id||':'||s.source||':'||s.source_id) AND NOT EXISTS(SELECT 1 FROM lr_matches m WHERE m.source_record_id=s.id AND m.status='active'))",(user_id,))
            db.execute("UPDATE lr_exceptions SET status='resolved' WHERE user_id=? AND status='open' AND EXISTS(SELECT 1 FROM lr_source_records old JOIN lr_matches m ON m.source_record_id=old.id AND m.status='active' WHERE old.user_id=lr_exceptions.user_id AND lr_exceptions.id=(old.user_id||':'||old.source||':'||old.source_id))",(user_id,))
        for item in exceptions:
            case_id=item["case_id"]
            self.queue.enqueue(f"investigation:{case_id}:{item['evidence_hash']}",{"kind":"investigation","case_id":case_id,"user_id":user_id,"evidence":item['scoped_evidence'],"evidence_hash":item['evidence_hash']})
        investigation={"status":"queued","case_id":exceptions[0]["case_id"]} if exceptions else None
        return {"matched":matched,"exceptions":exceptions,"investigation":investigation,"abstained":bool(exceptions),"reason":next((x['reason'] for x in exceptions if x['reason']=='missing_transaction_identity'),exceptions[0]['reason'] if exceptions else None)}

    def _process_investigation(self,payload:dict[str,Any])->dict[str,Any]:
        user_id,case_id=payload["user_id"],payload["case_id"]
        evidence=payload["evidence"]
        digest=hashlib.sha256(json.dumps(evidence,sort_keys=True,separators=(",",":")).encode()).hexdigest()
        with sqlite3.connect(self.database) as db:
            row=db.execute("SELECT evidence_json,status FROM lr_exceptions WHERE id=? AND user_id=?",(case_id,user_id)).fetchone()
            if not row or row[1]!="open":
                return {"status":"stale","case_id":case_id}
            source=json.loads(row[0]); expected=[source]
            if not source.get('transaction_id'):
                candidates=[]
            else:
                with sqlite3.connect(self.database) as candidate_db:
                    rows=candidate_db.execute("SELECT id,ledger_id,transaction_id,transaction_date,amount_cents,currency FROM lr_ledger_records WHERE user_id=? AND transaction_id=? ORDER BY ledger_id LIMIT 50",(user_id,source['transaction_id'])).fetchall()
                candidates=[{"id":f"ledger:{r[0]}","evidence_type":"ledger","ledger_record_id":r[0],"ledger_id":r[1],"transaction_id":r[2],"date":r[3],"amount_cents":r[4],"currency":r[5]} for r in rows]
            expected.extend(candidates)
            if evidence!=expected or hashlib.sha256(json.dumps(expected,sort_keys=True,separators=(",",":")).encode()).hexdigest()!=digest or digest!=payload.get('evidence_hash'):
                return {"status":"stale","case_id":case_id}
        if self.investigation_agent is None:
            raise RuntimeError("investigation provider unavailable; retry job")
        result=self.investigation_agent.investigate(case_id,evidence)
        if result.status == "unavailable":
            raise RuntimeError("investigation provider unavailable; retry graph node")
        if digest!=payload.get("evidence_hash"):
            return {"status":"stale","case_id":case_id}
        service=ResolutionService(self.database)
        service._ensure_schema()
        db=service._db()
        try:
            db.execute('BEGIN IMMEDIATE')
            job=getattr(self._lease_context,'job',None)
            if job is not None and not db.execute("SELECT 1 FROM lrq_jobs WHERE id=? AND lease_token=? AND status='running' AND lease_until>? AND generation=claimed_generation",(job.id,job.lease_token,time.time())).fetchone():
                raise RuntimeError('lease lost before persistence')
            row=db.execute("SELECT evidence_json,status FROM lr_exceptions WHERE id=? AND user_id=?",(case_id,user_id)).fetchone()
            if not row or row[1]!='open': return {'status':'stale','case_id':case_id}
            source=json.loads(row[0]); current_scope=[source]
            rows=db.execute("SELECT id,ledger_id,transaction_id,transaction_date,amount_cents,currency FROM lr_ledger_records WHERE user_id=? AND transaction_id=? ORDER BY ledger_id LIMIT 50",(user_id,source.get('transaction_id',''))).fetchall() if source.get('transaction_id') else []
            current_scope.extend({"id":f"ledger:{r[0]}","evidence_type":"ledger","ledger_record_id":r[0],"ledger_id":r[1],"transaction_id":r[2],"date":r[3],"amount_cents":r[4],"currency":r[5]} for r in rows)
            if current_scope!=evidence: return {'status':'stale','case_id':case_id}
            existing=db.execute('SELECT result_json FROM lr_investigations WHERE case_id=? AND evidence_hash=?',(case_id,digest)).fetchone()
            if existing: return json.loads(existing[0])
            proposal_id=None; rejected=False
            if result.suggestion:
                scope={e['id']:e for e in evidence}; suggestion=result.suggestion
                src=scope.get(suggestion.source_record_id,{}); led=scope.get(suggestion.ledger_id,{})
                if src.get('evidence_type')=='source' and led.get('evidence_type')=='ledger' and src.get('transaction_id') and src.get('transaction_id')==led.get('transaction_id'):
                    db.execute('SAVEPOINT draft')
                    try:
                        draft=service.propose(user_id,case_id,{'id':'investigation-agent','role':'reviewer'},{'source_record_id':src['record_id'],'ledger_id':led['ledger_id']},connection=db)
                        proposal_id=draft['id'];db.execute('RELEASE draft')
                    except ValueError:
                        db.execute('ROLLBACK TO draft');db.execute('RELEASE draft');rejected=True
                else: rejected=True
            result_data=result.model_dump();result_data['resolution_proposal_id']=proposal_id
            if rejected: result_data['suggestion_rejected']=True
            db.execute('INSERT INTO lr_investigations VALUES(?,?,?,?,?)',(case_id,user_id,digest,json.dumps(result_data,sort_keys=True),_now()))
            db.commit()
            return result_data
        except BaseException:
            db.rollback();raise
        finally: db.close()

    def run_one(self,worker:str,*,lease_seconds:float=60.0):
        import threading
        job=self.queue.claim(worker,lease_seconds=lease_seconds)
        if job is None:return None
        stop=threading.Event(); lost=threading.Event()
        def heartbeat():
            while not stop.wait(lease_seconds/3):
                try:
                    if not self.queue.renew(job.id,job.lease_token,lease_seconds=lease_seconds):
                        lost.set();return
                except Exception:
                    lost.set();return
        thread=threading.Thread(target=heartbeat,daemon=True);thread.start()
        self._lease_context.job=job
        try:
            result=self._process(job.payload)
            if lost.is_set():raise RuntimeError('lease lost during processing')
            if not self.queue.complete(job.id,job.lease_token):raise RuntimeError('lease lost before completion')
            return result
        except BaseException as exc:
            self.queue.fail(job.id,job.lease_token,type(exc).__name__)
            raise
        finally:
            stop.set();thread.join();self._lease_context.job=None
