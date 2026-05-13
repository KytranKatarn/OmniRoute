# Security Network: Login Anomaly Detection + IP Allowlisting + Module Visibility

**Date:** 2026-05-13
**Task:** #2675 — Project Alpha
**Scope:** Three independent hardening measures for admin platform access.

---

## Context

- `test_vip` account logged in 20+ times in one day with no alert fired
- Platform has no successful-login anomaly detection (failed-login lockout exists)
- NPM proxy has no IP restriction on `platform.kytranempowerment.com`
- All AI Command modules require ADMIN — partners cannot access A.R.C.H.I.E. Chat or Media Studio

---

## Part 1: Login Anomaly Detection

### Data source
`audit_log` table, `action = 'login_success'`. Already has 2,684 events. No new tables needed.

Schema confirmed: `user_id` (int), `ip_address` (varchar direct column), `created_at` (timestamp). JOIN `users` on `user_id` to get `username`.

```sql
SELECT a.user_id, u.username, COUNT(*) AS login_count,
       array_agg(DISTINCT a.ip_address) AS ips,
       MIN(a.created_at) AS first_login,
       MAX(a.created_at) AS last_login
FROM audit_log a
JOIN users u ON a.user_id = u.id
WHERE a.action = 'login_success'
  AND a.created_at >= NOW() - INTERVAL '24 hours'
GROUP BY a.user_id, u.username
HAVING COUNT(*) >= %(threshold)s
```

### New autonomy job
File: `ai_bridge/agent_loop.py`

**Function:** `_run_login_anomaly_check()`
**Schedule:** Every 30 minutes (same pattern as other alert jobs)
**Job name for `autonomy_loop_log`:** `login_anomaly_check`

**Logic:**
1. Run the query above with threshold from `system_config` key `login_anomaly_threshold` (fallback: 10), collecting all users over threshold.
2. For each user with `count >= LOGIN_ANOMALY_THRESHOLD` (default: 10, stored in `system_config` key `login_anomaly_threshold` with fallback 10):
   a. Check `system_config` for key `anomaly_alert_{user_id}` — if present and set within last 24h, skip (rate-limit).
   b. Send Telegram alert via `telegram_service.send_alert(...)`:
      ```
      🔐 LOGIN ANOMALY DETECTED
      User: {username} (id={user_id})
      Logins in 24h: {count}
      IPs: {ip_list}
      Window: {earliest} → {latest}
      ```
   c. Upsert `system_config` key `anomaly_alert_{user_id}` = current UTC timestamp.
3. Log one `autonomy_loop_log` row per cycle (items_processed = users checked, items_failed = alerts fired).

**Threshold config:** Admin can adjust via `POST /api/system/config` — no new UI needed; V.I.G.I.L. can set via MCP if needed.

---

## Part 2: IP Allowlisting via NPM

### NPM API access
Available at `http://nginx_proxy_manager:81/api` from inside the container.
Credentials: `NPM_ADMIN_EMAIL` env var + `NPM_ADMIN_PASSWORD` env var (verify at implementation).

### Setup script (run once)
File: `scripts/setup_npm_ip_allowlist.py`

Steps:
1. `POST /api/tokens` → get JWT token
2. `POST /api/access-lists` → create access list named "Admin Platform Allowlist" with:
   - `pass_auth: false`
   - IP addresses from `system_config` key `admin_ip_allowlist` (JSON array)
   - Fallback: if key missing, print instructions and exit
3. `GET /api/proxy-hosts` → find the host where `domain_names` contains `platform.kytranempowerment.com`
4. `PUT /api/proxy-hosts/{id}` → set `access_list_id` to the created list's ID

### IP list seeding
Before running the script, admin sets `system_config` key `admin_ip_allowlist` via:
```sql
INSERT INTO system_config (key, value) VALUES ('admin_ip_allowlist', '["x.x.x.x", "y.y.y.y"]')
ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value;
```
or via the platform's config API.

### Result
`platform.kytranempowerment.com` returns 403 to any IP not in the allowlist. NPM handles enforcement — no platform code change.

---

## Part 3: Module Visibility

### Change
File: `platform_v2/module_registry.py`

Two modules change from `minimum_role="ADMIN"` to `minimum_role="COLLABORATOR"`:

| Module | Route | Change |
|--------|-------|--------|
| `archie_chat` | `/tools/archie-chat` | ADMIN → COLLABORATOR |
| `media_studio` | `/tools/media-studio` | ADMIN → COLLABORATOR |

All other modules unchanged.

### Role tiers (clarification)
- `USER` (10): Family — sees Applications (fitness, therapy, doc, family_tree, media_hub)
- `COLLABORATOR` (15): Business partners — additionally sees A.R.C.H.I.E. Chat + Media Studio
- `ADMIN` (90): Kytran — sees everything

### Validation
After deploy: log in as a COLLABORATOR-role test account and verify the dashboard shows archie_chat and media_studio but NOT department_hq, repair_bay, consciousness, backup_manager.

---

## Files Changed

| File | Action |
|------|--------|
| `ai_bridge/agent_loop.py` | Add `_run_login_anomaly_check()` + schedule |
| `scripts/setup_npm_ip_allowlist.py` | New one-time setup script |
| `platform_v2/module_registry.py` | 2 minimum_role changes |

---

## Out of Scope

- Invite/onboarding flow for family/partners (→ task #2690)
- UI for managing the IP allowlist (future — Security Network tab)
- UI for adjusting the anomaly threshold (configurable via system_config, no UI needed)
- Blocking suspicious IPs automatically (existing auto-block feature handles this)

---

## Testing

1. **Anomaly detection:** Insert 11 `login_success` rows into `audit_log` for a test user, wait for next job cycle (or trigger manually), verify Telegram message received.
2. **IP allowlist:** From a non-allowlisted IP, attempt to reach `https://platform.kytranempowerment.com` — should get 403. From an allowlisted IP — should load normally.
3. **Module visibility:** Log in as COLLABORATOR-role account — verify archie_chat and media_studio appear in dashboard, Repair Bay and DHQ do not.
