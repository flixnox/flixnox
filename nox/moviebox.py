"""MovieBox API (H5 App - Real Endpoints)."""
import time
import secrets
import httpx
from .security import clean_text

BASE = "https://h5.aoneroom.com"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Accept": "application/json",
    "X-Client-Info": '{"timezone":"Asia/Kolkata","os":"web","client":"h5","version":"3.0.0"}'
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
    from . import config
    url = f"{BASE}{path}"
    proxy = getattr(config, "MOVIEBOX_PROXY", None)
    try:
        async with httpx.AsyncClient(timeout=10.0, proxy=proxy) as client:
            r = await client.get(url, params=params, headers=HEADERS)
            if r.status_code == 200:
                return r.json()
    except Exception:
        pass
    return None

async def search(q, limit=8):
    if not q: return []
    # H5 search API
    js = await _get("/wefeed-h5-bff/app/get-search", {"keyword": q, "page": 1, "perPage": limit})
    if not js or "data" not in js: return []
    
    out = []
    for item in js.get("data", {}).get("items", []):
        out.append({
            "id": str(item.get("id")),
            "title": clean_text(item.get("title", "")),
            "year": str(item.get("year", "")),
            "type": item.get("type", ""),
            "poster": item.get("cover", {}).get("url", ""),
            "rating": str(item.get("rating", "")),
            "desc": clean_text(item.get("description", ""))
        })
    return out

async def details(movie_id):
    js = await _get("/wefeed-h5-bff/app/get-post-detail", {"id": movie_id, "type": "1"})
    if not js or "data" not in js: return None
    item = js["data"]
    
    return {
        "id": str(item.get("id")),
        "title": clean_text(item.get("title", "")),
        "year": str(item.get("year", "")),
        "type": item.get("type", ""),
        "poster": item.get("cover", {}).get("url", ""),
        "desc": clean_text(item.get("description", "")),
        "rating": str(item.get("rating", "")),
        "streams": [],
        "token": ""
    }

async def episodes(movie_id):
    js = await _get("/wefeed-h5-bff/app/get-episode", {"id": movie_id})
    if not js or "data" not in js: return []
    out = []
    for ep in js["data"].get("episodes", []):
        out.append({
            "id": str(ep.get("id")),
            "title": ep.get("title", ""),
            "url": "",
        })
    return out
