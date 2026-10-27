with open("nox/music.py", "r") as f:
    code = f.read()

video_logic = '''
# ==========================================
# YOUTUBE VIDEO RESOLVER (For /vplay)
# ==========================================
async def _yt_resolve_video(sid):
    if not getattr(config, "YOUTUBE_ENABLED", True):
        return None
    
    body = {"context": INNERTUBE_CLIENTS[0], "videoId": sid, "contentCheckOk": True, "racyCheckOk": True}
    try:
        r = await client().post(
            f"https://www.youtube.com/youtubei/v1/player?key={INNERTUBE_KEY}&prettyPrint=false",
            json=body, cookies=_get_cookiejar(), timeout=10.0
        )
        data = r.json()
        if data.get("playabilityStatus", {}).get("status") != "OK":
            return None
            
        sd = data.get("streamingData", {})
        formats = sd.get("formats", []) # Muxed formats (audio+video)
        if not formats:
            formats = sd.get("adaptiveFormats", [])
            
        best = None
        best_score = -1
        for f in formats:
            u = f.get("url")
            if not u: continue
            mt = f.get("mimeType", "")
            score = 0
            if "video/mp4" in mt: score = 100 + int(f.get("height", 0) or 0)
            elif "video/" in mt: score = 50
            
            if score > best_score:
                best_score = score
                best = u
                
        if best:
            pub_url = f"{config.PUBLIC_ORIGIN}/api/ytstream?url={quote(best, safe='')}"
            return {"url": pub_url, "preview": False, "cover": None}
    except Exception:
        pass
    return None

async def resolve_video(track):
    if track.get("src") == "youtube":
        return await _yt_resolve_video(track.get("sid"))
    return await _orig_resolve(track)
'''

if "async def resolve_video" not in code:
    code += "\n" + video_logic

with open("nox/music.py", "w") as f:
    f.write(code)

print("✅ music.py me resolve_video add ho gaya!")
