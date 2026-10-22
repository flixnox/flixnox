"""Run in Termux:  python test_apis.py
Calls the JioSaavn API once and prints a short report, so you can see it works from your phone before deploying."""
import json
import urllib.parse
import urllib.request

BASE = "https://jiosaavn-api-ruddy-phi.vercel.app/api"
Q = "arijit singh"


def get(path, **params):
    url = BASE + path + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": "SonicNox-test", "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=40) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


out = []
try:
    js = get("/search/songs", query=Q, limit=3)
    rows = (js.get("data") or {}).get("results") or []
    out.append(f"songs: success={js.get('success')} results={len(rows)}")
    if rows:
        r = rows[0]
        dl = r.get("downloadUrl")
        out.append(f"  first: {r.get('name')} | duration={r.get('duration')} | image={'yes' if r.get('image') else 'NO'}")
        out.append(f"  audio links: {[d.get('quality') for d in dl] if isinstance(dl, list) else dl}")
        out.append("  keys: " + ", ".join(sorted(r.keys())))
except Exception as e:
    out.append(f"songs: FAILED {e}")
try:
    js = get("/search/artists", query="arijit", limit=3)
    rows = (js.get("data") or {}).get("results") or []
    out.append(f"artists: success={js.get('success')} results={len(rows)} first={rows[0].get('name') if rows else None}")
except Exception as e:
    out.append(f"artists: FAILED {e}")
text = "\n".join(out)
print(text)
open("api_report.txt", "w", encoding="utf-8").write(text + "\n")
print("\nSaved to api_report.txt")
