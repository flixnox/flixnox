"""Music source: JioSaavn API (songs, artists, direct audio links) + lyrics.
Everything runs server-side with short timeouts, caching and a circuit breaker, so the room never waits on a slow API."""
import asyncio
import html
import logging
import os
import re
import secrets
import time
from urllib.parse import quote

import httpx

from . import config, shruti, stream
from .security import clean_text, safe_https_url

log = logging.getLogger("music")


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
_YT = TTL(1500, 400)          # video id -> direct googlevideo URL
_sem = asyncio.Semaphore(16)
_client = None
_ytclient = None


def client():
    global _client
    if _client is None:
        _client = httpx.AsyncClient(
            timeout=httpx.Timeout(7.0, connect=3.5), follow_redirects=True,
            headers={"User-Agent": "Mozilla/5.0 SonicNox/2.0", "Accept": "application/json"},
            limits=httpx.Limits(max_connections=40, max_keepalive_connections=20, keepalive_expiry=60))
    return _client


def yt_client():
    """YouTube lookups use their own client so an optional YOUTUBE_PROXY applies to them only."""
    global _ytclient
    if not config.YOUTUBE_PROXY:
        return client()
    if _ytclient is None:
        _ytclient = httpx.AsyncClient(timeout=httpx.Timeout(10.0, connect=5.0), follow_redirects=True, proxy=config.YOUTUBE_PROXY,
                                      limits=httpx.Limits(max_connections=20, max_keepalive_connections=10, keepalive_expiry=60))
    return _ytclient


async def close():
    for c in (_client, _ytclient):
        if c is not None:
            await c.aclose()


def clear_caches():
    for c in (_SEARCH, _RESULTS, _SONG, _LYR, _YT):
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
        "id": f"js:{sid}", "sid": str(sid)[:40], "src": "saavn", "prov": "saavn", "title": title, "artist": _artist_names(item),
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


async def search_all(q, songs=10, artists=4):
    """One round trip for the Mini App: songs and artists fetched in parallel."""
    q = clean_text(q, 80)
    if len(q) < 2:
        return [], []
    key = (q.lower(), songs, artists)
    hit = _SEARCH.get(key)
    if hit is not None:
        return [dict(x) for x in hit[0]], hit[1]
    s, a = await asyncio.gather(_songs(q, songs), _artists(q, artists) if artists else asyncio.sleep(0, result=[]))
    if not s:
        s = await _fallback_songs(q, songs)
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
async def resolve(track):
    """{"url", "preview", "cover"} for a track, or None. Dispatches on track["prov"] (saavn / shruti / yt); a failed
    JioSaavn or Shruti track is retried on YouTube. Never raises."""
    prov = track.get("prov") or "saavn"
    try:
        if prov == "yt":
            return await _resolve_yt(track)
        r = await (_resolve_shruti(track) if prov == "shruti" else _resolve_saavn(track))
        if r:
            return r
        return await _resolve_yt_by_search(track) if config.YOUTUBE_ENABLED else None
    except Exception:
        log.exception("resolve failed for %s", track.get("id"))
        return None


async def _resolve_saavn(track):
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
    rows = await _songs(f'{track.get("title", "")} {track.get("artist", "")}'.strip(), 3)       # last resort
    for r in rows:
        if r["aud"]:
            track["aud"] = r["aud"]
            return {"url": pick_url(track), "preview": False, "cover": track.get("cover")}
    return None


async def related(track, exclude=()):
    """Songs similar to `track` (used by autoplay). Tries the suggestions endpoint, then the same artist."""
    sid = track.get("sid")
    rows = []
    if sid and (track.get("prov") or "saavn") == "saavn":
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

    async def yt():
        t = time.monotonic()
        try:
            return "YouTube", bool(await _yt_search("arijit", 1)), int((time.monotonic() - t) * 1000)
        except Exception:
            return "YouTube", False, None

    return await asyncio.gather(
        *([yt()] if config.YOUTUBE_ENABLED else []),
        one("JioSaavn songs", "/search/songs", {"query": "arijit", "limit": 1}),
        one("JioSaavn artists", "/search/artists", {"query": "arijit", "limit": 1}),
        one("Lyrics", "/Coldplay/Yellow", None, config.LYRICS_BASE))


# =====================================================================================================
# Extra sources, always behind JioSaavn:  Shruti API (needs SHRUTI_API_KEY)  ->  YouTube (InnerTube)
# Every track keeps the same shape as a JioSaavn track; track["prov"] says where it came from.
# =====================================================================================================
_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
_YT_BASE = "https://www.youtube.com/youtubei/v1"
_VID = re.compile(r"^[\w-]{11}$")


async def _fallback_songs(q, limit):
    if config.SHRUTI_API_KEY:
        rows = await _shruti_search(q, limit)
        if rows:
            return rows
    return await _yt_search(q, limit) if config.YOUTUBE_ENABLED else []


async def search_video(q, limit=1):
    """/vplay: search YouTube directly (skips JioSaavn)."""
    q = clean_text(q, 80)
    return await _yt_search(q, limit) if len(q) >= 2 and config.YOUTUBE_ENABLED else []


# ---------- Shruti ----------
def _first(d, *keys):
    for k in keys:
        v = d.get(k)
        if v not in (None, "", [], {}):
            return v
    return None


def _shruti_rows(js):
    if isinstance(js, list):
        return [x for x in js if isinstance(x, dict)]
    if isinstance(js, dict):
        for k in ("results", "data", "songs", "items", "tracks"):
            v = js.get(k)
            if isinstance(v, list):
                return [x for x in v if isinstance(x, dict)]
            if isinstance(v, dict):
                for kk in ("results", "songs", "items", "tracks"):
                    if isinstance(v.get(kk), list):
                        return [x for x in v[kk] if isinstance(x, dict)]
    return []


def _shruti_track(item):
    sid = _first(item, "id", "sid", "song_id", "track_id", "videoId")
    title = _text(str(_first(item, "title", "name", "song") or ""), 120)
    if not sid or not title:
        return None
    art = _first(item, "artist", "artists", "singer", "channel") or ""
    if isinstance(art, list):
        art = ", ".join(str(a.get("name") if isinstance(a, dict) else a) for a in art[:3])
    return {"id": f"sh:{sid}", "sid": str(sid)[:40], "src": "shruti", "prov": "shruti", "title": title,
            "artist": _text(str(art), 80) or "Unknown artist", "album": "", "dur": _dur(_first(item, "duration", "dur", "length")),
            "cover": _img(_first(item, "cover", "image", "thumbnail", "thumb", "img")), "aud": {}, "year": ""}


async def _shruti_call(endpoint, params=None):
    if not config.SHRUTI_API_KEY or not BREAKER.ok("shruti"):
        return None
    try:
        js = await asyncio.wait_for(shruti.api_call(endpoint, params), 20)
    except Exception:
        js = None
    BREAKER.good("shruti") if js else BREAKER.fail("shruti")
    return js


async def _shruti_search(q, limit):
    js = await _shruti_call("search", {"query": q, "limit": limit})
    return [t for t in (_shruti_track(x) for x in _shruti_rows(js)[:limit]) if t]


async def _resolve_shruti(track):
    js = await _shruti_call(f"download/{quote(str(track.get('sid') or ''), safe='')}")
    url = js if isinstance(js, str) else None
    if isinstance(js, dict):
        inner = js.get("data") if isinstance(js.get("data"), dict) else js
        url = _first(inner, "url", "download_url", "downloadUrl", "link", "stream", "stream_url", "audio")
    url = _https(url) if isinstance(url, str) else None
    if not url:
        return None
    if stream.allowed(url):                       # a YouTube link inside a Shruti answer still has to go through our proxy
        url = stream.proxy_url(url)
    return {"url": url, "preview": False, "cover": track.get("cover")}


# ---------- YouTube ----------
_ck = {"mtime": None, "v": None}


def _yt_cookie_header():
    """Cookie header from the cookies.txt that config wrote from COOKIES_B64. Only ever sent to youtube.com."""
    try:
        mt = os.path.getmtime(config.COOKIES_FILE)
    except OSError:
        return None
    if _ck["mtime"] != mt:
        pairs = []
        try:
            with open(config.COOKIES_FILE, encoding="utf-8", errors="ignore") as f:
                for line in f:
                    line = line.strip()
                    if line.startswith("#HttpOnly_"):
                        line = line[len("#HttpOnly_"):]
                    if not line or line.startswith("#"):
                        continue
                    parts = line.split("\t")
                    if len(parts) >= 7 and "youtube.com" in parts[0]:
                        pairs.append(f"{parts[5]}={parts[6]}")
        except OSError:
            pairs = []
        _ck.update(mtime=mt, v="; ".join(pairs) or None)
    return _ck["v"]


async def _yt_post(endpoint, body, ua=_UA):
    if not BREAKER.ok("yt"):
        return None
    headers = {"User-Agent": ua, "Content-Type": "application/json", "Origin": "https://www.youtube.com"}
    ck = _yt_cookie_header()
    if ck:
        headers["Cookie"] = ck
    try:
        async with _sem:
            r = await yt_client().post(f"{_YT_BASE}/{endpoint}", params={"key": config.YT_INNERTUBE_KEY, "prettyPrint": "false"},
                                       json=body, headers=headers, timeout=10.0)
        if r.status_code != 200 or len(r.content) > 3_000_000:
            raise ValueError(r.status_code)
        js = r.json()
        BREAKER.good("yt")
        return js
    except Exception as e:
        BREAKER.fail("yt")
        log.warning("YouTube %s failed: %s", endpoint, e)
        return None


def _yt_seconds(txt):
    try:
        sec = 0
        for p in str(txt).split(":"):
            sec = sec * 60 + int(p)
        return sec
    except ValueError:
        return 0


def _yt_walk(node, out):
    if isinstance(node, dict):
        vr = node.get("videoRenderer")
        if isinstance(vr, dict):
            out.append(vr)
        for v in node.values():
            if isinstance(v, (dict, list)):
                _yt_walk(v, out)
    elif isinstance(node, list):
        for v in node:
            _yt_walk(v, out)


def _yt_track(vr):
    vid = vr.get("videoId")
    if not isinstance(vid, str) or not _VID.match(vid):
        return None
    try:
        title = _text("".join(r.get("text", "") for r in vr["title"]["runs"]), 120)
    except (KeyError, TypeError, AttributeError):
        return None
    dur = _yt_seconds((vr.get("lengthText") or {}).get("simpleText", ""))
    if not title or not dur:                                    # live streams have no length
        return None
    try:
        chan = _text(vr["ownerText"]["runs"][0]["text"], 80)
    except (KeyError, IndexError, TypeError):
        chan = ""
    chan = re.sub(r"\s*-\s*Topic$", "", chan)
    return {"id": f"yt:{vid}", "sid": vid, "src": "yt", "prov": "yt", "title": title, "artist": chan or "YouTube",
            "album": "", "dur": _dur(dur), "cover": f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg", "aud": {}, "year": ""}


async def _yt_search(q, n=10):
    key = ("yt", q.lower(), n)
    hit = _SEARCH.get(key)
    if hit is not None:
        return [dict(x) for x in hit[0]]
    body = {"context": {"client": {"clientName": "WEB", "clientVersion": "2.20240726.00.00", "hl": "en", "gl": "US"}},
            "query": q, "params": "EgIQAQ%3D%3D"}                # videos only
    js = await _yt_post("search", body)
    rows, out, seen = [], [], set()
    _yt_walk(js or {}, rows)
    for vr in rows:
        t = _yt_track(vr)
        if t and t["sid"] not in seen:
            seen.add(t["sid"])
            out.append(t)
        if len(out) >= n:
            break
    if out:
        _SEARCH.put(key, (out, []))
    return [dict(x) for x in out]


_YT_CLIENTS = (
    ({"clientName": "ANDROID", "clientVersion": "19.09.37", "androidSdkVersion": 30, "hl": "en", "gl": "US"},
     "com.google.android.youtube/19.09.37 (Linux; U; Android 11) gzip"),
    ({"clientName": "IOS", "clientVersion": "19.09.3", "deviceModel": "iPhone16,2", "hl": "en", "gl": "US"},
     "com.google.ios.youtube/19.09.3 (iPhone16,2; U; CPU iOS 17_5 like Mac OS X)"),
)


def _yt_best_audio(streaming):
    want = config.AUDIO_KBPS * 1000
    audio = [f for f in (streaming.get("adaptiveFormats") or [])
             if str(f.get("mimeType", "")).startswith("audio/") and isinstance(f.get("url"), str)]
    if audio:      # m4a first (Telegram plays it natively), then the bitrate closest to AUDIO_KBPS
        audio.sort(key=lambda f: (str(f.get("mimeType", "")).startswith("audio/mp4"), -abs(int(f.get("bitrate") or 0) - want)), reverse=True)
        return audio[0]["url"]
    muxed = [f for f in (streaming.get("formats") or []) if isinstance(f.get("url"), str)]
    return max(muxed, key=lambda f: int(f.get("bitrate") or 0))["url"] if muxed else None


async def _yt_resolve(vid):
    """Direct googlevideo audio URL for a video id (only usable from this server's IP, hence the proxy)."""
    if not isinstance(vid, str) or not _VID.match(vid):
        return None
    cached = _YT.get(vid)
    if cached:
        return cached
    for ctx, ua in _YT_CLIENTS:
        js = await _yt_post("player", {"videoId": vid, "context": {"client": ctx}, "contentCheckOk": True, "racyCheckOk": True}, ua=ua)
        if not js:
            continue
        status = (js.get("playabilityStatus") or {}).get("status")
        if status not in (None, "OK"):
            log.info("YouTube %s not playable: %s", vid, status)
            continue
        url = _yt_best_audio(js.get("streamingData") or {})
        if url and stream.allowed(url):
            _YT.put(vid, url)
            return url
    return None


async def _resolve_yt(track):
    url = await _yt_resolve(track.get("sid"))
    return {"url": stream.proxy_url(url), "preview": False, "cover": track.get("cover")} if url else None


async def _resolve_yt_by_search(track):
    """JioSaavn/Shruti could not play this song: find the same song on YouTube and remember it on the track."""
    q = f'{track.get("title", "")} {track.get("artist", "")}'.strip()
    if len(q) < 2:
        return None
    rows = await _yt_search(q, 4)
    want = track.get("dur")
    if want:
        rows = [r for r in rows if r.get("dur") and abs(r["dur"] - want) <= 20] or rows
    for r in rows[:2]:
        res = await _resolve_yt(r)
        if res:
            track["prov"], track["sid"] = "yt", r["sid"]
            track["cover"] = track.get("cover") or r["cover"]
            return res
    return None


# ---------- downloads for chat (DM) ----------
async def _yt_download(url, limit):
    headers = {"User-Agent": stream.ANDROID_UA, "Accept": "*/*", "Accept-Encoding": "identity", "Referer": "https://www.youtube.com/"}
    buf, start, step = bytearray(), 0, 4 * 1024 * 1024
    while True:
        r = await yt_client().get(url, headers={**headers, "Range": f"bytes={start}-{start + step - 1}"}, timeout=40.0)
        if r.status_code == 200:                                 # server ignored Range and sent everything
            return r.content if 1000 < len(r.content) < limit else None
        if r.status_code != 206:
            return None
        buf += r.content
        if len(buf) >= limit:
            return None
        m = re.match(r"bytes (\d+)-(\d+)/(\d+|\*)", r.headers.get("content-range", ""))
        if not m:
            break
        start = int(m.group(2)) + 1
        if (m.group(3) != "*" and start >= int(m.group(3))) or (m.group(3) == "*" and len(r.content) < step):
            break
    return bytes(buf) if len(buf) > 1000 else None


async def fetch_audio(url, limit=45_000_000):
    """Download a song so it can be sent as a Telegram audio file. Our own YouTube proxy links are fetched directly."""
    try:
        inner = stream.unwrap(url)
        if inner:
            return await _yt_download(inner, limit)
        r = await client().get(url, timeout=40)
        if r.status_code == 200 and 1000 < len(r.content) < limit:
            return r.content
    except Exception as e:
        log.debug("audio fetch failed: %s", e)
    return None
