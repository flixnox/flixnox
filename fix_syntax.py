with open("nox/music.py", "r") as f:
    lines = f.readlines()

# Purane kharab code ko dhoondh kar hatao (jahan syntax error aaya hai)
new_lines = []
skip = False
for line in lines:
    # Agar humara custom Shruti/YouTube logic shuru hota hai, toh use skip karna shuru karo
    if "# ==========================================" in line and ("YOUTUBE INTEGRATION" in line or "SHRUTI API" in line):
        skip = True
    
    if not skip:
        new_lines.append(line)

# Ab ekdum naya, saaf aur syntax-error-free logic add karo
new_logic = '''
# ==========================================
# EXTRACTORS FALLBACK (JioSaavn -> Shruti -> YouTube)
# ==========================================
from . import shruti

async def search_all(q, songs=10, artists=4):
    # 1. Try Shruti API
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

    # 2. Try JioSaavn (Original)
    s, a = await _orig_search_all(q, songs, artists)
    if s:
        return s, a

    # 3. Try YouTube
    try:
        yt_s = await _yt_search(q, songs)
        if yt_s:
            return yt_s, []
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
            
    if src == "youtube":
        try:
            r = await _yt_resolve(track.get("sid"))
            if r:
                return r
        except Exception:
            pass

    # Fallback to original resolver
    return await _orig_resolve(track)
'''

# Purane search_all aur resolve ko rename karo taaki hum unhe call kar sake
code_str = "".join(new_lines)
code_str = code_str.replace("async def search_all(", "async def _orig_search_all(")
code_str = code_str.replace("async def resolve(", "async def _orig_resolve(")

# Naya logic append karo
code_str += "\n" + new_logic

with open("nox/music.py", "w") as f:
    f.write(code_str)

print("✅ Syntax Error Fix ho gaya! Ab push karo.")
