with open("nox/music.py", "r") as f:
    code = f.read()

# Naya Proxy aur Fetch Logic
proxy_logic = '''
import itertools

# Pool of public proxies for YouTube
PROXY_POOL = [
    "http://8.219.97.52:80",
    "http://47.91.65.23:3128",
    "http://103.152.112.162:80",
    "http://47.243.92.199:3128",
    "http://8.219.97.52:8080",
    "http://154.17.23.181:80",
    "http://154.17.23.181:8080",
    "http://47.91.65.23:80",
    "http://103.152.112.162:8080",
    "http://8.219.97.52:3128"
]
_proxy_cycle = itertools.cycle(PROXY_POOL)

def _get_next_proxy():
    # Agar config me proxies hain toh wahan se uthayega
    if getattr(config, "PROXIES", None):
        import random
        return random.choice(config.PROXIES)
    return next(_proxy_cycle)

async def _yt_request(endpoint, body):
    for _ in range(5): # 5 proxy try karega
        proxy = _get_next_proxy()
        try:
            r = await client().post(
                f"https://www.youtube.com/youtubei/v1/{endpoint}?key={INNERTUBE_KEY}&prettyPrint=false",
                json=body, cookies=_get_cookiejar(), timeout=8.0, proxy=proxy
            )
            if r.status_code == 200:
                return r.json()
        except Exception:
            continue
    return None
'''

# Purane proxy logic ko hata kar naya lagao
if "async def _yt_request" not in code:
    code = code.replace("# YOUTUBE INTEGRATION", proxy_logic + "\n# YOUTUBE INTEGRATION")

# _yt_search aur _yt_resolve ko update karo taaki wo naya request function use kare
code = code.replace('''    body = {"context": INNERTUBE_CLIENTS[0], "query": query, "params": "EgIQAQ%3D%3D"}
    try:
        r = await client().post(
            f"https://www.youtube.com/youtubei/v1/search?key={INNERTUBE_KEY}",
            json=body, cookies=_get_cookiejar(), timeout=8.0
        )
        data = r.json()
    except Exception as e:
        return []''', '''    body = {"context": INNERTUBE_CLIENTS[0], "query": query, "params": "EgIQAQ%3D%3D"}
    data = await _yt_request("search", body)
    if not data:
        return []''')

code = code.replace('''    body = {"context": INNERTUBE_CLIENTS[0], "videoId": sid, "contentCheckOk": True, "racyCheckOk": True}
    try:
        r = await client().post(
            f"https://www.youtube.com/youtubei/v1/player?key={INNERTUBE_KEY}&prettyPrint=false",
            json=body, cookies=_get_cookiejar(), timeout=10.0
        )
        data = r.json()
        if data.get("playabilityStatus", {}).get("status") != "OK":
            return None''', '''    body = {"context": INNERTUBE_CLIENTS[0], "videoId": sid, "contentCheckOk": True, "racyCheckOk": True}
    data = await _yt_request("player", body)
    if not data or data.get("playabilityStatus", {}).get("status") != "OK":
        return None''')

with open("nox/music.py", "w") as f:
    f.write(code)

print("✅ music.py me proxy rotation add ho gaya!")
