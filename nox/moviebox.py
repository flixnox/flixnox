"""MovieBox: search, detail, episodes via curiousapis.name.ng/moviebox.

All API calls go through a shared semaphore, TTL caches, and a circuit breaker —
same pattern as music.py so the bot never hangs waiting on a slow upstream."""
import asyncio
import html
import logging
import re
import secrets
import time

import httpx

log = logging.getLogger("moviebox")

from . import config
from .security import clean_text, safe_https_url


# ---------- re-use music.py infra classes (copy-safe, independent instances) ----------
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
    """4 failures within 30 s → skip that endpoint for 30 s."""

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

_SEARCH  = TTL(300, 400)   # 5 min  – search results
_DETAIL  = TTL(900, 200)   # 15 min – movie detail
_EPISODES = TTL(900, 200)  # 15 min – episode list
_STASH   = TTL(900, 2000)  # secure download tokens
_sem     = asyncio.Semaphore(8)
_client  = None


def client():
    global _client
    if _client is None:
        _client = httpx.AsyncClient(
            timeout=httpx.Timeout(9.0, connect=4.0),
            follow_redirects=True,
            headers={
                "User-Agent": "Mozilla/5.0 SonicNox/2.0",
                "Accept":     "application/json",
            },
            limits=httpx.Limits(
                max_connections=20,
                max_keepalive_connections=10,
                keepalive_expiry=60,
            ),
        )
    return _client


async def close():
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None


# ---------- raw API call ----------
async def _api(name, path, params=None, timeout=9.0):
    """GET {MOVIEBOX_BASE}{path}?{params}. Returns parsed JSON or None."""
    if not BREAKER.ok(name):
        return None
    url = config.MOVIEBOX_BASE + path
    try:
        async with _sem:
            r = await client().get(url, params=params, timeout=timeout)
        log.debug("MB %s %s params=%s → %s len=%d", name, url, params, r.status_code, len(r.content))
        if r.status_code != 200 or len(r.content) > 4_000_000:
            raise ValueError(r.status_code)
        js = r.json()
        BREAKER.good(name)
        return js
    except Exception as e:
        log.debug("MB %s %s → error %s", name, url, e)
        BREAKER.fail(name)
        return None


# ---------- normalise helpers ----------
def _txt(v, n=200):
    return clean_text(html.unescape(v), n) if isinstance(v, str) else ""


def _https(u):
    if isinstance(u, str) and u.startswith("http://"):
        u = "https://" + u[7:]
    return safe_https_url(u)


def _poster(item):
    """Try several field names the API might use for the cover image."""
    for k in ("poster", "banner", "cover", "thumbnail", "image", "backdrop"):
        v = item.get(k)
        if isinstance(v, str) and v:
            return _https(v)
        if isinstance(v, list) and v:
            return _https(v[0] if isinstance(v[0], str) else v[0].get("url", ""))
    return None


def _safe_id(v):
    if isinstance(v, (int, float)):
        return str(int(v))
    if isinstance(v, str):
        return re.sub(r"[^a-zA-Z0-9_\-]", "", v)[:60]
    return ""


# ---------- normalise a search hit into a small safe dict ----------
def _movie(item):
    if not isinstance(item, dict):
        return None
    mid   = _safe_id(item.get("id") or item.get("_id") or item.get("movie_id") or item.get("tmdb_id") or "")
    title = _txt(item.get("title") or item.get("name") or item.get("movie_name") or "", 120)
    if not mid or not title:
        return None
    year    = _txt(str(item.get("year") or item.get("release_year") or item.get("releaseYear") or ""), 4)
    genres  = item.get("genres") or item.get("genre") or []
    genre   = _txt(genres[0] if isinstance(genres, list) and genres else (genres if isinstance(genres, str) else ""), 30)
    mtype   = _txt(item.get("type") or item.get("media_type") or "movie", 10).lower()
    poster  = _poster(item)
    rating  = item.get("rating") or item.get("imdb_rating") or item.get("vote_average")
    try:
        rating = f"{float(rating):.1f}"
    except (TypeError, ValueError):
        rating = ""
    return {
        "id": mid, "title": title, "year": year,
        "genre": genre, "type": mtype,
        "poster": poster, "rating": rating,
    }


# ---------- normalise a detail response ----------
def _detail(item):
    base = _movie(item)
    if not base:
        return None
    desc     = _txt(item.get("description") or item.get("overview") or item.get("plot") or item.get("synopsis") or "", 800)
    duration = _txt(str(item.get("duration") or item.get("runtime") or ""), 10)
    language = _txt(item.get("language") or item.get("original_language") or "", 30)
    cast_raw = item.get("cast") or item.get("actors") or item.get("stars") or []
    if isinstance(cast_raw, list):
        cast = ", ".join(_txt(c.get("name") if isinstance(c, dict) else c, 30) for c in cast_raw[:5] if c)
    else:
        cast = _txt(cast_raw, 120)
    streams = item.get("streams") or item.get("sources") or item.get("links") or []
    seasons = item.get("seasons") or []
    episodes_raw = item.get("episodes") or []
    base.update({
        "desc": desc, "duration": duration, "language": language, "cast": cast,
        "streams": streams if isinstance(streams, list) else [],
        "seasons":  seasons  if isinstance(seasons,  list) else [],
        "episodes": episodes_raw if isinstance(episodes_raw, list) else [],
    })
    return base


# ---------- normalise an episode ----------
def _ep(item):
    if not isinstance(item, dict):
        return None
    eid   = _safe_id(item.get("id") or item.get("episode_id") or "")
    title = _txt(item.get("title") or item.get("name") or item.get("episode_title") or "Episode", 80)
    ep_no = item.get("episode") or item.get("episode_number") or item.get("ep") or ""
    s_no  = item.get("season")  or item.get("season_number")  or item.get("s")  or ""
    url   = _https(item.get("url") or item.get("stream") or item.get("link") or item.get("video_url") or "")
    return {"id": eid, "title": title, "episode": str(ep_no), "season": str(s_no), "url": url}


# ─────────────────────── public API ───────────────────────────────────────────

async def search(q: str, limit: int = 8):
    """Return up to `limit` normalised movie dicts matching `q`. Empty list on error."""
    q = clean_text(q, 80)
    if len(q) < 2:
        return []
    key = (q.lower(), limit)
    hit = _SEARCH.get(key)
    if hit is not None:
        return hit

    # primary path inferred from the known home URL: /movie/moviebox/home
    # → search lives at /movie/moviebox/search (or /movie/moviebox/movies with a query)
    js = (
        await _api("search", "/movie/moviebox/search",  {"q": q, "limit": limit})
        or await _api("search", "/movie/moviebox/search", {"query": q, "limit": limit})
        or await _api("search", "/movie/moviebox/movies", {"q": q, "limit": limit})
        or await _api("search", "/search",               {"q": q, "limit": limit})
        or await _api("search", "/movie/search",         {"q": q})
    )
    rows = []
    if isinstance(js, dict):
        rows = (
            js.get("results") or js.get("data") or js.get("movies")
            or js.get("items") or js.get("response") or []
        )
    elif isinstance(js, list):
        rows = js

    out = []
    seen: set = set()
    for r in (rows if isinstance(rows, list) else []):
        m = _movie(r)
        if m and m["id"] not in seen:
            seen.add(m["id"])
            out.append(m)
        if len(out) >= limit:
            break

    _SEARCH.put(key, out)
    return out


async def details(movie_id: str):
    """Full detail dict for one movie / series. None on error."""
    movie_id = _safe_id(movie_id)
    if not movie_id:
        return None
    hit = _DETAIL.get(movie_id)
    if hit is not None:
        return hit

    js = (
        await _api("detail", f"/movie/moviebox/{movie_id}")
        or await _api("detail", f"/movie/moviebox/movie/{movie_id}")
        or await _api("detail", f"/movie/{movie_id}")
        or await _api("detail", f"/movies/{movie_id}")
    )
    if isinstance(js, dict):
        data = js.get("data") or js.get("movie") or js.get("result") or js
        d = _detail(data) if isinstance(data, dict) else None
    else:
        d = None

    if d:
        _DETAIL.put(movie_id, d)
    return d


async def episodes(movie_id: str, season: str = ""):
    """List of episode dicts for a series. Empty list for plain movies or on error."""
    movie_id = _safe_id(movie_id)
    if not movie_id:
        return []
    key = (movie_id, season)
    hit = _EPISODES.get(key)
    if hit is not None:
        return hit

    params = {"season": season} if season else None
    js    = (
        await _api("eps", f"/movie/moviebox/{movie_id}/episodes", params)
        or await _api("eps", f"/movie/moviebox/episodes/{movie_id}", params)
        or await _api("eps", f"/movie/{movie_id}/episodes", params)
        or await _api("eps", f"/movies/{movie_id}/episodes", params)
    )
    rows = []
    if isinstance(js, dict):
        rows = js.get("episodes") or js.get("data") or js.get("results") or []
    elif isinstance(js, list):
        rows = js

    out = [e for e in (_ep(r) for r in (rows if isinstance(rows, list) else [])) if e]
    _EPISODES.put(key, out)
    return out


# ---------- secure token stash (group sees only opaque token, no injected URLs) ----------
def stash(user_id: int, movie: dict) -> str:
    """Store a movie dict under a short random token tied to user_id. Returns the token."""
    tok = secrets.token_urlsafe(8)
    _STASH.put(tok, (user_id, movie))
    return tok


def take(token: str, user_id: int):
    """Return the movie dict for this token+user pair, or None if invalid/expired."""
    if not isinstance(token, str) or len(token) > 20:
        return None
    v = _STASH.get(token)
    if not v or v[0] != user_id:
        return None
    return dict(v[1])


# ---------- episode token stash ----------
def stash_ep(user_id: int, ep: dict) -> str:
    tok = secrets.token_urlsafe(8)
    _STASH.put("ep:" + tok, (user_id, ep))
    return tok


def take_ep(token: str, user_id: int):
    if not isinstance(token, str) or len(token) > 24:
        return None
    v = _STASH.get("ep:" + token)
    if not v or v[0] != user_id:
        return None
    return dict(v[1])


def clear_caches():
    for c in (_SEARCH, _DETAIL, _EPISODES, _STASH):
        c.clear()
