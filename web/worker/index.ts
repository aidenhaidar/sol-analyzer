/// <reference types="@cloudflare/workers-types" />
/**
 * Edge entry point. Static assets come from the ASSETS binding; anything under
 * /api is forwarded to the API on AWS with a shared-secret header so the origin
 * only answers requests that came through this Worker.
 */
export interface Env {
  ASSETS: Fetcher;
  API_ORIGIN: string;
  API_SHARED_SECRET?: string;
}

// Edge cache TTLs per route family (seconds). Candles and metrics refresh often;
// holder risk is expensive and changes slowly.
const CACHE_TTL: Array<[RegExp, number]> = [
  [/^\/api\/status$/, 60],
  [/^\/api\/search/, 30],
  [/^\/api\/token\//, 10],
  [/^\/api\/chart\//, 5],
  [/^\/api\/metric\//, 5],
  [/^\/api\/risk\//, 60],
  [/^\/api\/cascade\//, 30],
  [/^\/api\/live\//, 0],
];

export default {
  async fetch(request: Request, env: Env, ctx: ExecutionContext): Promise<Response> {
    const url = new URL(request.url);
    // Live holder stream: pass the WebSocket upgrade straight through to the origin,
    // where Caddy routes /ws/* to the sol-stream service.
    if (url.pathname.startsWith('/ws/')) {
      if (request.headers.get('upgrade')?.toLowerCase() !== 'websocket') return new Response('expected websocket', { status: 426 });
      const upstream = new URL(url.pathname + url.search, env.API_ORIGIN);
      const headers = new Headers(request.headers);
      if (env.API_SHARED_SECRET) headers.set('x-api-secret', env.API_SHARED_SECRET);
      return fetch(upstream, { headers, method: 'GET' });
    }
    if (!url.pathname.startsWith('/api/')) return env.ASSETS.fetch(request);
    if (request.method !== 'GET') return new Response('method not allowed', { status: 405 });

    const ttl = CACHE_TTL.find(([re]) => re.test(url.pathname))?.[1] ?? 0;
    const cache = caches.default;
    const cacheKey = new Request(url.toString(), { method: 'GET' });
    if (ttl > 0) {
      const hit = await cache.match(cacheKey);
      if (hit) return withHeader(hit, 'cf-cache', 'HIT');
    }

    const upstream = new URL(url.pathname + url.search, env.API_ORIGIN);
    const headers = new Headers({ accept: 'application/json' });
    if (env.API_SHARED_SECRET) headers.set('x-api-secret', env.API_SHARED_SECRET);
    headers.set('x-forwarded-for', request.headers.get('cf-connecting-ip') ?? '');

    let res: Response;
    try {
      res = await fetch(upstream, { headers, cf: { cacheTtl: 0 } });
    } catch (err) {
      return Response.json({ detail: `api unreachable: ${(err as Error).message}` }, { status: 502 });
    }

    const out = new Response(res.body, res);
    out.headers.set('cache-control', ttl > 0 && res.ok ? `public, max-age=${ttl}` : 'no-store');
    out.headers.set('cf-cache', 'MISS');
    if (ttl > 0 && res.ok) ctx.waitUntil(cache.put(cacheKey, out.clone()));
    return out;
  },
} satisfies ExportedHandler<Env>;

function withHeader(res: Response, k: string, v: string): Response {
  const out = new Response(res.body, res);
  out.headers.set(k, v);
  return out;
}
