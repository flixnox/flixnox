"""Settings, read once from environment variables. Nothing secret is hard-coded."""
import base64
import hashlib
import json
import hmac
import os
import sys
import tempfile
from urllib.parse import urlparse


def _env(name, default="", required=False):
    v = os.getenv(name, default).strip()
    if required and not v:
        sys.exit(f"[config] Missing required environment variable: {name}")
    return v


BOT_TOKEN = _env("BOT_TOKEN", required=True)
BOT_USERNAME = _env("BOT_USERNAME", "SonicNoxBot").lstrip("@")
MINIAPP_SHORT = _env("MINIAPP_SHORT", "room")
PUBLIC_URL = _env("PUBLIC_URL", required=True).rstrip("/")       # your Cloudflare Worker URL
PROXY_SECRET = _env("PROXY_SECRET", required=True)               # shared with the Worker
WEBHOOK_SECRET = _env("WEBHOOK_SECRET", required=True)           # any long random string
OWNER_IDS = {int(x) for x in _env("OWNER_IDS", required=True).replace(" ", "").split(",") if x.isdigit()}
MONGO_URI = _env("MONGO_URI")
MONGO_DB = _env("MONGO_DB", "noxroom")
SUPPORT_URL = _env("SUPPORT_URL")
# Music source: JioSaavn API. The default works out of the box, so no env variable is needed on Render.
JIOSAAVN_BASE   = _env("JIOSAAVN_BASE",  "https://jiosaavn-api-ruddy-phi.vercel.app/api").rstrip("/")
LYRICS_BASE = _env("LYRICS_BASE", "https://api.lyrics.ovh/v1").rstrip("/")
# --- YouTube fallback (search + audio) -----------------------------------------------------------------
YOUTUBE_ENABLED = _env("YOUTUBE_ENABLED", "1") == "1"
YT_INNERTUBE_KEY = _env("YT_INNERTUBE_KEY", "AIzaSyAO_FJ2SlqU8Q4STEHLGCilw_Y9_11qcW8")   # public web-client key, not a secret
YOUTUBE_PROXY = _env("YOUTUBE_PROXY")             # optional http(s)://user:pass@host:port. Used for YouTube lookups AND the stream proxy
# --- Shruti API (optional second source; needs a key) --------------------------------------------------
SHRUTI_API_URL = _env("SHRUTI_API_URL", "https://api.shrutibots.in").rstrip("/")
SHRUTI_API_KEY = _env("SHRUTI_API_KEY")
AUDIO_KBPS = int(_env("AUDIO_KBPS", "160"))                      # 96 / 160 / 320 (160 starts fastest on mobile data)
MAX_QUEUE = int(_env("MAX_QUEUE", "500"))                        # invisible safety cap, not a user limit

if not OWNER_IDS:
    sys.exit("[config] OWNER_IDS must contain at least one numeric Telegram user id")
for _n, _v in (("PROXY_SECRET", PROXY_SECRET), ("WEBHOOK_SECRET", WEBHOOK_SECRET)):
    if len(_v) < 24:
        sys.exit(f"[config] {_n} must be at least 24 characters")
if not PUBLIC_URL.startswith("https://"):
    sys.exit("[config] PUBLIC_URL must start with https://")

_u = urlparse(PUBLIC_URL)
PUBLIC_ORIGIN = f"{_u.scheme}://{_u.netloc}"
PUBLIC_HOST = _u.netloc


def _derive(label):
    return hmac.new(WEBHOOK_SECRET.encode(), label.encode(), hashlib.sha256).hexdigest()


WEBHOOK_PATH = _derive("path")[:40]     # secret URL path
WEBHOOK_TOKEN = _derive("token")        # secret header Telegram sends with every update


def _ice():
    """WebRTC servers for voice. Default = free STUN. For phones behind strict NATs add a TURN server via ICE_SERVERS (JSON)."""
    out = [{"urls": ["stun:stun.l.google.com:19302", "stun:stun1.l.google.com:19302"]}]
    raw = _env("ICE_SERVERS", "")
    if raw:
        try:
            out = []
            for e in json.loads(raw)[:6]:
                u = e["urls"] if isinstance(e["urls"], list) else [e["urls"]]
                item = {"urls": [str(x)[:200] for x in u[:4]]}
                if e.get("username"):
                    item["username"], item["credential"] = str(e["username"])[:200], str(e.get("credential", ""))[:200]
                out.append(item)
        except Exception:
            print("[config] ICE_SERVERS is not valid JSON, using the default STUN servers", file=sys.stderr)
            out = [{"urls": ["stun:stun.l.google.com:19302"]}]
    return out


ICE = _ice()


# --- YouTube cookies: put the cookies.txt (Netscape format) in base64 into COOKIES_B64 on Render. Never commit the file. ---
COOKIES_FILE = os.path.join(tempfile.gettempdir(), "nox_yt_cookies.txt")
_b64 = _env("COOKIES_B64")
if _b64:
    try:
        with open(COOKIES_FILE, "wb") as _f:
            _f.write(base64.b64decode(_b64))
    except Exception:
        print("[config] COOKIES_B64 is not valid base64, YouTube cookies ignored", file=sys.stderr)
