# NPM Restore + OAuth Fix + DNS Cleanup + Security Network Restoration

**Date:** 2026-04-07
**Status:** Approved
**Project:** Unified Product Auth (#214) + new infrastructure project

---

## Problem

NPM (Nginx Proxy Manager) was previously running on hub (.200), managing 26 reverse proxy hosts with SSL termination for all `*.kytranempowerment.com` subdomains. It went down and was never restored, causing:

1. **OAuth login broken** on all 4 watch products (market, civic, legal, gov) — the browser redirect to `https://archie.kytranempowerment.com/oauth/authorize` hits a dead endpoint (port 443 not listening)
2. **Security Network module features offline** — NPM health check fails, proxy host management non-functional
3. **All hub-pointed subdomains dead over HTTPS** — archie, consciousness, business, server, adguard, brainstorm, etc.
4. **5 DNS records stale** — pointing to old hub IP 142.169.21.199 instead of current 153.68.195.85
5. **KytranAuth SDK design flaw** — uses public HTTPS URL for server-to-server calls (token exchange, userinfo) instead of internal URL

## Existing Infrastructure (Intact)

| Component | Location | Status |
|-----------|----------|--------|
| NPM data directory | `/mnt/HomeLab/nginx-proxy/data/` | Intact — SQLite DB, 26 proxy configs |
| SSL certificates | `/mnt/HomeLab/nginx-proxy/letsencrypt/` | Intact — archie cert valid until May 19 2026 |
| Old compose reference | `migrations/from-192.168.1.250/compose/reverse-proxy-stack/docker-compose.yml` | Image: `jc21/nginx-proxy-manager:2.14.0` |
| NPM service client | `platform_v2/tools/security_network/npm_service.py` | Built — expects NPM at `http://192.168.1.200:81/api` |
| NPM env vars | `docker-compose.yml` lines 97-99 | Configured (`NPM_API_URL`, `NPM_ADMIN_EMAIL`, `NPM_ADMIN_PASSWORD`) |
| OAuth provider | `platform_v2/oauth_provider.py` + `oauth_userinfo.py` | Functional — `/oauth/authorize`, `/oauth/token`, `/oauth/userinfo` |
| OAuth clients | `oauth_clients` DB table | 10 clients registered (market, civic, legal, gov, news, kbs, kso, etc.) |
| KytranAuth SDK | `kytran_auth.py` in each product | Deployed — uses `KYTRAN_AUTH_URL` for all calls |

### 26 Existing Proxy Hosts (from NPM SQLite)

archie, consciousness, bridge, devhq, mesh, webmail, mail-admin, brainstorm, server, business, api, proxy, civic, legal, market, gov, mail, adguard, portainer, mdm, nagios, store, mediahub, *.fleet + others

## Design

### Step 1 — Add NPM container to main docker-compose.yml

Add to the existing `docker-compose.yml` on hub:

```yaml
nginx-proxy-manager:
  image: 'jc21/nginx-proxy-manager:2.14.0'
  container_name: nginx_proxy_manager
  restart: unless-stopped
  mem_limit: 1g
  cpus: 1.0
  cap_drop:
    - ALL
  cap_add:
    - NET_BIND_SERVICE
    - DAC_OVERRIDE
    - CHOWN
    - SETGID
    - SETUID
  ports:
    - '80:80'
    - '443:443'
    - '127.0.0.1:81:81'  # Admin panel on localhost only
  volumes:
    - /mnt/HomeLab/nginx-proxy/data:/data
    - /mnt/HomeLab/nginx-proxy/letsencrypt:/etc/letsencrypt
  networks:
    - archie_net
```

Note: Port 81 bound to localhost only for security (admin panel not exposed externally).

### Step 2 — Start NPM, verify restoration

- `docker compose up -d nginx-proxy-manager` (only starts this one container)
- Verify NPM admin panel accessible at `http://192.168.1.200:81`
- Verify all 26 proxy hosts loaded from SQLite DB
- Test `https://archie.kytranempowerment.com` reaches ARCHIE platform
- Test Security Network module shows NPM as healthy (green badge)

### Step 3 — Fix stale DNS records

Update via Hostinger API:

| Subdomain | Current (wrong) | New (correct) |
|-----------|-----------------|---------------|
| `devhq` | 142.169.21.199 | 153.68.195.85 |
| `mail` | 142.169.21.199 | 153.68.195.85 |
| `mail-admin` | 142.169.21.199 | 153.68.195.85 |
| `webmail` | 142.169.21.199 | 153.68.195.85 |
| `mesh` | 142.169.21.199 | 153.68.195.85 |
| `*.fleet` | 142.169.21.199 | 153.68.195.85 |

### Step 4 — Fix KytranAuth SDK

Modify `kytran_auth.py` to support dual URLs:

- `KYTRAN_AUTH_URL` — public HTTPS URL for browser redirects (unchanged)
- `KYTRAN_AUTH_INTERNAL_URL` — internal URL for server-to-server calls (token exchange, userinfo)

Changes in the SDK:
- Add `self.internal_url` property (falls back to `self.auth_url` if not set)
- Token exchange (`/oauth/token`) uses `self.internal_url`
- Userinfo (`/oauth/userinfo`) uses `self.internal_url`
- Login redirect (`/oauth/authorize`) keeps using `self.auth_url` (browser-facing)

Update copies in all 4 watch products:
- `/mnt/archie_brain/market-watch/kytran_auth.py`
- `/mnt/archie_brain/watch-api/kytran_auth.py` (Civic Watch)
- `/mnt/archie_brain/legal-watch/kytran_auth.py`
- `/mnt/archie_brain/kytran-gov-watch/kytran_auth.py`

Also update the template: `/mnt/archie_brain/kytran-auth/kytran_auth.py`

### Step 5 — Test OAuth flow end-to-end

1. Navigate to `https://market.kytranempowerment.com`
2. Click "Sign In with Kytran"
3. Should redirect to `https://archie.kytranempowerment.com/oauth/authorize` (now alive)
4. Log in on ARCHIE
5. Callback should exchange token and load dashboard
6. Repeat for civic, legal, gov

### Step 6 — Dev HQ tracking

- Create project for NPM restoration + DNS cleanup
- Create tasks for each step
- Log decisions
- Update project understanding

## Out of Scope

- VPS changes (watch products already deployed and running)
- New proxy host creation (all 26 exist)
- Cert renewal (archie cert valid until May 19)
- Kytran News auth (separate task #1585 in project #214)

## Risks

- **docker-compose.yml modification** triggers potential rebuild of other containers if not careful — use `docker compose up -d nginx-proxy-manager` to only start the new service
- **Port 80/443 conflicts** — verify no other process is binding these ports on the hub
- **SSL cert auto-renewal** — NPM handles this automatically once running, but some certs may have expired during downtime and need manual renewal via NPM admin
- **DNS propagation** — stale record updates may take up to 5 minutes (TTL 300s)
