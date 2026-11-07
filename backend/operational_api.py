"""Separately startable, secured operational API. Set OPERATIONAL_DB and OPERATIONAL_ADMIN_CREDENTIAL."""
from __future__ import annotations
import csv, io, logging, os, re, sqlite3, threading, time
from contextlib import asynccontextmanager
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Literal
from fastapi import Body, Depends, FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field
from backend.domain_foundation import initialize, ReconciliationDomain
from backend.operational_auth import OperationalAuth
from backend.operational_pipeline import OperationalWorker
from backend.operational_metrics import OperationalMetrics
from backend.resolution import ResolutionService
import json

logger = logging.getLogger(__name__)
MAX_AMOUNT_CENTS = 10**14
MAX_BODY_BYTES = 2_000_000
MAX_BATCH_RECORDS = 1000

class SourceRecord(BaseModel):
    model_config=ConfigDict(extra='forbid')
    source_id: str=Field(min_length=1,max_length=200)
    date: str
    description: str=Field(min_length=1,max_length=1000)
    amount: str
    currency: str=Field(pattern=r'^[A-Z]{3}$')
    transaction_id: str=''

class ProposalBody(BaseModel):
    model_config=ConfigDict(extra='forbid')
    case_id: str=Field(min_length=1,max_length=200)
    source_record_id: str=Field(min_length=1,max_length=200)
    ledger_id: str=Field(min_length=1,max_length=200)
class ImportBody(BaseModel):
    model_config=ConfigDict(extra='forbid')
    source: str=Field(min_length=1,max_length=100)
    source_version: str=Field(min_length=1,max_length=100)
    records: list[SourceRecord]=Field(min_length=1,max_length=MAX_BATCH_RECORDS)

class LedgerRecord(BaseModel):
    model_config=ConfigDict(extra='forbid')
    ledger_id: str=Field(min_length=1,max_length=200)
    date: str
    description: str=Field(min_length=1,max_length=1000)
    amount: str
    currency: str=Field(pattern=r'^[A-Z]{3}$')
    transaction_id: str=''

class CsvPreviewBody(BaseModel):
    model_config=ConfigDict(extra='forbid')
    source: str=Field(min_length=1,max_length=100)
    source_version: str=Field(min_length=1,max_length=100)
    record_type: Literal['bank','ledger']='bank'
    csv_text: str=Field(max_length=1_900_000)
    mapping: dict[str,str]

class DispositionBody(BaseModel):
    model_config=ConfigDict(extra='forbid')
    disposition: Literal['request_evidence','reviewed_unsupported']
    note: str=Field(min_length=1,max_length=1000)

def _amount(s):
    if not re.fullmatch(r'-?(?:0|[1-9][0-9]*)(?:\.[0-9]{1,2})?',s): raise ValueError('amount must be a decimal with at most two fractional digits')
    cents=int(Decimal(s)*100)
    if abs(cents)>MAX_AMOUNT_CENTS: raise ValueError('amount exceeds supported limit')
    return cents

def _csv_cell(value):
    return "'"+str(value) if isinstance(value,str) and value[:1] in ('=','+','-','@','\t','\r') else value

def _day(s):
    try: date.fromisoformat(s)
    except ValueError as e: raise ValueError('date must be ISO YYYY-MM-DD') from e
    if len(s)!=10: raise ValueError('date must be ISO YYYY-MM-DD')

def create_app(database: str|Path|None=None, *, auth: OperationalAuth|None=None, start_worker=True, poll_interval=0.25):
    dbpath=str(database or os.environ.get('OPERATIONAL_DB',''))
    if not dbpath: raise RuntimeError('OPERATIONAL_DB or explicit database path is required')
    if auth is None:
        credential=os.environ.get('OPERATIONAL_ADMIN_CREDENTIAL')
        if not credential: raise RuntimeError('OPERATIONAL_ADMIN_CREDENTIAL is required')
        Path(dbpath).parent.mkdir(parents=True,exist_ok=True)
        auth=OperationalAuth(credential,frozenset({os.environ.get('OPERATIONAL_ORIGIN','http://127.0.0.1'), 'http://localhost'}),database=dbpath)
    initialize(dbpath); domain=ReconciliationDomain(dbpath); worker=OperationalWorker(dbpath)
    stop=threading.Event(); thread=None
    worker_error={'failed':False}
    @asynccontextmanager
    async def lifespan(app):
        nonlocal thread
        if start_worker:
            thread=threading.Thread(target=lambda: _work(worker,stop,poll_interval,worker_error),name='operational-worker',daemon=False); thread.start()
        yield
        stop.set()
        if thread:
            thread.join(timeout=10)
            if thread.is_alive():
                logger.error('operational worker did not stop before shutdown timeout')
    app=FastAPI(title='Operational API',lifespan=lifespan); app.state.auth=auth; app.state.database=dbpath; app.state.worker=worker
    source_read=auth.require_roles('admin','operator','reviewer','viewer')
    writer=auth.require_roles('admin','operator')
    reviewer=auth.require_roles('admin','operator','reviewer','viewer')
    resolver=auth.require_roles('admin','reviewer')
    administrator=auth.require_roles('admin')
    metrics=OperationalMetrics(dbpath)
    resolution=ResolutionService(dbpath)
    def fail(call):
        try:return call()
        except (ValueError,InvalidOperation) as e: raise HTTPException(422,str(e)) from e
    @app.middleware('http')
    async def body_limit(request, call_next):
        # Enforce limit on streamed bytes too: Content-Length may be absent or false.
        length=request.headers.get('content-length')
        if length and length.isdigit() and int(length)>MAX_BODY_BYTES:
            return __import__('starlette.responses',fromlist=['Response']).Response('request too large',status_code=413)
        received=0
        oversized=False
        original_receive=request.receive
        async def limited_receive():
            nonlocal received, oversized
            message=await original_receive()
            if message['type']=='http.request':
                received += len(message.get('body',b''))
                if received>MAX_BODY_BYTES:
                    oversized=True
                    raise HTTPException(413,'request too large')
            return message
        request._receive=limited_receive
        response=await call_next(request)
        if oversized:
            return __import__('starlette.responses',fromlist=['Response']).Response('request too large',status_code=413)
        return response
    @app.get('/health')
    def health():
        alive=thread is None or thread.is_alive()
        return {'status':'ok' if alive and not worker_error['failed'] else 'degraded','worker_alive':alive,'worker_failed':worker_error['failed']}
    @app.post('/api/import/bank')
    def import_bank(body:ImportBody, actor=Depends(writer)):
        rows=[]
        for r in body.records:
            fail(lambda: _day(r.date)); rows.append({'source_id':r.source_id,'date':r.date,'description':r.description,'amount_cents':fail(lambda:_amount(r.amount)),'currency':r.currency,'transaction_id':r.transaction_id})
        return fail(lambda: domain.ingest('local',body.source,body.source_version,rows))
    @app.post('/api/ledger')
    def add_ledger(r:LedgerRecord, actor=Depends(writer)):
        fail(lambda: _day(r.date)); cents=fail(lambda:_amount(r.amount))
        try:
            with sqlite3.connect(dbpath,timeout=10) as c:
                old=c.execute('SELECT transaction_date,description,amount_cents,currency,transaction_id FROM lr_ledger_records WHERE user_id=? AND ledger_id=?',('local',r.ledger_id)).fetchone()
                new=(r.date,r.description,cents,r.currency,r.transaction_id)
                if old and tuple(old)!=new: raise HTTPException(409,'immutable ledger conflict')
                if old:return {'inserted':0,'duplicate':1}
        except sqlite3.Error as e: raise HTTPException(500,'ledger storage failure') from e
        try:
            fail(lambda: domain.add_ledger_record('local',r.ledger_id,r.date,r.description,cents,r.currency,r.transaction_id))
        except HTTPException:
            raise
        except sqlite3.IntegrityError as e:
            # Concurrent insert: only accept as duplicate if the committed row is identical.
            with sqlite3.connect(dbpath) as c:
                row=c.execute('SELECT transaction_date,description,amount_cents,currency,transaction_id FROM lr_ledger_records WHERE user_id=? AND ledger_id=?',('local',r.ledger_id)).fetchone()
            if row and tuple(row)==new: return {'inserted':0,'duplicate':1}
            raise HTTPException(409,'immutable ledger conflict') from e
        return {'inserted':1,'duplicate':0}
    @app.get('/api/records')
    def records(actor=Depends(source_read)):
        with sqlite3.connect(dbpath) as c:
            c.row_factory=sqlite3.Row
            return {'bank':[dict(x) for x in c.execute('SELECT id,source,source_id,source_version,transaction_date,description,amount_cents,currency,transaction_id FROM lr_source_records WHERE user_id=? ORDER BY created_at,id',('local',))], 'ledger':[dict(x) for x in c.execute('SELECT id,ledger_id,transaction_date,description,amount_cents,currency,transaction_id FROM lr_ledger_records WHERE user_id=? ORDER BY ledger_id',('local',))]}
    @app.get('/api/jobs')
    def jobs(actor=Depends(reviewer)):
        with sqlite3.connect(dbpath) as c: c.row_factory=sqlite3.Row; return [dict(x) for x in c.execute("SELECT id,job_key,status,attempts,available_at FROM lrq_jobs WHERE json_extract(payload,'$.user_id')=? ORDER BY id",('local',))]
    @app.get('/api/exceptions')
    def exceptions(actor=Depends(reviewer)):
        resolution._ensure_schema()
        with sqlite3.connect(dbpath) as c:
            c.row_factory=sqlite3.Row
            rows=[dict(x) for x in c.execute('SELECT id,reason,evidence_json,created_at,status FROM lr_exceptions WHERE user_id=? ORDER BY created_at,id',('local',))]
            for row in rows:
                inv=c.execute('SELECT result_json,created_at FROM lr_investigations WHERE user_id=? AND case_id=? ORDER BY created_at DESC LIMIT 1',('local',row['id'])).fetchone()
                row['investigation']=json.loads(inv['result_json']) if inv else None
                row['investigated_at']=inv['created_at'] if inv else None
                row['dispositions']=[dict(x) for x in c.execute('SELECT disposition,note,actor,created_at FROM lr_case_dispositions WHERE user_id=? AND case_id=? ORDER BY created_at',('local',row['id']))] if c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='lr_case_dispositions'").fetchone() else []
                row['resolutions']=[dict(x) for x in c.execute('SELECT id,status,actor,approver,created_at,applied_at,snapshot,rehearsal_hash FROM lr_resolution_proposals WHERE user_id=? AND case_id=? ORDER BY created_at,id',('local',row['id']))]
                row['audit']=[dict(x) for x in c.execute('SELECT action,actor,data,created_at FROM lr_resolution_audit WHERE user_id=? AND proposal_id IN (SELECT id FROM lr_resolution_proposals WHERE user_id=? AND case_id=?) ORDER BY created_at,id',('local','local',row['id']))]
            return rows

    @app.post('/api/import/preview')
    def preview_csv(body:CsvPreviewBody, actor=Depends(writer)):
        required={'source_id','date','description','amount','currency','transaction_id'}
        if set(body.mapping)!=required or len(set(body.mapping.values()))!=len(required): raise HTTPException(422,'Map each required field to a distinct CSV column.')
        try:
            reader=csv.DictReader(io.StringIO(body.csv_text,newline=''))
            headers=reader.fieldnames or []
            if not headers or any(column not in headers for column in body.mapping.values()): raise ValueError('Mapped CSV column is missing from the header.')
            rows=[]; errors=[]; seen={}
            for number,raw in enumerate(reader,start=2):
                if len(rows)+len(errors)>=10000: raise ValueError('CSV exceeds the 10,000 row limit.')
                row={key:(raw.get(column) or '').strip() for key,column in body.mapping.items()}
                try:
                    if None in raw: raise ValueError('row has more fields than the CSV header')
                    if not row['source_id'] or not row['description']: raise ValueError('source_id and description are required')
                    _day(row['date']); cents=_amount(row['amount'])
                    if not re.fullmatch(r'[A-Z]{3}',row['currency']): raise ValueError('currency must be a three-letter uppercase code')
                    if row['source_id'] in seen and seen[row['source_id']]!=row: raise ValueError('source_id is repeated with different row content')
                    if row['source_id'] in seen: raise ValueError('duplicate source_id in this file')
                    seen[row['source_id']]=row
                    rows.append({**row,'amount_cents':cents})
                except ValueError as exc: errors.append({'row':number,'source_id':row['source_id'] or None,'error':str(exc)})
            return {'source':body.source,'source_version':body.source_version,'headers':headers,'mapping':body.mapping,'valid_rows':len(rows),'errors':errors,'preview':rows[:20],'ready':bool(rows) and not errors}
        except (csv.Error,UnicodeError,ValueError) as exc: raise HTTPException(422,str(exc)) from exc

    @app.post('/api/import/commit')
    def commit_csv(body:CsvPreviewBody, actor=Depends(writer)):
        checked=preview_csv(body,actor)
        if not checked['ready']: raise HTTPException(422,detail={'message':'Fix preview errors before importing.','errors':checked['errors']})
        # Reparse all rows after validation; preview is bounded for display only.
        reader=csv.DictReader(io.StringIO(body.csv_text,newline=''))
        records=[]
        for raw in reader:
            row={key:(raw.get(column) or '').strip() for key,column in body.mapping.items()}
            records.append({'source_id':row['source_id'],'date':row['date'],'description':row['description'],'amount_cents':_amount(row['amount']),'currency':row['currency'],'transaction_id':row['transaction_id']})
        if body.record_type=='bank': return domain.ingest('local',body.source,body.source_version,records)
        inserted=duplicates=0; db=domain._connect()
        try:
            db.execute('BEGIN IMMEDIATE')
            for row in records:
                old=db.execute('SELECT transaction_date,description,amount_cents,currency,transaction_id FROM lr_ledger_records WHERE user_id=? AND ledger_id=?',('local',row['source_id'])).fetchone()
                data=(row['date'],row['description'],row['amount_cents'],row['currency'],row['transaction_id'])
                if old:
                    if tuple(old)!=data: raise ValueError(f"ledger_id {row['source_id']} already exists with different content")
                    duplicates+=1; continue
                import uuid
                db.execute('INSERT INTO lr_ledger_records VALUES(?,?,?,?,?,?,?,?)',(str(uuid.uuid4()),'local',row['source_id'],*data))
                db.execute('INSERT INTO lr_events VALUES(?,?,?,?,?)',(str(uuid.uuid4()),'local','ledger.added',json.dumps({'ledger_id':row['source_id']}),__import__('datetime').datetime.now(__import__('datetime').timezone.utc).isoformat()))
                domain._queue(db,'local');inserted+=1
            db.commit()
        except ValueError as exc: db.rollback(); raise HTTPException(409,str(exc)) from exc
        except Exception: db.rollback(); raise
        finally: db.close()
        return {'inserted':inserted,'duplicates':duplicates}

    @app.post('/api/exceptions/{case_id}/disposition')
    def record_disposition(case_id:str, body:DispositionBody, actor=Depends(resolver)):
        with sqlite3.connect(dbpath) as c:
            c.execute('CREATE TABLE IF NOT EXISTS lr_case_dispositions(id TEXT PRIMARY KEY,user_id TEXT NOT NULL,case_id TEXT NOT NULL,disposition TEXT NOT NULL,note TEXT NOT NULL,actor TEXT NOT NULL,created_at TEXT NOT NULL)')
            if not c.execute("SELECT 1 FROM lr_exceptions WHERE user_id=? AND id=?",('local',case_id)).fetchone(): raise HTTPException(404,'case not found')
            created=__import__('datetime').datetime.now(__import__('datetime').timezone.utc).isoformat()
            c.execute('INSERT INTO lr_case_dispositions VALUES(?,?,?,?,?,?,?)',( __import__('uuid').uuid4().hex,'local',case_id,body.disposition,body.note,actor.name,created))
            c.execute('INSERT INTO lr_events VALUES(?,?,?,?,?)',(__import__('uuid').uuid4().hex,'local','case.disposition_recorded',json.dumps({'case_id':case_id,'disposition':body.disposition,'note':body.note,'actor':actor.name}),created))
            c.commit()
        return {'case_id':case_id,'disposition':body.disposition,'financially_resolved':False,'created_at':created}

    @app.get('/api/exports/exceptions.json')
    def export_json(actor=Depends(reviewer)):
        from fastapi.responses import JSONResponse
        return JSONResponse(content={'semantics':'Internal evidence and review record. No external journal posting.','cases':exceptions(actor)},headers={'Content-Disposition':'attachment; filename="ledger-rehearsal-evidence.json"'})

    @app.get('/api/exports/exceptions.csv')
    def export_csv(actor=Depends(reviewer)):
        import csv as csv_module
        output=io.StringIO(newline=''); writer_csv=csv_module.writer(output)
        writer_csv.writerow(['case_id','reason','status','created_at','evidence_json','investigation_json','resolutions_json','reviewer_dispositions_json','audit_json','outcome_semantics'])
        for row in exceptions(actor):
            cells=[row['id'],row['reason'],row['status'],row['created_at'],json.dumps(row.get('evidence_json')),json.dumps(row.get('investigation')),json.dumps(row.get('resolutions')),json.dumps(row.get('dispositions')),json.dumps(row.get('audit')), 'Internal only; no external journal posting']
            writer_csv.writerow([_csv_cell(x) for x in cells])
        return StreamingResponse(iter([output.getvalue()]),media_type='text/csv',headers={'Content-Disposition':'attachment; filename="ledger-rehearsal-evidence.csv"'})
    @app.get('/api/overview')
    def overview(actor=Depends(reviewer)):
        result=metrics.snapshot('local')
        with sqlite3.connect(dbpath) as c:
            bank=c.execute("SELECT count(*) FROM lr_source_records s WHERE s.user_id='local' AND s.source_version=(SELECT s2.source_version FROM lr_source_records s2 WHERE s2.user_id=s.user_id AND s2.source=s.source AND s2.source_id=s.source_id ORDER BY s2.created_at DESC,s2.rowid DESC LIMIT 1)").fetchone()[0]
            ledger=c.execute("SELECT count(*) FROM lr_ledger_records WHERE user_id='local'").fetchone()[0]
            active=c.execute("SELECT count(*) FROM lr_matches WHERE user_id='local' AND status='active'").fetchone()[0]
            open_cases=c.execute("SELECT count(*) FROM lr_exceptions WHERE user_id='local' AND status='open'").fetchone()[0]
        return {'bank_records':bank,'ledger_records':ledger,'active_matches':active,'exceptions':open_cases}
    @app.get('/api/metrics')
    def operational_metrics(actor=Depends(reviewer)):
        snapshot=metrics.snapshot('local')
        with sqlite3.connect(dbpath) as c:
            snapshot['bank_records']=c.execute("SELECT count(*) FROM lr_source_records s WHERE s.user_id='local' AND s.source_version=(SELECT s2.source_version FROM lr_source_records s2 WHERE s2.user_id=s.user_id AND s2.source=s.source AND s2.source_id=s.source_id ORDER BY s2.created_at DESC,s2.rowid DESC LIMIT 1)").fetchone()[0]
            snapshot['ledger_records']=c.execute("SELECT count(*) FROM lr_ledger_records WHERE user_id='local'").fetchone()[0]
            snapshot['active_matches']=c.execute("SELECT count(*) FROM lr_matches WHERE user_id='local' AND status='active'").fetchone()[0]
            snapshot['open_exceptions']=c.execute("SELECT count(*) FROM lr_exceptions WHERE user_id='local' AND status='open'").fetchone()[0]
        return snapshot

    @app.get('/api/evaluation')
    def evaluation(actor=Depends(reviewer)):
        resolution._ensure_schema()
        with sqlite3.connect(dbpath) as c:
            c.row_factory=sqlite3.Row
            outcomes={r['event_type']:r['n'] for r in c.execute('SELECT event_type,count(*) AS n FROM lr_events WHERE user_id=? GROUP BY event_type',('local',))}
            investigations=[json.loads(r['result_json']) for r in c.execute('SELECT result_json FROM lr_investigations WHERE user_id=? ORDER BY created_at',('local',))]
            proposals={r['status']:r['n'] for r in c.execute('SELECT status,count(*) AS n FROM lr_resolution_proposals WHERE user_id=? GROUP BY status',('local',))}
            dispositions=c.execute('SELECT count(*) FROM lr_case_dispositions WHERE user_id=?',('local',)).fetchone()[0] if c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='lr_case_dispositions'").fetchone() else 0
        return {
            'data_scope':'Persisted local workspace records only; source data may be synthetic and provenance is not independently verified.',
            'events_by_type':outcomes,
            'investigations':{'total':len(investigations),'proposed':sum(x.get('status')=='proposed' for x in investigations),'abstained':sum(x.get('status')=='abstain' for x in investigations),'unavailable':sum(x.get('status')=='unavailable' for x in investigations),'suggestion_rejected':sum(bool(x.get('suggestion_rejected')) for x in investigations)},
            'proposals_by_status':proposals,'reviewer_dispositions':dispositions,
            'reviewer_corrections':'unknown: no correction event is currently measured',
            'human_effort':'unknown: time-on-task is not measured',
            'tokens_and_cost':'unknown: provider usage and pricing are not persisted',
        }
    @app.get('/api/events')
    async def events(request: Request, actor=Depends(reviewer)):
        raw=request.headers.get('last-event-id','0')
        try:
            cursor=int(raw)
            if cursor < 0: raise ValueError()
        except ValueError: raise HTTPException(400,'Last-Event-ID must be a non-negative integer')
        async def stream():
            last=cursor
            while not await request.is_disconnected():
                with sqlite3.connect(dbpath) as c:
                    c.row_factory=sqlite3.Row
                    rows=c.execute('SELECT rowid AS cursor,id,event_type,data_json,created_at FROM lr_events WHERE user_id=? AND rowid>? ORDER BY rowid LIMIT 100',('local',last)).fetchall()
                if rows:
                    for row in rows:
                        last=int(row['cursor'])
                        payload={'event_id':row['id'],'type':row['event_type'],'data':json.loads(row['data_json']),'created_at':row['created_at']}
                        yield f"id: {last}\ndata: {json.dumps(payload,separators=(',',':'))}\n\n"
                else:
                    yield ': keepalive\n\n'
                    import asyncio
                    await asyncio.sleep(10)
        return StreamingResponse(stream(),media_type='text/event-stream',headers={'Cache-Control':'no-cache','X-Accel-Buffering':'no'})
    class ProposalBody(BaseModel):
        model_config=ConfigDict(extra='forbid')
        case_id: str=Field(min_length=1,max_length=200)
        source_record_id: str=Field(min_length=1,max_length=200)
        ledger_id: str=Field(min_length=1,max_length=200)
    def resolution_call(fn):
        try: return fn()
        except ValueError as exc: raise HTTPException(409,str(exc)) from exc
        except Exception as exc:
            logger.exception('resolution operation failed')
            raise HTTPException(500,'resolution operation failed') from exc
    def principal(actor): return {'id':actor.name,'role':actor.role}
    @app.get('/api/me')
    def me(actor=Depends(reviewer)):
        return {'name':actor.name,'role':actor.role,'workspace':'local'}
    @app.get('/api/resolutions/proposals')
    def proposal_list(actor=Depends(reviewer)):
        with resolution._db() as c:
            resolution._schema(c)
            return [dict(row) for row in c.execute("SELECT id,case_id,status,actor,approver,created_at FROM lr_resolution_proposals WHERE user_id=? ORDER BY created_at,id",('local',))]
    @app.post('/api/resolutions/proposals')
    def propose(body:ProposalBody=Body(...), actor=Depends(resolver)):
        return resolution_call(lambda: resolution.propose('local',body.case_id,principal(actor),{'source_record_id':body.source_record_id,'ledger_id':body.ledger_id}))
    @app.get('/api/resolutions/proposals/{proposal_id}')
    def read_proposal(proposal_id:str, actor=Depends(reviewer)):
        def read():
            resolution._ensure_schema()
            with resolution._db() as db:
                row=resolution._load(db,'local',proposal_id)
                return {k:row[k] for k in ('id','case_id','actor','source_id','ledger_id','status','approver','created_at','applied_at')}
        return resolution_call(read)
    @app.post('/api/resolutions/proposals/{proposal_id}/rehearse')
    def rehearse(proposal_id:str, actor=Depends(resolver)):
        return resolution_call(lambda: resolution.rehearse('local',proposal_id,principal(actor)))
    @app.post('/api/resolutions/proposals/{proposal_id}/approve')
    def approve(proposal_id:str, actor=Depends(administrator)):
        return resolution_call(lambda: resolution.approve('local',proposal_id,principal(actor)))
    @app.post('/api/resolutions/proposals/{proposal_id}/apply')
    def apply(proposal_id:str, request:Request, actor=Depends(administrator)):
        key=request.headers.get('Idempotency-Key')
        return resolution_call(lambda: resolution.apply('local',proposal_id,principal(actor),key))
    return app

def _work(worker,stop,interval,state=None):
    while not stop.is_set():
        try:
            worker.dispatch_outbox()
            worker.run_one('operational-api-worker')
        except Exception as exc:
            if state is not None: state['failed']=True
            logger.error('operational worker iteration failed (%s)',type(exc).__name__)
        stop.wait(interval)

app=create_app() if os.environ.get('OPERATIONAL_DB') else None
