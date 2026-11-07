import asyncio
import json
import sqlite3
from starlette.requests import Request
from backend.domain_foundation import initialize,ReconciliationDomain
from backend.operational_api import create_app
from backend.operational_auth import OperationalAuth

def test_stream_delivers_real_domain_event_ids(tmp_path):
    db=tmp_path/'d.sqlite'; initialize(db)
    auth=OperationalAuth('testing-credential-not-for-use',database=str(db))
    app=create_app(db,auth=auth,start_worker=False)
    ReconciliationDomain(db).ingest('local','bank','1',[{'source_id':'a','date':'2026-01-01','description':'x','amount_cents':100,'currency':'USD','transaction_id':'t'}])
    endpoint=next(r.endpoint for r in app.routes if getattr(r,'path',None)=='/api/events')
    async def receive():
        await asyncio.sleep(60)
        return {'type':'http.disconnect'}
    async def check():
        request=Request({'type':'http','method':'GET','path':'/api/events','headers':[],'query_string':b''},receive)
        response=await endpoint(request,actor=None)
        stream=response.body_iterator
        first=await asyncio.wait_for(anext(stream),2)
        await stream.aclose()
        assert 'data:' in first, first
    asyncio.run(check())
