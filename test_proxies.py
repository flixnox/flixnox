import asyncio
import httpx

async def check_proxy(proxy, session):
    proxy_url = f"http://{proxy}"
    try:
        r = await session.get("http://www.gstatic.com/generate_204", proxy=proxy_url, timeout=10.0)
        if r.status_code in (200, 204):
            return proxy
    except Exception:
        pass
    return None

async def main():
    try:
        with open("proxies.txt", "r") as f:
            proxies = [line.strip() for line in f if line.strip()]
    except FileNotFoundError:
        print("proxies.txt nahi mili!")
        return

    print(f"Total {len(proxies)} proxies check ho rahi hain...")
    alive = []
    sem = asyncio.Semaphore(40)
    
    async with httpx.AsyncClient() as session:
        async def limited_check(p):
            async with sem:
                return await check_proxy(p, session)
                
        tasks = [limited_check(p) for p in proxies]
        
        for i, coro in enumerate(asyncio.as_completed(tasks)):
            res = await coro
            if res:
                alive.append(res)
                print(f"✅ Alive: {res}")
            if (i+1) % 100 == 0:
                print(f"Checked {i+1}/{len(proxies)}...")

    with open("alive_proxies.txt", "w") as f:
        f.write("\n".join(alive))
        
    print(f"\n✅ Total Alive: {len(alive)}")
    print("Alive proxies 'alive_proxies.txt' me save ho gayi hain.")

if __name__ == "__main__":
    asyncio.run(main())
