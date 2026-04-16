# Profile + Subscription Integration — Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix Profile page backend (Connections, Activity), add Subscription tab, add Overview tier card, and create Platform Stats API — the foundation for the entire subscription integration system.

**Architecture:** Profile page (`user_profile.html`, 1,755 lines, inline CSS+JS) gets a 7th Subscription tab reading from `billing_subscriptions`. New DB tables (`user_oauth_connections`, `user_api_keys`) back the Connections tab. A public Stats API endpoint lets the website pull live platform numbers. All changes follow existing patterns: Blueprint routes at `/tools/my-profile/api/*`, LCARS tab structure, `get_db_cursor()` for DB access.

**Tech Stack:** Flask, PostgreSQL, Jinja2, vanilla JS (inline in template), LCARS CSS

**Spec:** `docs/superpowers/specs/2026-04-16-profile-account-center-subscription-design.md`

**Security note:** Code examples in this plan use innerHTML for brevity, matching the existing profile template pattern. During implementation, use the same sanitization approach as the existing template (escaping user-provided strings before insertion). All data rendered is from authenticated API responses (not user-supplied HTML).

---

## File Map

### New Files
| File | Purpose |
|------|---------|
| `platform_v2/migrations/029_subscription_integration.sql` | DB migration: new tables + billing_subscriptions columns |
| `platform_v2/services/subscription_service.py` | Service layer: read entitlements, compute tier, trial logic |

### Modified Files
| File | Changes |
|------|---------|
| `platform_v2/templates/tools/user_profile.html` | Add Subscription tab (7th), "Your Plan" card on Overview, fix Connections tab |
| `platform_v2/tools/user_profile/routes.py` | Add `/api/subscriptions`, `/api/connections` endpoints |
| `platform_v2/app.py` | Add `/api/public/stats` endpoint |

---

## Task 1: DB Migration (MCP Task #2003)

**Files:**
- Create: `platform_v2/migrations/029_subscription_integration.sql`

- [ ] **Step 1: Check the current migration numbering**

```bash
ls platform_v2/migrations/*.sql | tail -5
```

Confirm the next number is 029 (or adjust if higher exists).

- [ ] **Step 2: Write the migration SQL**

Create `platform_v2/migrations/029_subscription_integration.sql`:

```sql
-- Migration 029: Subscription Integration — Phase 1
-- New tables: user_oauth_connections, user_api_keys
-- Modified: billing_subscriptions (trial/override support)

-- 1. user_oauth_connections
CREATE TABLE IF NOT EXISTS user_oauth_connections (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    provider VARCHAR(64) NOT NULL,
    provider_user_id VARCHAR(256),
    email VARCHAR(256),
    display_name VARCHAR(256),
    access_token_encrypted TEXT,
    refresh_token_encrypted TEXT,
    token_expires_at TIMESTAMP,
    connected_at TIMESTAMP DEFAULT NOW(),
    disconnected_at TIMESTAMP,
    UNIQUE(user_id, provider)
);

CREATE INDEX IF NOT EXISTS idx_user_oauth_user_id ON user_oauth_connections(user_id);

-- 2. user_api_keys
CREATE TABLE IF NOT EXISTS user_api_keys (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    key_hash VARCHAR(128) NOT NULL,
    key_prefix VARCHAR(8) NOT NULL,
    product VARCHAR(64) NOT NULL,
    name VARCHAR(128),
    created_at TIMESTAMP DEFAULT NOW(),
    last_used_at TIMESTAMP,
    revoked_at TIMESTAMP,
    UNIQUE(key_hash)
);

CREATE INDEX IF NOT EXISTS idx_user_api_keys_user_id ON user_api_keys(user_id);
CREATE INDEX IF NOT EXISTS idx_user_api_keys_hash ON user_api_keys(key_hash);

-- 3. billing_subscriptions additions (idempotent)
ALTER TABLE billing_subscriptions
    ADD COLUMN IF NOT EXISTS expires_at TIMESTAMP,
    ADD COLUMN IF NOT EXISTS granted_by INTEGER REFERENCES users(id),
    ADD COLUMN IF NOT EXISTS revoked_at TIMESTAMP;

COMMENT ON COLUMN billing_subscriptions.expires_at IS 'Trial expiration. NULL for permanent subscriptions.';
COMMENT ON COLUMN billing_subscriptions.granted_by IS 'Admin who granted trial/override. NULL for Stripe.';
COMMENT ON COLUMN billing_subscriptions.revoked_at IS 'When trial/override was revoked. NULL if active.';
```

- [ ] **Step 3: Run the migration**

```bash
docker exec archie_database psql -U archie -d archie -f /app/migrations/029_subscription_integration.sql
```

Expected: `CREATE TABLE`, `CREATE INDEX`, `ALTER TABLE` with no errors.

- [ ] **Step 4: Verify tables exist**

```bash
docker exec archie_database psql -U archie -d archie -c "\d user_oauth_connections"
docker exec archie_database psql -U archie -d archie -c "\d user_api_keys"
docker exec archie_database psql -U archie -d archie -c "\d billing_subscriptions"
```

Expected: All three tables show correct columns.

- [ ] **Step 5: Commit**

```bash
git add platform_v2/migrations/029_subscription_integration.sql
git commit -m "feat: add subscription integration tables (user_oauth_connections, user_api_keys, billing trial fields)"
```

---

## Task 2: Subscription Service Layer (MCP Task #2005 foundation)

**Files:**
- Create: `platform_v2/services/subscription_service.py`

- [ ] **Step 1: Read the existing service pattern**

Read `platform_v2/services/auth_service.py` (first 50 lines) to see import style, logging, and `get_db_cursor` usage pattern.

- [ ] **Step 2: Create the subscription service**

Create `platform_v2/services/subscription_service.py` with these functions:
- `get_user_subscriptions(user_id)` — returns list of active subscriptions (excludes revoked/expired)
- `get_user_entitlements(user_id, user_role)` — computes effective entitlements map (module → tier/source)
- `get_user_membership_tier(user_id, user_role)` — returns overall tier string (explorer/starter/professional/enterprise/vip/staff)
- `grant_trial(user_id, module, tier_price_id, duration_days, granted_by_user_id)` — creates trial billing_subscriptions row
- `revoke_subscription(subscription_id, revoked_by_user_id)` — sets revoked_at on trial/override rows

Key implementation details:
- Admin bypass: if `user_role in ('admin', 'ADMIN', 'SUPER_ADMIN')` return staff tier with all access
- Query `billing_subscriptions WHERE user_id = %s AND revoked_at IS NULL AND (expires_at IS NULL OR expires_at > NOW()) AND status NOT IN ('canceled', 'revoked')`
- Tier resolution from stripe_price_id: check for 'pro'/'viewer'/'starter'/'enterprise' in the price ID string as fallback
- Trial grant uses `ON CONFLICT (user_id, module) DO UPDATE` for idempotent upsert
- All DB access via `get_db_cursor()` context manager with `commit=True` for writes

- [ ] **Step 3: Commit**

```bash
git add platform_v2/services/subscription_service.py
git commit -m "feat: add subscription service — entitlements, trials, tier resolution"
```

---

## Task 3: Platform Stats API (MCP Task #2004)

**Files:**
- Modify: `platform_v2/app.py`

- [ ] **Step 1: Read app.py API section**

Read `platform_v2/app.py` around lines 407-450 where `/api/*` routes are defined. Note the imports and patterns used.

- [ ] **Step 2: Add the /api/public/stats endpoint**

Add near the existing `/api/` routes in app.py. The endpoint:
- No auth required (public)
- Cached for 5 minutes (module-level dict with timestamp)
- Queries: agent counts by worker_type (non-decommissioned), department count (DISTINCT department), KB entry count
- Gets module count from `module_registry.get_enabled_modules()`
- Returns JSON: `{agents: {total, ai, internal, contractor, departments}, platform: {modules, knowledge_entries, languages: 8}, updated_at}`
- Catches exceptions, returns 503 with error message on failure

- [ ] **Step 3: Deploy and test**

```bash
docker compose restart archie_platform
sleep 5
curl -s http://192.168.1.200:3000/api/public/stats | python3 -m json.tool
```

Expected: JSON with live agent counts, department count, module count, KB entries.

- [ ] **Step 4: Commit**

```bash
git add platform_v2/app.py
git commit -m "feat: add /api/public/stats — live platform stats for website"
```

---

## Task 4: Profile Subscription Tab — Backend (MCP Task #2005)

**Files:**
- Modify: `platform_v2/tools/user_profile/routes.py`

- [ ] **Step 1: Read routes.py to understand existing pattern**

Read `platform_v2/tools/user_profile/routes.py` — note the blueprint name, decorator pattern (`@login_required`), imports, and how existing endpoints like `/api/profile` and `/api/preferences` are structured.

- [ ] **Step 2: Add the /api/subscriptions endpoint**

Add a new route to `routes.py`:
- Route: `@user_profile_bp.route("/api/subscriptions", methods=["GET"])`
- Requires login (`@login_required`)
- Imports from `services.subscription_service`: `get_user_subscriptions`, `get_user_entitlements`, `get_user_membership_tier`
- Gets `current_user.id` and `current_user.role`
- Returns JSON: `{success: true, membership_tier, subscriptions: [...], entitlements: {...}}`
- Error handling: catch Exception, log, return 500

- [ ] **Step 3: Deploy and test**

```bash
docker compose restart archie_platform
```

Test via browser network tab or curl (with auth cookie): `GET /tools/my-profile/api/subscriptions`

Expected: JSON with membership_tier (likely "staff" for admin), subscriptions array, entitlements dict.

- [ ] **Step 4: Commit**

```bash
git add platform_v2/tools/user_profile/routes.py
git commit -m "feat: add profile subscriptions API endpoint"
```

---

## Task 5: Profile Subscription Tab — Frontend (MCP Task #2005)

**Files:**
- Modify: `platform_v2/templates/tools/user_profile.html`

- [ ] **Step 1: Read the tab structure**

Read `platform_v2/templates/tools/user_profile.html`:
- Lines 717-724: tab navigation buttons (find exact structure)
- Lines 782-1055: tab content panels (find the pattern)
- Lines 1064-1100: switchProfileTab() function
- Note how other tabs lazy-load data (e.g., loadPreferences, loadActivity)

- [ ] **Step 2: Add Subscription tab button**

After the last tab button (Activity), add a 7th button for Subscription (icon: `credit-card`). Follow the exact same HTML pattern as existing tab buttons.

- [ ] **Step 3: Add Subscription tab content panel**

After the last tab panel (Activity), add the Subscription tab panel with:
- Membership tier card: badge + description + "Manage Billing" link to `business.kytranempowerment.com/billing`
- Product entitlements grid: auto-fill cards showing each entitled product with source (Subscription/Trial/Admin Grant) and expiry if applicable
- Subscription details table: product, status, source, since date, expires date

- [ ] **Step 4: Add loadSubscriptions() JavaScript function**

In the inline script section, add a function that:
- Fetches `/tools/my-profile/api/subscriptions`
- Renders tier badge with color coding (staff=red, explorer=gray, starter=blue, professional=purple, enterprise=amber, vip=red)
- Renders entitlements as cards (admin users see "Staff Access — All products unlocked")
- Renders subscription details as a table
- Handles empty states gracefully

- [ ] **Step 5: Wire tab switching**

In `switchProfileTab()`, add the lazy-load trigger for the subscription tab (check if content already loaded before fetching).

- [ ] **Step 6: Add minimal CSS**

Add subscription tab styles to the embedded `<style>` section. Follow existing patterns (`.profile-info-card`, `.role-badge`).

- [ ] **Step 7: Deploy and browser test**

```bash
docker compose restart archie_platform
```

Navigate to `http://192.168.1.200:3000/tools/my-profile`, click Subscription tab. Verify tier badge loads, entitlements render, details table shows.

- [ ] **Step 8: Commit**

```bash
git add platform_v2/templates/tools/user_profile.html
git commit -m "feat: add Subscription tab to profile — tier badge, entitlements, details"
```

---

## Task 6: Profile Overview "Your Plan" Card (MCP Task #2006)

**Files:**
- Modify: `platform_v2/templates/tools/user_profile.html`

- [ ] **Step 1: Read Overview tab content**

Read `platform_v2/templates/tools/user_profile.html` lines 782-829 to see the Overview tab structure (Account Details card).

- [ ] **Step 2: Add "Your Plan" card**

After the Account Details card in the Overview tab, add a new card with:
- Amber left border accent
- "Your Plan" heading
- Tier badge (populated from subscription API)
- Product count text
- "View Plan →" button that calls `switchProfileTab('subscription')`

- [ ] **Step 3: Populate in loadProfile()**

In the `loadProfile()` function (around line 1172), after existing profile rendering, add a fetch to `/tools/my-profile/api/subscriptions` that populates the tier badge and product count. Handle errors gracefully (card stays empty, no crash).

- [ ] **Step 4: Deploy and browser test**

```bash
docker compose restart archie_platform
```

Overview tab should show "Your Plan" card with tier badge. "View Plan" button should switch to Subscription tab.

- [ ] **Step 5: Commit**

```bash
git add platform_v2/templates/tools/user_profile.html
git commit -m "feat: add Your Plan card to profile Overview tab"
```

---

## Task 7: Fix Connections Tab (MCP Task #2006)

**Files:**
- Modify: `platform_v2/tools/user_profile/routes.py`
- Modify: `platform_v2/templates/tools/user_profile.html`

- [ ] **Step 1: Read existing Connections tab code**

Read the current Connections tab HTML (around lines 882-926) and the `loadConnectedServices()` JS function (around lines 1455-1466). Understand what it currently tries to do and what's broken.

- [ ] **Step 2: Add /api/connections backend endpoint**

Add to `routes.py` a new endpoint that returns three sections:
- **OAuth connections**: query `user_oauth_connections` for the user (provider, email, display_name, connected_at, active status)
- **Product connections**: check which standalone products the user has active billing_subscriptions for (list of 6 known products with connected/not-connected status)
- **API keys**: query `user_api_keys` for the user (key_prefix, product, name, created_at, last_used_at, active status)

Return as: `{success: true, oauth: [...], products: [...], api_keys: [...]}`

- [ ] **Step 3: Replace Connections tab HTML**

Replace the existing Connections tab content with three sections:
1. OAuth Providers — list with provider name, email, connected/disconnected badge
2. Product Connections — 6 standalone products with active/not-connected badge and URL link
3. API Keys — list with key prefix, product, name, last used, active/revoked badge

- [ ] **Step 4: Add loadConnections() JavaScript**

Replace `loadConnectedServices()` with `loadConnections()` that fetches from the new `/api/connections` endpoint and renders all three sections. Update the tab switch to call `loadConnections()` instead.

- [ ] **Step 5: Deploy and browser test**

```bash
docker compose restart archie_platform
```

Connections tab should show 3 sections. OAuth will be empty for most users. Products shows 6 products. API Keys empty.

- [ ] **Step 6: Commit**

```bash
git add platform_v2/tools/user_profile/routes.py platform_v2/templates/tools/user_profile.html
git commit -m "feat: fix Connections tab — OAuth providers, product connections, API keys"
```

---

## Task 8: Fix Activity Feed (MCP Task #2007)

**Files:**
- Modify: `platform_v2/tools/user_profile/routes.py` (if backend broken)
- Modify: `platform_v2/templates/tools/user_profile.html` (if frontend broken)

- [ ] **Step 1: Diagnose the Activity tab issue**

Read the Activity tab HTML (lines 1004-1055), the `loadActivity()` JS function (lines 1682-1743), and the `/api/activity` route handler. Test the API endpoint:

```bash
curl -s -b cookies.txt http://192.168.1.200:3000/tools/my-profile/api/activity
```

Check for: missing tables, wrong column names, empty responses, 500 errors.

- [ ] **Step 2: Fix identified issue**

Apply fix based on diagnosis. Common issues:
- `user_activity_log` table may not exist (check, create if needed)
- Column names may differ from what the query expects
- Session data may be in `active_sessions` vs `user_sessions`
- Failed logins may be in `auth_events` not `user_activity_log`
- Error handling may be swallowing the actual error

- [ ] **Step 3: Deploy and test**

```bash
docker compose restart archie_platform
```

Activity tab should show last login info, active sessions, and login history.

- [ ] **Step 4: Commit**

```bash
git add platform_v2/tools/user_profile/routes.py platform_v2/templates/tools/user_profile.html
git commit -m "fix: profile Activity tab — correct table/column references"
```

---

## Task 9: Branch, PR, Deploy

- [ ] **Step 1: Create feature branch with all commits**

```bash
git checkout -b feat/profile-subscription-phase1
git push -u origin feat/profile-subscription-phase1
```

Note: If working in a worktree, commits are already on the branch. Just push.

- [ ] **Step 2: Create PR**

```bash
gh pr create --title "feat: Profile Subscription Phase 1 — tabs, stats API, connections" --body "$(cat <<'EOF'
## Summary
- New Subscription tab on profile (7th tab) — tier badge, entitlements, billing link
- Your Plan card on Overview tab with tier badge and View Plan link
- Fixed Connections tab — 3 sections: OAuth providers, product connections, API keys
- Platform Stats API (/api/public/stats) — cached live numbers for website
- Subscription service layer (entitlements, trials, tier resolution)
- DB migration: user_oauth_connections, user_api_keys, billing trial fields

## Project
#266 — Profile + Account Center + Subscription Integration (Phase 1)
Tasks: #2003, #2004, #2005, #2006, #2007

## Test Plan
- [ ] Profile Subscription tab loads tier badge and entitlements
- [ ] Overview tab shows Your Plan card with tier
- [ ] Connections tab shows 3 sections (OAuth, Products, API Keys)
- [ ] Activity tab loads without errors
- [ ] /api/public/stats returns live numbers (no auth required)
- [ ] DB tables created (user_oauth_connections, user_api_keys)
- [ ] billing_subscriptions has new columns (expires_at, granted_by, revoked_at)

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

- [ ] **Step 3: Deploy and full browser verification**

```bash
docker compose restart archie_platform
```

Test checklist at `http://192.168.1.200:3000/tools/my-profile`:
1. Overview tab — "Your Plan" card shows tier
2. Connections tab — 3 sections render
3. Activity tab — no errors
4. Subscription tab — tier badge, entitlements, details table
5. Stats API — `curl http://192.168.1.200:3000/api/public/stats`

- [ ] **Step 4: Mark MCP tasks complete**

```
mcp complete_task #2003 — DB migration verified
mcp complete_task #2004 — Stats API live
mcp complete_task #2005 — Subscription tab working
mcp complete_task #2006 — Overview card + Connections fix
mcp complete_task #2007 — Activity feed fixed
```
