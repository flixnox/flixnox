with open("nox/handlers.py", "r") as f:
    code = f.read()

dm_logic = '''
# ==========================================
# PRIVATE CHAT (DM) AUDIO LOGIC
# ==========================================
import hashlib
import httpx
from aiogram.enums import ChatAction
from aiogram.types import BufferedInputFile
from aiogram.utils.keyboard import InlineKeyboardBuilder

MAX_BYTES = 49 * 1024 * 1024
RANGE_STEP = 8 * 1024 * 1024
RESULTS = 8

_UA_WEB = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
_UA_ANDROID = "com.google.android.youtube/19.09.37 (Linux; U; Android 11) gzip"

def _fmt_dur(sec) -> str:
    try:
        sec = int(sec)
    except Exception:
        return ""
    if sec <= 0:
        return ""
    return f"{sec // 60}:{sec % 60:02d}"

def _is_yt(track: dict, url: str = "") -> bool:
    return track.get("src") == "youtube" or "googlevideo.com" in (url or "")

def _ext(ctype: str, url: str) -> str:
    c = (ctype or "").lower()
    if "mpeg" in c or url.split("?")[0].lower().endswith(".mp3"):
        return "mp3"
    if "webm" in c:
        return "webm"
    return "m4a"

def _safe_name(s: str) -> str:
    return re.sub(r'[\\\\/:*?"<>|\\r\\n]+', "", s).strip()[:80] or "track"

async def _fetch_plain(c: httpx.AsyncClient, url: str, headers: dict):
    async with c.stream("GET", url, headers=headers) as r:
        r.raise_for_status()
        ctype = r.headers.get("content-type", "")
        clen = int(r.headers.get("content-length") or 0)
        if clen > MAX_BYTES:
            raise ValueError("file too large")
        buf = bytearray()
        async for chunk in r.aiter_bytes(64 * 1024):
            buf += chunk
            if len(buf) > MAX_BYTES:
                raise ValueError("file too large")
        return bytes(buf), ctype

async def _fetch_ranged(c: httpx.AsyncClient, url: str, headers: dict):
    buf = bytearray()
    start = 0
    ctype = ""
    while True:
        r = await c.get(url, headers={**headers, "Range": f"bytes={start}-{start + RANGE_STEP - 1}"})
        if not ctype:
            ctype = r.headers.get("content-type", "")
        if r.status_code == 200:
            if len(r.content) > MAX_BYTES:
                raise ValueError("file too large")
            return r.content, ctype
        if r.status_code != 206:
            r.raise_for_status()
            raise RuntimeError(f"unexpected status {r.status_code}")

        buf += r.content
        if len(buf) > MAX_BYTES:
            raise ValueError("file too large")

        m = re.match(r"bytes (\\d+)-(\\d+)/(\\d+|\\*)", r.headers.get("content-range", ""))
        if not m:
            break
        last = int(m.group(2))
        total = None if m.group(3) == "*" else int(m.group(3))
        start = last + 1
        if total is not None and start >= total:
            break
        if total is None and len(r.content) < RANGE_STEP:
            break
    return bytes(buf), ctype

async def _fetch(url: str, yt: bool = False):
    headers = {"Accept": "*/*", "Accept-Encoding": "identity"}
    if yt:
        headers.update({"User-Agent": _UA_ANDROID, "Referer": "https://www.youtube.com/"})
    else:
        headers["User-Agent"] = _UA_WEB
    timeout = httpx.Timeout(connect=15.0, read=60.0, write=15.0, pool=15.0)
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as c:
        if yt:
            return await _fetch_ranged(c, url, headers)
        return await _fetch_plain(c, url, headers)

async def _fetch_thumb(url: str):
    if not url: return None
    try:
        async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as c:
            r = await c.get(url, headers={"User-Agent": _UA_WEB})
            r.raise_for_status()
        ctype = r.headers.get("content-type", "")
        if "jpeg" in ctype or "jpg" in ctype:
            if 0 < len(r.content) <= 200 * 1024:
                return BufferedInputFile(r.content, filename="cover.jpg")
    except Exception:
        pass
    return None

async def send_audio_card(bot, uid: int, track: dict) -> bool:
    title = track.get("title") or "Unknown"
    artist = track.get("artist") or ""
    try:
        await bot.send_chat_action(uid, ChatAction.UPLOAD_VOICE)
        try:
            url = await asyncio.wait_for(music.resolve(track), 40)
        except Exception:
            url = None
        if not url:
            await bot.send_message(uid, "❌ Couldn't load that track. Try another result.")
            return False

        data, ctype = await _fetch(url, yt=_is_yt(track, url))
        if not data:
            raise RuntimeError("empty download")

        filename = f"{_safe_name(f'{artist} - {title}' if artist else title)}.{_ext(ctype, url)}"
        file = BufferedInputFile(data, filename=filename)
        thumb = await _fetch_thumb(track.get("img", ""))

        caption = f"🎵 <b>{html.escape(title)}</b>"
        if artist:
            caption += f"\\n👤 {html.escape(artist)}"
        dur = _fmt_dur(track.get("dur"))
        if dur:
            caption += f"\\n⏱ {dur}"

        await bot.send_chat_action(uid, ChatAction.UPLOAD_VOICE)
        await bot.send_audio(
            uid,
            file,
            title=title,
            performer=artist or None,
            duration=int(track.get("dur") or 0) or None,
            thumbnail=thumb,
            caption=caption,
            parse_mode="HTML",
        )
        return True
    except Exception as e:
        log.exception(f"send_audio_card crashed: {e}")
        await bot.send_message(uid, "❌ Something went wrong.")
        return False

async def private_search(m: Message, q: str):
    q = clean_text(q or "", 80)
    if len(q) < 2:
        return await m.answer("🔎 <b>Send me a song or artist name</b>")
    tracks = await music.search(q, RESULTS)
    if not tracks:
        return await m.answer("😕 No results. Try the artist name too.")

    kb = InlineKeyboardBuilder()
    for t in tracks:
        if len(f"ps:{t.get('id', '')}".encode()) > 64:
            t = {**t, "id": hashlib.sha1(str(t.get("id")).encode()).hexdigest()[:16]}
        key = music.stash(t)
        dur = _fmt_dur(t.get("dur"))
        label = f"{t.get('title', '?')} — {t.get('artist', '')}".strip(" —")
        if dur:
            label += f" · {dur}"
        kb.button(text=label[:60], callback_data=f"ps:{key}")
    kb.adjust(1)

    await m.answer(f"🔎 <b>Results for</b> “{html.escape(q[:60])}”\\n\\nTap a song to get it:", reply_markup=kb.as_markup(), parse_mode="HTML")

@router.callback_query(F.data.startswith("ps:"))
async def cb_pick(cb: CallbackQuery):
    if not await guard_cb(cb): return
    key = cb.data[3:]
    track = music.take(key)
    if not track:
        return await cb.answer("This search expired. Please search again.", show_alert=True)
    await cb.answer("⏳ Getting your song…")
    uid = cb.from_user.id
    room = rooms.get(uid)
    if room is None:
        room = rooms.get(uid)
    await send_audio_card(bot, uid, track)
'''

# Purane DM handlers ko hata do
import re
code = re.sub(r'@router\.message\(F\.chat\.type == "private".*?(?=@router|async def|$)', '', code, flags=re.DOTALL)
code = re.sub(r'@router\.message\(Command\("play", "search"\), F\.chat\.type == "private"\).*?(?=@router|async def|$)', '', code, flags=re.DOTALL)
code = re.sub(r'@router\.callback_query\(F\.data\.startswith\("ps:"\)\).*?(?=@router|async def|$)', '', code, flags=re.DOTALL)

# Naya logic file ke end me add kar do
code += "\n" + dm_logic

with open("nox/handlers.py", "w") as f:
    f.write(code)

print("✅ handlers.py me DM audio card add ho gaya!")
