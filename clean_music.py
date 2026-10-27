import re

with open("nox/music.py", "r") as f:
    code = f.read()

# Puraane saare custom blocks (YouTube, Shruti, Proxy) ko dhoond kar delete karo
# Hum file ko sirf base JioSaavn API tak rakhna chahte hain
pattern = r"# ==========================================\n# (YOUTUBE INTEGRATION|SHRUTI API|YOUTUBE VIDEO RESOLVER).*"
clean_code = re.split(pattern, code)[0]

# Ekdum naya, ekdum saaf integrated code
new_additions = '''
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
'''

# Purane search_all aur resolve ko rename kar do
clean_code = clean_code.replace("async def search_all(", "async def _orig_search_all(")
clean_code = clean_code.replace("async def resolve(", "async def _orig_resolve(")

# Naya code append karo
clean_code += "\n" + new_additions

with open("nox/music.py", "w") as f:
    f.write(clean_code)

print("✅ music.py ekdum saaf ho gayi hai!")
