"""YouTube audio proxy.

googlevideo links are tied to the IP that resolved them and carry no CORS headers, so the Mini App can't play
them directly. This router re-serves them from the same server, with Range support (iOS/Safari need it).

Security: every link is HMAC-signed with an expiry, so only links this server created work, and only
YouTube hosts are ever contacted. Nobody can use this as an open proxy.
"""
import hmac
import logging
import time
from hashlib import sha256
from urllib.parse import parse_qs, quote, urljoin, urlsplit

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response, StreamingResponse

from . import config

log = logging.getLogger(__name__)
router = APIRouter()

PATH = "/api/ytstream"
CHUNK = 64 * 1024
LINK_TTL = 6 * 3600
ANDROID_UA = "com.google.android.youtube/19.09.37 (Linux; U; Android 11) gzip"
BROWSER_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
UA_BY_CLIENT = {
    "ANDROID_VR": "com.google.android.apps.youtube.vr.oculus/1.60.19 (Linux; U; Android 12L; eureka-user Build/SQ3A.220605.009.A1) gzip",
    "ANDROID": ANDROID_UA,
    "IOS": "com.google.ios.youtube/19.09.3 (iPhone16,2; U; CPU iOS 17_5 like Mac OS X)",
}


def ua_for(url):
    """googlevideo links carry c=<client>; YouTube likes the same client's User-Agent back."""
    try:
        c = (parse_qs(urlsplit(url).query).get("c") or [""])[0].upper()
    except ValueError:
        c = ""
    return UA_BY_CLIENT.get(c) or (BROWSER_UA if c else ANDROID_UA)
ALLOWED_HOSTS = ("googlevideo.com", "youtube.com", "ytimg.com")
MAX_REDIRECTS = 4
CORS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Expose-Headers": "Content-Length, Content-Range, Accept-Ranges",
}
PASS_HEADERS = ("content-length", "content-range", "accept-ranges")


def allowed(url: str) -> bool:
    try:
        p = urlsplit(url)
        host = (p.hostname or "").lower()
    except ValueError:
        return False
    if p.scheme != "https" or not host:
        return False
    return any(host == h or host.endswith("." + h) for h in ALLOWED_HOSTS)


def _sig(url: str, exp: int) -> str:
    return hmac.new(config._derive("ytstream").encode(), f"{exp}|{url}".encode(), sha256).hexdigest()[:32]


def proxy_url(url: str) -> str:
    """Public, signed link to play `url` through this server (goes via the Cloudflare Worker, so the secret header is added)."""
    exp = int(time.time()) + LINK_TTL
    return f"{config.PUBLIC_ORIGIN}{PATH}?url={quote(url, safe='')}&exp={exp}&sig={_sig(url, exp)}"


def unwrap(link: str):
    """If `link` is one of our own proxy links, return the googlevideo URL inside (the bot downloads it directly, no round trip)."""
    try:
        p = urlsplit(link)
        if p.netloc != config.PUBLIC_HOST or p.path != PATH:
            return None
        inner = (parse_qs(p.query).get("url") or [""])[0]
    except ValueError:
        return None
    return inner if allowed(inner) else None


def client_kwargs():
    kw = dict(timeout=httpx.Timeout(connect=10.0, read=60.0, write=10.0, pool=10.0), follow_redirects=False)
    if config.YOUTUBE_PROXY:
        kw["proxy"] = config.YOUTUBE_PROXY
    return kw


async def _open_upstream(client, url, headers):
    for _ in range(MAX_REDIRECTS + 1):
        resp = await client.send(client.build_request("GET", url, headers=headers), stream=True)
        if resp.status_code in (301, 302, 303, 307, 308):
            loc = resp.headers.get("location")
            await resp.aclose()
            url = urljoin(url, loc or "")
            if not loc or not allowed(url):
                raise HTTPException(502, "Bad redirect")
            continue
        return resp
    raise HTTPException(502, "Too many redirects")


@router.options(PATH)
async def ytstream_options():
    return Response(status_code=204, headers={**CORS, "Access-Control-Allow-Methods": "GET, HEAD, OPTIONS",
                                              "Access-Control-Allow-Headers": "Range, Content-Type", "Access-Control-Max-Age": "86400"})


@router.api_route(PATH, methods=["GET", "HEAD"])
async def ytstream(request: Request, url: str, exp: int = 0, sig: str = ""):
    if exp < time.time() or not hmac.compare_digest(sig, _sig(url, exp)) or not allowed(url):
        raise HTTPException(403, "Link expired or invalid")
    headers = {"User-Agent": ua_for(url), "Accept": "*/*", "Accept-Encoding": "identity", "Referer": "https://www.youtube.com/"}
    if request.headers.get("range"):
        headers["Range"] = request.headers["range"]

    client = httpx.AsyncClient(**client_kwargs())
    try:
        up = await _open_upstream(client, url, headers)
    except HTTPException:
        await client.aclose()
        raise
    except httpx.HTTPError as e:
        await client.aclose()
        log.warning("ytstream upstream error: %s", e)
        raise HTTPException(502, "Upstream unreachable")
    if up.status_code >= 400:
        code = up.status_code
        await up.aclose()
        await client.aclose()
        log.warning("ytstream upstream status %s", code)
        raise HTTPException(code if code in (403, 404, 410, 416) else 502, "Upstream error")

    ctype = up.headers.get("content-type", "")
    media = ctype.split(";")[0].strip() if ctype.startswith(("audio/", "video/")) else "audio/mp4"
    out = dict(CORS)
    out["Cache-Control"] = "private, max-age=300"
    for h in PASS_HEADERS:
        if up.headers.get(h):
            out[h] = up.headers[h]
    out.setdefault("accept-ranges", "bytes")

    if request.method == "HEAD":
        status = up.status_code
        await up.aclose()
        await client.aclose()
        return Response(status_code=status, headers=out, media_type=media)

    async def body():
        try:
            async for chunk in up.aiter_raw(CHUNK):
                yield chunk
        except httpx.HTTPError as e:
            log.warning("ytstream interrupted: %s", e)
        finally:
            await up.aclose()
            await client.aclose()

    return StreamingResponse(body(), status_code=up.status_code, headers=out, media_type=media)
