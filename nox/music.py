"""nox/music.py - unified music source resolver.

Sources (order configurable via SOURCE_ORDER):
    1. JioSaavn API   (base)
    2. Shruti API     (secondary, nox/shruti.py)
    3. YouTube        (fallback, InnerTube)

Public API:
    search_all(q, songs=10, artists=4) -> (songs, artists)
    search(q, limit=5)                 -> songs
    resolve(track)                     -> direct audio URL or None
    stash(track) / take(key)           -> short-lived track storage
    song / artist / pick_url           -> JioSaavn helpers
"""

import asyncio
import html
import logging
import os
import re
import time

import httpx

from . import shruti

try:  # config is optional
    from . import config
except Exception:  # pragma: no cover
    config = None

log = logging.getLogger(__name__)

# --------------------------------------------------------------------------
# Settings
# --------------------------------------------------------------------------

JS_BASE = (getattr(config, "JIOSAAVN_API", None) or "https://saavn.dev/api").rstrip("/")
YT_KEY = "AIzaSyAO_FJ2SlqU8Q4STEHLGCilw_Y9_11qcW8"
YT_BASE = "https://www.youtube.com/youtubei/v1"
QUALITY_PREF = ("320kbps", "160kbps", "96kbps", "48kbps", "12kbps")

# Flip this tuple if you want Shruti to be tried before JioSaavn.
SOURCE_ORDER = ("jiosaavn", "shruti", "youtube")

_HTTP_TIMEOUT = httpx.Timeout(15.0, connect=8.0)
_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)


# --------------------------------------------------------------------------
# TTL cache + circuit breaker
# --------------------------------------------------------------------------

class TTL:
    """Tiny in-memory TTL cache."""

    def __init__(self, ttl=300, maxsize=512):
        self.ttl = ttl
        self.maxsize = maxsize
        self._d = {}

    def get(self, key):
        item = self._d.get(key)
        if item is None:
            return None
        exp, val = item
        if exp < time.monotonic():
            self._d.pop(key, None)
            return None
        return val

    def set(self, key, val, ttl=None):
        if len(self._d) >= self.maxsize:
            now = time.monotonic()
            for k in [k for k, (e, _) in self._d.items() if e < now]:
                self._d.pop(k, None)
            while len(self._d) >= self.maxsize:
                self._d.pop(next(iter(self._d)), None)
        self._d[key] = (time.monotonic() + (ttl or self.ttl), val)
        return val

    def pop(self, key, default=None):
        item = self._d.pop(key, None)
        if item is None:
            return default
        exp, val = item
        return val if exp >= time.monotonic() else default


class Breaker:
    """Circuit breaker: opens after `limit` consecutive failures for `cool` seconds."""

    def __init__(self, limit=5, cool=60):
        self.limit = limit
        self.cool = cool
        self.fails = 0
        self.until = 0.0

    def allow(self):
        if self.fails >= self.limit:
            if time.monotonic() >= self.until:
                self.fails = self.limit - 1  # half-open: allow one probe
                return True
            return False
        return True

    def ok(self):
        self.fails = 0
        self.until = 0.0

    def fail(self):
        self.fails += 1
        if self.fails >= self.limit:
            self.until = time.monotonic() + self.cool


_cache = TTL(ttl=300, maxsize=512)
_stash = TTL(ttl=3600, maxsize=2048)
_js_breaker = Breaker(limit=5, cool=60)
_yt_breaker = Breaker(limit=5, cool=60)

_client = None


def _http():
    global _client
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient(
            timeout=_HTTP_TIMEOUT,
            follow_redirects=True,
            headers={"User-Agent": _UA},
        )
    return _client


# --------------------------------------------------------------------------
# JioSaavn base helpers
# --------------------------------------------------------------------------

async def _api(path, params=None):
    """GET JioSaavn API, returns parsed JSON dict or None."""
    if not _js_breaker.allow():
        return None
    key = ("js", path, tuple(sorted((params or {}).items())))
    hit = _cache.get(key)
    if hit is not None:
        return hit
    try:
        r = await _http().get(f"{JS_BASE}/{path.lstrip('/')}", params=params)
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        _js_breaker.fail()
        log.warning("JioSaavn %s failed: %s", path, e)
        return None
    _js_breaker.ok()
    return _cache.set(key, data)


def _text(s):
    if not s:
        return ""
    s = html.unescape(str(s))
    s = re.sub(r"<[^>]+>", "", s)
    return re.sub(r"\s+", " ", s).strip()


def _https(u):
    if not u:
        return ""
    u = str(u).strip()
    return "https://" + u[7:] if u.startswith("http://") else u


def _img(images):
    """Pick the best image URL from a list of {quality,url} or a plain string."""
    if not images:
        return ""
    if isinstance(images, str):
        url = images
    else:
        try:
            last = images[-1]
            url = last.get("url", "") if isinstance(last, dict) else str(last)
        except Exception:
            url = ""
    return _https(url.replace("150x150", "500x500"))


def _artist_names(item):
    arts = item.get("artists") or {}
    people = []
    if isinstance(arts, dict):
        people = arts.get("primary") or arts.get("all") or []
    elif isinstance(arts, list):
        people = arts
    names = [_text(p.get("name")) for p in people if isinstance(p, dict) and p.get("name")]
    if not names and item.get("primaryArtists"):
        names = [_text(item["primaryArtists"])]
    return ", ".join(dict.fromkeys(names))


def _audio_map(item):
    """Return {quality: https_url} from a JioSaavn song payload."""
    out = {}
    for d in item.get("downloadUrl") or []:
        if isinstance(d, dict) and d.get("url"):
            out[str(d.get("quality") or d.get("bitrate") or "")] = _https(d["url"])
    return out


def _dur(x):
    try:
        return int(float(x))
    except Exception:
        return 0


def song(item):
    """Normalise a JioSaavn song payload to the standard track dict."""
    sid = str(item.get("id", ""))
    return {
        "id": f"jiosaavn:{sid}",
        "sid": sid,
        "src": "jiosaavn",
        "title": _text(item.get("name") or item.get("title")),
        "artist": _artist_names(item),
        "album": _text((item.get("album") or {}).get("name")) if isinstance(item.get("album"), dict) else "",
        "dur": _dur(item.get("duration")),
        "img": _img(item.get("image")),
        "aud": _audio_map(item),
    }


def artist(item):
    aid = str(item.get("id", ""))
    return {
        "id": f"artist:{aid}",
        "aid": aid,
        "name": _text(item.get("name")),
        "img": _img(item.get("image")),
    }


def _results(data):
    """Extract the results list from a JioSaavn response."""
    if not isinstance(data, dict):
        return []
    d = data.get("data")
    if isinstance(d, dict):
        r = d.get("results")
        return r if isinstance(r, list) else []
    if isinstance(d, list):
        return d
    return []


def pick_url(aud, prefer=None):
    """Choose the best URL from an {quality: url} map."""
    if not aud:
        return None
    order = ((prefer,) if prefer else ()) + QUALITY_PREF
    for q in order:
        if aud.get(q):
            return aud[q]
    return next((u for u in aud.values() if u), None)


async def _songs(q, n=10):
    data = await _api("search/songs", {"query": q, "limit": n})
    return [t for t in (song(i) for i in _results(data)[:n]) if t["sid"] and t["title"]]


async def _artists(q, n=4):
    if n <= 0:
        return []
    data = await _api("search/artists", {"query": q, "limit": n})
    return [a for a in (artist(i) for i in _results(data)[:n]) if a["aid"] and a["name"]]


async def _js_search_all(q, songs=10, artists=4):
    s, a = await asyncio.gather(_songs(q, songs), _artists(q, artists), return_exceptions=True)
    if isinstance(s, Exception):
        log.warning("JioSaavn songs error: %s", s)
        s = []
    if isinstance(a, Exception):
        log.warning("JioSaavn artists error: %s", a)
        a = []
    return s, a


async def _js_resolve(track):
    url = pick_url(track.get("aud"))
    if url:
        return url
    sid = track.get("sid")
    if not sid:
        return None
    data = await _api(f"songs/{sid}")
    items = _results(data) if isinstance(data, dict) and isinstance(data.get("data"), dict) else (data or {}).get("data") or []
    if isinstance(items, list) and items:
        t = song(items[0])
        track["aud"] = t["aud"]
        return pick_url(t["aud"])
    return None


def stash(track):
    """Store a track for later lookup (e.g. from callback data). Returns the key."""
    key = str(track.get("id") or f"{track.get('src')}:{track.get('sid')}")
    _stash.set(key, track)
    return key


def take(key):
    """Fetch a stashed track (kept for repeat use until TTL expires)."""
    return _stash.get(str(key))


# --------------------------------------------------------------------------
# Shruti integration
# --------------------------------------------------------------------------

def _first(d, *keys):
    for k in keys:
        v = d.get(k)
        if v not in (None, "", [], {}):
            return v
    return None


def _shruti_list(data):
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for k in ("results", "data", "songs", "items", "tracks"):
            v = data.get(k)
            if isinstance(v, list):
                return v
            if isinstance(v, dict):
                for kk in ("results", "songs", "items", "tracks"):
                    if isinstance(v.get(kk), list):
                        return v[kk]
    return []


def _shruti_track(item):
    if not isinstance(item, dict):
        return None
    sid = _first(item, "id", "sid", "song_id", "track_id", "videoId")
    if sid is None:
        return None
    sid = str(sid)
    art = _first(item, "artist", "artists", "singer", "subtitle", "channel") or ""
    if isinstance(art, list):
        art = ", ".join(_text(a.get("name") if isinstance(a, dict) else a) for a in art)
    img = _first(item, "img", "image", "thumbnail", "cover", "thumb") or ""
    if isinstance(img, list):
        img = _img(img)
    return {
        "id": f"shruti:{sid}",
        "sid": sid,
        "src": "shruti",
        "title": _text(_first(item, "title", "name", "song") or ""),
        "artist": _text(art),
        "album": _text(_first(item, "album") if isinstance(_first(item, "album"), str) else ""),
        "dur": _dur(_first(item, "duration", "dur", "length") or 0),
        "img": _https(img),
        "aud": {},
    }


async def _shruti_search(q, n):
    data = await shruti.api_call("search", {"query": q, "limit": n})
    out = []
    for item in _shruti_list(data)[:n]:
        t = _shruti_track(item)
        if t and t["title"]:
            out.append(t)
    return out


async def _shruti_resolve(sid):
    data = await shruti.api_call(f"download/{sid}")
    if isinstance(data, str):
        return _https(data) if data.startswith("http") else None
    if isinstance(data, dict):
        url = _first(data, "url", "download_url", "downloadUrl", "link", "stream", "stream_url", "audio")
        if not url and isinstance(data.get("data"), (dict, str)):
            inner = data["data"]
            if isinstance(inner, str):
                url = inner
            else:
                url = _first(inner, "url", "download_url", "downloadUrl", "link", "stream", "stream_url", "audio")
        if isinstance(url, str) and url.startswith("http"):
            return _https(url)
    return None


# --------------------------------------------------------------------------
# YouTube (InnerTube)
# --------------------------------------------------------------------------

_yt_cookie_cache = {"v": None, "done": False}


def _yt_cookie_header():
    """Cookie header from config (YT_COOKIES / YOUTUBE_COOKIES): a raw string or a cookies.txt path."""
    if _yt_cookie_cache["done"]:
        return _yt_cookie_cache["v"]
    _yt_cookie_cache["done"] = True
    raw = None
    if config is not None:
        raw = getattr(config, "YT_COOKIES", None) or getattr(config, "YOUTUBE_COOKIES", None)
    raw = raw or os.environ.get("YT_COOKIES")
    if not raw:
        return None
    raw = str(raw).strip()
    try:
        if os.path.isfile(raw):
            pairs = []
            with open(raw, "r", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    line = line.strip()
                    if line.startswith("#HttpOnly_"):
                        line = line[len("#HttpOnly_"):]
                    if not line or line.startswith("#"):
                        continue
                    parts = line.split("\t")
                    if len(parts) >= 7 and "youtube" in parts[0]:
                        pairs.append(f"{parts[5]}={parts[6]}")
            raw = "; ".join(pairs)
    except Exception as e:
        log.warning("YouTube cookie file read failed: %s", e)
        raw = None
    _yt_cookie_cache["v"] = raw or None
    return _yt_cookie_cache["v"]


def _yt_headers(ua=_UA):
    h = {
        "User-Agent": ua,
        "Content-Type": "application/json",
        "Origin": "https://www.youtube.com",
        "X-YouTube-Client-Name": "1",
    }
    ck = _yt_cookie_header()
    if ck:
        h["Cookie"] = ck
    return h


async def _yt_post(endpoint, body, ua=_UA):
    if not _yt_breaker.allow():
        return None
    try:
        r = await _http().post(
            f"{YT_BASE}/{endpoint}",
            params={"key": YT_KEY, "prettyPrint": "false"},
            json=body,
            headers=_yt_headers(ua),
        )
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        _yt_breaker.fail()
        log.warning("YouTube %s failed: %s", endpoint, e)
        return None
    _yt_breaker.ok()
    return data


def _yt_seconds(txt):
    try:
        parts = [int(p) for p in str(txt).split(":")]
    except Exception:
        return 0
    sec = 0
    for p in parts:
        sec = sec * 60 + p
    return sec


def _yt_walk(node, out):
    """Collect every videoRenderer in the response tree."""
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


async def _yt_search(q, n=10):
    body = {
        "context": {"client": {"clientName": "WEB", "clientVersion": "2.20240726.00.00", "hl": "en", "gl": "US"}},
        "query": q,
        "params": "EgIQAQ%3D%3D",  # videos only
    }
    data = await _yt_post("search", body)
    if not data:
        return []
    renderers = []
    _yt_walk(data, renderers)
    out, seen = [], set()
    for vr in renderers:
        vid = vr.get("videoId")
        if not vid or vid in seen or not re.fullmatch(r"[\w-]{11}", vid):
            continue
        seen.add(vid)
        try:
            title = _text("".join(r.get("text", "") for r in vr["title"]["runs"]))
        except Exception:
            continue
        try:
            chan = _text(vr["ownerText"]["runs"][0]["text"])
        except Exception:
            chan = ""
        try:
            thumb = vr["thumbnail"]["thumbnails"][-1]["url"].split("?")[0]
        except Exception:
            thumb = f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg"
        dur = _yt_seconds((vr.get("lengthText") or {}).get("simpleText", ""))
        if dur == 0:  # live streams / shorts without length
            continue
        out.append({
            "id": f"yt:{vid}",
            "sid": vid,
            "src": "youtube",
            "title": title,
            "artist": chan,
            "album": "",
            "dur": dur,
            "img": _https(thumb),
            "aud": {},
        })
        if len(out) >= n:
            break
    return out


_YT_CLIENTS = (
    {
        "ctx": {
            "clientName": "ANDROID",
            "clientVersion": "19.09.37",
            "androidSdkVersion": 30,
            "hl": "en",
            "gl": "US",
        },
        "ua": "com.google.android.youtube/19.09.37 (Linux; U; Android 11) gzip",
    },
    {
        "ctx": {
            "clientName": "IOS",
            "clientVersion": "19.09.3",
            "deviceModel": "iPhone16,2",
            "hl": "en",
            "gl": "US",
        },
        "ua": "com.google.ios.youtube/19.09.3 (iPhone16,2; U; CPU iOS 17_5 like Mac OS X)",
    },
)


def _yt_best_audio(streaming):
    fmts = streaming.get("adaptiveFormats") or []
    audio = [
        f for f in fmts
        if str(f.get("mimeType", "")).startswith("audio/") and f.get("url")
    ]
    if audio:
        # Prefer m4a (audio/mp4) for Telegram, then highest bitrate.
        audio.sort(key=lambda f: (str(f.get("mimeType", "")).startswith("audio/mp4"), f.get("bitrate", 0)), reverse=True)
        return audio[0]["url"]
    muxed = [f for f in (streaming.get("formats") or []) if f.get("url")]
    if muxed:
        muxed.sort(key=lambda f: f.get("bitrate", 0), reverse=True)
        return muxed[0]["url"]
    return None


async def _yt_resolve(vid):
    if not vid or not re.fullmatch(r"[\w-]{11}", str(vid)):
        return None
    for c in _YT_CLIENTS:
        body = {
            "videoId": vid,
            "context": {"client": c["ctx"]},
            "contentCheckOk": True,
            "racyCheckOk": True,
        }
        data = await _yt_post("player", body, ua=c["ua"])
        if not data:
            continue
        status = (data.get("playabilityStatus") or {}).get("status")
        if status not in (None, "OK"):
            log.info("YouTube %s playability: %s", vid, status)
            continue
        url = _yt_best_audio(data.get("streamingData") or {})
        if url:
            return url
    return None


# --------------------------------------------------------------------------
# Unified resolver
# --------------------------------------------------------------------------

async def search_all(q, songs=10, artists=4):
    """Search all sources in SOURCE_ORDER. Returns (songs, artists)."""
    q = (q or "").strip()
    if not q:
        return [], []
    songs = max(1, int(songs or 1))
    artists = max(0, int(artists or 0))

    for name in SOURCE_ORDER:
        try:
            if name == "jiosaavn":
                s, a = await _js_search_all(q, songs, artists)
                if s:
                    return s, a
            elif name == "shruti":
                s = await _shruti_search(q, songs)
                if s:
                    return s, []
            elif name == "youtube":
                s = await _yt_search(q, songs)
                if s:
                    return s, []
        except Exception as e:
            log.warning("search source %s failed: %s", name, e)
    return [], []


async def search(q, limit=5):
    s, _ = await search_all(q, limit, 0)
    return s


async def resolve(track):
    """Return a direct audio URL for a track dict, or None."""
    if not isinstance(track, dict):
        return None
    src = track.get("src")
    url = None
    try:
        if src == "shruti":
            url = await _shruti_resolve(track.get("sid"))
        elif src == "youtube":
            url = await _yt_resolve(track.get("sid"))
        else:
            url = await _js_resolve(track)
    except Exception as e:
        log.warning("resolve via %s failed: %s", src, e)

    if url:
        return url

    # Last resort: find the same song on YouTube.
    if src != "youtube":
        try:
            query = " ".join(x for x in (track.get("title"), track.get("artist")) if x).strip()
            if query:
                for t in await _yt_search(query, 3):
                    u = await _yt_resolve(t["sid"])
                    if u:
                        return u
        except Exception as e:
            log.warning("YouTube fallback resolve failed: %s", e)
    return None
