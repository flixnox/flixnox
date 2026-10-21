"""Settings, read once from environment variables. Nothing secret is hard-coded."""
import hashlib
import hmac
import os
import sys
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
API_BASE = _env("API_BASE", "https://curiousapis.name.ng").rstrip("/")
SC_SEARCH_PATH = _env("SC_SEARCH_PATH", "/soundcloud/search")
SUPPORT_URL = _env("SUPPORT_URL")
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
CURIOUS_API_KEY = _env("CURIOUS_API_KEY", "")
