"""Live container smoke test; run with /lsiopy/bin/python inside fallback.
Uses a disposable test target and a cookie-protected slow HTTP attachment.
"""
import asyncio
import hashlib
import time
import uuid
from pathlib import Path
from urllib.parse import quote

from aiohttp import ClientSession, web

DATA = bytes(range(256)) * 16384
CLIENT = uuid.uuid4().hex
OTHER = uuid.uuid4().hex
NAME = "fly-download-smoke-" + uuid.uuid4().hex + ".bin"
ROOT = Path("/config/Downloads")


async def run():
    finished = asyncio.Event()

    async def attachment(request):
        if request.cookies.get("flySmoke") != "yes":
            raise web.HTTPForbidden()
        resp = web.StreamResponse(headers={
            "Content-Length": str(len(DATA)),
            "Content-Disposition": "attachment; filename*=UTF-8''" + quote(NAME),
        })
        await resp.prepare(request)
        for offset in range(0, len(DATA), 65536):
            await resp.write(DATA[offset:offset + 65536])
            await asyncio.sleep(.055)
        await resp.write_eof()
        finished.set()
        return resp

    app = web.Application()
    app.router.add_get("/download", attachment)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]
    origin = f"http://127.0.0.1:{port}"
    async with ClientSession() as session:
        async def poll(cid=CLIENT, enabled=True, claim=False):
            async with session.post("http://127.0.0.1:3000/fly-downloads/poll", json={
                "client":cid, "active":True, "enabled":enabled, "claim":claim
            }) as response:
                response.raise_for_status()
                return await response.json()
        target = None
        try:
            result = await poll(claim=True)
            assert result["ready"] and result["mode"] == "client"
            async with session.put("http://127.0.0.1:9222/json/new?about:blank") as r:
                target = await r.json(content_type=None)
            async with session.ws_connect(target["webSocketDebuggerUrl"]) as ws:
                i = 0
                async def cmd(method, params):
                    nonlocal i
                    i += 1
                    await ws.send_json({"id":i,"method":method,"params":params})
                    while True:
                        item = await ws.receive_json()
                        if item.get("id") == i:
                            assert "error" not in item, item
                            return item
                await cmd("Network.setCookie", {"name":"flySmoke","value":"yes","url":origin})
                await cmd("Page.navigate", {"url":origin + "/download"})
                rec = None
                for _ in range(100):
                    result = await poll()
                    rec = next((r for r in result["downloads"] if r["name"] == NAME), None)
                    if rec:
                        break
                    await asyncio.sleep(.1)
                assert rec, "download event missing"
                assert not (await poll(OTHER))["downloads"], "wrong client can see token"
                async with session.get("http://127.0.0.1:3000/fly-downloads/file/" + rec["token"]) as r:
                    r.raise_for_status()
                    assert NAME in r.headers["Content-Disposition"]
                    first = await r.content.read(65536)
                    assert first and not finished.is_set(), "client did not start before origin completed"
                    result = first + await r.read()
                    assert hashlib.sha256(result).digest() == hashlib.sha256(DATA).digest(), "corrupt file"
                    print("PASS: authenticated attachment streamed before origin completed; exact SHA-256")
                await asyncio.wait_for(finished.wait(), 5)
                for _ in range(100):
                    if not any(x["name"] == NAME for x in (await poll())["downloads"]):
                        break
                    await asyncio.sleep(.1)
                else:
                    raise AssertionError("completed relay was not acknowledged")
                result = await poll(enabled=False)
                assert result["mode"] == "colima" and not result["owner"]
                assert not result["downloads"]
                print("PASS: Colima mode restores Chromium default download handling (no auto relay)")

        finally:
            await poll(enabled=False)
            if target:
                async with session.get("http://127.0.0.1:9222/json/close/" + target["id"]):
                    pass
            for p in ROOT.glob(NAME.removesuffix(".bin") + "*.bin"):
                p.unlink()
            await runner.cleanup()


if __name__ == "__main__":
    asyncio.run(run())
