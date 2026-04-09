# NPM Restore + OAuth Fix + DNS Cleanup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restore the NPM reverse proxy container on the hub, fix OAuth login for all watch subdomains, clean up stale DNS records, and bring the Security Network module back online.

**Architecture:** NPM was previously running on .200 with 26 proxy hosts, SSL certs, and full config — all data intact at `/mnt/HomeLab/nginx-proxy/`. We restore (not rebuild) by adding the NPM container to the main docker-compose.yml, then fix the KytranAuth SDK to use internal URLs for server-to-server OAuth calls.

**Tech Stack:** Docker (jc21/nginx-proxy-manager:2.14.0), Flask/Python (KytranAuth SDK), Hostinger DNS API, Playwright (testing)

**Spec:** `docs/superpowers/specs/2026-04-07-npm-restore-oauth-fix-design.md`

---

### Task 1: Add NPM container to docker-compose.yml

**Files:**
- Modify: `/mnt/archie_brain/docker-compose.yml` (insert before security scanners, ~line 589)

- [ ] **Step 1: Read current state of docker-compose.yml around insertion point**

Read lines 580-600 of `/mnt/archie_brain/docker-compose.yml` to confirm the insertion point before `security_nmap`.

- [ ] **Step 2: Add NPM service definition**

Insert before the `security_nmap:` service block:

```yaml
  # Nginx Proxy Manager — Reverse proxy + SSL termination for all subdomains
  nginx_proxy_manager:
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
      - '127.0.0.1:81:81'
    volumes:
      - /mnt/HomeLab/nginx-proxy/data:/data
      - /mnt/HomeLab/nginx-proxy/letsencrypt:/etc/letsencrypt
    networks:
      - archie_internal
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:81/api"]
      interval: 30s
      timeout: 10s
      retries: 3
```

- [ ] **Step 3: Validate docker-compose syntax**

Run: `docker compose -f /mnt/archie_brain/docker-compose.yml config --quiet`
Expected: No errors (exit code 0)

- [ ] **Step 4: Commit**

```bash
git add docker-compose.yml
git commit -m "feat: restore NPM reverse proxy container to docker-compose.yml"
```

---

### Task 2: Start NPM and verify restoration

**Files:** None (infrastructure only)

- [ ] **Step 1: Start only the NPM container**

Run: `docker compose up -d nginx_proxy_manager`
Expected: Container starts, pulls image if needed. Other containers untouched.

- [ ] **Step 2: Verify container is running and healthy**

Run: `docker ps --filter name=nginx_proxy_manager --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"`
Expected: Container running with ports 80, 443, 127.0.0.1:81 mapped.

- [ ] **Step 3: Verify NPM admin panel is accessible**

Run: `curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:81/api`
Expected: HTTP 200 or 401 (means NPM API is responding).

- [ ] **Step 4: Verify proxy hosts loaded from SQLite**

Run: `curl -s http://127.0.0.1:81/api/nginx/proxy-hosts | python3 -c "import sys,json; data=json.load(sys.stdin); print(f'{len(data)} proxy hosts loaded')" 2>/dev/null`

Note: This will fail without auth. Use NPM admin panel at `http://192.168.1.200:81` in browser to verify 26 proxy hosts are listed. Credentials are in `.env` (`NPM_ADMIN_EMAIL`, `NPM_ADMIN_PASSWORD`).

- [ ] **Step 5: Test archie.kytranempowerment.com is alive**

Use Playwright: Navigate to `https://archie.kytranempowerment.com`
Expected: ARCHIE platform login page loads over HTTPS.

- [ ] **Step 6: Verify Security Network module sees NPM as healthy**

Navigate to `http://192.168.1.200:3000/tools/security-network` in browser.
Expected: NPM badge shows green/healthy status.

---

### Task 3: Fix stale DNS records

**Files:** None (DNS API calls only)

- [ ] **Step 1: Update devhq DNS record**

Call `mcp__hostinger-api__DNS_updateDNSRecordsV1`:
```json
{
  "domain": "kytranempowerment.com",
  "overwrite": true,
  "zone": [{"name": "devhq", "type": "A", "ttl": 300, "records": [{"content": "153.68.195.85"}]}]
}
```

- [ ] **Step 2: Update mail DNS record**

Call `mcp__hostinger-api__DNS_updateDNSRecordsV1`:
```json
{
  "domain": "kytranempowerment.com",
  "overwrite": true,
  "zone": [{"name": "mail", "type": "A", "ttl": 300, "records": [{"content": "153.68.195.85"}]}]
}
```

- [ ] **Step 3: Update mail-admin DNS record**

Call `mcp__hostinger-api__DNS_updateDNSRecordsV1`:
```json
{
  "domain": "kytranempowerment.com",
  "overwrite": true,
  "zone": [{"name": "mail-admin", "type": "A", "ttl": 300, "records": [{"content": "153.68.195.85"}]}]
}
```

- [ ] **Step 4: Update webmail DNS record**

Call `mcp__hostinger-api__DNS_updateDNSRecordsV1`:
```json
{
  "domain": "kytranempowerment.com",
  "overwrite": true,
  "zone": [{"name": "webmail", "type": "A", "ttl": 300, "records": [{"content": "153.68.195.85"}]}]
}
```

- [ ] **Step 5: Update mesh DNS record**

Call `mcp__hostinger-api__DNS_updateDNSRecordsV1`:
```json
{
  "domain": "kytranempowerment.com",
  "overwrite": true,
  "zone": [{"name": "mesh", "type": "A", "ttl": 300, "records": [{"content": "153.68.195.85"}]}]
}
```

- [ ] **Step 6: Update *.fleet DNS record**

Call `mcp__hostinger-api__DNS_updateDNSRecordsV1`:
```json
{
  "domain": "kytranempowerment.com",
  "overwrite": true,
  "zone": [{"name": "*.fleet", "type": "A", "ttl": 300, "records": [{"content": "153.68.195.85"}]}]
}
```

- [ ] **Step 7: Verify DNS updates**

Call `mcp__hostinger-api__DNS_getDNSRecordsV1` for `kytranempowerment.com`.
Verify all 6 records now show `153.68.195.85`.

---

### Task 4: Fix KytranAuth SDK — add internal URL support

**Files:**
- Modify: `/mnt/archie_brain/kytran-auth/kytran_auth.py` (template)
- Modify: `/mnt/archie_brain/market-watch/kytran_auth.py`
- Modify: `/mnt/archie_brain/watch-api/kytran_auth.py` (Civic Watch)
- Modify: `/mnt/archie_brain/legal-watch/kytran_auth.py`
- Modify: `/mnt/archie_brain/kytran-gov-watch/kytran_auth.py`

- [ ] **Step 1: Modify the template SDK to add internal_url support**

In `/mnt/archie_brain/kytran-auth/kytran_auth.py`, update `init_app` to read the internal URL:

In the `init_app` method, after the line:
```python
self.redirect_uri = app.config.get("KYTRAN_REDIRECT_URI") or os.environ.get("KYTRAN_REDIRECT_URI", "")
```

Add:
```python
self.internal_url = (
    app.config.get("KYTRAN_AUTH_INTERNAL_URL")
    or os.environ.get("KYTRAN_AUTH_INTERNAL_URL", "")
    or self.auth_url
)
```

- [ ] **Step 2: Update token exchange to use internal_url**

In the `kytran_callback` function, change the token exchange URL from:
```python
token_resp = requests.post(
    f"{sdk.auth_url}/oauth/token",
```
to:
```python
token_resp = requests.post(
    f"{sdk.internal_url}/oauth/token",
```

- [ ] **Step 3: Update userinfo to use internal_url**

In the `kytran_callback` function, change the userinfo URL from:
```python
userinfo_resp = requests.get(
    f"{sdk.auth_url}/oauth/userinfo",
```
to:
```python
userinfo_resp = requests.get(
    f"{sdk.internal_url}/oauth/userinfo",
```

- [ ] **Step 4: Also add internal_url to __init__**

In the `__init__` method, add after `self.redirect_uri = None`:
```python
self.internal_url = None
```

- [ ] **Step 5: Copy updated SDK to all 4 watch products**

```bash
cp /mnt/archie_brain/kytran-auth/kytran_auth.py /mnt/archie_brain/market-watch/kytran_auth.py
cp /mnt/archie_brain/kytran-auth/kytran_auth.py /mnt/archie_brain/watch-api/kytran_auth.py
cp /mnt/archie_brain/kytran-auth/kytran_auth.py /mnt/archie_brain/legal-watch/kytran_auth.py
cp /mnt/archie_brain/kytran-auth/kytran_auth.py /mnt/archie_brain/kytran-gov-watch/kytran_auth.py
```

- [ ] **Step 6: Verify .env files have KYTRAN_AUTH_INTERNAL_URL set**

Check each product's `.env` for `KYTRAN_AUTH_INTERNAL_URL`. Should be:
- Market Watch: `KYTRAN_AUTH_INTERNAL_URL=http://172.17.0.1:3000` (already set)
- Civic Watch: Check and add if missing
- Legal Watch: Check and add if missing
- Gov Watch: Check and add if missing

The internal URL is `http://172.17.0.1:3000` for VPS containers (Docker bridge gateway to host, then mesh/direct to hub port 3000).

- [ ] **Step 7: Commit**

```bash
git add kytran-auth/kytran_auth.py market-watch/kytran_auth.py watch-api/kytran_auth.py legal-watch/kytran_auth.py kytran-gov-watch/kytran_auth.py
git commit -m "fix: KytranAuth SDK uses internal URL for server-to-server OAuth calls"
```

---

### Task 5: Redeploy watch products on VPS

**Files:** None (deployment only)

- [ ] **Step 1: Check VPS connectivity**

Run: `ssh kytran@76.13.107.109 'docker ps --format "table {{.Names}}\t{{.Status}}" | grep -E "market|civic|legal|gov"'`
Expected: All 4 watch containers listed.

- [ ] **Step 2: Deploy updated SDK to VPS**

For each product, copy the updated files to VPS and restart:

```bash
# Market Watch
scp /mnt/archie_brain/market-watch/kytran_auth.py kytran@76.13.107.109:~/market-watch/kytran_auth.py

# Civic Watch
scp /mnt/archie_brain/watch-api/kytran_auth.py kytran@76.13.107.109:~/watch-api/kytran_auth.py

# Legal Watch
scp /mnt/archie_brain/legal-watch/kytran_auth.py kytran@76.13.107.109:~/legal-watch/kytran_auth.py

# Gov Watch
scp /mnt/archie_brain/kytran-gov-watch/kytran_auth.py kytran@76.13.107.109:~/kytran-gov-watch/kytran_auth.py
```

Note: Exact VPS paths may differ — verify with `ssh kytran@76.13.107.109 'ls ~/market-watch/'` first.

- [ ] **Step 3: Restart watch containers on VPS**

```bash
ssh kytran@76.13.107.109 'cd ~/market-watch && docker compose restart'
ssh kytran@76.13.107.109 'cd ~/watch-api && docker compose restart'
ssh kytran@76.13.107.109 'cd ~/legal-watch && docker compose restart'
ssh kytran@76.13.107.109 'cd ~/kytran-gov-watch && docker compose restart'
```

- [ ] **Step 4: Verify all 4 products are running after restart**

Run: `ssh kytran@76.13.107.109 'docker ps --format "table {{.Names}}\t{{.Status}}" | grep -E "market|civic|legal|gov"'`
Expected: All 4 containers running with fresh uptime.

---

### Task 6: Test OAuth flow end-to-end

**Files:** None (testing only)

- [ ] **Step 1: Test Market Watch login**

Use Playwright:
1. Navigate to `https://market.kytranempowerment.com`
2. Click "Sign In" button
3. Should redirect to `https://archie.kytranempowerment.com/oauth/authorize?...`
4. ARCHIE login page should load
5. Log in with test credentials (`admin` / `Kyt$13ran2025`)
6. Should redirect back to Market Watch dashboard

Expected: Dashboard loads with authenticated user session.

- [ ] **Step 2: Test Civic Watch login**

Navigate to `https://civic.kytranempowerment.com`, click Sign In.
Expected: Same OAuth flow, redirects to dashboard after auth.

- [ ] **Step 3: Test Legal Watch login**

Navigate to `https://legal.kytranempowerment.com`, click Sign In.
Expected: Same OAuth flow, redirects to dashboard after auth.

- [ ] **Step 4: Test Gov Watch login**

Navigate to `https://gov.kytranempowerment.com`, click Sign In.
Expected: Same OAuth flow, redirects to dashboard after auth.

- [ ] **Step 5: Verify Security Network module**

Navigate to `http://192.168.1.200:3000/tools/security-network`.
1. Check NPM badge is green
2. Navigate to DNS tab — verify AdGuard integration works
3. Check proxy hosts list — should show all 26 hosts

---

### Task 7: Dev HQ tracking + knowledge base updates

**Files:** None (MCP calls only)

- [ ] **Step 1: Create project for NPM restoration**

Call `mcp__archie__create_project`:
- Name: "NPM Reverse Proxy Restoration + DNS Cleanup"
- Type: infrastructure
- Priority: 9

- [ ] **Step 2: Log decision for NPM restoration approach**

Call `mcp__archie__log_decision`:
- Decision: Restore NPM from existing data at /mnt/HomeLab/nginx-proxy/ rather than rebuilding
- Context: All 26 proxy hosts, SSL certs (valid until May 19), and config intact. Port 81 bound to localhost only for security.

- [ ] **Step 3: Log decision for KytranAuth SDK internal URL**

Call `mcp__archie__log_decision`:
- Decision: KytranAuth SDK split into public URL (browser redirects) and internal URL (server-to-server token exchange/userinfo)
- Context: VPS containers can't reach hub HTTPS directly. Internal URL uses Docker bridge gateway or mesh IP.

- [ ] **Step 4: Store mistake learned**

Call `mcp__archie__store_memory`:
- Type: mistake_learned
- Title: "NPM going down silently breaks OAuth + all hub HTTPS subdomains"
- Content: When NPM container stops, all 26 proxy hosts go dead including archie.kytranempowerment.com which is the OAuth provider. This breaks login for all standalone products. Add NPM to health monitoring and alerting.

- [ ] **Step 5: Update session handoff**

Update `project_session-handoff.md` with what was done this session.
