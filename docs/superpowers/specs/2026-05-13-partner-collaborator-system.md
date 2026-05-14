# Partner / Collaborator System

**Date:** 2026-05-13
**Task:** #2690 — Project Alpha
**Scope:** Full partner onboarding system — admin wizard, COLLABORATOR accounts, scoped A.R.C.H.I.E. chat, cosmetic subdomain, fleet node contribution.

---

## Context

COLLABORATOR role (Level 15) is already defined in `rbac.py` as "Invited partner — shared access, own agent, no admin." The `user_invites` table and invite routes (`POST /api/invites`) already exist in Account Center. A.R.C.H.I.E. Chat already scopes conversations by `user_id`. The fleet node system (Headscale mesh, remote_nodes table, DHQ Fleet tab) already handles hardware registration. What's missing is the admin wizard that ties it all together, the `partner_profiles` table, the subdomain provisioning step, and the partner welcome/onboarding screen.

**Approach:** Admin wizard in Account Center — Kytran fills one 3-step form per partner. Everything else (subdomain, invite, fleet) flows from that single entry point.

---

## Data

### New table: `partner_profiles`

```sql
CREATE TABLE IF NOT EXISTS partner_profiles (
    id SERIAL PRIMARY KEY,
    user_id INTEGER REFERENCES users(id),
    slug VARCHAR(50) UNIQUE NOT NULL,
    display_name VARCHAR(100) NOT NULL,
    invited_by INTEGER REFERENCES users(id),
    npm_proxy_host_id INTEGER,
    fleet_node_id INTEGER REFERENCES remote_nodes(id),
    onboarding_complete BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_partner_profiles_user_id ON partner_profiles(user_id);
CREATE INDEX IF NOT EXISTS idx_partner_profiles_slug ON partner_profiles(slug);
```

### Alter `user_invites`

Add `partner_profile_id` FK so the invite token can be traced back to the partner stub:

```sql
ALTER TABLE user_invites ADD COLUMN IF NOT EXISTS partner_profile_id INTEGER REFERENCES partner_profiles(id);
```

---

## Backend

### 1. New route file: `platform_v2/tools/account_center/partner_routes.py`

Register as `register_partner_routes(bp, admin_required)` — ADR-045 pattern.

**Endpoints:**

#### `POST /api/admin/partners` (admin required)
Body: `{"email": "...", "display_name": "...", "slug": "..."}`

Logic:
1. Validate slug is unique in `partner_profiles` and URL-safe (`[a-z0-9-]+`)
2. Create `partner_profiles` stub row (user_id=NULL until invite accepted)
3. Call NPM API to create proxy host: `{slug}.kytranempowerment.com` → `192.168.1.200:3000`
   - Store returned `npm_proxy_host_id` in partner_profiles
   - No advanced_config needed — proxy forwards directly to port 3000, same platform serves all routes
4. Call existing invite logic: insert into `user_invites` with `role='COLLABORATOR'`, `subscription_tier='guest'`, `partner_profile_id=<new_id>`
5. Send invite email via Stalwart (existing `send_invite_email()` helper)
6. Return: `{"partner_profile_id": ..., "subdomain": "{slug}.kytranempowerment.com", "invite_sent": true}`

#### `GET /api/admin/partners` (admin required)
Returns all partner_profiles with user join (email, last_login, onboarding_complete, fleet_node_id).

#### `PATCH /api/admin/partners/<int:id>` (admin required)
Body: `{"fleet_node_id": <remote_nodes.id>}` — links a fleet node to a partner profile after their hardware connects.

#### `DELETE /api/admin/partners/<int:id>` (admin required)
- Deactivates the user (`is_active=FALSE`)
- Revokes NPM proxy host (NPM API DELETE)
- Sets `partner_profiles` row inert (keep for audit)

### 2. Extend `/accept-invite` flow in `account_center/routes.py`

After a COLLABORATOR invite is accepted and user row created:
- Set `partner_profiles.user_id = new_user.id` WHERE `partner_profile_id` matches invite token
- Redirect to `/partner-welcome` instead of `/` for COLLABORATOR role

### 3. New public route: `GET /partner-welcome`

Renders `templates/partner_welcome.html`. Accessible only to authenticated COLLABORATOR users with `onboarding_complete=FALSE`.

On "Enter Platform" button → `POST /api/partner/onboarding-complete` → sets `partner_profiles.onboarding_complete=TRUE` → redirect to `/`.

#### `POST /api/partner/onboarding-complete` (login required, COLLABORATOR only)

Sets `partner_profiles.onboarding_complete = TRUE` for `current_user.id`.

### 4. A.R.C.H.I.E. Chat context injection — `tools/archie_chat/api_routes.py`

When `current_user.role_value == 15`, prepend to the system prompt:

```python
if getattr(current_user, 'role_value', 0) == 15:
    with get_db_cursor() as (conn, cur):
        cur.execute(
            "SELECT p.display_name, u.username FROM partner_profiles p "
            "JOIN users u ON p.invited_by = u.id WHERE p.user_id = %s",
            (current_user.id,)
        )
        row = cur.fetchone()
    if row:
        partner_context = (
            f"You are speaking with {row['display_name']}, "
            f"an invited collaborator of {row['username']}. "
            "Greet them warmly and assist with their creative and business needs."
        )
        system_prompt = partner_context + "\n\n" + system_prompt
```

### 5. Register in `account_center/__init__.py`

```python
from .partner_routes import register_partner_routes
register_partner_routes(account_center_bp, admin_required)
```

---

## Frontend

### 1. Partner welcome page — `templates/partner_welcome.html`

Standalone page (no full nav) shown after first login:
- Greeting: "Welcome, {display_name}. You've been invited to collaborate on the A.R.C.H.I.E. platform."
- Your subdomain: `{slug}.kytranempowerment.com` with copy button
- Optional fleet node section (collapsible): shows Headscale join command for their OS
- "Enter Platform" button → POST to `/api/partner/onboarding-complete` → redirect `/`

Style: dark LCARS aesthetic matching `demo_expired.html` but welcoming.

### 2. Admin wizard in Account Center — "PARTNERS" section in Overview tab

Add after the DEMO LINKS section. UI:
- "Add Partner" button → opens 3-step LCARS modal (`bm-overlay`, amber `#f59e0b` accent)
  - **Step 1:** Display name + email + auto-suggested slug (editable, validates uniqueness via `GET /api/admin/partners/check-slug?slug=...`)
  - **Step 2:** Preview `{slug}.kytranempowerment.com`, confirm NPM will be provisioned
  - **Step 3:** Review + Send — button calls `POST /api/admin/partners`
- Partners table: display_name, subdomain, status (pending/active), fleet node (linked/none), actions (link node, revoke)

### 3. Slug validation endpoint

`GET /api/admin/partners/check-slug?slug=<value>` (admin required) — returns `{"available": true/false}`. Called on input debounce in the wizard.

---

## Modules visible to COLLABORATOR (Level 15)

Already configured in `module_registry.py`:
- `archie_chat` — A.R.C.H.I.E. Chat (confirmed COLLABORATOR access, PR #687)
- `media_studio` — Media Studio (confirmed COLLABORATOR access, PR #687)

No changes needed to module registry.

---

## NPM Integration

Uses the same NPM API pattern established for `store.kytranempowerment.com`:
- `POST /api/nginx/proxy-hosts` via `http://nginx_proxy_manager:81/api` from inside Docker
- Credentials from `NPM_ADMIN_EMAIL` + `NPM_ADMIN_PASSWORD` env vars
- SSL: deferred — admin enables via NPM UI after creation (wildcard cert for `*.kytranempowerment.com` would handle this permanently, but that's out of scope)

---

## Fleet Node Linking

No new infrastructure. Flow:
1. Partner follows Headscale join instructions shown on welcome screen
2. Their node appears in `remote_nodes` table (existing fleet heartbeat system)
3. Kytran sees node in DHQ Fleet tab, identifies it by hostname
4. Kytran calls `PATCH /api/admin/partners/<id>` with `fleet_node_id` to link it
5. Partner node appears in fleet dispatch pool automatically (existing routing)

---

## Files Changed

| File | Action |
|------|--------|
| `database/migrations/380_partner_profiles.sql` | Create `partner_profiles` table + alter `user_invites` |
| `platform_v2/tools/account_center/partner_routes.py` | **Create** — 5 endpoints |
| `platform_v2/tools/account_center/__init__.py` | Register partner_routes |
| `platform_v2/tools/account_center/routes.py` | Extend accept-invite to set partner user_id + redirect |
| `platform_v2/app.py` | Add `GET /partner-welcome` route |
| `platform_v2/templates/partner_welcome.html` | **Create** |
| `platform_v2/tools/archie_chat/api_routes.py` | COLLABORATOR context injection into system prompt |
| `platform_v2/templates/tools/account_center.html` | PARTNERS admin section + wizard modal |

---

## Out of Scope

- Custom AI agent persona per partner (they use scoped A.R.C.H.I.E., not a custom agent)
- Per-partner billing or resource quotas
- Partner-facing fleet management UI
- Wildcard SSL cert for `*.kytranempowerment.com` (manual SSL via NPM UI per subdomain)
- Partner ability to invite sub-partners

---

## Testing

1. Kytran opens Account Center → Add Partner → fills wizard → sends invite
2. Partner receives invite email → clicks link → sets password → lands on partner-welcome
3. Partner-welcome shows subdomain URL + fleet instructions → clicks "Enter Platform"
4. Partner sees only A.R.C.H.I.E. Chat + Media Studio in dashboard
5. Partner opens A.R.C.H.I.E. Chat → first message includes personalized greeting
6. Partner visits `{slug}.kytranempowerment.com` → same platform, same session
7. Partner connects hardware → Kytran links node via PATCH endpoint → node appears in fleet
8. Kytran revokes partner → user deactivated, NPM host removed, subdomain stops resolving
