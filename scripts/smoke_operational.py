#!/usr/bin/env python3
"""Fresh isolated operational launch check; never touches repo databases."""
import os, pathlib, secrets, socket, subprocess, sys, tempfile, time, urllib.request, urllib.error
ROOT=pathlib.Path(__file__).resolve().parents[1]
def port():
 s=socket.socket(); s.bind(('127.0.0.1',0)); p=s.getsockname()[1]; s.close(); return p
api,ui=port(),port()
while ui==api: ui=port()
cred=secrets.token_urlsafe(32)
with tempfile.TemporaryDirectory(prefix='ledger-op-smoke-') as td:
 env=os.environ.copy(); env.update(OPERATIONAL_PORT=str(api),LEDGER_FRONTEND_PORT=str(ui),OPERATIONAL_DB=str(pathlib.Path(td)/'fresh.sqlite3'),OPERATIONAL_ADMIN_CREDENTIAL=cred)
 p=subprocess.Popen([str(ROOT/'start.sh')],cwd=ROOT,env=env,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)
 try:
  def get(url,token=None):
   r=urllib.request.Request(url,headers={'Authorization':'Bearer '+token} if token else {})
   return urllib.request.urlopen(r,timeout=2)
  end=time.time()+40
  while time.time()<end:
   if p.poll() is not None: raise RuntimeError('launcher exited early')
   try:
    assert get(f'http://127.0.0.1:{api}/health').status==200
    break
   except Exception: time.sleep(.3)
  else: raise RuntimeError('API health timeout')
  # Bootstrap token convention is <id>.<credential>.
  token='bootstrap.'+cred
  assert get(f'http://127.0.0.1:{api}/api/records',token).status==200
  with get(f'http://127.0.0.1:{ui}/api/records',token) as resp:
   body=resp.read()
   assert resp.status==200 and b'[' in body
  print(f'PASS fresh DB={pathlib.Path(td)/"fresh.sqlite3"}; API=127.0.0.1:{api}; UI proxy=127.0.0.1:{ui}; health/authenticated records/proxy all 200')
 finally:
  p.terminate()
  try: p.wait(timeout=8)
  except subprocess.TimeoutExpired: p.kill(); p.wait()
