with open("nox/rooms.py", "r") as f:
    code = f.read()

# Imports update karo
if "from urllib.parse import quote, urlparse" not in code:
    code = code.replace("import asyncio", "import asyncio\nimport time\nfrom urllib.parse import quote, urlparse")

# Helper functions add karo
helpers = '''
YT_HOSTS = ("googlevideo.com", "youtube.com", "ytimg.com")
URL_TTL = 3 * 3600

def is_youtube_url(url: str) -> bool:
    try:
        host = (urlparse(url).hostname or "").lower()
    except Exception:
        return False
    return any(host == h or host.endswith("." + h) for h in YT_HOSTS)

def proxy_url(url: str) -> str:
    origin = str(getattr(config, "PUBLIC_ORIGIN", "") or "").rstrip("/")
    return f"{origin}/api/ytstream?url={quote(url, safe='')}"
'''
if "def is_youtube_url" not in code:
    code = code.replace("PUB = (", helpers + "\nPUB = (")

# _pre_resolve ko update karo
old_pre = '''    async def _pre_resolve(self, t):
        from . import music
        try:
            r = await asyncio.wait_for(music.resolve(t), 50)
            if r:
                t["_r"] = (r, time.time())
            else:
                t["_rf"] = time.time()
        except Exception:
            t["_rf"] = time.time()
        finally:
            t["_rp"] = False
        await self.push(panel=False)'''

new_pre = '''    async def _pre_resolve(self, t):
        from . import music
        try:
            r = await asyncio.wait_for(music.resolve(t), 50)
            if r:
                if is_youtube_url(r):
                    r = proxy_url(r)
                t["_r"] = (r, time.time())
            else:
                t["_rf"] = time.time()
        except Exception:
            t["_rf"] = time.time()
        finally:
            t["_rp"] = False
        await self.push(panel=False)'''

code = code.replace(old_pre, new_pre)

# _advance ko update karo
old_adv = '''    async def _advance(self):
        """Move to the next playable track. Caller must hold the lock."""
        from . import music
        self._cancel_wd()'''
new_adv = '''    async def _advance(self):
        """Move to the next playable track. Caller must hold the lock."""
        from . import music
        self._cancel_wd()
        # ... rest of advance stays same, but resolve is handled by _fresh logic '''
code = code.replace(old_adv, new_adv)

with open("nox/rooms.py", "w") as f:
    f.write(code)

print("✅ rooms.py me proxy logic add ho gaya!")
