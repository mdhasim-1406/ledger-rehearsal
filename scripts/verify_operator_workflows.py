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
(async()=>{const browser=await chromium.launch({headless:true});try{const page=await browser.newPage();await page.goto(process.env.TEST_URL);await page.locator('#credential').fill(process.env.ADMIN);await page.getByRole('button',{name:'Connect securely'}).click();await page.locator('.op-live i.good').waitFor();const header='source_id,transaction_id,date,description,amount,currency\n';const upload=async(value)=>{await page.getByLabel('CSV file').setInputFiles({name:'test.csv',mimeType:'text/csv',buffer:Buffer.from(header+value)});await page.getByRole('button',{name:'Validate preview'}).click()};await upload('S-1,T-1,2026-01-01,Sample,invalid,USD');await page.getByText(/1 row errors/).waitFor();await upload('S-1,T-1,2026-01-01,Sample,10.00,USD');await page.getByRole('button',{name:'Import validated revision'}).click();await page.getByRole('button',{name:/Missing Ledger Record/i}).click({timeout:15000});await page.getByLabel('Reviewer note').fill('Please provide corresponding ledger evidence');await page.getByRole('button',{name:'Request evidence',exact:true}).click();await page.getByText(/Please provide corresponding ledger evidence/).last().waitFor();if(await page.locator('.op-pill').textContent()!=='open')throw Error('Disposition incorrectly resolved case');for(const format of ['JSON','CSV']){const download=page.waitForEvent('download');await page.getByRole('button',{name:'Download '+format+' evidence'}).click();const file=await download;if(await file.failure())throw Error('Download failed')}await page.setViewportSize({width:390,height:844});if(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth))throw Error('Mobile overflow');await page.screenshot({path:process.env.SHOT});console.log('PASS UI invalid CSV -> valid preview/import -> automatic case -> request evidence stays open -> JSON/CSV downloads -> mobile width');}finally{await browser.close()}})().catch(e=>{console.error(e.message);process.exit(1)});'''
 (scratch/'test.cjs').write_text(js); env.update(TEST_URL=f'http://127.0.0.1:{b}',MAKER=maker,ADMIN=admin,SHOT=str(scratch/'result.png'))
 r=subprocess.run(['node',str(scratch/'test.cjs')],env=env,timeout=50,capture_output=True,text=True);print(r.stdout);print(r.stderr);print('Artifacts:',scratch);sys.exit(r.returncode)
finally:
 import signal
 os.killpg(p.pid,signal.SIGTERM);p.wait(timeout=5);server.should_exit=True;t.join(timeout=10)
