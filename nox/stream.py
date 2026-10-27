from fastapi import APIRouter, Query, HTTPException
from fastapi.responses import StreamingResponse
import httpx

router = APIRouter()

@router.get("/api/ytstream")
async def yt_stream(url: str = Query(...)):
    headers = {
        "User-Agent": "com.google.android.youtube/19.09.37 (Linux; U; Android 11) gzip",
        "Accept": "*/*",
        "Accept-Language": "en-US,en;q=0.9",
        "Origin": "https://www.youtube.com",
        "Referer": "https://www.youtube.com/",
        "Connection": "keep-alive"
    }
    
    async def streamer():
        async with httpx.AsyncClient(timeout=30.0) as client:
            req = client.build_request("GET", url, headers=headers)
            r = await client.send(req, stream=True)
            
            if r.status_code not in (200, 206):
                raise HTTPException(status_code=r.status_code, detail="Upstream failed")
                
            async for chunk in r.aiter_bytes(chunk_size=64*1024):
                yield chunk
            await r.aclose()

    return StreamingResponse(streamer(), media_type="audio/mp4")
