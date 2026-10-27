with open("nox/rooms.py", "r") as f:
    code = f.read()

# _pre_resolve aur _advance me resolve() ke baad URL check lagana
# Hum ensure karenge ki agar src youtube hai toh use waise hi bhej dein

code = code.replace(
'''            r = await asyncio.wait_for(music.resolve(t), 50)
            if r:
                t["_r"] = (r, time.time())''',
'''            r = await asyncio.wait_for(music.resolve(t), 50)
            if r:
                # Ensure YouTube links don't break
                if isinstance(r, str) and "googlevideo.com" in r:
                    r = f"https://flixnox-k1g6.onrender.com/api/ytstream?url={quote(r, safe='')}"
                t["_r"] = (r, time.time())'''
)

with open("nox/rooms.py", "w") as f:
    f.write(code)

print("✅ rooms.py updated for YT Media proxy!")
