"""nox/stream.py - audio proxy for YouTube (googlevideo) streams."""
import logging
from urllib.parse import urljoin, urlparse
import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response, StreamingResponse

log = logging.getLogger(__name__)
router = APIRouter()
CHUNK = 64 * 1024
ANDROID_UA = "com.google.android.youtube/19.09.37 (Linux; U; Android 11) gzip"
ALLOWED_HOSTS = ("googlevideo.com", "youtube.com", "ytimg.com")
MAX_REDIRECTS = 4
CORS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Expose-Headers": "Content-Length, Content-Range, Accept-Ranges",
}
PASS_HEADERS = ("content-length", "content-range", "accept-ranges")

def _allowed(url: str) -> bool:
    try:
        p = urlparse(url)
    except Exception:
        return False
    host = (p.hostname or "").lower()
    if p.scheme not in ("http", "https") or not host:
        return False
    return any(host == h or host.endswith("." + h) for h in ALLOWED_HOSTS)

async def _open_upstream(client: httpx.AsyncClient, url: str, headers: dict) -> httpx.Response:
    for _ in range(MAX_REDIRECTS + 1):
        req = client.build_request("GET", url, headers=headers)
        resp = await client.send(req, stream=True)
        if resp.status_code in (301, 302, 303, 307, 308):
            loc = resp.headers.get("location")
            await resp.aclose()
            if not loc:
                raise HTTPException(502, "Bad redirect")
            url = urljoin(url, loc)
            if not _allowed(url):
                raise HTTPException(502, "Redirect target not allowed")
            continue
        return resp
    raise HTTPException(502, "Too many redirects")

@router.options("/api/ytstream")
async def ytstream_options():
    return Response(
        status_code=204,
        headers={
            **CORS,
            "Access-Control-Allow-Methods": "GET, HEAD, OPTIONS",
            "Access-Control-Allow-Headers": "Range, Content-Type",
            "Access-Control-Max-Age": "86400",
        },
    )

@router.api_route("/api/ytstream", methods=["GET", "HEAD"])
async def ytstream(request: Request, url: str):
    if not _allowed(url):
        raise HTTPException(400, "Unsupported URL")
    headers = {
        "User-Agent": ANDROID_UA,
        "Accept": "*/*",
        "Accept-Encoding": "identity",
        "Referer": "https://www.youtube.com/",
    }
    rng = request.headers.get("range")
    if rng:
        headers["Range"] = rng
    client = httpx.AsyncClient(
        timeout=httpx.Timeout(connect=10.0, read=60.0, write=10.0, pool=10.0),
        follow_redirects=False,
    )
    try:
        upstream = await _open_upstream(client, url, headers)
    except HTTPException:
        await client.aclose()
        raise
    except httpx.HTTPError as e:
        await client.aclose()
        log.warning("ytstream upstream error: %s", e)
        raise HTTPException(502, "Upstream unreachable")
    if upstream.status_code >= 400:
        code = upstream.status_code
        await upstream.aclose()
        await client.aclose()
        log.warning("ytstream upstream status %s", code)
        raise HTTPException(code if code in (403, 404, 410, 416) else 502, "Upstream error")
    ctype = upstream.headers.get("content-type", "")
    media_type = ctype.split(";")[0].strip() if ctype.startswith("audio/") else "audio/mp4"
    out = dict(CORS)
    out["Cache-Control"] = "private, max-age=300"
    for h in PASS_HEADERS:
        v = upstream.headers.get(h)
        if v:
            out[h] = v
    out.setdefault("accept-ranges", "bytes")
    if request.method == "HEAD":
        status = upstream.status_code
        await upstream.aclose()
        await client.aclose()
        return Response(status_code=status, headers=out, media_type=media_type)
    async def body():
        try:
            async for chunk in upstream.aiter_raw(CHUNK):
                yield chunk
        except httpx.HTTPError as e:
            log.warning("ytstream interrupted: %s", e)
        finally:
            await upstream.aclose()
            await client.aclose()
    return StreamingResponse(
        body(),
        status_code=upstream.status_code,
        headers=out,
        media_type=media_type,
    )
