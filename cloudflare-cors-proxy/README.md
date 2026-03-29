# Kytran CORS Proxy

Cloudflare Worker that proxies API requests for Kytran News, adding CORS headers.

## Deploy

```bash
npx wrangler login
npx wrangler deploy
```

## Usage

```
https://cors-proxy.kytranempowerment.com/?url=https://api.gdeltproject.org/api/v2/doc/doc?query=...
```

## Allowed APIs
- GDELT (api.gdeltproject.org, data.gdeltproject.org)
- arXiv (export.arxiv.org)
- NewsAPI (newsapi.org)
- ReliefWeb (api.reliefweb.int)
- ACLED (api.acleddata.com)
