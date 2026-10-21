"""Security helpers: Telegram initData verification, rate limits, input cleaning, URL checks."""
import hashlib
import hmac
import ipaddress
import json
import re
import time
import unicodedata
from urllib.parse import parse_qsl, urlsplit


def verify_init_data(raw, bot_token, max_age=14400):
    """Validate Telegram Mini App initData (HMAC-SHA256). Returns {'user','start_param'} or None."""
    try:
        if not isinstance(raw, str) or not raw or len(raw) > 4096:
            return None
        pairs = parse_qsl(raw, keep_blank_values=True, strict_parsing=True)
        data = dict(pairs)
        if len(data) != len(pairs):          # duplicate keys -> reject
            return None
        got = data.pop("hash", None)
        if not got:
            return None
        check = "\n".join(f"{k}={data[k]}" for k in sorted(data))
        secret = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
        calc = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(calc, got):
            return None
        age = time.time() - int(data["auth_date"])
        if age > max_age or age < -120:
            return None
        user = json.loads(data["user"])
        if not isinstance(user, dict) or not isinstance(user.get("id"), int) or user.get("is_bot"):
            return None
        return {"user": user, "start_param": data.get("start_param", "")}
    except Exception:
        return None


def same(a, b):
    """Constant-time string comparison."""
    return hmac.compare_digest(str(a).encode(), str(b).encode())


class RateLimiter:
    """Token bucket per key."""

    def __init__(self, rate, burst):
        self.rate, self.burst, self.b = rate, burst, {}

    def allow(self, key, cost=1.0):
        now = time.monotonic()
        tokens, last = self.b.get(key, (self.burst, now))
        tokens = min(self.burst, tokens + (now - last) * self.rate)
        ok = tokens >= cost
        self.b[key] = (tokens - cost if ok else tokens, now)
        if len(self.b) > 20000:
            self.b = {k: v for k, v in self.b.items() if now - v[1] < 120}
        return ok


class Penalty:
    """Too many violations in a window -> temporary block."""

    def __init__(self, limit=8, window=60, block=300):
        self.limit, self.window, self.block = limit, window, block
        self.hits, self.until = {}, {}

    def strike(self, key):
        now = time.monotonic()
        h = [t for t in self.hits.get(key, []) if now - t < self.window] + [now]
        self.hits[key] = h
        if len(h) >= self.limit:
            self.until[key] = now + self.block
            self.hits[key] = []

    def blocked(self, key):
        u = self.until.get(key)
        if u and u > time.monotonic():
            return True
        self.until.pop(key, None)
        return False


_WS = re.compile(r"\s+")


def clean_text(s, maxlen=120):
    """Remove control/format characters (incl. bidi tricks), collapse spaces, cut length."""
    if not isinstance(s, str):
        return ""
    s = "".join(ch for ch in s if unicodedata.category(ch)[0] != "C" or ch in " \t\n")
    return _WS.sub(" ", s).strip()[:maxlen]


def safe_https_url(u, maxlen=2048):
    """Accept only plain https URLs to public hostnames (no IPs, no credentials, no quotes)."""
    if not isinstance(u, str) or not u or len(u) > maxlen or re.search(r"[\s\"'<>\\]", u):
        return None
    try:
        p = urlsplit(u)
        host = (p.hostname or "").lower()
    except ValueError:
        return None
    if p.scheme != "https" or not host or p.username or p.password:
        return None
    if host == "localhost" or host.endswith((".local", ".internal", ".localhost")) or "." not in host:
        return None
    try:
        ipaddress.ip_address(host)
        return None
    except ValueError:
        pass
    return u


_ROOM = re.compile(r"^n?\d{1,20}$")


def encode_room(chat_id):
    return ("n" if chat_id < 0 else "") + str(abs(int(chat_id)))


def decode_room(p):
    if not isinstance(p, str) or not _ROOM.match(p):
        return None
    v = int(p.lstrip("n"))
    return -v if p.startswith("n") else v
