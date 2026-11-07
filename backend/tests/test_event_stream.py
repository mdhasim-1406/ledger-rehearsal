import asyncio
import httpx
from backend import main

def test_generator_replay_and_boundary(tmp_path, monkeypatch):
    monkeypatch.setattr(main, 'DB_PATH', tmp_path/'events.sqlite')
    with main.connect() as c:
        c.execute('CREATE TABLE events(id INTEGER PRIMARY KEY, case_id TEXT, type TEXT, message TEXT, data TEXT, created_at TEXT)')
        c.execute("INSERT INTO events VALUES(1,NULL,'detected','first','{}','2026')")
    async def run():
        stream=main.event_stream(after=0)
        assert b'event: ready' in await anext(stream)
        assert b'id: 1' in await anext(stream)
        await stream.aclose()
        fresh=main.event_stream()
        assert b'event: ready' in await anext(fresh)
        with main.connect() as c:
            c.execute("INSERT INTO events VALUES(2,NULL,'detected','second','{}','2026')")
        assert b'id: 2' in await asyncio.wait_for(anext(fresh),2)
        await fresh.aclose()
    asyncio.run(run())

def test_invalid_cursor_rejected():
    async def run():
        transport=httpx.ASGITransport(app=main.app)
        async with httpx.AsyncClient(transport=transport,base_url='http://test') as client:
            assert (await client.get('/api/events/stream',headers={'Last-Event-ID':'invalid'})).status_code==400
            assert (await client.get('/api/events/stream?after=-1')).status_code==422
    asyncio.run(run())
