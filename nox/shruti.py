import httpx
from . import config

HEADERS = {
    "Authorization": f"Bearer {config.SHRUTI_API_KEY}",
    "Accept": "application/json"
}

async def api_call(endpoint: str, params: dict = None):
    url = f"{config.SHRUTI_API_URL}/{endpoint.lstrip('/')}"
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            r = await client.get(url, params=params, headers=HEADERS)
            if r.status_code == 200:
                return r.json()
    except Exception as e:
        print(f"Shruti API Error: {e}")
    return None
