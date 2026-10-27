"""FastAPI app: Telegram webhook, Mini App files and the room WebSocket. Every route sits behind the proxy secret."""
import asyncio
import hashlib
import json
import logging
import time
from contextlib import asynccontextmanager
from pathlib import Path

from aiogram import Dispatcher
from aiogram.types import (BotCommand, BotCommandScopeAllGroupChats, BotCommandScopeAllPrivateChats, Update)
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, PlainTextResponse
from starlette.middleware.gzip import GZipMiddleware
from fastapi.staticfiles import StaticFiles

from . import admin, broadcast, config, handlers, moviebox, music, security, state, stream
from .stream import router as stream_router
from .security import clean_text, same
from .state import bot, conn_rl, penalty, rooms, rtc_rl, search_rl, store, ws_rl

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
log = logging.getLogger("nox")
WEB = Path(__file__).resolve().parent.parent / "webapp"
dp = Dispatcher()
_h = hashlib.md5()
for _f in sorted((WEB / "static").glob("*")):
    _h.update(_f.read_bytes())
ASSET_V = _h.hexdigest()[:10]                                           # changes whenever the UI files change
INDEX_HTML = (WEB / "index.html").read_text(encoding="utf-8").replace("__V__", ASSET_V)
dp.include_router(admin.router)       # owner panel first
dp.include_router(handlers.router)
_tasks = set()

CSP = ("default-src 'none'; script-src 'self' https://telegram.org; style-src 'self' https://fonts.googleapis.com; "
       "font-src https://fonts.gstatic.com; img-src 'self' https: data:; media-src https: blob:; "
       f"connect-src 'self' wss://{config.PUBLIC_HOST} https://*.saavncdn.com; base-uri 'none'; form-action 'none'; "
       "frame-ancestors https://web.telegram.org https://*.telegram.org")
SEC_HEADERS = {
    "Content-Security-Policy": CSP, "X-Content-Type-Options": "nosniff", "Referrer-Policy": "no-referrer",
    "Permissions-Policy": "camera=(), microphone=(self), display-capture=(self), geolocation=(), payment=()",
    "Cross-Origin-Opener-Policy": "same-origin", "Strict-Transport-Security": "max-age=31536000",
}


@asynccontextmanager
async def lifespan(app):
    await store.init(config.MONGO_URI, config.MONGO_DB)
    state.me = await bot.get_me()
    rooms.on_play, rooms.on_fail, rooms.panel_changed = handlers.on_play, handlers.on_fail, handlers.panel_changed
    rooms.on_drop = handlers.on_drop
    await bot.set_webhook(f"{config.PUBLIC_URL}/webhook/{config.WEBHOOK_PATH}", secret_token=config.WEBHOOK_TOKEN,
                          allowed_updates=["message", "callback_query", "my_chat_member"], max_connections=40)
    try:
        await bot.set_my_commands([BotCommand(command="start", description="Open the bot"),
                                   BotCommand(command="help", description="How it works")],
                                  scope=BotCommandScopeAllPrivateChats())
        await bot.set_my_commands([BotCommand(command=c, description=d) for c, d in (
            ("start", "Open the room (admins)"), ("play", "Add a song"), ("queue", "Show the queue"), ("invite", "Invite the group to the room"),
            ("skip", "Skip song (admins)"), ("pause", "Pause (admins)"), ("resume", "Resume (admins)"),
            ("loop", "Toggle loop (admins)"), ("autoplay", "Toggle autoplay (admins)"), ("join", "Get the join button"), ("shuffle", "Shuffle queue (admins)"), ("clear", "Clear queue (admins)"),
            ("end", "Stop the room (admins)"), ("settings", "Group settings (admins)"), ("search", "Search movies / series"), ("help", "How it works"))],
            scope=BotCommandScopeAllGroupChats())
        await bot.set_my_short_description("Live listening rooms for your Telegram group.")
        await bot.set_my_description("Sonic Nox turns your group into a live listening room. Add me to a group, "
                                     "send /start, and queue songs with /play.")
    except Exception as e:
        log.warning("could not set bot profile: %s", e)
    bg = [asyncio.create_task(rooms.sweeper())]
    for d in store.bc_running():
        bg.append(asyncio.create_task(broadcast.run(d["_id"])))     # resume interrupted broadcasts
    log.info("Sonic Nox is up as @%s", state.me.username)
    yield
    for t in bg:
        t.cancel()
    await music.close()
    await moviebox.close()
    await bot.session.close()


app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
app.include_router(stream_router)
app.add_middleware(GZipMiddleware, minimum_size=500)                  # smaller downloads = faster Mini App


@app.middleware("http")
async def shield(request: Request, call_next):
    if request.url.path == "/healthz":
        return PlainTextResponse("ok")
    if not same(request.headers.get("x-proxy-secret", ""), config.PROXY_SECRET):
        return PlainTextResponse("Not found", status_code=404)          # look like nothing is here
    if int(request.headers.get("content-length") or 0) > 1_000_000:
        return PlainTextResponse("Too large", status_code=413)
    resp = await call_next(request)
    for k, v in SEC_HEADERS.items():
        resp.headers[k] = v
    if request.url.path.startswith("/static/"):
        resp.headers["Cache-Control"] = "public, max-age=31536000, immutable"   # files are versioned with ?v=
    elif "cache-control" not in resp.headers:
        resp.headers["Cache-Control"] = "no-store"
    return resp


@app.get("/")
async def index():
    return HTMLResponse(INDEX_HTML)


@app.get("/health")
async def health():
    return PlainTextResponse("ok")


app.mount("/static", StaticFiles(directory=WEB / "static"), name="static")


@app.post("/webhook/{path}")
async def webhook(path: str, request: Request):
    if not same(path, config.WEBHOOK_PATH) or not same(request.headers.get("x-telegram-bot-api-secret-token", ""), config.WEBHOOK_TOKEN):
        return PlainTextResponse("Not found", status_code=404)
    try:
        update = Update.model_validate(await request.json(), context={"bot": bot})
    except Exception:
        return PlainTextResponse("Bad request", status_code=400)
    t = asyncio.create_task(dp.feed_update(bot, update))
    _tasks.add(t)
    t.add_done_callback(_tasks.discard)
    return {"ok": True}


# ---------------- WebSocket: one room per group ----------------
MAX_SPEAKERS = 8


class Client:
    def __init__(self, ws, user):
        self.ws, self.user, self.uid = ws, user, user["id"]
        self.lock = asyncio.Lock()
        self.name = clean_text(user.get("first_name", "") or "Listener", 30)
        ph = str(user.get("photo_url") or "")
        self.photo = ph if ph.startswith("https://t.me/i/userpic/") and len(ph) < 220 else None
        self.adm = False
        self.joined = int(time.time())
        self.v = self.m = self.s = False          # in voice / muted / sharing screen

    async def send(self, msg):
        try:
            async with self.lock:
                await asyncio.wait_for(self.ws.send_text(json.dumps(msg, separators=(",", ":"))), 5)
            return True
        except Exception:
            return False

    async def close(self):
        try:
            await self.ws.close(code=1000)
        except Exception:
            pass


_ip_conns = {}


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    h = ws.headers
    if not same(h.get("x-proxy-secret", ""), config.PROXY_SECRET):
        return await ws.close(code=1008)
    origin = h.get("origin")
    if origin and origin != config.PUBLIC_ORIGIN:
        return await ws.close(code=1008)
    ip = h.get("cf-connecting-ip") or (ws.client.host if ws.client else "?")
    if not conn_rl.allow(ip) or _ip_conns.get(ip, 0) >= 8:
        return await ws.close(code=1013)
    await ws.accept()
    _ip_conns[ip] = _ip_conns.get(ip, 0) + 1
    client = room = None

    async def fatal(msg):
        try:
            await ws.send_text(json.dumps({"t": "fatal", "m": msg}))
            await ws.close(code=1000)
        except Exception:
            pass

    try:
        first = json.loads(await asyncio.wait_for(ws.receive_text(), 8))
        info = security.verify_init_data(first.get("initData") if isinstance(first, dict) else None, config.BOT_TOKEN)
        if not info:
            return await fatal("Open this room from the pinned message in your Telegram group.")
        user = info["user"]
        uid = user["id"]
        chat_id = security.decode_room(info["start_param"])
        solo = chat_id is not None and chat_id == uid           # your own private player (opened from a chat with the bot)
        if chat_id is None or (chat_id >= 0 and not solo):
            return await fatal("This room link isn't valid.")
        if uid not in config.OWNER_IDS:
            if store.get_kv("maint", False):
                return await fatal("Sonic Nox is under maintenance. Please try again soon.")
            if store.is_banned("u", uid) or (not solo and store.is_banned("g", chat_id)) or penalty.blocked(uid):
                return await fatal("You can't use this room.")
        if not await state.is_member(chat_id, uid):
            return await fatal("Join the group to listen in its room.")
        g = {"title": "Your player"} if solo else store.group(chat_id)
        if not solo and (not g.get("panel") or g.get("dead")):
            return await fatal("This room isn't open. Ask an admin to send /start in the group.")
        room = rooms.get(chat_id)
        if room is None:
            return await fatal("The server is busy. Please try again in a minute.")
        if len(room.clients) >= 300 and uid not in room.clients:
            return await fatal("This room is full.")
        client = Client(ws, user)
        admin_now = await state.is_admin(chat_id, uid)
        client.adm = admin_now
        await client.send({"t": "hello", "admin": admin_now, "id": uid, "solo": solo, "ice": config.ICE, "room": g.get("title", "")[:60],
                           "me": clean_text(user.get("first_name", ""), 32),
                           "link": f"https://t.me/{config.BOT_USERNAME}/{config.MINIAPP_SHORT}?startapp={security.encode_room(chat_id)}"})
        await room.join(client)
        name = clean_text(user.get("first_name", "") or "Listener", 30)

        while True:
            raw = await asyncio.wait_for(ws.receive_text(), 240)
            is_rtc = raw.startswith('{"t":"rtc"')
            if len(raw) > (16384 if is_rtc else 4096):
                return await ws.close(code=1009)
            if not (rtc_rl if is_rtc else ws_rl).allow(uid):
                penalty.strike(uid)
                await client.send({"t": "err", "m": "Slow down a little."})
                continue
            try:
                js = json.loads(raw)
                t = js["t"]
            except Exception:
                penalty.strike(uid)
                continue
            try:
                await handle(t, js, room, client, chat_id, uid, name)
            except Exception:
                log.exception("handler error (%s)", t)
                await client.send({"t": "err", "m": "Something went wrong. Please try again."})
    except (WebSocketDisconnect, asyncio.TimeoutError, json.JSONDecodeError):
        pass
    except Exception:
        log.exception("ws error")
    finally:
        _ip_conns[ip] = max(0, _ip_conns.get(ip, 1) - 1)
        if room is not None and client is not None:
            await room.leave(client)


async def handle(t, js, room, client, chat_id, uid, name):
    send = client.send
    seq = js.get("seq")
    if t == "ping":
        adm = await state.is_admin(chat_id, uid)
        if adm != client.adm:
            client.adm = adm
            room.people_changed()
        return await send({"t": "pong", "c": js.get("c"), "st": time.time(), "adm": adm})
    if t == "ended":
        return await room.vote_end(uid, seq)
    if t == "meta":
        return room.report_dur(uid, seq, js.get("dur"))
    if t == "bad":
        return await room.vote_bad(uid, seq)
    if t == "vstate":                                   # voice / screen flags (the audio itself goes peer to peer)
        v, s_ = bool(js.get("v")), bool(js.get("s"))
        m = bool(js.get("m")) if v else False
        if v and not client.v and sum(1 for c in room.clients.values() if c.v) >= MAX_SPEAKERS:
            return await send({"t": "vdeny", "m": f"Voice is full ({MAX_SPEAKERS} speakers). Try again later."})
        if s_ and not client.s and any(c.s for c in room.clients.values()):
            return await send({"t": "vdeny", "k": "s", "m": "Someone is already sharing their screen."})
        client.v, client.m, client.s = v, m, s_
        return room.people_changed()
    if t == "rtc":                                      # relay WebRTC handshakes between two members of this room
        k, to, d = js.get("k"), js.get("to"), js.get("d")
        target = room.clients.get(to) if isinstance(to, int) and to != uid else None
        if k not in ("mic", "scr") or target is None or not isinstance(d, dict):
            return
        clean = {"o": 1 if d.get("o") else 0}
        sd, cd = d.get("s"), d.get("c")
        if isinstance(sd, dict) and sd.get("type") in ("offer", "answer") and isinstance(sd.get("sdp"), str) and len(sd["sdp"]) < 14000:
            if sd["type"] == "offer" and not (client.v if k == "mic" else client.s):
                return                                  # only people who are really in voice / sharing may send offers
            clean["s"] = {"type": sd["type"], "sdp": sd["sdp"]}
        elif isinstance(cd, dict) and isinstance(cd.get("candidate"), str) and len(cd["candidate"]) < 800:
            mid = cd.get("sdpMid")
            idx = cd.get("sdpMLineIndex")
            clean["c"] = {"candidate": cd["candidate"], "sdpMid": mid if isinstance(mid, str) and len(mid) < 40 else None,
                          "sdpMLineIndex": idx if isinstance(idx, int) and 0 <= idx < 8 else 0}
        else:
            return
        return await target.send({"t": "rtc", "from": uid, "k": k, "d": clean})
    if t == "vmute":                                    # admins can mute someone's mic
        if not await state.is_admin(chat_id, uid):
            return await send({"t": "err", "m": "Only group admins can do this."})
        target = room.clients.get(js.get("to")) if isinstance(js.get("to"), int) else None
        if target is not None and target.v:
            await target.send({"t": "vmute", "by": name})
        return
    if t == "invite":                                   # any member in the room may call the rest of the group
        if await handlers.invite_group(chat_id, name) is None:
            return await send({"t": "err", "m": "An invite was just sent. Try again in a minute."})
        return await send({"t": "ok", "m": "Invite sent to the group"})

    if t == "search":
        if not search_rl.allow(uid):
            return await send({"t": "err", "m": "Searching too fast. Wait a second."})
        q = clean_text(js.get("q"), 80)
        by_artist = bool(js.get("artist"))
        songs, artists = await music.search_all(q, 20 if by_artist else 12, 0 if by_artist else 6) if len(q) >= 2 else ([], [])
        rid = js.get("id")
        return await send({"t": "results", "id": rid if isinstance(rid, int) else None, "q": q, "artist": by_artist, "items": music.stash(uid, songs), "artists": artists})

    if t == "add":
        g = {"play": "all"} if chat_id > 0 else store.group(chat_id)
        if g["play"] == "admins" and not await state.is_admin(chat_id, uid):
            return await send({"t": "err", "m": "Only admins can add songs in this group."})
        track = music.take(js.get("token"), uid)
        if not track:
            return await send({"t": "err", "m": "That result expired. Search again."})
        track.update(by=name, by_id=uid, src="a")
        pos = room.add(track)
        if pos is None:
            return await send({"t": "err", "m": "The queue is full right now."})
        return await send({"t": "ok", "m": "Starting now…" if pos == "start" else f"Added at #{pos}"})

    if t == "lyrics":
        if not search_rl.allow(uid):
            return await send({"t": "err", "m": "Wait a second."})
        cur = room.cur
        if not cur:
            return await send({"t": "err", "m": "Nothing is playing."})
        txt = await music.lyrics(cur["artist"], cur["title"])
        return await send({"t": "lyrics", "title": cur["title"], "text": txt})

    if t in ("skip", "pause", "resume", "loop", "autoplay", "shuffle", "clear", "remove", "end"):
        if not await state.is_admin(chat_id, uid):
            return await send({"t": "err", "m": "Only group admins can do this."})
        if t == "skip":
            await room.skip()
        elif t == "pause":
            await room.pause()
        elif t == "resume":
            await room.resume()
        elif t == "loop":
            await room.toggle_loop()
        elif t == "autoplay":
            await room.toggle_autoplay()
        elif t == "shuffle":
            await room.shuffle()
        elif t == "clear":
            await room.clear()
        elif t == "end":
            await handlers.close_room(chat_id)
        else:
            await room.remove(js.get("i"))
        return
    penalty.strike(uid)
