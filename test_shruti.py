"""Finds out how api.shrutibots.in wants to be called. Stdlib only.

Usage (Termux):
    export SHRUTI_API_KEY="your key"        # never put the key inside a file
    python test_shruti.py
Then paste shruti_report.txt here. The key is masked in the report.
"""
import json
import os
import urllib.error
import urllib.parse
import urllib.request

BASE = os.environ.get("SHRUTI_API_URL", "https://api.shrutibots.in").rstrip("/")
KEY = os.environ.get("SHRUTI_API_KEY", "")
VID = "Kx7B-XvmFtE"                      # Believer, Imagine Dragons
YT = f"https://www.youtube.com/watch?v={VID}"
Q = urllib.parse.quote("Believer Imagine Dragons")
U = urllib.parse.quote(YT, safe="")

# (label, path, extra headers)
TESTS = [
    ("song id ?api=", f"/song/{VID}?api={KEY}", {}),
    ("song id audio ?api=", f"/song/{VID}?api={KEY}&video=false", {}),
    ("song id x-api-key", f"/song/{VID}", {"x-api-key": KEY}),
    ("song id bearer", f"/song/{VID}", {"Authorization": f"Bearer {KEY}"}),
    ("download url ?api=", f"/download?url={U}&type=audio&api={KEY}", {}),
    ("download id ?api_key=", f"/download?id={VID}&api_key={KEY}", {}),
    ("audio ?url=", f"/audio?url={U}&api={KEY}", {}),
    ("search ?q=", f"/search?q={Q}&api={KEY}", {}),
    ("search x-api-key", f"/search?q={Q}", {"x-api-key": KEY}),
    ("yt search", f"/youtube/search?q={Q}&api={KEY}", {}),
    ("root json", "/", {"x-api-key": KEY}),
    ("openapi", "/openapi.json", {}),
    ("docs", "/docs", {}),
]


def mask(s):
    return s.replace(KEY, "<KEY>") if KEY else s


def hit(path, headers):
    req = urllib.request.Request(BASE + path, headers={"User-Agent": "SonicNox-test", **headers})
    try:
        with urllib.request.urlopen(req, timeout=40) as r:
            return r.status, r.read(1500).decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read(600).decode("utf-8", "replace")
    except Exception as e:                # noqa: BLE001
        return 0, repr(e)


def main():
    if not KEY:
        print("Set SHRUTI_API_KEY first:  export SHRUTI_API_KEY='...'")
        return
    out = []
    for label, path, headers in TESTS:
        code, body = hit(path, headers)
        try:
            body = json.dumps(json.loads(body), indent=1)[:700]
        except Exception:                 # not JSON (html, text)
            body = body[:300].replace("\n", " ")
        out.append(f"=== {label}  [{code}] {mask(path)[:90]}\n{mask(body)}\n")
        print(out[-1])
    open("shruti_report.txt", "w", encoding="utf-8").write("\n".join(out))
    print("Saved to shruti_report.txt")


if __name__ == "__main__":
    main()
