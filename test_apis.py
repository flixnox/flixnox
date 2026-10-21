"""Run this in Termux:  python test_apis.py
It calls your music APIs once and saves what they return to api_report.txt, so field names can be checked."""
import json
import urllib.parse
import urllib.request

BASE = "https://curiousapis.name.ng"
Q = "Believer Imagine Dragons"
TESTS = [
    ("Deezer search", "/deezer/search?" + urllib.parse.urlencode({"q": Q})),
    ("iTunes search", "/itunes/search?" + urllib.parse.urlencode({"term": Q, "media": "music", "limit": 3})),
    ("SoundCloud search (path may differ)", "/soundcloud/search?" + urllib.parse.urlencode({"q": Q})),
    ("YT Music Audio (doubled path)", "/yt_music_audio/yt_music_audio?" + urllib.parse.urlencode({"q": Q})),
    ("YT Music Audio (single path)", "/yt_music_audio?" + urllib.parse.urlencode({"q": Q})),
    ("Lyrics.ovh", "/lyrics_ovh/Imagine%20Dragons/Believer"),
]
out = []
for name, path in TESTS:
    try:
        req = urllib.request.Request(BASE + path, headers={"User-Agent": "SonicNox-test", "x-api-key": __import__("os").environ.get("CURIOUS_API_KEY", "")})
        with urllib.request.urlopen(req, timeout=40) as r:
            body = r.read().decode("utf-8", "replace")
        try:
            body = json.dumps(json.loads(body), indent=1, ensure_ascii=False)
        except ValueError:
            pass
        out.append(f"=== {name}  [{r.status}] ===\n{body[:1800]}\n")
    except Exception as e:
        out.append(f"=== {name}  FAILED: {e} ===\n")
text = "\n".join(out)
print(text)
open("api_report.txt", "w", encoding="utf-8").write(text)
print("Saved to api_report.txt")
