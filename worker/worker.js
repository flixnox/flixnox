// Cloudflare Worker: the only public address of your bot. It hides the Render URL and adds the secret header.
// Variables to set in the Worker settings:  ORIGIN (your Render URL, https://xxx.onrender.com)  and  PROXY_SECRET (encrypted).
export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const p = url.pathname;
    const allowed = p === "/" || p === "/health" || p === "/ws" || p.startsWith("/static/") || p.startsWith("/webhook/");
    if (!allowed || !["GET", "HEAD", "POST"].includes(request.method)) {
      return new Response("Not found", { status: 404 });
    }
    const origin = new URL(env.ORIGIN);
    url.protocol = origin.protocol;
    url.hostname = origin.hostname;
    url.port = origin.port;
    const req = new Request(url.toString(), request);
    req.headers.set("X-Proxy-Secret", env.PROXY_SECRET);
    const isStatic = p.startsWith("/static/") && request.method === "GET";
    const resp = await fetch(req, isStatic ? { cf: { cacheEverything: true, cacheTtl: 31536000 } } : undefined);   // files are versioned (?v=), so long caching is safe
    if (resp.status === 101) return resp;                     // WebSocket upgrade
    const out = new Response(resp.body, resp);
    for (const k of [...out.headers.keys()]) {
      if (/^(rndr-|x-render|server$|x-powered-by)/i.test(k)) out.headers.delete(k);   // don't leak the host
    }
    return out;
  },
};
