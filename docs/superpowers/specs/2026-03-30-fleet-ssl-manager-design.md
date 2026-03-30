# Fleet SSL Manager — Design Spec

**Date:** 2026-03-30
**Project:** #193 — Kytran System Operations
**Task:** #1408 — Fleet SSL Manager
**Status:** Design approved

---

## Overview

An agent loop job on the hub that automatically obtains and renews a `*.kytranempowerment.com` wildcard SSL cert via DNS-01 challenge using Hostinger's DNS API (pure Python), then serves it to fleet nodes via a pull endpoint.

## Architecture

```
Hub (agent loop job, Autonomy module)
  1. Check cert expiry (runs daily at 03:00 UTC)
  2. If <30 days to expiry → renew:
     a. Generate CSR via Python acme/cryptography libraries
     b. Create _acme-challenge TXT record via Hostinger DNS API
     c. Complete ACME challenge → receive cert
     d. Clean up TXT record
     e. Save cert to /opt/archie-fleet/certs/wildcard/
  3. Serve cert via /api/fleet/certs/wildcard

Fleet nodes (KSO)
  1. On startup + every 12h: GET /api/fleet/certs/wildcard/check
  2. Compare hash with local cert
  3. If newer → GET /api/fleet/certs/wildcard → save, reload proxy
```

## Component 1: Cert Manager Module (`ai_bridge/cert_manager.py`)

Pure Python ACME client that handles the full DNS-01 challenge flow.

### Dependencies
- `acme` — ACME protocol client (from Let's Encrypt's `certbot` package)
- `cryptography` — CSR/key generation
- `josepy` — JOSE/JWS for ACME (dependency of `acme`)
- `requests` — Hostinger DNS API calls

### ACME DNS-01 Flow

1. **Load or create account key** — RSA 2048, stored at `/opt/archie-fleet/certs/account.key`
2. **Register with Let's Encrypt** — or load existing registration. Use production directory (`https://acme-v02.api.letsencrypt.org/directory`). Store registration URI.
3. **Request certificate** for `*.kytranempowerment.com` — create new order
4. **Get DNS-01 challenge** — extract token and key authorization
5. **Create TXT record** — POST to Hostinger DNS API: `_acme-challenge.kytranempowerment.com` with the challenge digest value
6. **Wait for DNS propagation** — poll DNS every 10s for up to 2 minutes, verifying TXT record resolves
7. **Answer challenge** — tell ACME server the challenge is ready
8. **Poll for issuance** — wait for order to transition to `valid` state
9. **Download certificate chain** — save `fullchain.pem` (cert + intermediates)
10. **Clean up** — DELETE the TXT record from Hostinger DNS
11. **Save files** — `fullchain.pem` + `privkey.pem` to `/opt/archie-fleet/certs/wildcard/`

### Hostinger DNS API Integration

Uses Hostinger DNS API directly via `requests` (not MCP — agent loop runs outside Flask context):

- `GET /api/dns/v1/zones/{domain}/records` — list existing records
- `PUT /api/dns/v1/zones/{domain}/records` — update DNS records (add TXT)
- `DELETE /api/dns/v1/zones/{domain}/records` — remove challenge TXT

Auth: Bearer token from `HOSTINGER_API_TOKEN` env var.

### Public Functions

```python
def check_cert_expiry(cert_path: str) -> int:
    """Return days until cert expires. -1 if cert doesn't exist."""

def renew_wildcard_cert(domain: str, cert_dir: str) -> tuple[bool, str]:
    """Run full ACME DNS-01 flow. Returns (success, message)."""

def get_cert_info(cert_dir: str) -> dict:
    """Return cert metadata: expires_at, sha256, domain, issuer."""
```

### Cert Storage

```
/opt/archie-fleet/certs/
  account.key               — ACME account RSA private key
  account.uri               — ACME registration URI (text file)
  wildcard/
    fullchain.pem           — certificate + intermediates
    privkey.pem             — private key
    cert-meta.json          — {expires_at, sha256, renewed_at, domain}
```

## Component 2: Agent Loop Job (Autonomy Module)

### Job Registration

New agent loop job registered in the Autonomy module's job list:

- **Job ID:** 61 (next available)
- **Name:** `_renew_fleet_ssl`
- **Schedule:** Daily at 03:00 UTC
- **Owner:** Security & Compliance (V.I.G.I.L.)
- **Tier:** 1 (auto-approve — no human approval needed)

### Job Logic

```python
def _renew_fleet_ssl(self):
    """Job #61: Renew wildcard SSL cert if expiring within 30 days."""
    from ai_bridge.cert_manager import check_cert_expiry, renew_wildcard_cert

    cert_dir = "/opt/archie-fleet/certs/wildcard"
    days_left = check_cert_expiry(os.path.join(cert_dir, "fullchain.pem"))

    if days_left > 30:
        logger.info(f"[SSL] Wildcard cert valid for {days_left} more days, skipping renewal")
        return

    logger.info(f"[SSL] Cert expires in {days_left} days, starting renewal...")
    success, message = renew_wildcard_cert("kytranempowerment.com", cert_dir)

    if success:
        logger.info(f"[SSL] Renewal successful: {message}")
    else:
        logger.error(f"[SSL] Renewal failed: {message}")
        # Only notify on failure — no spam
        from database import get_db_cursor
        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                """INSERT INTO system_notifications
                   (type, title, message, source, priority, visibility, is_read, created_at)
                   VALUES ('error', 'SSL Renewal Failed', %s, 'agent_loop', 'high', 'admin', FALSE, NOW())""",
                (message,),
            )
```

## Component 3: Hub API — Cert Serving Endpoints

Added to `platform_v2/tools/starbase/fleet_routes.py`:

### Endpoints

```
GET /api/fleet/certs/wildcard/check
  — Lightweight metadata check
  — Auth: X-Node-API-Key header
  — Returns: {success, expires_at, sha256, domain}

GET /api/fleet/certs/wildcard
  — Full cert download
  — Auth: X-Node-API-Key header
  — Returns: {success, cert_pem, key_pem, expires_at, sha256}
```

### Security
- Authenticated via existing node API key (same as heartbeat)
- Private key is transmitted — must be over mesh VPN (100.64.x.x) only
- Consider: reject requests from non-mesh IPs (check `request.remote_addr` starts with `100.64.`)

## Component 4: KSO Cert Sync Service

New service in KSO: `kytran-server-manager/kytran_server_manager/services/cert_service.py`

### Functions

```python
def check_and_sync_cert() -> bool:
    """Check hub for newer cert, download if available. Returns True if updated."""

def get_local_cert_info() -> dict:
    """Return local cert metadata (sha256, expires_at)."""
```

### Sync Logic

1. Call `GET /api/fleet/certs/wildcard/check` on hub
2. Compare `sha256` with local cert hash
3. If different: call `GET /api/fleet/certs/wildcard`, save files
4. If cert changed: reload proxy (Caddy API call or signal)

### Schedule
- On KSO startup (in `app.py` after init)
- Every 12 hours via background thread or APScheduler

### Local Storage
```
/opt/archie-fleet/certs/wildcard/
  fullchain.pem
  privkey.pem
```

## Error Handling

| Scenario | Behavior |
|----------|----------|
| Hostinger DNS API unreachable | Retry 3x with 30s backoff, then log error notification |
| ACME challenge fails | Log error, keep TXT record (for debugging), retry next day |
| DNS propagation timeout (>2min) | Fail gracefully, retry next day |
| Cert file missing on hub | API returns 404, node continues with existing cert |
| Node can't reach hub | Keeps existing cert, retries next 12h cycle |
| Private key file permissions | `chmod 600` on write, owned by app user |
| Let's Encrypt rate limit | 5 certs per week per domain — daily job with 30-day threshold prevents this |

## Docker Volume Mount

Hub `docker-compose.yml` needs the cert directory mounted:

```yaml
# In archie_platform volumes:
- /opt/archie-fleet/certs:/opt/archie-fleet/certs:ro
```

The cert_manager writes directly to `/opt/archie-fleet/certs/` on the host (agent loop runs as a thread inside the container, but the directory is volume-mounted rw from the host).

Actually, since agent_loop runs inside the Docker container, the cert_manager needs write access. Mount as `:rw`:

```yaml
- /opt/archie-fleet/certs:/opt/archie-fleet/certs:rw
```

## Testing Strategy

| Test | Method | Verification |
|------|--------|-------------|
| Cert expiry check | Unit test with mock cert | Returns correct days |
| ACME account creation | Integration test against LE staging | Account key + URI saved |
| DNS TXT record create | Call Hostinger API | Record visible via dig |
| DNS TXT record cleanup | Call Hostinger API | Record removed |
| Full renewal (staging) | End-to-end against LE staging | Cert files written |
| Cert serve endpoint | curl hub API with node key | Returns PEM data |
| Cert check endpoint | curl hub API | Returns metadata |
| KSO sync | Deploy on outpost, trigger sync | Cert matches hub |
| Non-mesh rejection | curl from non-100.64.x.x IP | Returns 403 |

Use Let's Encrypt **staging** directory for all testing (`https://acme-staging-v02.api.letsencrypt.org/directory`). Switch to production only after end-to-end works.

## Not in Scope

- Per-node individual certs (wildcard covers all subdomains)
- Non-Hostinger DNS providers
- GUI for cert management (logs visible in Autonomy module)
- Certs for non-kytranempowerment.com domains
- OCSP stapling (handled by proxy)
- Automatic proxy reload on hub (NPM handles its own certs)
