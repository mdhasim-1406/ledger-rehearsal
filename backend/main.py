from fastapi import FastAPI, HTTPException, Query, Request
from pydantic import BaseModel
import sqlite3, json, os, hashlib, uuid, threading, time, csv, io, re, asyncio
from fastapi.responses import StreamingResponse
from decimal import Decimal
from pathlib import Path
from datetime import datetime, timezone

DB_PATH = Path(os.environ.get('LEDGER_DEMO_DB', str(Path(__file__).with_name('ledger-demo.sqlite3'))))
DB_PATH.parent.mkdir(parents=True, exist_ok=True)
app = FastAPI(title='Local Synthetic Accounting Demo', version='2.0')

def now(): return datetime.now(timezone.utc).isoformat()
def connect():
    c=sqlite3.connect(DB_PATH, timeout=15, check_same_thread=False, isolation_level=None)
    c.row_factory=sqlite3.Row
    c.execute('PRAGMA foreign_keys=ON'); c.execute('PRAGMA journal_mode=WAL'); c.execute('PRAGMA busy_timeout=15000')
    return c
def init():
    with connect() as c:
        c.executescript('''CREATE TABLE IF NOT EXISTS records(id TEXT PRIMARY KEY,kind TEXT NOT NULL,description TEXT NOT NULL,amount_cents INTEGER NOT NULL,currency TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'open',source_ref TEXT UNIQUE,created_at TEXT NOT NULL,version INTEGER NOT NULL DEFAULT 1);
        CREATE TABLE IF NOT EXISTS cases(id TEXT PRIMARY KEY,title TEXT NOT NULL,kind TEXT NOT NULL,status TEXT NOT NULL,amount_cents INTEGER NOT NULL,currency TEXT NOT NULL,summary TEXT NOT NULL,record_ids TEXT NOT NULL,steering TEXT NOT NULL DEFAULT '',version INTEGER NOT NULL DEFAULT 1,proposal TEXT,proposal_hash TEXT,approved_hash TEXT,created_at TEXT NOT NULL,updated_at TEXT NOT NULL,run_id TEXT,phase TEXT);
        CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY AUTOINCREMENT,case_id TEXT,type TEXT NOT NULL,message TEXT NOT NULL,data TEXT NOT NULL,created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS applied(proposal_hash TEXT PRIMARY KEY,case_id TEXT NOT NULL,applied_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS journal_entries(id TEXT PRIMARY KEY,case_id TEXT NOT NULL,proposal_hash TEXT NOT NULL UNIQUE, currency TEXT NOT NULL, memo TEXT NOT NULL, created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS journal_lines(id INTEGER PRIMARY KEY AUTOINCREMENT,entry_id TEXT NOT NULL REFERENCES journal_entries(id),account TEXT NOT NULL,side TEXT NOT NULL CHECK(side IN ('debit','credit')),amount_cents INTEGER NOT NULL CHECK(amount_cents>0));''')
        c.execute('''CREATE TABLE IF NOT EXISTS imported_rows(user_id TEXT NOT NULL,source TEXT NOT NULL,source_id TEXT NOT NULL,transaction_id TEXT NOT NULL,transaction_date TEXT NOT NULL,description TEXT NOT NULL,amount_cents INTEGER NOT NULL,currency TEXT NOT NULL,created_at TEXT NOT NULL,PRIMARY KEY(user_id,source,source_id))''')
        c.execute('''CREATE TABLE IF NOT EXISTS import_cases(id TEXT PRIMARY KEY,user_id TEXT NOT NULL,kind TEXT NOT NULL,transaction_id TEXT NOT NULL,record_ids TEXT NOT NULL,details TEXT NOT NULL,created_at TEXT NOT NULL,UNIQUE(user_id,kind,transaction_id))''')
        c.execute('''CREATE TABLE IF NOT EXISTS import_case_state(id TEXT PRIMARY KEY REFERENCES cases(id),user_id TEXT NOT NULL,transaction_id TEXT NOT NULL,provenance TEXT NOT NULL)''')
        for table,col,ddl in [('records','version','INTEGER NOT NULL DEFAULT 1'),('cases','run_id','TEXT'),('cases','phase','TEXT')]:
            if col not in [x['name'] for x in c.execute(f'PRAGMA table_info({table})')]: c.execute(f'ALTER TABLE {table} ADD COLUMN {col} {ddl}')
init()
def event(c,cid,t,m,d=None): c.execute('INSERT INTO events(case_id,type,message,data,created_at) VALUES(?,?,?,?,?)',(cid,t,m,json.dumps(d or {}),now()))
def proposal_digest(proposal):
 payload={k:v for k,v in proposal.items() if k not in ('hash','status','approval_status')}
 return hashlib.sha256(json.dumps(payload,sort_keys=True,separators=(',',':')).encode()).hexdigest()
def case_dict(r): return {k:r[k] for k in ('id','title','kind','status','currency','summary','version','steering','created_at','updated_at','run_id','phase')} | {'amount':r['amount_cents']/100,'posting':'not supported; sandbox state changes only'}
def getcase(c,i):
 r=c.execute('SELECT * FROM cases WHERE id=?',(i,)).fetchone()
 if not r: raise HTTPException(404,'Case not found')
 return r
class Msg(BaseModel): message:str
class Hash(BaseModel): proposal_hash:str
class PairedCsv(BaseModel):
 bank_csv:str; ledger_csv:str
@app.get('/api/health')
def health(): return {'name':'Local Synthetic Accounting Demo','mode':'synthetic-demo','database':'sqlite-persistent-local','inference':'deterministic-rules','writes':'non-financial synthetic sandbox only; no financial posting'}
@app.get('/api/overview')
def overview():
 with connect() as c:
  s=dict(c.execute('SELECT status,count(*) FROM cases GROUP BY status').fetchall())
  return {'stats':{'total_cases':sum(s.values()),'by_status':s,'records':c.execute('SELECT count(*) FROM records').fetchone()[0]},'activity':[dict(x) for x in c.execute('SELECT id,case_id,type,message,created_at FROM events ORDER BY id DESC LIMIT 20')]}
@app.get('/api/cases')
def cases():
 with connect() as c:
  ordinary=[case_dict(x) for x in c.execute('SELECT * FROM cases WHERE id NOT IN (SELECT id FROM import_case_state) ORDER BY created_at DESC')]
  imported=[dict(x) for x in c.execute('SELECT c.id,c.title,c.kind,c.status,c.currency,c.summary,c.version,c.steering,c.created_at,c.updated_at,c.run_id,c.phase,c.amount_cents,s.user_id,s.transaction_id,s.provenance FROM cases c JOIN import_case_state s ON s.id=c.id ORDER BY c.created_at DESC')]
  return {'cases':ordinary+[dict(case_dict(x),provenance=json.loads(x['provenance'])) for x in imported]}
@app.get('/api/records')
def records():
 with connect() as c:return {'records':[dict(x) for x in c.execute('SELECT * FROM records ORDER BY created_at,id')]}
@app.get('/api/cases/{case_id}')
def detail(case_id:str):
 with connect() as c:
  imported=c.execute('SELECT user_id,transaction_id,provenance FROM import_case_state WHERE id=?',(case_id,)).fetchone()
  if imported:
   r=getcase(c,case_id)
   return {'case':case_dict(r)|{'provenance':json.loads(imported['provenance'])},'evidence':[dict(x) for x in c.execute('SELECT * FROM imported_rows WHERE user_id=? AND transaction_id=? ORDER BY source,source_id',(imported['user_id'],imported['transaction_id']))],'events':[dict(x) for x in c.execute('SELECT * FROM events WHERE case_id=? ORDER BY id',(case_id,))],'proposal':None,'safe_investigation':False}
  r=getcase(c,case_id); ids=json.loads(r['record_ids']); q=','.join('?'*len(ids))
  return {'case':case_dict(r),'evidence':[dict(x) for x in c.execute(f'SELECT * FROM records WHERE id IN ({q})',ids)],'events':[dict(x) for x in c.execute('SELECT * FROM events WHERE case_id=? ORDER BY id',(case_id,))],'proposal':json.loads(r['proposal']) if r['proposal'] else None}
@app.post('/api/ingest/demo')
def ingest():
 fixtures=[('INV-104','invoice','Synthetic invoice INV-104',125000,'INV-104','invoice_without_payment',['invoice','bank']),('PAY-204','bank','Synthetic bank receipt PAY-204',120000,'PAY-204','payment_mismatch',['bank','ledger']),('EXP-305','ledger','Synthetic duplicate subscription expense',4999,'EXP-305','duplicate_expense',['ledger','invoice']),('FEE-406','bank','Synthetic processor fee discrepancy',350,'FEE-406','fee_discrepancy',['bank','ledger']),('REV-501','invoice','Synthetic customer payment matched to invoice',24000,'REV-501','matched_customer_payment',['invoice','bank']),('EXP-502','invoice','Synthetic vendor bill matched to bank payment',8750,'EXP-502','matched_vendor_payment',['invoice','bank'])]
 created=0
 with connect() as c:
  c.execute('BEGIN IMMEDIATE')
  for ref,kind,desc,amt,sref,label,related in fixtures:
   ids=[]
   for suffix,k in enumerate(related):
    rr=ref+('-PAIR' if suffix else '')
    rid='rec_'+hashlib.sha256(rr.encode()).hexdigest()[:16]
    typ='bank' if k=='bank' else ('invoice' if k=='invoice' else 'ledger')
    amount=amt if suffix==0 else (amt-5000 if label=='invoice_without_payment' else amt)
    cur=c.execute('INSERT OR IGNORE INTO records(id,kind,description,amount_cents,currency,source_ref,created_at) VALUES(?,?,?,?,?,?,?)',(rid,typ,desc if suffix==0 else f'Synthetic paired {k} entry for {ref}',amount,'USD',rr,now()))
    if cur.rowcount: created+=1
    ids.append(rid)
   cid='case_'+hashlib.sha256(('case:'+ref).encode()).hexdigest()[:16]
   cur=c.execute('INSERT OR IGNORE INTO cases(id,title,kind,status,amount_cents,currency,summary,record_ids,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)',(cid,label.replace('_',' ').title(),label,'detected',amt,'USD',desc,json.dumps(ids),now(),now()))
   if cur.rowcount:event(c,cid,'detected','Paired synthetic bank/ledger/invoice evidence detected.',{'record_ids':ids,'source_ref':ref})
  event(c,None,'ingestion','Synthetic paired fixture ingestion completed.',{'new_records':created}); c.commit()
 return {'count':created,'source':'synthetic-paired-local-fixtures','case_types':[x[5] for x in fixtures]}

@app.post('/api/ingest/csv')
def ingest_csv(payload:PairedCsv):
 """Import paired bank/ledger CSV snapshots. Detect only; never post accounting entries."""
 user_id='local'
 def parse(text,source):
  if len(text.encode('utf-8'))>2_000_000: raise HTTPException(413,f'{source}_csv exceeds 2 MB')
  required={'source_id','transaction_id','date','description','amount','currency'}
  try:
   reader=csv.DictReader(io.StringIO(text,newline=''))
   if not reader.fieldnames or len(reader.fieldnames)!=len(set(reader.fieldnames)) or set(reader.fieldnames)!=required: raise ValueError('header must contain exactly: '+', '.join(sorted(required)))
   out=[]; seen=set()
   for line,r in enumerate(reader,2):
    if line>10001: raise HTTPException(413,'CSV exceeds 10000 rows')
    sid=r['source_id'].strip(); tid=r['transaction_id'].strip(); date=r['date'].strip(); desc=r['description'].strip(); currency=r['currency'].strip().upper(); raw=r['amount'].strip()
    if sid in seen: raise ValueError(f'duplicate source_id at line {line}')
    seen.add(sid)
    if not sid or len(sid)>128 or not tid or len(tid)>128 or not re.fullmatch(r'\d{4}-\d{2}-\d{2}',date) or not desc or len(desc)>500 or not re.fullmatch(r'[A-Z]{3}',currency): raise ValueError(f'invalid required field at line {line}')
    try: datetime.strptime(date,'%Y-%m-%d')
    except ValueError: raise ValueError(f'invalid date at line {line}')
    if not re.fullmatch(r'-?\d+(\.\d{1,2})?',raw): raise ValueError(f'invalid amount at line {line}')
    amount=int(Decimal(raw)*100)
    if abs(amount)>10_000_000_000: raise ValueError(f'amount outside supported range at line {line}')
    out.append((sid,tid,date,desc,amount,currency))
   return out
  except HTTPException: raise
  except (ValueError,TypeError,csv.Error) as e: raise HTTPException(422,f'{source}_csv: {e}')
 bank=parse(payload.bank_csv,'bank'); ledger=parse(payload.ledger_csv,'ledger')
 with connect() as c:
  c.execute('BEGIN IMMEDIATE')
  for source,rows in (('bank',bank),('ledger',ledger)):
   for sid,tid,date,desc,amount,currency in rows:
    old=c.execute('SELECT transaction_id,transaction_date,description,amount_cents,currency FROM imported_rows WHERE user_id=? AND source=? AND source_id=?',(user_id,source,sid)).fetchone(); vals=(tid,date,desc,amount,currency)
    if old and tuple(old)!=vals: c.rollback(); raise HTTPException(409,f'{source} source_id {sid!r} conflicts with previously imported content')
    c.execute('INSERT OR IGNORE INTO imported_rows VALUES(?,?,?,?,?,?,?,?,?)',(user_id,source,sid,tid,date,desc,amount,currency,now()))
  rows=c.execute('SELECT transaction_id,source,source_id,transaction_date,description,amount_cents,currency FROM imported_rows WHERE user_id=? ORDER BY transaction_id,source,source_id',(user_id,)).fetchall(); grouped={}
  for row in rows: grouped.setdefault(row['transaction_id'],{'bank':[],'ledger':[]})[row['source']].append(dict(row))
  active_ids=set()
  for tid,g in grouped.items():
   issues=[]
   if len(g['bank'])>1 or len(g['ledger'])>1: issues.append(('duplicate_source','Repeated transaction_id on at least one side'))
   if not g['bank']: issues.append(('missing_bank','Ledger transaction has no bank-side match'))
   if not g['ledger']: issues.append(('missing_ledger','Bank transaction has no ledger-side match'))
   if g['bank'] and g['ledger'] and any((r['amount_cents'],r['currency'])!=(g['ledger'][0]['amount_cents'],g['ledger'][0]['currency']) for r in g['bank']): issues.append(('amount_mismatch','Amount or currency differs; human review required'))
   ids=[f"{src}:{r['source_id']}" for src in ('bank','ledger') for r in g[src]]
   for kind,details in issues:
    cid=hashlib.sha256(f'{user_id}|{kind}|{tid}'.encode()).hexdigest()[:32]
    active_ids.add(cid)
    c.execute('INSERT OR IGNORE INTO import_cases VALUES(?,?,?,?,?,?,?)',(cid,user_id,kind,tid,json.dumps(ids),details,now()))
  all_cases=c.execute('SELECT * FROM import_cases WHERE user_id=? ORDER BY transaction_id,kind',(user_id,)).fetchall()
  for tid,g in grouped.items():
   issues=[]
   if len(g['bank'])>1 or len(g['ledger'])>1: issues.append(('duplicate_source','Repeated transaction_id on at least one side'))
   if not g['bank']: issues.append(('missing_bank','Ledger transaction has no bank-side match'))
   if not g['ledger']: issues.append(('missing_ledger','Bank transaction has no ledger-side match'))
   if g['bank'] and g['ledger'] and any((r['amount_cents'],r['currency'])!=(g['ledger'][0]['amount_cents'],g['ledger'][0]['currency']) for r in g['bank']): issues.append(('amount_mismatch','Amount or currency differs; human review required'))
   if not issues and g['bank'] and g['ledger']:
    current_ids=[f"{src}:{r['source_id']}" for src in ('bank','ledger') for r in g[src]]
    for oldcase in c.execute('SELECT id FROM import_cases WHERE user_id=? AND transaction_id=?',(user_id,tid)):
     updated=c.execute('UPDATE cases SET status=?,updated_at=? WHERE id=? AND status!=?',('resolved_nonfinancial',now(),oldcase['id'],'resolved_nonfinancial'))
     if updated.rowcount: event(c,oldcase['id'],'resolved','Matching counterparty evidence is now present; no financial posting was made.',{'record_ids':current_ids})
  for imported_case in all_cases:
   cid=imported_case['id']
   if cid not in active_ids: continue
   ids=json.loads(imported_case['record_ids']); evidence=[]
   for value in ids:
    src,sid=value.split(':',1); row=c.execute('SELECT * FROM imported_rows WHERE user_id=? AND source=? AND source_id=?',(user_id,src,sid)).fetchone()
    if row: evidence.append(dict(row))
   amount=abs(next((x['amount_cents'] for x in evidence),0)); currency=next((x['currency'] for x in evidence),'XXX')
   c.execute('INSERT OR IGNORE INTO cases(id,title,kind,status,amount_cents,currency,summary,record_ids,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)',(cid,f"Imported {imported_case['kind']}: {imported_case['transaction_id']}",imported_case['kind'],'needs_review',amount,currency,imported_case['details'],json.dumps(ids),now(),now()))
   c.execute('UPDATE cases SET status=?,updated_at=? WHERE id=? AND status='"'"'resolved_nonfinancial'"'"'',('needs_review',now(),cid))
   c.execute('INSERT OR REPLACE INTO import_case_state VALUES(?,?,?,?)',(cid,user_id,imported_case['transaction_id'],json.dumps({'source':'csv-import','transaction_id':imported_case['transaction_id'],'record_ids':ids},sort_keys=True)))
   for ev in evidence:
    rid=f"import:{ev['source']}:{ev['source_id']}"
    c.execute('INSERT OR IGNORE INTO records(id,kind,description,amount_cents,currency,source_ref,created_at) VALUES(?,?,?,?,?,?,?)',(rid,ev['source'],ev['description'],ev['amount_cents'],ev['currency'],rid,ev['created_at']))
  cases=[dict(r) for r in all_cases]
  c.commit()
  cases=[{'id':r['id'],'kind':r['kind'],'transaction_id':r['transaction_id'],'record_ids':r['record_ids'],'details':r['details']} for r in cases]
 return {'user_id':user_id,'accepted':{'bank':len(bank),'ledger':len(ledger)},'cases':cases,'case_count':len(cases),'writes':'local import and exception records only; no journal or external writes'}
def worker(cid,rid):
 # Every phase is an independent durable transaction; other requests can steer between them.
 for phase in ('collect_evidence','validate_pair','construct_operation'):
  with connect() as c:
   c.execute('BEGIN IMMEDIATE'); r=getcase(c,cid)
   if r['run_id']!=rid or r['status']!='investigating': c.commit();return
   steering=r['steering'].lower()
   if any(x in steering for x in ('manual review','do not auto','no automatic','hold','stop')):
    c.execute("UPDATE cases SET status='needs_review',phase='paused',updated_at=? WHERE id=?",(now(),cid)); event(c,cid,'investigation_paused','Steering paused investigation before next phase.',{'phase':phase,'steering':r['steering']});c.commit();return
   if phase=='construct_operation':
    ids=json.loads(r['record_ids']); qs=','.join('?'*len(ids)); rows=[dict(x) for x in c.execute(f'SELECT * FROM records WHERE id IN ({qs}) ORDER BY id',ids)]
    typ={'invoice_without_payment':'flag_invoice_unpaid','payment_mismatch':'flag_amount_mismatch','duplicate_expense':'flag_possible_duplicate','fee_discrepancy':'flag_fee_variance','matched_customer_payment':'record_customer_payment','matched_vendor_payment':'record_vendor_payment'}.get(r['kind'],'flag_evidence_for_review')
    # These typed operations only annotate records; they do not create, debit, credit, or post money.
    journal=None
    if r['kind'] in ('matched_customer_payment','matched_vendor_payment') and len(rows)==2 and {x['kind'] for x in rows}=={'bank','invoice'} and len({x['currency'] for x in rows})==1 and rows[0]['amount_cents']==rows[1]['amount_cents'] and all(x['status']=='open' and x['amount_cents']>0 for x in rows):
     cash='Cash'; clearing='Accounts Receivable' if r['kind']=='matched_customer_payment' else 'Accounts Payable'; expense='Sales Revenue' if r['kind']=='matched_customer_payment' else 'Operating Expense'
     journal={'currency':rows[0]['currency'],'memo':'Synthetic matched transaction; assumed invoice treatment and exact bank match','lines':([{'account':cash,'side':'debit','amount_cents':rows[0]['amount_cents']},{'account':expense,'side':'credit','amount_cents':rows[0]['amount_cents']}] if r['kind']=='matched_customer_payment' else [{'account':expense,'side':'debit','amount_cents':rows[0]['amount_cents']},{'account':cash,'side':'credit','amount_cents':rows[0]['amount_cents']}])}
    op={'type':typ,'record_ids':ids,'record_versions':{x['id']:x['version'] for x in rows},'expected_statuses':{x['id']:x['status'] for x in rows},'effects':{'status':'reviewed','review_note':typ},'journal':journal,'financial_posting':False}
    sandbox=sqlite3.connect(':memory:');sandbox.execute('CREATE TABLE snapshot(id TEXT,version INTEGER,status TEXT,review_note TEXT)');sandbox.executemany('INSERT INTO snapshot VALUES(?,?,?,?)',[(x['id'],x['version'],x['status'],'') for x in rows]); before=[tuple(x) for x in sandbox.execute('SELECT * FROM snapshot ORDER BY id')]
    sandbox.executemany("UPDATE snapshot SET status='reviewed',review_note=? WHERE id=?",[(typ,i) for i in ids]);after=[tuple(x) for x in sandbox.execute('SELECT * FROM snapshot ORDER BY id')]
    checks={'evidence_count_matches':len(rows)==len(ids),'all_amounts_nonnegative':all(x['amount_cents']>=0 for x in rows),'single_currency':len({x['currency'] for x in rows})==1,'before_after_changed_only_as_operation':all(a[0:2]==b[0:2] and b[2:] == ('reviewed',typ) for a,b in zip(before,after)),'sandbox_isolated':True}
    if journal is not None:
     sandbox.execute('CREATE TABLE journal(account TEXT,side TEXT,amount_cents INTEGER)')
     sandbox.executemany("INSERT INTO journal VALUES(?,?,?)",[(x['account'],x['side'],x['amount_cents']) for x in journal['lines']])
     actual=[tuple(x) for x in sandbox.execute('SELECT account,side,amount_cents FROM journal ORDER BY rowid')]
     debits=sandbox.execute("SELECT COALESCE(SUM(amount_cents),0) FROM journal WHERE side='debit'").fetchone()[0];credits=sandbox.execute("SELECT COALESCE(SUM(amount_cents),0) FROM journal WHERE side='credit'").fetchone()[0]
     checks.update(journal_balanced=debits==credits and debits>0,journal_accounts_valid=len(actual)==len(journal['lines']) and all(a and s in ('debit','credit') and n>0 for a,s,n in actual),journal_lines_match_proposal=actual==[(x['account'],x['side'],x['amount_cents']) for x in journal['lines']])
    elif r['kind'] in ('matched_customer_payment','matched_vendor_payment'):
     checks['sufficient_evidence']=False
    if not all(checks.values()):
     c.execute("UPDATE cases SET status='needs_review',phase='validation_failed',updated_at=? WHERE id=?",(now(),cid));event(c,cid,'validation_failed','Sandbox validations failed; no proposal produced.',checks);c.commit();return
    payload={'case_id':cid,'case_version':r['version'],'evidence':[{'id':x['id'],'version':x['version']} for x in rows],'operation':op,'accounting_assumptions':['Synthetic fixtures only. Exact invoice/bank amount match; no taxes, fees, discounts, or multi-currency effects. Customer receipt: debit Cash, credit Sales Revenue (assumes revenue not previously recognized). Vendor payment: debit Operating Expense, credit Cash (assumes expense treatment, not capitalization).'],'sandbox':{'before':before,'after':after,'checks':checks},'financial_posting':False}
    proposal={**payload,'status':'awaiting_approval'};ph=proposal_digest(proposal);proposal['hash']=ph
    c.execute("UPDATE cases SET status='awaiting_approval',phase='complete',proposal=?,proposal_hash=?,approved_hash=NULL,updated_at=? WHERE id=?",(json.dumps(proposal),ph,now(),cid));event(c,cid,'proposal_ready','Isolated non-financial rehearsal passed; exact proposal awaits approval.',{'proposal_hash':ph,'checks':checks})
   else:
    c.execute('UPDATE cases SET phase=?,updated_at=? WHERE id=?',(phase,now(),cid));event(c,cid,'investigation_phase',f'Investigation phase committed: {phase}.',{'phase':phase})
   c.commit()
  time.sleep(.08)
@app.post('/api/cases/{case_id}/steer')
def steer(case_id:str,body:Msg):
 text=body.message.strip()
 if not text:raise HTTPException(422,'Steering message cannot be empty')
 with connect() as c:
  c.execute('BEGIN IMMEDIATE');r=getcase(c,case_id)
  if r['status'] in ('applied','closed'):raise HTTPException(409,'Case is no longer steerable')
  c.execute('UPDATE cases SET steering=steering||?,version=version+1,proposal=NULL,proposal_hash=NULL,approved_hash=NULL,updated_at=? WHERE id=?',(('\n' if r['steering'] else '')+text,now(),case_id));event(c,case_id,'steering_received','Steering accepted and visible to the next committed investigation phase.',{'message':text});c.commit()
  return {'case':case_dict(getcase(c,case_id))}
@app.post('/api/cases/{case_id}/investigate')
def investigate(case_id:str):
 with connect() as c:
  if c.execute('SELECT 1 FROM import_case_state WHERE id=?',(case_id,)).fetchone(): raise HTTPException(409,'Imported CSV evidence is read-only; investigation proposals are unsupported')
  c.execute('BEGIN IMMEDIATE');r=getcase(c,case_id)
  if r['status']=='investigating':return {'case':case_dict(r),'already_running':True}
  if r['status'] in ('applied','closed'):raise HTTPException(409,'Case is terminal')
  rid=str(uuid.uuid4());c.execute("UPDATE cases SET status='investigating',run_id=?,phase='started',proposal=NULL,proposal_hash=NULL,approved_hash=NULL,updated_at=? WHERE id=?",(rid,now(),case_id));event(c,case_id,'investigation_started','Durable asynchronous investigation started.',{'run_id':rid});c.commit()
 threading.Thread(target=worker,args=(case_id,rid),daemon=True).start()
 return {'case':case_dict(getcase(connect(),case_id)),'run_id':rid}
@app.post('/api/cases/{case_id}/approve')
def approve(case_id:str,body:Hash):
 with connect() as c:
  c.execute('BEGIN IMMEDIATE');r=getcase(c,case_id)
  if not r['proposal_hash'] or body.proposal_hash!=r['proposal_hash'] or r['status']!='awaiting_approval':raise HTTPException(409,'Proposal missing, stale, or hash does not match')
  p=json.loads(r['proposal'])
  if proposal_digest(p)!=r['proposal_hash']:raise HTTPException(409,'Proposal content changed; re-investigate')
  fresh=[dict(x) for x in c.execute('SELECT id,version,status,currency FROM records WHERE id IN (%s)' % ','.join(['?'] * len(p['operation']['record_ids'])), p['operation']['record_ids'])]
  if len(fresh)!=len(p['evidence']) or any(x['version']!=p['operation']['record_versions'][x['id']] or x['status']!=p['operation']['expected_statuses'][x['id']] for x in fresh):raise HTTPException(409,'Evidence changed; re-investigate')
  if p['case_version']!=r['version']:raise HTTPException(409,'Case version changed; re-investigate')
  c.execute("UPDATE cases SET status='approved',approved_hash=?,updated_at=? WHERE id=?",(body.proposal_hash,now(),case_id));event(c,case_id,'approved','Human approved immutable operation and evidence-version hash.',{'proposal_hash':body.proposal_hash});c.commit();return {'case':case_dict(getcase(c,case_id))}
@app.post('/api/cases/{case_id}/apply')
def apply(case_id:str,body:Hash):
 with connect() as c:
  c.execute('BEGIN IMMEDIATE');r=getcase(c,case_id);old=c.execute('SELECT case_id FROM applied WHERE proposal_hash=?',(body.proposal_hash,)).fetchone()
  if old:
   if old['case_id']!=case_id:raise HTTPException(409,'Hash belongs to another case')
   c.commit();return {'case':case_dict(r),'idempotent':True,'financial_posting':False}
  if r['status']!='approved' or body.proposal_hash!=r['approved_hash'] or body.proposal_hash!=r['proposal_hash']:raise HTTPException(409,'Exact current proposal must be approved')
  p=json.loads(r['proposal']); op=p['operation']; ids=op['record_ids']
  if proposal_digest(p)!=r['proposal_hash'] or r['approved_hash']!=proposal_digest(p):raise HTTPException(409,'Approved proposal content changed; refusing apply')
  if p['case_version']!=r['version']:raise HTTPException(409,'Case version changed; re-investigate')
  rows=[dict(x) for x in c.execute('SELECT id,version,status FROM records WHERE id IN (%s)'%','.join('?'*len(ids)),ids)]
  if len(rows)!=len(ids) or any(x['version']!=op['record_versions'][x['id']] or x['status']!=op['expected_statuses'][x['id']] for x in rows):raise HTTPException(409,'Evidence versions/statuses changed; refusing apply')
  if op.get('journal'):
   j=op['journal'];lines=j['lines'];debits=sum(x['amount_cents'] for x in lines if x['side']=='debit');credits=sum(x['amount_cents'] for x in lines if x['side']=='credit')
   if debits<=0 or debits!=credits or any(x['side'] not in ('debit','credit') or not x['account'] or x['amount_cents']<=0 for x in lines):raise HTTPException(409,'Journal invalid or unbalanced')
   entry='jrnl_'+uuid.uuid4().hex
   c.execute('INSERT INTO journal_entries VALUES(?,?,?,?,?,?)',(entry,case_id,body.proposal_hash,j['currency'],j['memo'],now()))
   c.executemany('INSERT INTO journal_lines(entry_id,account,side,amount_cents) VALUES(?,?,?,?)',[(entry,x['account'],x['side'],x['amount_cents']) for x in lines])
  c.executemany("UPDATE records SET status='reviewed',version=version+1 WHERE id=?",[(i,) for i in ids]);c.execute("UPDATE cases SET status='resolved_nonfinancial',updated_at=? WHERE id=?",(now(),case_id));c.execute('INSERT INTO applied VALUES(?,?,?)',(body.proposal_hash,case_id,now()));event(c,case_id,'applied_nonfinancial','Approved synthetic rehearsal applied atomically; any journal remains isolated local rehearsal data, never an external/live ledger posting.',{'proposal_hash':body.proposal_hash,'operation':op});c.commit();return {'case':case_dict(getcase(c,case_id)),'idempotent':False,'financial_posting':False}

@app.get('/api/cases/{case_id}/journal')
def journal(case_id:str):
 with connect() as c:
  getcase(c,case_id)
  entries=[dict(x) for x in c.execute('SELECT * FROM journal_entries WHERE case_id=? ORDER BY created_at',(case_id,))]
  for e in entries:e['lines']=[dict(x) for x in c.execute('SELECT account,side,amount_cents FROM journal_lines WHERE entry_id=? ORDER BY id',(e['id'],))]
  return {'entries':entries,'external_posting':False,'synthetic_demo_only':True}


async def event_stream(after: int | None = None, last_event_id: str | None = None, request: Request | None = None):
    """Stream committed local-demo events after a snapshot boundary; no DB handle spans waits."""
    cursor = after
    if last_event_id is not None:
        try:
            cursor = max(cursor if cursor is not None else 0, int(last_event_id))
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="Last-Event-ID must be an integer")
        if cursor < 0:
            raise HTTPException(status_code=400, detail="Last-Event-ID must be non-negative")

    # Boundary excludes historical backlog unless the client explicitly supplied a cursor.
    with connect() as c:
        boundary = c.execute("SELECT COALESCE(MAX(id), 0) FROM events").fetchone()[0]
    if cursor is None:
        cursor = boundary
    yield b"event: ready\ndata: {}\n\n"
    last_keepalive = time.monotonic()
    while True:
        if request is not None and await request.is_disconnected():
            return
        with connect() as c:
            rows = c.execute("SELECT id,case_id,type,message,data,created_at FROM events WHERE id > ? ORDER BY id LIMIT 200", (cursor,)).fetchall()
        if rows:
            for row in rows:
                cursor = row["id"]
                payload = json.dumps(dict(row), separators=(",", ":"), ensure_ascii=False)
                yield f"id: {cursor}\ndata: {payload}\n\n".encode()
        else:
            now_mono = time.monotonic()
            if now_mono - last_keepalive >= 15:
                yield b": keepalive\n\n"
                last_keepalive = now_mono
            await asyncio.sleep(1.0)

@app.get("/api/events/stream")
async def stream_events(request: Request, after: int | None = Query(None, ge=0)):
    last_event_id = request.headers.get("last-event-id")
    if last_event_id is not None and (not last_event_id.isdecimal() or len(last_event_id) > 18):
        raise HTTPException(status_code=400, detail="Last-Event-ID must be a non-negative integer")
    response = StreamingResponse(event_stream(after, last_event_id, request), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
    return response
