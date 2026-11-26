#!/usr/bin/env python3
"""Private Chromium CDP -> authenticated same-origin browser download bridge."""
import asyncio
import json
import os
import re
import secrets
import time
from pathlib import Path
from urllib.parse import quote

from aiohttp import ClientSession, web

ROOT = Path("/config/Downloads")
STAGE = ROOT / ".fly-transfer"
GUID = re.compile(r"[a-fA-F0-9-]{36}")
CLIENT = re.compile(r"[a-f0-9]{32}")
LEASE = 20
RETRY_TTL = 3600
MAX_RECORDS = 256


def filename(value):
    name = Path(str(value).replace("\\", "/")).name.replace("\x00", "")
    name = name.encode("utf-8")[:220].decode("utf-8", "ignore")
    return name if name not in ("", ".", "..") else "download"


def unique_path(root, name):
    name = filename(name)
    p = root / name
    i = 1
    while p.exists() or p.is_symlink():
        i += 1
        p = root / f"{Path(name).stem} ({i}){Path(name).suffix}"
    return p


class Bridge:
    def __init__(self):
        self.owner = None
        self.expires = 0
        self.ws = None
        self.mode = None
        self.seq = 0
        self.pending = {}
        self.records = {}
        self.lock = asyncio.Lock()

    async def command(self, method, params):
        self.seq += 1
        seq = self.seq
        future = asyncio.get_running_loop().create_future()
        self.pending[seq] = future
        try:
            await self.ws.send_json({"id": seq, "method": method, "params": params})
            return await asyncio.wait_for(future, 5)
        finally:
            self.pending.pop(seq, None)

    async def sync_mode(self):
        async with self.lock:
            desired = "allowAndName" if self.owner and self.expires > time.monotonic() else "default"
            if not self.ws or self.mode == desired:
                return
            params = {"behavior": desired, "eventsEnabled": True}
            if desired == "allowAndName":
                params["downloadPath"] = str(STAGE)
            result = await self.command("Browser.setDownloadBehavior", params)
            if "error" in result:
                raise RuntimeError("Chromium download control unavailable")
            self.mode = desired

    def save(self, rec):
        p = STAGE / (rec["guid"] + ".json")
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps({"name": rec["name"], "guid": rec["guid"]}))
        tmp.replace(p)

    def recover(self):
        # A completed but unclaimed download survives a service/container restart.
        for meta in STAGE.glob("*.json"):
            try:
                data = json.loads(meta.read_text())
                guid = data["guid"]
                if not GUID.fullmatch(guid):
                    continue
                final = STAGE / guid
                if final.is_file() and not final.is_symlink():
                    final.rename(unique_path(ROOT, data["name"]))
                    meta.unlink()
            except (OSError, ValueError, KeyError):
                pass

    def event(self, event):
        method, p = event.get("method"), event.get("params", {})
        guid = p.get("guid", "")
        if not GUID.fullmatch(guid):
            return
        if method == "Browser.downloadWillBegin" and self.mode == "allowAndName":
            rec = {"guid": guid, "name": filename(p.get("suggestedFilename", "download")),
                   "owner": self.owner, "token": secrets.token_urlsafe(32), "received": 0,
                   "total": 0, "state": "inProgress", "created": time.monotonic(),
                   "claimed": False, "active": False, "sent": False, "path": None}
            self.records[guid] = rec
            self.save(rec)
        elif method == "Browser.downloadProgress" and guid in self.records:
            rec = self.records[guid]
            received = max(0, int(p.get("receivedBytes", 0)))
            if received < rec["received"] and rec["active"]:
                rec["restart"] = True
            rec.update(received=received,
                       total=max(0, int(p.get("totalBytes", 0))), state=p.get("state", "inProgress"))
            if rec["state"] == "completed":
                # The GUID file is renamed by Chromium before this event. Keep a
                # normal named server copy available for interrupted client transfers.
                f = STAGE / guid
                if f.is_file() and not f.is_symlink():
                    target = unique_path(ROOT, rec["name"])
                    f.rename(target)
                    rec["path"] = target
                    rec["total"] = target.stat().st_size
                    (STAGE / (guid + ".json")).unlink(missing_ok=True)
            if rec["state"] == "canceled":
                rec["finished"] = time.monotonic()

    async def listen(self):
        while True:
            try:
                async with ClientSession() as session:
                    async with session.get("http://127.0.0.1:9222/json/version") as r:
                        endpoint = (await r.json(content_type=None))["webSocketDebuggerUrl"]
                    async with session.ws_connect(endpoint, heartbeat=15) as ws:
                        self.ws, self.mode = ws, None
                        init = asyncio.create_task(self.sync_mode())
                        async for msg in ws:
                            if msg.type.name != "TEXT":
                                continue
                            obj = json.loads(msg.data)
                            future = self.pending.get(obj.get("id"))
                            if future and not future.done():
                                future.set_result(obj)
                            else:
                                self.event(obj)
                        init.cancel()
            except (OSError, RuntimeError, ValueError, KeyError, asyncio.TimeoutError):
                pass
            finally:
                self.ws, self.mode = None, None
                for future in list(self.pending.values()):
                    if not future.done():
                        future.set_exception(RuntimeError("CDP disconnected"))
                # Don't declare incomplete streams successful after a CDP failure.
                for rec in self.records.values():
                    if rec["state"] == "inProgress":
                        rec["state"] = "interrupted"
                self.recover()
            await asyncio.sleep(2)

    async def maintain(self):
        while True:
            await asyncio.sleep(2)
            try:
                await self.sync_mode()
            except (RuntimeError, OSError, asyncio.TimeoutError):
                pass
            now = time.monotonic()
            for guid, rec in list(self.records.items()):
                if rec["active"] or rec["state"] == "inProgress":
                    continue
                if rec["sent"] and now - rec.get("finished", now) >= 60:
                    # Remove only the exact file that was successfully streamed.
                    p = rec["path"]
                    try:
                        if p and p.exists() and not p.is_symlink():
                            st = p.stat()
                            if (st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns) == rec.get("identity"):
                                p.unlink()
                    except OSError:
                        pass
                    self.records.pop(guid, None)
                elif now - rec["created"] > RETRY_TTL:
                    self.records.pop(guid, None)

    async def poll(self, request):
        if request.headers.get("Sec-Fetch-Site") == "cross-site":
            raise web.HTTPForbidden()
        data = await request.json()
        client = data.get("client", "")
        if not isinstance(client, str) or not CLIENT.fullmatch(client):
            raise web.HTTPBadRequest()
        active = data.get("active") is True
        enabled = data.get("enabled") is True
        if active and enabled and (data.get("claim") is True or self.owner == client or self.expires <= time.monotonic()):
            self.owner, self.expires = client, time.monotonic() + LEASE
        elif self.owner == client and not enabled:
            self.owner, self.expires = None, 0
        try:
            await self.sync_mode()
        except (RuntimeError, OSError, asyncio.TimeoutError):
            pass
        records = [{"id": r["guid"], "name": r["name"], "token": r["token"],
                    "state": r["state"], "received": r["received"], "total": r["total"],
                    "sent": r["sent"], "active": r["active"]}
                   for r in self.records.values() if r["owner"] == client and not r["sent"] and
                   r["state"] in ("inProgress", "completed")][-MAX_RECORDS:]
        return web.json_response({"ready": self.mode is not None, "owner": self.owner == client,
                                  "mode": "client" if self.mode == "allowAndName" else "colima",
                                  "downloads": records}, headers={"Cache-Control": "no-store"})

    async def stream(self, request):
        token = request.match_info["token"]
        rec = next((r for r in self.records.values() if secrets.compare_digest(r["token"], token)), None)
        if not rec or rec["sent"] or rec["active"]:
            raise web.HTTPNotFound()
        rec["active"] = True
        deadline = time.monotonic() + 3600
        f = None
        try:
            # Unknown-length responses wait for completion; known lengths can
            # stream sequentially, bounded by CDP's actual received byte count.
            while rec["state"] == "inProgress" and not rec["total"] and time.monotonic() < deadline:
                await asyncio.sleep(.1)
            if rec["state"] not in ("inProgress", "completed") or time.monotonic() >= deadline:
                raise web.HTTPGone()
            total = rec["total"]
            response = web.StreamResponse(headers={
                "Content-Type": "application/octet-stream",
                "Content-Disposition": "attachment; filename=\"download\"; filename*=UTF-8''" + quote(rec["name"], safe=""),
                "Content-Length": str(total), "Cache-Control": "no-store",
                "X-Content-Type-Options": "nosniff", "X-Accel-Buffering": "no",
            })
            await response.prepare(request)
            offset = 0
            while offset < total or rec["state"] == "inProgress":
                if time.monotonic() >= deadline:
                    raise ConnectionError("Download timeout")
                if rec["state"] not in ("inProgress", "completed") or rec.get("restart"):
                    raise ConnectionError("Chromium download interrupted")
                if rec["state"] == "completed" and total != rec["total"]:
                    raise ConnectionError("Chromium download size changed")
                if f is None:
                    p = rec["path"] or STAGE / (rec["guid"] + ".crdownload")
                    try:
                        f = os.fdopen(os.open(p, os.O_RDONLY | os.O_NOFOLLOW), "rb")
                    except FileNotFoundError:
                        if rec["state"] == "completed":
                            raise ConnectionError("Completed file unavailable")
                        await asyncio.sleep(.1)
                        continue
                available = min(total, os.fstat(f.fileno()).st_size,
                                rec["total"] if rec["state"] == "completed" else min(rec["received"], max(0, total - 1)))
                if available > offset:
                    chunk = f.read(min(256 * 1024, available - offset))
                    if chunk:
                        await response.write(chunk)
                        offset += len(chunk)
                        continue
                if rec["state"] == "completed" and offset != total:
                    raise ConnectionError("Incomplete Chromium download")
                await asyncio.sleep(.1)
            await response.write_eof()
            if rec["path"] and rec["path"].exists():
                st = rec["path"].stat()
                rec["identity"] = (st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns)
            rec["sent"], rec["finished"] = True, time.monotonic()
            return response
        except (ConnectionError, OSError, asyncio.CancelledError):
            # With Content-Length the browser identifies a truncated transfer.
            if request.transport:
                request.transport.close()
            raise
        finally:
            rec["active"] = False
            if f:
                f.close()


async def start(app):
    b = app["bridge"]
    ROOT.mkdir(exist_ok=True)
    STAGE.mkdir(mode=0o700, exist_ok=True)
    b.recover()
    tasks = [asyncio.create_task(b.listen()), asyncio.create_task(b.maintain())]
    yield
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)


def create_app():
    app = web.Application(client_max_size=4096)
    b = Bridge()
    app["bridge"] = b
    app.cleanup_ctx.append(start)
    app.router.add_post("/fly-downloads/poll", b.poll)
    app.router.add_get("/fly-downloads/file/{token}", b.stream, allow_head=False)
    return app


if __name__ == "__main__":
    web.run_app(create_app(), host="127.0.0.1", port=8789, access_log=None)
