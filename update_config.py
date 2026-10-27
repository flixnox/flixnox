with open("nox/config.py", "r") as f:
    code = f.read()

# Purana COOKIES_FILE hatao
import re
code = re.sub(r"# --- Cookies Path ---.*?COOKIES_FILE = .*?\n", "", code, flags=re.DOTALL)

b64_logic = '''
# --- Cookies Support (B64) ---
import base64
import os
COOKIES_B64 = _env("COOKIES_B64", "")
COOKIES_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "cookies.txt")

if COOKIES_B64 and not os.path.exists(COOKIES_FILE):
    try:
        with open(COOKIES_FILE, "wb") as f:
            f.write(base64.b64decode(COOKIES_B64))
    except Exception:
        pass
'''
code += b64_logic

with open("nox/config.py", "w") as f:
    f.write(code)

print("✅ config.py update ho gayi Base64 support ke liye!")
