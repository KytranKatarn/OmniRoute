# OAuth/SSO Audit & Fix — All Standalone Products

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix "Connect with Kytran Empowerment" SSO login across all standalone products after the archie.→platform. domain rename.

**Architecture:** All standalone products use the KytranAuth SDK (`kytran_auth.py`) for OAuth against the ARCHIE platform at `platform.kytranempowerment.com`. The flow is: product → `/auth/kytran/login` → platform `/oauth/authorize` → user logs in → callback `/auth/kytran/callback` → token exchange → userinfo + entitlement check → local session. Products on the hub need `dns: 192.168.1.200` in docker-compose so containers can resolve subdomains via AdGuard. VPS products use Caddy on 76.13.107.109.

**Tech Stack:** Flask, KytranAuth SDK, PostgreSQL (oauth_clients table), Docker, NPM proxy (hub), Caddy (VPS)

**Reference implementation:** KSO at `/mnt/archie_brain/kytran-server-manager/` — working end-to-end.

---

## What KSO Does Right (Reference)

KSO works because:
1. `kytran_auth.py` is in the project as a reusable SDK module
2. `register_auth_routes(app)` calls `kytran_auth.init_app(app)` inside auth.py
3. `on_login` callback creates/updates local user + calls `login_user()`
4. Public routes whitelist includes `kytran_login`, `kytran_callback`
5. docker-compose has `dns: 192.168.1.200` so container resolves subdomains
6. KYTRAN_AUTH_URL uses `https://platform.kytranempowerment.com` (was fixed this session from `http://192.168.1.200:3000`)
7. Login template has "Connect with Kytran Empowerment" button with `href="/auth/kytran/login"`
8. No service worker blocking navigation

## Current State (from this session's audit)

| Product | Location | Port | OAuth Client | Status | Issues |
|---------|----------|------|-------------|--------|--------|
| Platform | hub | 3000 | — | WORKING | — |
| KSO | hub | 8085 | kso | WORKING | — |
| KBS | hub | 8091 | kbs | BROKEN | kytran_auth added this session but button click doesn't navigate (service worker cache + no on_login callback) |
| Market Watch | VPS | 8101 | market-watch-viewer | BROKEN | Needs auth audit |
| Civic Watch | VPS | 8099 | civic-watch | BROKEN | Needs auth audit |
| Legal Watch | VPS | 8100 | legal-watch | BROKEN | Needs auth audit |
| Gov Watch | VPS | 8102 | gov-watch | BROKEN | Needs auth audit |
| The News | VPS | 8103 | news-watch | BROKEN | Needs auth audit |

## oauth_clients DB Table (verified this session)

```
client_id        | redirect_uri                                                   | is_active
-----------------+----------------------------------------------------------------+----------
kso              | https://server.kytranempowerment.com/auth/kytran/callback       | t
kbs              | https://business.kytranempowerment.com/auth/kytran/callback     | t
market-watch-viewer | https://market.kytranempowerment.com/auth/kytran/callback    | t
civic-watch      | https://civic.kytranempowerment.com/auth/kytran/callback       | t
legal-watch      | https://legal.kytranempowerment.com/auth/kytran/callback       | t
gov-watch        | https://gov.kytranempowerment.com/auth/kytran/callback         | t
news-watch       | https://thenews.kytranempowerment.com/auth/kytran/callback     | t
```

---

### Task 1: Fix KBS — Complete the SSO Integration

**Files:**
- Modify: `/mnt/archie_brain/kytran-business-suite/core/auth.py` (add KytranAuth init + on_login callback)
- Modify: `/mnt/archie_brain/kytran-business-suite/core/app.py` (remove standalone KytranAuth init — move to auth.py)
- Modify: `/mnt/archie_brain/kytran-business-suite/shared/templates/login.html` (match KSO login design)
- Verify: `/mnt/archie_brain/kytran-business-suite/core/tenant.py` (public routes whitelist)
- Verify: `/mnt/archie_brain/kytran-business-suite/.env` (KYTRAN_* vars)

**Context:** KytranAuth was added to KBS this session but the button click doesn't navigate. Root causes:
1. KytranAuth.init_app() was called in app.py but KSO does it inside auth.py's register_auth_routes()
2. No `on_login` callback — after OAuth, there's no local user creation or Flask-Login session
3. Service worker was caching old pages (unregister added but may need hard refresh)
4. Login template doesn't match KSO design (missing logo, different layout)

- [ ] **Step 1: Read KSO auth.py lines 350-410 for the on_login pattern**

Reference: `/mnt/archie_brain/kytran-server-manager/kytran_system_operations/auth.py:357-400`
The callback creates/updates a local user with `sso_provider='kytran'`, calls `login_user()`, and syncs subscription tier.

- [ ] **Step 2: Remove KytranAuth init from app.py**

In `/mnt/archie_brain/kytran-business-suite/core/app.py`, remove the 4 lines added this session:
```python
# DELETE THESE LINES:
    from core.kytran_auth import KytranAuth
    kytran_auth = KytranAuth()
    kytran_auth.init_app(app)
```

- [ ] **Step 3: Add KytranAuth init + on_login to auth.py**

In `/mnt/archie_brain/kytran-business-suite/core/auth.py`, add at module level:
```python
from core.kytran_auth import KytranAuth
kytran_auth = KytranAuth()
```

Then add a `register_kytran_auth(app)` function that:
1. Calls `kytran_auth.init_app(app)`
2. Defines `@kytran_auth.on_login` callback that:
   - Looks up user by email with `sso_provider='kytran'`
   - Creates user if not found (with random password hash, sso_provider='kytran')
   - Creates tenant if needed (or assigns to default)
   - Calls `login_user(user)` and sets `session["tenant_id"]`
3. Call this function from app.py after auth_bp registration

KBS uses PostgreSQL (not SQLite like KSO), so queries use `%s` params not `?`.
KBS has tenant isolation — users need a tenant_users row.

- [ ] **Step 4: Wire register_kytran_auth into app.py**

```python
    from core.auth import auth_bp, init_login_manager, register_kytran_auth
    init_login_manager(app)
    app.register_blueprint(auth_bp, url_prefix="/auth")
    register_kytran_auth(app)
```

- [ ] **Step 5: Update login template to match KSO design**

Replace `/mnt/archie_brain/kytran-business-suite/shared/templates/login.html` login form section to include:
- Local login form (email + password)
- "or" divider
- "Connect with Kytran Empowerment" button as `<a href="/auth/kytran/login">`
- Match KSO's CSS styling (`.login-btn-sso` class pattern)

- [ ] **Step 6: Verify tenant.py PUBLIC_ROUTES**

Confirm `kytran_login` and `kytran_callback` are in the PUBLIC_ROUTES frozenset (already added this session).

- [ ] **Step 7: Rebuild and test**

```bash
docker compose build kytran-business-suite
docker compose up -d kytran-business-suite
# Wait 5s for startup
# Test: nc to 192.168.1.200:8091 GET /auth/kytran/login — should 302 to platform.kytranempowerment.com/oauth/authorize
# Test: browser https://business.kytranempowerment.com/auth/login — click SSO button
```

- [ ] **Step 8: Commit**

```bash
git add kytran-business-suite/
git commit -m "feat: KBS Kytran SSO — on_login callback + login template matching KSO"
```

---

### Task 2: Audit & Fix VPS Watch Products OAuth

**Files:**
- Source directories on hub (build from here, deploy to VPS):
  - Market Watch: find via `grep -B5 'kytran_market' /mnt/archie_brain/docker-compose.yml`
  - Civic/Legal/Gov/News: similar grep patterns
- VPS docker-compose at deployment path
- Each product's `.env` file
- Each product's auth module

**Context:** Watch products run on VPS (76.13.107.109). They use Caddy for SSL, not NPM. Their KYTRAN_AUTH_URL may still point to `http://192.168.1.200:3000` (internal IP unreachable from VPS). They need to use `https://platform.kytranempowerment.com` or the mesh IP `http://100.64.0.1:3000`.

- [ ] **Step 1: Find Watch product source directories**

```bash
# Check docker-compose for build paths
grep -B3 'kytran_market\|kytran_watch\|kytran_civic\|kytran_legal\|kytran_gov\|kytran_news' /mnt/archie_brain/docker-compose.yml
# Check for standalone directories
find /mnt/archie_brain -maxdepth 2 -name '*.py' -path '*watch*' -o -name '*.py' -path '*civic*' -o -name '*.py' -path '*legal*' -o -name '*.py' -path '*news*' | head -20
```

- [ ] **Step 2: For each product, audit auth files**

For each of Market Watch, Civic Watch, Legal Watch, Gov Watch, The News:
1. Does `kytran_auth.py` exist?
2. What is KYTRAN_AUTH_URL in .env?
3. What is KYTRAN_CLIENT_ID?
4. Does the login template have SSO button?
5. Are auth routes whitelisted from login_required?

- [ ] **Step 3: Fix KYTRAN_AUTH_URL in all .env files**

Must be `https://platform.kytranempowerment.com` (NOT `http://192.168.1.200:3000` — unreachable from VPS).

For VPS products that use mesh: can also use `http://100.64.0.1:3000` but HTTPS subdomain is more reliable.

- [ ] **Step 4: Verify kytran_auth.py exists in each product**

If missing, copy from `/mnt/archie_brain/kytran-auth/kytran_auth.py` (the shared SDK).

- [ ] **Step 5: Verify login templates have SSO button**

Each should have the "Connect with Kytran Empowerment" button linking to `/auth/kytran/login`.

- [ ] **Step 6: Deploy fixes to VPS**

```bash
# For each product, rebuild and push to VPS
# Method depends on deployment setup (docker push, git push, scp)
```

- [ ] **Step 7: Test each product**

```bash
for domain in market civic legal gov thenews; do
  echo "=== $domain ==="
  curl -sk -o /dev/null -w '%{http_code} %{redirect_url}' "https://$domain.kytranempowerment.com/auth/kytran/login"
done
```

- [ ] **Step 8: Commit**

```bash
git add .
git commit -m "fix: update KYTRAN_AUTH_URL to platform.kytranempowerment.com across all Watch products"
```

---

### Task 3: Add UFW Rules for All Hub Standalone Ports

**Context:** KBS was broken because port 8091 wasn't in UFW. Other hub products may have the same issue.

- [ ] **Step 1: Audit current UFW rules vs required ports**

```bash
sudo ufw status | grep -E '3000|3002|8085|8086|8091'
```

Required ports:
- 3000: Platform (should exist)
- 3002: archie_comms (added last session)
- 8085: KSO
- 8086: C.R.E.E.D.
- 8091: KBS (added this session)

- [ ] **Step 2: Add any missing UFW rules**

```bash
sudo ufw allow 3002/tcp comment "archie_comms"
sudo ufw allow 8085/tcp comment "KSO"
sudo ufw allow 8086/tcp comment "CREED"
# 8091 already added this session
```

- [ ] **Step 3: Commit docker-compose.yml with dns changes**

The docker-compose.yml has an uncommitted `dns: 192.168.1.200` change for KBS. Commit it.

---

### Task 4: Verify End-to-End OAuth Flow

- [ ] **Step 1: Test platform OAuth provider endpoints**

```bash
# Authorize endpoint exists
curl -s -o /dev/null -w '%{http_code}' 'https://platform.kytranempowerment.com/oauth/authorize?client_id=kbs&redirect_uri=https://business.kytranempowerment.com/auth/kytran/callback&response_type=code&state=test'
# Should return 302 to login or 200 authorize page

# Token endpoint exists
curl -s -o /dev/null -w '%{http_code}' -X POST 'https://platform.kytranempowerment.com/oauth/token'
# Should return 400 (missing params), not 404

# Userinfo endpoint exists
curl -s -o /dev/null -w '%{http_code}' 'https://platform.kytranempowerment.com/oauth/userinfo'
# Should return 401 (no token), not 404
```

- [ ] **Step 2: Full browser test for KBS**

1. Open https://business.kytranempowerment.com/auth/login
2. Click "Connect with Kytran Empowerment"
3. Should redirect to platform login
4. Log in with admin credentials
5. Should redirect back to KBS dashboard
6. Verify session has kytran_user data

- [ ] **Step 3: Full browser test for each Watch product**

Repeat step 2 for civic, legal, market, gov, thenews subdomains.

---

## Key Lessons from This Session

1. **dns: 192.168.1.200** required in docker-compose for any container calling subdomains
2. **UFW must allow ports** — Docker bypasses UFW for direct container access, but NPM proxy goes through host networking
3. **Service workers can cache old pages** — unregister or disable during development
4. **KytranAuth on_login callback is essential** — without it, OAuth completes but no Flask-Login session is created
5. **PUBLIC_ROUTES must include kytran_login + kytran_callback** — tenant/auth middleware blocks them otherwise
6. **KYTRAN_AUTH_URL must use https://platform.kytranempowerment.com** — not http://192.168.1.200:3000 (containers can't resolve internal IPs without DNS config)
