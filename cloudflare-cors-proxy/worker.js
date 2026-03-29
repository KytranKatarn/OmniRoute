/**
 * Kytran CORS Proxy — Cloudflare Worker
 * Proxies requests to APIs that block CORS (GDELT, etc.)
 *
 * Usage: https://cors-proxy.kytranempowerment.com/?url=https://api.gdeltproject.org/...
 */

const ALLOWED_ORIGINS = [
  'https://news.kytranempowerment.com',
  'https://kytranempowerment.com',
  'http://192.168.1.200:3000',
  'http://localhost:3000',
];

const ALLOWED_API_HOSTS = [
  'api.gdeltproject.org',
  'data.gdeltproject.org',
  'export.arxiv.org',
  'newsapi.org',
  'api.reliefweb.int',
  'api.acleddata.com',
];

export default {
  async fetch(request, env) {
    // Handle CORS preflight
    if (request.method === 'OPTIONS') {
      return handlePreflight(request);
    }

    const url = new URL(request.url);
    const targetUrl = url.searchParams.get('url');

    if (!targetUrl) {
      return new Response(JSON.stringify({ error: 'Missing ?url= parameter' }), {
        status: 400,
        headers: { 'Content-Type': 'application/json' },
      });
    }

    // Validate target URL
    try {
      const target = new URL(targetUrl);
      if (!ALLOWED_API_HOSTS.some(host => target.hostname.endsWith(host))) {
        return new Response(JSON.stringify({ error: 'Host not allowed' }), {
          status: 403,
          headers: { 'Content-Type': 'application/json' },
        });
      }
    } catch {
      return new Response(JSON.stringify({ error: 'Invalid URL' }), {
        status: 400,
        headers: { 'Content-Type': 'application/json' },
      });
    }

    // Fetch from target API
    try {
      const response = await fetch(targetUrl, {
        method: request.method,
        headers: {
          'User-Agent': 'KytranNews/1.0',
          'Accept': 'application/json',
        },
      });

      const body = await response.text();
      const origin = request.headers.get('Origin') || '';
      const corsOrigin = ALLOWED_ORIGINS.includes(origin) ? origin : ALLOWED_ORIGINS[0];

      return new Response(body, {
        status: response.status,
        headers: {
          'Content-Type': response.headers.get('Content-Type') || 'application/json',
          'Access-Control-Allow-Origin': corsOrigin,
          'Access-Control-Allow-Methods': 'GET, OPTIONS',
          'Access-Control-Allow-Headers': 'Content-Type',
          'Access-Control-Max-Age': '86400',
          'Cache-Control': 'public, max-age=300',
          'X-Proxied-By': 'kytran-cors-proxy',
        },
      });
    } catch (err) {
      return new Response(JSON.stringify({ error: 'Proxy fetch failed', detail: err.message }), {
        status: 502,
        headers: { 'Content-Type': 'application/json' },
      });
    }
  },
};

function handlePreflight(request) {
  const origin = request.headers.get('Origin') || '';
  const corsOrigin = ALLOWED_ORIGINS.includes(origin) ? origin : ALLOWED_ORIGINS[0];

  return new Response(null, {
    status: 204,
    headers: {
      'Access-Control-Allow-Origin': corsOrigin,
      'Access-Control-Allow-Methods': 'GET, OPTIONS',
      'Access-Control-Allow-Headers': 'Content-Type',
      'Access-Control-Max-Age': '86400',
    },
  });
}
