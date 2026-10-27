import re

with open("nox/music.py", "r") as f:
    code = f.read()

# 1. Import config for cookies path
if "from . import config" not in code:
    code = code.replace("from .security import clean_text, safe_https_url", "from .security import clean_text, safe_https_url\nfrom . import config")

# 2. Update _yt_search function
search_old = '''r = await client().post(
            f"https://www.youtube.com/youtubei/v1/search?key={INNERTUBE_KEY}",
            json=body, proxy=proxy, timeout=8.0
        )'''
search_new = '''r = await client().post(
            f"https://www.youtube.com/youtubei/v1/search?key={INNERTUBE_KEY}",
            json=body, proxy=proxy, timeout=8.0,
            cookies={"cookie_file": getattr(config, "COOKIES_FILE", None)} if getattr(config, "COOKIES_FILE", None) else None
        )'''
code = code.replace(search_old, search_new)

# 3. Update _yt_resolve function
resolve_old = '''r = await client().post(
                f"https://www.youtube.com/youtubei/v1/player?key={INNERTUBE_KEY}&prettyPrint=false",
                json=body, proxy=proxy, timeout=8.0
            )'''
resolve_new = '''r = await client().post(
                f"https://www.youtube.com/youtubei/v1/player?key={INNERTUBE_KEY}&prettyPrint=false",
                json=body, proxy=proxy, timeout=8.0,
                cookies={"cookie_file": getattr(config, "COOKIES_FILE", None)} if getattr(config, "COOKIES_FILE", None) else None
            )'''
code = code.replace(resolve_old, resolve_new)

with open("nox/music.py", "w") as f:
    f.write(code)

print("✅ music.py successfully update ho gayi cookies ke saath!")
