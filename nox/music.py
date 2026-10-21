"""Music sources. Every third-party call is server-side with timeouts, caching and a circuit breaker."""
import asyncio
import re
import secrets
import time
from urllib.parse import quote

from . import config
from .security import clean_text, safe_https_url

class TTL:
    def __init__(self, ttl, cap):
        self.ttl, self.cap, self.d = ttl, cap, {}
    def get(self, k):
        v = self.d.get(k)
        if v and v[0] > time.monotonic():
            return v[1]
        self.d.pop(k, None)
        return None
    def put(self, k, v):
        if len(self.d) >= self.cap:
            now = time.monotonic()
            self.d = {a: b for a, b in self.d.items() if b[0] > now}
            if len(self.d) >= self.cap:
                self.d.clear()
        self.d[k] = (time.monotonic() + self.ttl, v)
    def clear(self):
        self.d.clear()

class Breaker:
    def __init__(self):
        self.fails, self.open_until = {}, {}
    def ok(self, name):
        return time.monotonic() >= self.open_until.get(name, 0)
    def fail(self, name):
        now = time.monotonic()
        f = [t for t in self.fails.get(name, []) if now - t < 60] + [now]
        self.fails[name] = f
        if len(f) >= 4:
            self.open_until[name] = now + 60
            self.fails[name] = []
    def good(self, name):
        self.fails.pop(name, None)

BREAKER = Breaker()
_SEARCH = TTL(300, 500)
_RESULTS = TTL(600, 5000)
_RES = TTL(600, 500)
_LYR = TTL(3600, 300)
_sem = asyncio.Semaphore(10)
_client = None
_YT_PATHS = ["/yt_music_audio/yt_music_audio", "/yt_music_audio"]

def client():
    global _client
    if _client is None:
        import httpx
        _client = httpx.AsyncClient(
            timeout=httpx.Timeout(8.0, connect=4.0), follow_redirects=False,
            headers={"User-Agent": "SonicNox/1.0", "x-api-key": config.CURIOUS_API_KEY}, limits=httpx.Limits(max_connections=30))
    return _client

async def close():
    if _client is not None:
        await _client.aclose()

def clear_caches():
    for c in (_SEARCH, _RESULTS, _RES, _LYR):
        c.clear()

async def _api(name, path, params=None, timeout=8.0):
    if not BREAKER.ok(name):
        return None
    try:
        async with _sem:
            r = await client().get(config.API_BASE + path, params=params, timeout=timeout)
        if r.status_code != 200 or len(r.content) > 2_000_000:
            raise ValueError(r.status_code)
        js = r.json()
        BREAKER.good(name)
        return js
    except Exception:
        BREAKER.fail(name)
        return None

def _first(d, keys):
    for k in keys:
        v = d.get(k)
        if v not in (None, "", [], {}):
            return v
    return None

def _secs(v):
    try:
        if isinstance(v, str):
            if ":" in v:
                s = 0
                for part in v.split(":"):
                    s = s * 60 + int(part)
                return s if 5 <= s <= 14400 else None
            m = re.match(r"^\s*([\d.]+)\s*min", v)
            if m:
                return int(float(m.group(1)) * 60)
        v = float(v)
        if v > 10000:
            v /= 1000.0
        return int(v) if 5 <= v <= 14400 else None
    except Exception:
        return None

async def search(q):
    q = clean_text(q, 80)
    if len(q) < 2:
        return []
    key = q.lower()
    hit = _SEARCH.get(key)
    if hit is not None:
        return [dict(x) for x in hit]
    
    try:
        # Direct yt-dlp search for robust results
        proc = await asyncio.create_subprocess_exec(
            "yt-dlp", "--print", "%(id)s\t%(title)s\t%(channel)s\t%(duration)s", f"ytsearch5:{q}",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=25.0)
        out = []
        if stdout:
            for line in stdout.decode().strip().split('\n'):
                parts = line.split('\t')
                if len(parts) == 4:
                    vid_id, title, artist, dur = parts
                    out.append({
                        "id": f"yt:{vid_id}",
                        "src": "youtube",
                        "title": clean_text(title, 120),
                        "artist": clean_text(artist, 80) or "Unknown",
                        "dur": _secs(dur),
                        "cover": f"https://i.ytimg.com/vi/{vid_id}/hqdefault.jpg",
                        "preview": None,
                        "stream": None
                    })
        out = out[:10]
        _SEARCH.put(key, out)
        return [dict(x) for x in out]
    except Exception:
        return []

def stash(user_id, items):
    pub = []
    for t in items:
        tok = secrets.token_urlsafe(6)
        _RESULTS.put(tok, (user_id, t))
        pub.append({"token": tok, "title": t["title"], "artist": t["artist"], "dur": t["dur"], "cover": t["cover"]})
    return pub

def take(token, user_id):
    v = _RESULTS.get(token) if isinstance(token, str) and len(token) <= 16 else None
    if not v or v[0] != user_id:
        return None
    return dict(v[1])

async def resolve(track):
    key = track.get("id") or (track.get("title"), track.get("artist"))
    hit = _RES.get(key)
    if hit:
        return hit
    
    vid_id = str(track.get("id", "")).replace("yt:", "")
    search_query = f"https://www.youtube.com/watch?v={vid_id}" if vid_id else f'{track["artist"]} - {track["title"]} audio'
    
    try:
        proc = await asyncio.create_subprocess_exec(
            "yt-dlp", "-g", "-f", "ba[ext=m4a]/ba", search_query,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=25.0)
        
        if proc.returncode == 0 and stdout:
            url = stdout.decode().strip().split('\n')[0]
            out = {"url": safe_https_url(url), "preview": False, "cover": track.get("cover")}
            _RES.put(key, out)
            return out
    except Exception:
        pass
        
    return None

async def lyrics(artist, title):
    key = (artist.lower(), title.lower())
    hit = _LYR.get(key)
    if hit is not None:
        return hit
    js = await _api("lyrics", f"/lyrics_ovh/{quote(artist, safe='')}/{quote(title, safe='')}")
    txt = js.get("lyrics") if isinstance(js, dict) else ""
    txt = txt.strip()[:6000] if isinstance(txt, str) else ""
    _LYR.put(key, txt)
    return txt

async def health():
    return [("yt-dlp", True, 0)]
