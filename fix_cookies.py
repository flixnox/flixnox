import re

with open("nox/music.py", "r") as f:
    code = f.read()

# Naya function jo cookies.txt ko httpx format me padhega
cookie_parser = '''
import http.cookiejar

def _get_cookiejar():
    if not getattr(config, "COOKIES_FILE", None) or not os.path.exists(config.COOKIES_FILE):
        return None
    cj = http.cookiejar.MozillaCookieJar(config.COOKIES_FILE)
    try:
        cj.load(ignore_discard=True, ignore_expires=True)
        return cj
    except Exception:
        return None
'''

# Yahan maine _get_cookiejar ko _get_proxy ke theek baad daala hai
code = code.replace("def _get_proxy():", cookie_parser + "\ndef _get_proxy():")

# Aur ab jo maine pehle galat parameter diya tha (cookies={"cookie_file"}) usko replace kar rahe hain sahi se
code = code.replace('cookies={"cookie_file": getattr(config, "COOKIES_FILE", None)} if getattr(config, "COOKIES_FILE", None) else None', 'cookies=_get_cookiejar()')

with open("nox/music.py", "w") as f:
    f.write(code)

print("✅ Cookies ka format fix ho gaya!")
