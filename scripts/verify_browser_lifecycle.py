import os,sys,pathlib,tempfile,socket,subprocess,time,secrets,json,urllib.request
root=pathlib.Path(__file__).resolve().parents[1];sys.path.insert(0,str(root))
from backend.operational_auth import OperationalAuth
from backend.operational_api import create_app
import uvicorn,threading
scratch=pathlib.Path(tempfile.mkdtemp(prefix='ledger-browser-',dir=os.environ['TMPDIR']))
def port():
 with socket.socket() as s:s.bind(('127.0.0.1',0));return s.getsockname()[1]
a,b=port(),port(); secret=secrets.token_urlsafe(32)
auth=OperationalAuth(secret,allowed_origins=frozenset({f'http://127.0.0.1:{b}'}),database=str(scratch/'db.sqlite'))
maker=auth.issue_token('maker','reviewer'); admin=auth.issue_token('approver','admin')
app=create_app(scratch/'db.sqlite',auth=auth);server=uvicorn.Server(uvicorn.Config(app,host='127.0.0.1',port=a,log_level='error'))
t=threading.Thread(target=server.run);t.start()
env=os.environ.copy();env.update(LEDGER_API_URL=f'http://127.0.0.1:{a}',VITE_API_MODE='operational',VITE_API_BASE='/api')
log=open(scratch/'vite.log','w');p=subprocess.Popen(['node','node_modules/vite/bin/vite.js','--host','127.0.0.1','--port',str(b),'--strictPort'],cwd=root/'frontend',env=env,stdout=log,stderr=log,start_new_session=True)
try:
 for i in range(100):
  try:urllib.request.urlopen(f'http://127.0.0.1:{b}',timeout=1);break
  except Exception:time.sleep(.1)
 js=r'''const {chromium}=require('/home/mohamedhasim/.hermes/node/lib/node_modules/omniroute/node_modules/playwright');
(async()=>{const browser=await chromium.launch({headless:true});try{const page=await browser.newPage();const errors=[];page.on('pageerror',e=>errors.push(e.message));await page.goto(process.env.TEST_URL);await page.locator('#credential').fill(process.env.MAKER);await page.getByRole('button',{name:'Connect securely'}).click();await page.locator('.op-live i.good').waitFor();const api=async(path,data)=>{const r=await page.request.post(process.env.TEST_URL+'/api'+path,{headers:{Authorization:'Bearer '+process.env.ADMIN,Origin:process.env.TEST_URL},data});if(!r.ok())throw Error(path+' '+r.status()+' '+await r.text());return r.json()};await api('/ledger',{ledger_id:'audit-l',date:'2026-02-04',description:'Audit ledger',amount:'23.45',currency:'USD',transaction_id:'audit-t'});await api('/import/bank',{source:'bank',source_version:'1',records:[{source_id:'audit-s',date:'2026-02-03',description:'Audit bank',amount:'23.45',currency:'USD',transaction_id:'audit-t'}]});await page.getByRole('button',{name:/date mismatch/i}).click({timeout:15000});await page.getByRole('button',{name:'Propose resolution'}).click();const rehearsed=page.waitForResponse(r=>r.url().endsWith('/rehearse')&&r.request().method()==='POST');await page.getByRole('button',{name:'Rehearse'}).click();const rr=await rehearsed;if(!rr.ok())throw Error('Rehearsal failed '+rr.status());const rehearsal=await rr.json();if(rehearsal.no_changes!==true)throw Error('Rehearsal did not confirm no writes');await page.getByRole('button',{name:'Switch identity'}).click();await page.locator('#credential').fill(process.env.ADMIN);await page.getByRole('button',{name:'Connect securely'}).click();await page.locator('.op-live i.good').waitFor();await page.getByRole('button',{name:/date mismatch/i}).click();await page.getByRole('button',{name:'Approve',exact:true}).waitFor();const approved=page.waitForResponse(r=>r.url().endsWith('/approve')&&r.request().method()==='POST');await page.getByRole('button',{name:'Approve',exact:true}).click();if(!(await approved).ok())throw Error('Approval failed');const applied=page.waitForResponse(r=>r.url().endsWith('/apply')&&r.request().method()==='POST');await page.getByRole('button',{name:'Apply',exact:true}).click();const ar=await applied;if(!ar.ok())throw Error('Apply failed '+await ar.text());await page.waitForFunction(()=>document.querySelector('.op-pill')?.textContent==='resolved');await page.screenshot({path:process.env.SHOT});console.log('PASS browser login -> actual API ingest -> automatic case -> evidence -> proposal -> rehearsal -> distinct approver -> apply -> resolved readback');if(errors.length)throw Error(errors.join(';'));}finally{await browser.close()}})().catch(e=>{console.error(e.message);process.exit(1)});'''
 (scratch/'test.cjs').write_text(js); env.update(TEST_URL=f'http://127.0.0.1:{b}',MAKER=maker,ADMIN=admin,SHOT=str(scratch/'result.png'))
 r=subprocess.run(['node',str(scratch/'test.cjs')],env=env,timeout=50,capture_output=True,text=True);print(r.stdout);print(r.stderr);print('Artifacts:',scratch);sys.exit(r.returncode)
finally:
 import signal
 os.killpg(p.pid,signal.SIGTERM);p.wait(timeout=5);server.should_exit=True;t.join(timeout=10)
