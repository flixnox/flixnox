"""Music source: JioSaavn API (songs, artists, direct audio links) + lyrics.
Everything runs server-side with short timeouts, caching and a circuit breaker, so the room never waits on a slow API."""
import asyncio
import html
import re
import secrets
import time
from urllib.parse import quote

import httpx

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
    """4 failures within 30 s -> that endpoint is skipped for 30 s."""

    def __init__(self):
        self.fails, self.open_until = {}, {}

    def ok(self, name):
        return time.monotonic() >= self.open_until.get(name, 0)

    def fail(self, name):
        now = time.monotonic()
        f = [t for t in self.fails.get(name, []) if now - t < 30] + [now]
        self.fails[name] = f
        if len(f) >= 4:
            self.open_until[name] = now + 30
            self.fails[name] = []

    def good(self, name):
        self.fails.pop(name, None)


BREAKER = Breaker()
_SEARCH = TTL(600, 800)
_RESULTS = TTL(900, 6000)
_SONG = TTL(1800, 800)
_LYR = TTL(3600, 400)
_sem = asyncio.Semaphore(16)
_client = None


def client():
    global _client
    if _client is None:
        _client = httpx.AsyncClient(
            timeout=httpx.Timeout(7.0, connect=3.5), follow_redirects=True,
            headers={"User-Agent": "Mozilla/5.0 SonicNox/2.0", "Accept": "application/json"},
            limits=httpx.Limits(max_connections=40, max_keepalive_connections=20, keepalive_expiry=60))
    return _client


async def close():
    if _client is not None:
        await _client.aclose()


def clear_caches():
    for c in (_SEARCH, _RESULTS, _SONG, _LYR):
        c.clear()


async def _api(name, path, params=None, base=None, timeout=7.0):
    if not BREAKER.ok(name):
        return None
    try:
        async with _sem:
            r = await client().get((base or config.JIOSAAVN_BASE) + path, params=params, timeout=timeout)
        if r.status_code != 200 or len(r.content) > 3_000_000:
            raise ValueError(r.status_code)
        js = r.json()
        BREAKER.good(name)
        return js
    except Exception:
        BREAKER.fail(name)
        return None


# ---------- turning JioSaavn JSON into small, safe dicts (tolerant of small format differences) ----------
def _text(v, n=120):
    return clean_text(html.unescape(v), n) if isinstance(v, str) else ""


def _https(u):
    if isinstance(u, str) and u.startswith("http://"):
        u = "https://" + u[7:]
    return safe_https_url(u)


def _img(v):
    """image may be [{quality,url}, ...], a url string or a dict. Prefer the biggest picture."""
    urls = []
    if isinstance(v, str):
        urls = [v]
    elif isinstance(v, dict):
        urls = [v.get("url")]
    elif isinstance(v, list):
        urls = [(x.get("url") if isinstance(x, dict) else x) for x in v]
    urls = [u for u in urls if isinstance(u, str) and u]
    if not urls:
        return None
    u = urls[-1]
    u = re.sub(r"-(50x50|150x150)\.", "-500x500.", u)
    return _https(u)


def _artist_names(item):
    a = item.get("artists")
    names = []
    if isinstance(a, dict):
        names = [x.get("name") for x in (a.get("primary") or a.get("all") or []) if isinstance(x, dict)]
    elif isinstance(a, list):
        names = [x.get("name") if isinstance(x, dict) else x for x in a]
    if not [n for n in names if n]:
        names = [item.get("primaryArtists") or item.get("primary_artists") or item.get("singers") or item.get("subtitle") or ""]
    names = [_text(n, 40) for n in names if isinstance(n, str) and n.strip()]
    return clean_text(", ".join(names[:3]), 80) or "Unknown artist"


def _audio_map(item):
    """{kbps: url}. Supports downloadUrl as a list of {quality,url} or a single url string."""
    d = item.get("downloadUrl") or item.get("download_url") or item.get("media_url") or item.get("url_320")
    out = {}
    if isinstance(d, str):
        u = _https(d)
        if u:
            out[160] = u
    elif isinstance(d, list):
        for x in d:
            if not isinstance(x, dict):
                continue
            q = re.sub(r"\D", "", str(x.get("quality") or "")) or "0"
            u = _https(x.get("url") or x.get("link"))
            if u:
                out[int(q)] = u
    return out


def _dur(v):
    try:
        v = float(v)
        return int(v) if 5 <= v <= 14400 else None
    except (TypeError, ValueError):
        return None


def song(item):
    if not isinstance(item, dict):
        return None
    title = _text(item.get("name") or item.get("title") or item.get("song"), 120)
    sid = item.get("id")
    if not title or not sid:
        return None
    album = item.get("album")
    return {
        "id": f"js:{sid}", "sid": str(sid)[:40], "src": "saavn", "title": title, "artist": _artist_names(item),
        "album": _text(album.get("name") if isinstance(album, dict) else album, 80),
        "dur": _dur(item.get("duration")), "cover": _img(item.get("image")), "aud": _audio_map(item),
        "year": _text(str(item.get("year") or ""), 4),
    }


def artist(item):
    if not isinstance(item, dict) or not item.get("name"):
        return None
    return {"name": _text(item.get("name"), 60), "cover": _img(item.get("image")), "id": str(item.get("id") or "")[:40]}


def _results(js):
    d = js.get("data") if isinstance(js, dict) else None
    if isinstance(d, dict):
        r = d.get("results")
        if isinstance(r, list):
            return [x for x in r if isinstance(x, dict)]
        s = d.get("songs")
        if isinstance(s, dict) and isinstance(s.get("results"), list):
            return s["results"]
    if isinstance(d, list):
        return [x for x in d if isinstance(x, dict)]
    return []


def pick_url(track, kbps=None):
    """Best audio URL for a track, close to the wanted bitrate (default 160 kbps)."""
    aud = track.get("aud") or {}
    if not aud:
        return None
    want = kbps or config.AUDIO_KBPS
    below = [q for q in aud if q <= want]
    return aud[max(below)] if below else aud[min(aud)]


# ---------- search ----------
async def _songs(q, limit):
    js = await _api("songs", "/search/songs", {"query": q, "limit": limit})
    rows = _results(js)
    if not rows:                                                  # fallback: global search endpoint
        rows = _results(await _api("global", "/search", {"query": q}))
    out, seen = [], set()
    for r in rows:
        s = song(r)
        if s and s["sid"] not in seen:
            seen.add(s["sid"])
            out.append(s)
    return out[:limit]


async def _artists(q, limit):
    rows = _results(await _api("artists", "/search/artists", {"query": q, "limit": limit}))
    return [a for a in (artist(r) for r in rows) if a][:limit]


async def _orig_search_all(q, songs=10, artists=4):
    """One round trip for the Mini App: songs and artists fetched in parallel."""
    q = clean_text(q, 80)
    if len(q) < 2:
        return [], []
    key = (q.lower(), songs, artists)
    hit = _SEARCH.get(key)
    if hit is not None:
        return [dict(x) for x in hit[0]], hit[1]
    s, a = await asyncio.gather(_songs(q, songs), _artists(q, artists) if artists else asyncio.sleep(0, result=[]))
    _SEARCH.put(key, (s, a))
    return [dict(x) for x in s], a


async def search(q, limit=5):
    """Used by /play in groups."""
    return (await search_all(q, limit, 0))[0]


def stash(user_id, items):
    """Full results stay on the server; the browser only gets opaque tokens (nobody can inject a fake track or URL)."""
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


# ---------- playing ----------
async def _orig_resolve(track):
    """Audio link for a track. Search results already carry it, so this is instant in the normal case."""
    url = pick_url(track)
    if url:
        return {"url": url, "preview": False, "cover": track.get("cover")}
    sid = track.get("sid")
    if sid:
        cached = _SONG.get(sid)
        if cached is None:
            js = await _api("song", f"/songs/{quote(sid, safe='')}")
            d = js.get("data") if isinstance(js, dict) else None
            first = d[0] if isinstance(d, list) and d else (d if isinstance(d, dict) else None)
            cached = song(first) if first else None
            if cached:
                _SONG.put(sid, cached)
        if cached and cached["aud"]:
            track["aud"] = cached["aud"]
            return {"url": pick_url(track), "preview": False, "cover": track.get("cover")}
    rows = await search(f'{track.get("title", "")} {track.get("artist", "")}', 3)       # last resort
    for r in rows:
        if r["aud"]:
            track["aud"] = r["aud"]
            return {"url": pick_url(track), "preview": False, "cover": track.get("cover")}
    return None


async def related(track, exclude=()):
    """Songs similar to `track` (used by autoplay). Tries the suggestions endpoint, then the same artist."""
    sid = track.get("sid")
    rows = []
    if sid:
        js = await _api("suggest", f"/songs/{quote(sid, safe='')}/suggestions", {"limit": 10})
        rows = _results(js)
    out = [s for s in (song(r) for r in rows) if s]
    if not out:
        first = (track.get("artist") or "").split(",")[0].strip()
        out = await search(first, 10) if first else []
    return [s for s in out if s["id"] not in exclude and s["id"] != track.get("id") and s["aud"]][:6]


async def lyrics(artist_name, title):
    a = re.split(r"[,&]", artist_name or "")[0].strip()
    t = re.sub(r"\s*[\(\[].*?[\)\]]", "", title or "").strip()
    key = (a.lower(), t.lower())
    hit = _LYR.get(key)
    if hit is not None:
        return hit
    js = await _api("lyrics", f"/{quote(a, safe='')}/{quote(t, safe='')}", base=config.LYRICS_BASE, timeout=8.0)
    txt = js.get("lyrics") if isinstance(js, dict) else ""
    txt = txt.replace("\r", "").strip()[:6000] if isinstance(txt, str) else ""
    _LYR.put(key, txt)
    return txt


async def health():
    async def one(n, path, params, base=None):
        t = time.monotonic()
        try:
            async with _sem:
                r = await client().get((base or config.JIOSAAVN_BASE) + path, params=params, timeout=15.0)
            return n, r.status_code == 200, int((time.monotonic() - t) * 1000)
        except Exception:
            return n, False, None

    return await asyncio.gather(
        one("JioSaavn songs", "/search/songs", {"query": "arijit", "limit": 1}),
        one("JioSaavn artists", "/search/artists", {"query": "arijit", "limit": 1}),
        one("Lyrics", "/Coldplay/Yellow", None, config.LYRICS_BASE))

# ==========================================

import itertools

# Pool of public proxies for YouTube
PROXY_POOL = [
    "http://8.219.97.52:80",
    "http://47.91.65.23:3128",
    "http://103.152.112.162:80",
    "http://47.243.92.199:3128",
    "http://8.219.97.52:8080",
    "http://154.17.23.181:80",
    "http://154.17.23.181:8080",
    "http://47.91.65.23:80",
    "http://103.152.112.162:8080",
    "http://8.219.97.52:3128"
]
_proxy_cycle = itertools.cycle(PROXY_POOL)

def _get_next_proxy():
    # Agar config me proxies hain toh wahan se uthayega
    if getattr(config, "PROXIES", None):
        import random
        return random.choice(config.PROXIES)
    return next(_proxy_cycle)

async def _yt_request(endpoint, body):
    for _ in range(5): # 5 proxy try karega
        proxy = _get_next_proxy()
        try:
            r = await client().post(
                f"https://www.youtube.com/youtubei/v1/{endpoint}?key={INNERTUBE_KEY}&prettyPrint=false",
                json=body, cookies=_get_cookiejar(), timeout=8.0, proxy=proxy
            )
            if r.status_code == 200:
                return r.json()
        except Exception:
            continue
    return None

# YOUTUBE INTEGRATION (Fallback)
# ==========================================
import random
import json
from urllib.parse import quote

INNERTUBE_CLIENTS = [
    {"client": {"clientName": "ANDROID", "clientVersion": "19.09.37", "androidSdkVersion": 30, "hl": "en", "gl": "US"}},
    {"client": {"clientName": "IOS", "clientVersion": "19.09.3", "deviceModel": "iPhone14,3", "hl": "en", "gl": "US"}},
    {"client": {"clientName": "WEB", "clientVersion": "2.20240101.00.00", "hl": "en", "gl": "US"}}
]
INNERTUBE_KEY = "AIzaSyAO_FJ2SlqU8Q4STEHLGCilw_Y9_11qcW8"


import http.cookiejar

def _get_cookiejar():
    if not getattr(config, "COOKIES_FILE", None) or not os.path.exists(config.COOKIES_FILE):
        return None
    cj = http.cookiejar.MozillaCookieJar(config.COOKIES_FILE)
    try:
        cj.load(ignore_discard=True, ignore_expires=True)
        return cj
    except Exception:
        return None

def _get_proxy():
    if getattr(config, "PROXIES", None):
        return random.choice(config.PROXIES)
    return None

async def _yt_search(query, limit=5):
    if not getattr(config, "YOUTUBE_ENABLED", True):
        return []
    proxy = _get_proxy()
    body = {"context": INNERTUBE_CLIENTS[0], "query": query, "params": "EgIQAQ%3D%3D"}
    try:
        r = await client().post(
            f"https://www.youtube.com/youtubei/v1/search?key={INNERTUBE_KEY}",
            json=body, proxy=proxy, timeout=8.0,
            cookies=_get_cookiejar()
        )
        data = r.json()
    except Exception as e:
        return []

    out = []
    def walk(node):
        if isinstance(node, dict):
            if "videoRenderer" in node:
                vr = node["videoRenderer"]
                vid = vr.get("videoId", "")
                if vid:
                    title = "".join(x.get("text", "") for x in vr.get("title", {}).get("runs", []))
                    artist = vr.get("ownerText", {}).get("runs", [{}])[0].get("text", "Unknown")
                    dur = vr.get("lengthText", {}).get("simpleText", "")
                    dur_sec = 0
                    if dur:
                        try:
                            parts = [int(x) for x in dur.split(":")]
                            while len(parts) < 3: parts.insert(0, 0)
                            dur_sec = parts[0]*3600 + parts[1]*60 + parts[2]
                        except: pass
                    
                    thumbs = vr.get("thumbnail", {}).get("thumbnails", [])
                    cover = thumbs[-1]["url"] if thumbs else f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg"
                    
                    out.append({
                        "id": f"yt:{vid}", "sid": vid, "src": "youtube", 
                        "title": _text(title, 120), "artist": _text(artist, 80),
                        "album": "YouTube", "dur": _dur(dur_sec), "cover": _https(cover),
                        "aud": {}, "year": ""
                    })
            for v in node.values(): walk(v)
        elif isinstance(node, list):
            for v in node: walk(v)
            
    walk(data)
    return out[:limit]

async def _yt_resolve(sid):
    if not getattr(config, "YOUTUBE_ENABLED", True):
        return None
    proxy = _get_proxy()
    for c_ctx in INNERTUBE_CLIENTS:
        body = {"context": c_ctx, "videoId": sid, "contentCheckOk": True, "racyCheckOk": True}
        try:
            r = await client().post(
                f"https://www.youtube.com/youtubei/v1/player?key={INNERTUBE_KEY}&prettyPrint=false",
                json=body, proxy=proxy, timeout=8.0,
                cookies=_get_cookiejar()
            )
            data = r.json()
            ps = data.get("playabilityStatus", {})
            if ps.get("status") != "OK":
                continue
            
            sd = data.get("streamingData", {})
            formats = sd.get("adaptiveFormats", []) + sd.get("formats", [])
            
            best = None
            best_score = -1
            for f in formats:
                mt = f.get("mimeType", "")
                u = f.get("url")
                if not u: continue
                
                score = 0
                if "audio/mp4" in mt and "140" in str(f.get("itag")): score = 100
                elif "audio/" in mt: score = 60
                elif "video/mp4" in mt: score = 40
                
                if score > best_score:
                    best_score = score
                    best = u
            
            if best:
                pub_url = f"{config.PUBLIC_ORIGIN}/api/ytstream?url={quote(best, safe='')}"
                return {"url": pub_url, "preview": False, "cover": None}
                
        except Exception:
            continue
    return None

_orig_search = search_all
_orig_resolve = resolve

async def _orig_search_all(q, songs=10, artists=4):
    s, a = await _orig_search(q, songs, artists)
    if len(s) < 2:
        yt_s = await _yt_search(q, songs)
        s.extend(yt_s)
    return s, a

async def search(q, limit=5):
    s, _ = await search_all(q, limit, 0)
    return s

async def _orig_resolve(track):
    if track.get("src") == "youtube":
        r = await _yt_resolve(track.get("sid"))
        if r:
            return r
    return await _orig_resolve(track)




# ==========================================
# UNIFIED SEARCH & RESOLVE (JioSaavn + Shruti + YT)
# ==========================================
from . import shruti

async def search_all(q, songs=10, artists=4):
    # 1. Shruti API (Priority)
    try:
        js = await shruti.api_call("search", {"query": q, "limit": songs})
        if js and "results" in js and js["results"]:
            out = []
            for item in js["results"]:
                out.append({
                    "id": f"shruti:{item.get('id')}", "sid": str(item.get('id')), "src": "shruti",
                    "title": _text(item.get("title", ""), 120), "artist": _text(item.get("artist", ""), 80),
                    "album": _text(item.get("album", ""), 80), "dur": _dur(item.get("duration")),
                    "cover": _https(item.get("cover", "")), "aud": {}, "year": ""
                })
            return out, []
    except Exception:
        pass

    # 2. JioSaavn (Original base logic)
    try:
        s, a = await _orig_search_all(q, songs, artists)
        if s:
            return s, a
    except Exception:
        pass

    return [], []

async def search(q, limit=5):
    s, _ = await search_all(q, limit, 0)
    return s

async def resolve(track):
    src = track.get("src")
    
    if src == "shruti":
        try:
            js = await shruti.api_call(f"download/{track.get('sid')}")
            if js and "url" in js:
                return {"url": js["url"], "preview": False, "cover": track.get("cover")}
        except Exception:
            pass
            
    # JioSaavn base logic
    try:
        return await _orig_resolve(track)
    except Exception:
        pass
        
    return None
