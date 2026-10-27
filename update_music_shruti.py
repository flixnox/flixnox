with open("nox/music.py", "r") as f:
    code = f.read()

shruti_logic = '''
# ==========================================
# SHRUTI API INTEGRATION
# ==========================================
from . import shruti

async def shruti_search(query, limit=5):
    # Shruti API ka search endpoint (assuming /search)
    js = await shruti.api_call("search", {"query": query, "limit": limit})
    if not js or "results" not in js:
        return []
    
    out = []
    for item in js.get("results", []):
        out.append({
            "id": f"shruti:{item.get('id')}", "sid": str(item.get('id')), "src": "shruti",
            "title": _text(item.get("title", ""), 120), "artist": _text(item.get("artist", ""), 80),
            "album": _text(item.get("album", ""), 80), "dur": _dur(item.get("duration")),
            "cover": _https(item.get("cover", "")), "aud": {}, "year": ""
        })
    return out[:limit]

async def shruti_resolve(track):
    sid = track.get("sid")
    js = await shruti.api_call(f"download/{sid}")
    if js and "url" in js:
        return {"url": js["url"], "preview": False, "cover": track.get("cover")}
    return None

_orig_search_all = search_all
_orig_resolve = resolve

async def search_all(q, songs=10, artists=4):
    # Shruti API se try karo pehle
    shruti_res = await shruti_search(q, songs)
    if shruti_res:
        return shruti_res, []
    
    # Agar nahi mila, toh JioSaavn/YouTube fallback
    return await _orig_search_all(q, songs, artists)

async def search(q, limit=5):
    s, _ = await search_all(q, limit, 0)
    return s

async def resolve(track):
    if track.get("src") == "shruti":
        res = await shruti_resolve(track)
        if res:
            return res
    return await _orig_resolve(track)
'''

if "async def shruti_search" not in code:
    code += "\n" + shruti_logic

with open("nox/music.py", "w") as f:
    f.write(code)

print("✅ music.py me Shruti API add ho gaya!")
