with open("nox/moviebox.py", "r") as f:
    code = f.read()

# Update the _get function to use proxy
old_get = '''async def _get(path, params=None):
    url = f"{BASE}{path}"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.get(url, params=params, headers=HEADERS)
            if r.status_code == 200:
                return r.json()
    except Exception:
        pass
    return None'''

new_get = '''async def _get(path, params=None):
    from . import config
    url = f"{BASE}{path}"
    proxy = getattr(config, "MOVIEBOX_PROXY", None)
    try:
        async with httpx.AsyncClient(timeout=10.0, proxy=proxy) as client:
            r = await client.get(url, params=params, headers=HEADERS)
            if r.status_code == 200:
                return r.json()
    except Exception:
        pass
    return None'''

code = code.replace(old_get, new_get)

with open("nox/moviebox.py", "w") as f:
    f.write(code)

print("✅ moviebox.py me proxy add ho gaya!")
