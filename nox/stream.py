import httpx
from fastapi import APIRouter, Query
from fastapi.responses import StreamingResponse

router = APIRouter()

@router.get("/api/ytstream")
async def yt_stream(url: str = Query(...)):
    headers = {
        "User-Agent": "com.google.android.youtube/19.09.37 (Linux; U; Android 11) gzip",
        "Accept": "*/*"
    }
    async def streamer():
        async with httpx.AsyncClient() as client:
            async with client.stream("GET", url, headers=headers, follow_redirects=True, timeout=30) as r:
                if r.status_code not in (200, 206):
                    return
                async for chunk in r.aiter_bytes(chunk_size=64*1024):
                    yield chunk
    
    return StreamingResponse(streamer(), media_type="audio/mp4")
