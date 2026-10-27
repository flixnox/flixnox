"""MovieBox API (api.moviebox.pro - No Auth Needed)."""
import time
import secrets
import httpx
from .security import clean_text

BASE = "https://api.moviebox.pro/api/v1"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Accept": "application/json"
}

_stash = {}
_stash_ep = {}

def stash(uid, data):
    tok = secrets.token_urlsafe(8)
    _stash[tok] = (uid, data, time.time())
    return tok

def take(tok, uid):
    item = _stash.get(tok)
    if not item or item[0] != uid or time.time() - item[2] > 1800:
        return None
    return item[1]

def stash_ep(uid, data):
    tok = secrets.token_urlsafe(8)
    _stash_ep[tok] = (uid, data, time.time())
    return tok

def take_ep(tok, uid):
    item = _stash_ep.get(tok)
    if not item or item[0] != uid or time.time() - item[2] > 1800:
        return None
    return item[1]

async def _get(path, params=None):
    url = f"{BASE}{path}"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.get(url, params=params, headers=HEADERS)
            if r.status_code == 200:
                return r.json()
    except Exception:
        pass
    return None

async def search(q, limit=8):
    if not q: return []
    js = await _get("/search", {"query": q, "page": 1})
    if not js or "results" not in js: return []
    
    out = []
    for item in js.get("results", [])[:limit]:
        poster = item.get("poster", "")
        title = item.get("title", "")
        out.append({
            "id": str(item.get("id", "")),
            "title": clean_text(title),
            "year": str(item.get("year", "")),
            "type": item.get("type", "movie"),
            "poster": poster,
            "rating": str(item.get("rating", "")),
            "desc": clean_text(item.get("description", ""))
        })
    return out

async def details(movie_id):
    js = await _get(f"/movie/{movie_id}")
    if not js or "id" not in js: return None
    
    out = {
        "id": str(js.get("id")),
        "title": clean_text(js.get("title", "")),
        "year": str(js.get("year", "")),
        "type": js.get("type", "movie"),
        "poster": js.get("poster", ""),
        "desc": clean_text(js.get("description", "")),
        "rating": str(js.get("rating", "")),
        "streams": js.get("streams", []),
        "token": ""
    }
    return out

async def episodes(movie_id):
    js = await _get(f"/series/{movie_id}/episodes")
    if not js or "episodes" not in js: return []
    
    out = []
    for ep in js["episodes"]:
        out.append({
            "id": str(ep.get("id", "")),
            "title": f"Ep {ep.get('episode', '')} - {ep.get('title', '')}",
            "url": ep.get("url", ""),
        })
    return out
