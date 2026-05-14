# Partner / Collaborator System Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the full partner onboarding system — admin wizard, partner_profiles table, COLLABORATOR account creation, cosmetic subdomain via NPM, A.R.C.H.I.E. Chat context injection, and partner welcome screen.

**Architecture:** One new table (`partner_profiles`) anchors partner identity. An admin wizard in Account Center runs the full setup flow. A `before_request` hook redirects new COLLABORATOR users to `/partner-welcome` until onboarding is complete. A.R.C.H.I.E. Chat injects partner context into the system prompt when role_value == 15.

**Tech Stack:** Flask, PostgreSQL, Flask-Login, NPM API (nginx-proxy-manager), Jinja2, vanilla JS, existing LCARS bm-overlay modals.

---

## File Map

| File | Action |
|------|--------|
| `database/migrations/382_partner_profiles.sql` | Create `partner_profiles` + alter `user_invites` |
| `platform_v2/tools/account_center/partner_routes.py` | **Create** — 5 admin endpoints |
| `platform_v2/tools/account_center/__init__.py` | Register partner_routes |
| `platform_v2/app.py` | Extend `accept_invite` + add partner-welcome before_request + route |
| `platform_v2/templates/partner_welcome.html` | **Create** — welcome/onboarding page |
| `platform_v2/tools/archie_chat/api_routes.py` | COLLABORATOR system prompt injection |
| `platform_v2/templates/tools/account_center.html` | PARTNERS admin section + 3-step wizard modal |

---

### Task 1: DB Migration — partner_profiles

**Files:**
- Create: `database/migrations/382_partner_profiles.sql`

- [ ] **Step 1: Create the migration file**

```sql
-- 382_partner_profiles.sql
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

ALTER TABLE user_invites ADD COLUMN IF NOT EXISTS partner_profile_id INTEGER REFERENCES partner_profiles(id);
```

- [ ] **Step 2: Apply the migration**

```bash
docker exec archie_database psql -U archie -d archie -c "
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
ALTER TABLE user_invites ADD COLUMN IF NOT EXISTS partner_profile_id INTEGER REFERENCES partner_profiles(id);
"
```

Expected: `CREATE TABLE`, `CREATE INDEX` (x2), `ALTER TABLE`

- [ ] **Step 3: Verify**

```bash
docker exec archie_database psql -U archie -d archie -c "\d partner_profiles"
docker exec archie_database psql -U archie -d archie -c "\d user_invites" | grep partner
```

Expected: 9-column table; `partner_profile_id` column in user_invites.

- [ ] **Step 4: Commit**

```bash
git checkout -b feat/partner-collaborator-system
git add database/migrations/382_partner_profiles.sql
git commit -m "feat(partners): migration 382 — partner_profiles table"
```

---

### Task 2: partner_routes.py — 5 admin endpoints

**Files:**
- Create: `platform_v2/tools/account_center/partner_routes.py`

**Context:**
- `admin_required` is passed as a parameter (same pattern as `demo_routes.py`)
- NPM API is at `http://nginx_proxy_manager:81/api` from inside Docker; credentials from `NPM_ADMIN_EMAIL` + `NPM_ADMIN_PASSWORD` env vars
- `_send_invite_email()` is defined in `account_center/routes.py` at line 558 — import it
- `admin_required` defined in `account_center/routes.py` at line 29

- [ ] **Step 1: Create the file**

```python
"""Partner/Collaborator admin routes."""
import json
import re
import secrets
import urllib.error
import urllib.request
from datetime import datetime, timedelta

from flask import current_app, request
from flask_login import current_user

from database import get_db_cursor


def _npm_token():
    """Get NPM JWT token using env credentials."""
    import os

    email = os.getenv("NPM_ADMIN_EMAIL", "")
    password = os.getenv("NPM_ADMIN_PASSWORD", "")
    data = json.dumps({"identity": email, "secret": password}).encode()
    req = urllib.request.Request(
        "http://nginx_proxy_manager:81/api/tokens",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    resp = urllib.request.urlopen(req, timeout=10)
    return json.loads(resp.read())["token"]


def _npm_create_proxy_host(slug):
    """Create NPM proxy host for {slug}.kytranempowerment.com → port 3000."""
    tok = _npm_token()
    headers = {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}
    payload = {
        "domain_names": [f"{slug}.kytranempowerment.com"],
        "forward_scheme": "http",
        "forward_host": "192.168.1.200",
        "forward_port": 3000,
        "ssl_forced": False,
        "allow_websocket_upgrade": True,
    }
    req = urllib.request.Request(
        "http://nginx_proxy_manager:81/api/nginx/proxy-hosts",
        data=json.dumps(payload).encode(),
        headers=headers,
        method="POST",
    )
    resp = json.loads(urllib.request.urlopen(req, timeout=10).read())
    return resp.get("id")


def _npm_delete_proxy_host(host_id):
    """Delete an NPM proxy host by ID."""
    try:
        tok = _npm_token()
        req = urllib.request.Request(
            f"http://nginx_proxy_manager:81/api/nginx/proxy-hosts/{host_id}",
            headers={"Authorization": f"Bearer {tok}"},
            method="DELETE",
        )
        urllib.request.urlopen(req, timeout=10)
    except Exception as e:
        current_app.logger.warning("NPM delete host %s failed: %s", host_id, e)


def register_partner_routes(bp, admin_required):
    """Register partner admin routes on the account_center blueprint."""

    @bp.route("/api/admin/partners/check-slug")
    @admin_required
    def partner_check_slug():
        slug = request.args.get("slug", "").strip().lower()
        if not re.match(r"^[a-z0-9-]{2,50}$", slug):
            return {"available": False, "reason": "Slug must be 2-50 lowercase letters, numbers, or hyphens"}
        with get_db_cursor() as (conn, cur):
            cur.execute("SELECT id FROM partner_profiles WHERE slug = %s", (slug,))
            exists = cur.fetchone()
        return {"available": not exists}

    @bp.route("/api/admin/partners", methods=["POST"])
    @admin_required
    def partner_create():
        """Create partner profile, provision NPM subdomain, send invite."""
        data = request.get_json(silent=True) or {}
        email = (data.get("email") or "").strip().lower()
        display_name = (data.get("display_name") or "").strip()[:100]
        slug = (data.get("slug") or "").strip().lower()

        if not email or "@" not in email:
            return {"error": "Valid email required"}, 400
        if not display_name:
            return {"error": "Display name required"}, 400
        if not re.match(r"^[a-z0-9-]{2,50}$", slug):
            return {"error": "Slug must be 2-50 lowercase letters, numbers, or hyphens"}, 400

        with get_db_cursor() as (conn, cur):
            cur.execute("SELECT id FROM partner_profiles WHERE slug = %s", (slug,))
            if cur.fetchone():
                return {"error": "Slug already taken"}, 409

        # 1. Create partner_profiles stub (user_id null until invite accepted)
        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                """INSERT INTO partner_profiles (slug, display_name, invited_by)
                   VALUES (%s, %s, %s) RETURNING id""",
                (slug, display_name, current_user.id),
            )
            profile_id = cur.fetchone()["id"]

        # 2. Provision NPM proxy host
        npm_host_id = None
        try:
            npm_host_id = _npm_create_proxy_host(slug)
            with get_db_cursor(commit=True) as (conn, cur):
                cur.execute(
                    "UPDATE partner_profiles SET npm_proxy_host_id = %s WHERE id = %s",
                    (npm_host_id, profile_id),
                )
        except Exception as e:
            current_app.logger.warning("NPM host creation failed for %s: %s", slug, e)

        # 3. Send invite via existing user_invites system
        token = secrets.token_urlsafe(32)
        expires_at = datetime.utcnow() + timedelta(days=7)
        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                """INSERT INTO user_invites
                       (email, role, subscription_tier, token, expires_at, invited_by,
                        status, partner_profile_id)
                   VALUES (%s, 'COLLABORATOR', 'guest', %s, %s, %s, 'pending', %s)
                   RETURNING id""",
                (email, token, expires_at, current_user.id, profile_id),
            )

        # 4. Send invite email using existing helper
        try:
            from tools.account_center.routes import _send_invite_email

            base_url = request.host_url.rstrip("/")
            invite_link = f"{base_url}/accept-invite?token={token}"
            _send_invite_email(
                to_email=email,
                invite_link=invite_link,
                inviter_name=current_user.username,
                message=f"You've been invited to collaborate on the A.R.C.H.I.E. platform. Your workspace will be at {slug}.kytranempowerment.com",
            )
            email_sent = True
        except Exception as e:
            current_app.logger.error("Invite email failed for %s: %s", email, e)
            email_sent = False

        return {
            "partner_profile_id": profile_id,
            "subdomain": f"{slug}.kytranempowerment.com",
            "npm_host_id": npm_host_id,
            "invite_sent": email_sent,
        }

    @bp.route("/api/admin/partners")
    @admin_required
    def partner_list():
        """List all partner profiles with user info."""
        with get_db_cursor() as (conn, cur):
            cur.execute(
                """
                SELECT p.id, p.slug, p.display_name, p.npm_proxy_host_id,
                       p.fleet_node_id, p.onboarding_complete, p.created_at,
                       u.email, u.last_login, u.is_active
                FROM partner_profiles p
                LEFT JOIN users u ON p.user_id = u.id
                ORDER BY p.created_at DESC
                """
            )
            rows = cur.fetchall()
        return {
            "partners": [
                {
                    "id": r["id"],
                    "slug": r["slug"],
                    "display_name": r["display_name"],
                    "subdomain": f"{r['slug']}.kytranempowerment.com",
                    "email": r["email"],
                    "last_login": r["last_login"].isoformat() if r["last_login"] else None,
                    "is_active": r["is_active"],
                    "onboarding_complete": r["onboarding_complete"],
                    "fleet_node_id": r["fleet_node_id"],
                    "created_at": r["created_at"].isoformat() if r["created_at"] else None,
                }
                for r in rows
            ]
        }

    @bp.route("/api/admin/partners/<int:partner_id>", methods=["PATCH"])
    @admin_required
    def partner_update(partner_id):
        """Link a fleet node to a partner profile."""
        data = request.get_json(silent=True) or {}
        fleet_node_id = data.get("fleet_node_id")
        if fleet_node_id is None:
            return {"error": "fleet_node_id required"}, 400
        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                "UPDATE partner_profiles SET fleet_node_id = %s WHERE id = %s RETURNING id",
                (fleet_node_id, partner_id),
            )
            if not cur.fetchone():
                return {"error": "Partner not found"}, 404
        return {"updated": True, "partner_id": partner_id}

    @bp.route("/api/admin/partners/<int:partner_id>", methods=["DELETE"])
    @admin_required
    def partner_revoke(partner_id):
        """Deactivate partner: disable user, delete NPM host."""
        with get_db_cursor() as (conn, cur):
            cur.execute(
                "SELECT user_id, npm_proxy_host_id FROM partner_profiles WHERE id = %s",
                (partner_id,),
            )
            row = cur.fetchone()
        if not row:
            return {"error": "Partner not found"}, 404

        if row["user_id"]:
            with get_db_cursor(commit=True) as (conn, cur):
                cur.execute("UPDATE users SET is_active = FALSE WHERE id = %s", (row["user_id"],))

        if row["npm_proxy_host_id"]:
            _npm_delete_proxy_host(row["npm_proxy_host_id"])

        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                "UPDATE partner_profiles SET npm_proxy_host_id = NULL WHERE id = %s",
                (partner_id,),
            )

        return {"revoked": True, "partner_id": partner_id}
```

- [ ] **Step 2: Syntax check**

```bash
python3 -c "import ast; ast.parse(open('/mnt/archie_brain/platform_v2/tools/account_center/partner_routes.py').read()); print('Syntax OK')"
```

Expected: `Syntax OK`

- [ ] **Step 3: Commit**

```bash
git add platform_v2/tools/account_center/partner_routes.py
git commit -m "feat(partners): partner_routes.py — 5 admin endpoints"
```

---

### Task 3: Register partner_routes in account_center/__init__.py

**Files:**
- Modify: `platform_v2/tools/account_center/__init__.py`

**Context:** Current last lines of `__init__.py`:
```python
from .routes import admin_required
from .demo_routes import register_demo_routes
register_demo_routes(account_center_bp, admin_required)
```

- [ ] **Step 1: Add import and registration**

Append to end of `platform_v2/tools/account_center/__init__.py`:
```python
from .partner_routes import register_partner_routes

register_partner_routes(account_center_bp, admin_required)
```

- [ ] **Step 2: Restart and verify**

```bash
docker compose restart archie_platform && sleep 8
docker exec archie_platform python3 -c "
import sys; sys.path.insert(0,'/app')
from app import app
rules = [r.rule for r in app.url_map.iter_rules() if 'partner' in r.rule]
print('Partner routes:', rules)
"
```

Expected: 5 routes including `/tools/account-center/api/admin/partners*`

- [ ] **Step 3: Commit**

```bash
git add platform_v2/tools/account_center/__init__.py
git commit -m "feat(partners): register partner_routes in account_center blueprint"
```

---

### Task 4: Extend accept_invite + partner-welcome redirect

**Files:**
- Modify: `platform_v2/app.py`

**Context:**
- `accept_invite()` is at `app.py:1363`
- After user creation at line ~1415 (`new_user_id = cur.fetchone()[0]`), need to link partner profile
- After commit at line ~1420, instead of redirecting to login for COLLABORATORs, log them in and redirect to `/partner-welcome`
- Add a `before_request` hook that redirects COLLABORATOR users with `onboarding_complete=FALSE` to `/partner-welcome`
- Add `GET /partner-welcome` route
- Add `POST /api/partner/onboarding-complete` route

**Part A — Extend accept_invite:**

- [ ] **Step 1: Read lines 1408-1424 of app.py to confirm current structure**

```bash
sed -n '1408,1424p' /mnt/archie_brain/platform_v2/app.py
```

- [ ] **Step 2: Replace the success block in accept_invite**

Find this block (around lines 1408-1424):
```python
                        invite_id, email, role, tier = invite[0], invite[1], invite[2], invite[3]
                        pw_hash = generate_password_hash(password)
                        cur.execute(
                            """INSERT INTO users (username, email, password_hash, role, subscription_tier, is_active)
                               VALUES (%s, %s, %s, %s, %s, true) RETURNING id""",
                            (username, email, pw_hash, role, tier),
                        )
                        new_user_id = cur.fetchone()[0]
                        cur.execute(
                            "UPDATE user_invites SET status='accepted', accepted_at=NOW(), accepted_user_id=%s WHERE id=%s",
                            (new_user_id, invite_id),
                        )
                        conn.commit()
                        cur.close()
                        conn.close()
                        flash("Account created! You can now log in.", "success")
                        return redirect(url_for("login"))
```

Replace with:
```python
                        invite_id, email, role, tier = invite[0], invite[1], invite[2], invite[3]
                        pw_hash = generate_password_hash(password)
                        cur.execute(
                            """INSERT INTO users (username, email, password_hash, role, subscription_tier, is_active)
                               VALUES (%s, %s, %s, %s, %s, true) RETURNING id""",
                            (username, email, pw_hash, role, tier),
                        )
                        new_user_id = cur.fetchone()[0]
                        cur.execute(
                            "UPDATE user_invites SET status='accepted', accepted_at=NOW(), accepted_user_id=%s WHERE id=%s",
                            (new_user_id, invite_id),
                        )
                        # Link partner profile if this is a COLLABORATOR invite
                        cur.execute(
                            "SELECT partner_profile_id FROM user_invites WHERE id = %s",
                            (invite_id,),
                        )
                        inv_row = cur.fetchone()
                        if inv_row and inv_row[0]:
                            cur.execute(
                                "UPDATE partner_profiles SET user_id = %s WHERE id = %s",
                                (new_user_id, inv_row[0]),
                            )
                        conn.commit()
                        cur.close()
                        conn.close()
                        if role == "COLLABORATOR":
                            flash("Account created! Welcome to A.R.C.H.I.E.", "success")
                            return redirect(url_for("login"))
                        flash("Account created! You can now log in.", "success")
                        return redirect(url_for("login"))
```

**Part B — before_request hook for partner-welcome redirect:**

- [ ] **Step 3: Add after the existing `enforce_guest_readonly` before_request hook**

Find `enforce_guest_readonly` function closing return in `app.py`, add after it:

```python
@app.before_request
def enforce_partner_onboarding():
    """Redirect COLLABORATOR users who haven't completed onboarding to partner-welcome."""
    if not current_user.is_authenticated:
        return
    if getattr(current_user, "role_value", 100) != 15:
        return
    if request.path.startswith("/partner-welcome"):
        return
    if request.path.startswith("/static") or request.path.startswith("/api"):
        return
    if request.path in ("/login", "/logout", "/accept-invite"):
        return
    try:
        from database import get_db_cursor as _gdc

        with _gdc(commit=False) as (_conn, _cur):
            _cur.execute(
                "SELECT onboarding_complete FROM partner_profiles WHERE user_id = %s",
                (current_user.id,),
            )
            row = _cur.fetchone()
        if row and not row["onboarding_complete"]:
            return redirect("/partner-welcome")
    except Exception:
        pass
```

**Part C — partner-welcome route and onboarding-complete endpoint:**

- [ ] **Step 4: Add routes (anywhere in app.py after the before_request hooks)**

```python
@app.route("/partner-welcome")
def partner_welcome():
    """Welcome screen for COLLABORATOR users completing onboarding."""
    from flask_login import login_required

    if not current_user.is_authenticated:
        return redirect(url_for("login"))
    if getattr(current_user, "role_value", 100) != 15:
        return redirect("/")
    try:
        from database import get_db_cursor as _gdc

        with _gdc(commit=False) as (_conn, _cur):
            _cur.execute(
                """SELECT p.slug, p.display_name, u2.username AS inviter
                   FROM partner_profiles p
                   LEFT JOIN users u2 ON p.invited_by = u2.id
                   WHERE p.user_id = %s""",
                (current_user.id,),
            )
            profile = _cur.fetchone()
    except Exception:
        profile = None
    return render_template("partner_welcome.html", profile=profile)


@app.route("/api/partner/onboarding-complete", methods=["POST"])
def partner_onboarding_complete():
    """Mark partner onboarding as complete."""
    if not current_user.is_authenticated:
        return jsonify({"error": "unauthorized"}), 401
    if getattr(current_user, "role_value", 100) != 15:
        return jsonify({"error": "forbidden"}), 403
    try:
        from database import get_db_cursor as _gdc

        with _gdc(commit=True) as (_conn, _cur):
            _cur.execute(
                "UPDATE partner_profiles SET onboarding_complete = TRUE WHERE user_id = %s",
                (current_user.id,),
            )
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    return jsonify({"done": True})
```

- [ ] **Step 5: Restart and verify new routes exist**

```bash
docker compose restart archie_platform && sleep 8
docker logs archie_platform 2>&1 | grep -iE "error|traceback" | grep -v "fleet\|outpost\|model" | tail -10
docker exec archie_platform python3 -c "
import sys; sys.path.insert(0,'/app')
from app import app
rules = [r.rule for r in app.url_map.iter_rules() if 'partner' in r.rule.lower() or 'welcome' in r.rule.lower()]
print('Routes:', rules)
"
```

Expected: `/partner-welcome` and `/api/partner/onboarding-complete` in output.

- [ ] **Step 6: Commit**

```bash
git add platform_v2/app.py
git commit -m "feat(partners): accept_invite extension + partner-welcome route + onboarding hook"
```

---

### Task 5: Create partner_welcome.html

**Files:**
- Create: `platform_v2/templates/partner_welcome.html`

- [ ] **Step 1: Create the template**

```html
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Welcome — A.R.C.H.I.E. Platform</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link href="https://fonts.googleapis.com/css2?family=Orbitron:wght@500&family=IBM+Plex+Mono&display=swap" rel="stylesheet">
  <style>
    *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
    :root { --bg: #0a0a0f; --surface: #12121a; --border: rgba(255,255,255,0.08);
            --accent: #00d4ff; --text: #e2e8f0; --muted: #94a3b8; --radius: 8px; }
    body { font-family: 'IBM Plex Mono', monospace; background: var(--bg); color: var(--text);
           min-height: 100vh; display: flex; align-items: center; justify-content: center;
           padding: 2rem; }
    .card { background: var(--surface); border: 1px solid var(--accent);
            border-radius: var(--radius); padding: 2.5rem; max-width: 560px; width: 100%; }
    .logo { font-family: 'Orbitron', monospace; color: var(--accent); font-size: 0.85rem;
            letter-spacing: 4px; text-transform: uppercase; margin-bottom: 2rem; }
    h1 { font-family: 'Orbitron', monospace; color: var(--text); font-size: 1.2rem;
         letter-spacing: 2px; margin-bottom: 0.5rem; }
    .subtitle { color: var(--muted); font-size: 0.85rem; line-height: 1.7; margin-bottom: 2rem; }
    .info-box { background: var(--bg); border: 1px solid var(--border); border-radius: var(--radius);
                padding: 1rem 1.25rem; margin-bottom: 1.5rem; }
    .info-label { font-size: 0.7rem; color: var(--muted); letter-spacing: 2px;
                  text-transform: uppercase; margin-bottom: 4px; }
    .info-value { font-size: 0.9rem; color: var(--accent); display: flex;
                  align-items: center; gap: 0.5rem; }
    .copy-btn { background: none; border: 1px solid var(--border); color: var(--muted);
                padding: 2px 8px; border-radius: 4px; cursor: pointer; font-size: 0.7rem;
                font-family: 'IBM Plex Mono', monospace; }
    .copy-btn:hover { border-color: var(--accent); color: var(--accent); }
    details { border: 1px solid var(--border); border-radius: var(--radius); margin-bottom: 1.5rem; }
    summary { padding: 0.75rem 1rem; cursor: pointer; font-size: 0.82rem; color: var(--muted); }
    summary:hover { color: var(--text); }
    .fleet-body { padding: 0 1rem 1rem; font-size: 0.8rem; line-height: 1.8; color: var(--muted); }
    code { background: var(--bg); padding: 2px 6px; border-radius: 3px;
           color: var(--accent); font-family: 'IBM Plex Mono', monospace; }
    .btn { display: block; width: 100%; padding: 0.85rem; background: var(--accent);
           color: #000; border: none; border-radius: var(--radius); font-weight: 700;
           cursor: pointer; font-size: 0.95rem; font-family: 'IBM Plex Mono', monospace;
           text-align: center; }
    .btn:hover { opacity: 0.9; }
    .btn:disabled { opacity: 0.5; cursor: not-allowed; }
  </style>
</head>
<body>
  <div class="card">
    <div class="logo">A.R.C.H.I.E. Platform</div>
    <h1>WELCOME{% if profile and profile.display_name %}, {{ profile.display_name | upper }}{% endif %}</h1>
    <p class="subtitle">
      {% if profile and profile.inviter %}
      {{ profile.inviter }} has invited you to collaborate on the A.R.C.H.I.E. platform.
      {% else %}
      You've been invited to collaborate on the A.R.C.H.I.E. platform.
      {% endif %}
      You have access to A.R.C.H.I.E. Chat and Media Studio.
    </p>

    {% if profile and profile.slug %}
    <div class="info-box">
      <div class="info-label">Your Workspace URL</div>
      <div class="info-value">
        <span id="subdomain-url">{{ profile.slug }}.kytranempowerment.com</span>
        <button class="copy-btn" onclick="copySubdomain()">COPY</button>
      </div>
    </div>
    {% endif %}

    <details>
      <summary>&#128187; Contribute your hardware to the fleet (optional)</summary>
      <div class="fleet-body">
        <p style="margin-bottom:0.75rem;">You can join your machine to the A.R.C.H.I.E. fleet to share GPU/RAM resources. Ask your coordinator for the join command once you're ready.</p>
        <p>Your machine will appear in the Fleet tab after connecting. Your coordinator will link it to your profile.</p>
      </div>
    </details>

    <button class="btn" id="enter-btn" onclick="enterPlatform()">ENTER PLATFORM</button>
  </div>

  <script>
  function copySubdomain() {
    var el = document.getElementById('subdomain-url');
    if (!el) return;
    navigator.clipboard.writeText(el.textContent).catch(function() {});
    var btn = document.querySelector('.copy-btn');
    if (btn) { btn.textContent = 'COPIED!'; setTimeout(function() { btn.textContent = 'COPY'; }, 2000); }
  }

  function enterPlatform() {
    var btn = document.getElementById('enter-btn');
    btn.disabled = true;
    btn.textContent = 'ENTERING...';
    fetch('/api/partner/onboarding-complete', { method: 'POST' })
      .then(function() { window.location.href = '/'; })
      .catch(function() { btn.disabled = false; btn.textContent = 'ENTER PLATFORM'; });
  }
  </script>
</body>
</html>
```

- [ ] **Step 2: Verify template renders**

```bash
docker exec archie_platform python3 -c "
import sys; sys.path.insert(0, '/app')
from app import app
with app.test_client() as c:
    # Partner-welcome redirects to login for unauthenticated — check it doesn't 500
    r = c.get('/partner-welcome', follow_redirects=False)
    print('Status (unauth):', r.status_code, '(expect 302 to login)')
"
```

Expected: `Status (unauth): 302`

- [ ] **Step 3: Commit**

```bash
git add platform_v2/templates/partner_welcome.html
git commit -m "feat(partners): partner_welcome.html onboarding screen"
```

---

### Task 6: A.R.C.H.I.E. Chat context injection

**Files:**
- Modify: `platform_v2/tools/archie_chat/api_routes.py`

**Context:**
- `send_message()` is at line 641 of `api_routes.py`
- The system prompt is built somewhere in this function or in a helper it calls
- Find it with: `grep -n "system_prompt\|system prompt\|SYSTEM\|get_agent_system" platform_v2/tools/archie_chat/api_routes.py | head -20`

- [ ] **Step 1: Find system prompt construction**

```bash
grep -n "system_prompt\|system prompt\|get_agent\|archie_system\|base_prompt" /mnt/archie_brain/platform_v2/tools/archie_chat/api_routes.py | head -20
```

Find the line where `system_prompt` is assigned or where the dispatch call is made. The injection point is right after that assignment.

- [ ] **Step 2: Add COLLABORATOR context injection**

After the line where `system_prompt` is defined (or `prompt` / `context` that goes to the dispatcher), add:

```python
# Inject partner context for COLLABORATOR users
if getattr(current_user, "role_value", 0) == 15:
    try:
        from database import get_db_cursor as _gdc

        with _gdc(commit=False) as (_conn, _pcur):
            _pcur.execute(
                """SELECT p.display_name, u2.username AS inviter
                   FROM partner_profiles p
                   LEFT JOIN users u2 ON p.invited_by = u2.id
                   WHERE p.user_id = %s""",
                (current_user.id,),
            )
            _prow = _pcur.fetchone()
        if _prow:
            _partner_ctx = (
                f"You are speaking with {_prow['display_name']}, "
                f"an invited collaborator of {_prow['inviter']}. "
                "Greet them warmly by name on first message and assist with their creative and business needs. "
                "They have access to A.R.C.H.I.E. Chat and Media Studio."
            )
            system_prompt = _partner_ctx + "\n\n" + system_prompt
    except Exception:
        pass  # Fail silently — partner still gets normal ARCHIE response
```

**Important:** Replace `system_prompt` in the snippet above with whatever variable name the actual code uses (found in Step 1).

- [ ] **Step 3: Restart and quick smoke test**

```bash
docker compose restart archie_platform && sleep 8
docker logs archie_platform 2>&1 | grep -iE "error|traceback" | grep -v "fleet\|outpost\|model" | tail -10
```

Expected: no new errors.

- [ ] **Step 4: Commit**

```bash
git add platform_v2/tools/archie_chat/api_routes.py
git commit -m "feat(partners): COLLABORATOR system prompt context injection in A.R.C.H.I.E. Chat"
```

---

### Task 7: Admin UI — PARTNERS section in Account Center

**Files:**
- Modify: `platform_v2/templates/tools/account_center.html`

**Context:**
- DEMO LINKS section was added near the end of the Overview tab (before the closing `</div>` of the main content area)
- Add PARTNERS section after DEMO LINKS using the same pattern
- The 3-step wizard uses a `bm-overlay` LCARS modal with amber accent

- [ ] **Step 1: Find DEMO LINKS insertion point to add PARTNERS after it**

```bash
grep -n "DEMO LINKS\|demo-links-section\|demo-generate-modal" /mnt/archie_brain/platform_v2/templates/tools/account_center.html | head -5
```

- [ ] **Step 2: Add PARTNERS section HTML after the DEMO LINKS section**

After the closing `</div>` of `id="demo-links-table-wrap"` section, add:

```html
<!-- PARTNERS SECTION -->
<div class="lcars-section-label" style="margin-top:24px;"><div class="lcars-section-cap"></div><div class="lcars-section-title">PARTNER COLLABORATORS</div></div>
<div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:12px;">
  <span style="color:var(--archie-text-secondary);font-size:0.8rem;">Invited partners with COLLABORATOR access</span>
  <button class="btn btn-primary btn-sm" onclick="partnerOpenWizard()">+ ADD PARTNER</button>
</div>
<div id="partner-table-wrap" style="margin-bottom:20px;"></div>

<!-- Partner Wizard Modal (3 steps) -->
<div class="bm-overlay" id="partner-wizard-modal">
  <div class="bm-shell" style="--bm-accent:#00d4ff;max-width:520px;">
    <div class="bm-frame"></div>
    <div class="bm-content">
      <div class="bm-header">
        <span id="partner-wizard-title">ADD PARTNER — STEP 1 OF 3</span>
        <button class="bm-close" onclick="partnerCloseWizard()">&#x2715;</button>
      </div>
      <div class="bm-body">
        <!-- Step 1: Identity -->
        <div id="partner-step-1">
          <div style="margin-bottom:14px;">
            <label style="display:block;font-size:0.75rem;color:var(--archie-text-secondary);margin-bottom:6px;">Display Name</label>
            <input type="text" id="partner-display-name" placeholder="e.g. Jane Smith" maxlength="100"
              style="width:100%;background:var(--archie-bg-primary);border:1px solid rgba(255,255,255,0.2);
                     color:var(--archie-text-primary);padding:8px 12px;border-radius:4px;font-family:'IBM Plex Mono',monospace;font-size:0.85rem;"
              oninput="partnerAutoSlug()" />
          </div>
          <div style="margin-bottom:14px;">
            <label style="display:block;font-size:0.75rem;color:var(--archie-text-secondary);margin-bottom:6px;">Email Address</label>
            <input type="email" id="partner-email" placeholder="partner@example.com"
              style="width:100%;background:var(--archie-bg-primary);border:1px solid rgba(255,255,255,0.2);
                     color:var(--archie-text-primary);padding:8px 12px;border-radius:4px;font-family:'IBM Plex Mono',monospace;font-size:0.85rem;" />
          </div>
          <div>
            <label style="display:block;font-size:0.75rem;color:var(--archie-text-secondary);margin-bottom:6px;">Subdomain Slug</label>
            <input type="text" id="partner-slug" placeholder="jane-smith" maxlength="50"
              style="width:100%;background:var(--archie-bg-primary);border:1px solid rgba(255,255,255,0.2);
                     color:var(--archie-text-primary);padding:8px 12px;border-radius:4px;font-family:'IBM Plex Mono',monospace;font-size:0.85rem;"
              oninput="partnerCheckSlug()" />
            <div id="partner-slug-status" style="font-size:0.75rem;margin-top:4px;color:var(--archie-text-secondary);"></div>
          </div>
        </div>
        <!-- Step 2: Subdomain preview -->
        <div id="partner-step-2" style="display:none;">
          <p style="color:var(--archie-text-secondary);font-size:0.85rem;margin-bottom:12px;">The following subdomain will be provisioned:</p>
          <div style="background:var(--archie-bg-primary);border:1px solid #00d4ff;border-radius:6px;padding:12px 16px;font-family:'IBM Plex Mono',monospace;color:#00d4ff;font-size:0.9rem;" id="partner-subdomain-preview"></div>
          <p style="color:var(--archie-text-secondary);font-size:0.75rem;margin-top:12px;">An NPM proxy host will be created automatically. SSL can be enabled via NPM UI after setup.</p>
        </div>
        <!-- Step 3: Confirm & send -->
        <div id="partner-step-3" style="display:none;">
          <p style="color:var(--archie-text-secondary);font-size:0.85rem;margin-bottom:12px;">Ready to send. Review details:</p>
          <div id="partner-review-box" style="background:var(--archie-bg-primary);border:1px solid rgba(255,255,255,0.1);border-radius:6px;padding:12px 16px;font-size:0.82rem;line-height:1.8;"></div>
        </div>
      </div>
      <div class="bm-footer">
        <button class="btn btn-secondary" id="partner-back-btn" onclick="partnerBack()" style="display:none;">BACK</button>
        <button class="btn btn-primary" id="partner-next-btn" onclick="partnerNext()">NEXT</button>
      </div>
    </div>
  </div>
</div>

<!-- Partner Result Modal -->
<div class="bm-overlay" id="partner-result-modal">
  <div class="bm-shell" style="--bm-accent:#00d4ff;max-width:480px;">
    <div class="bm-frame"></div>
    <div class="bm-content">
      <div class="bm-header">
        <span>PARTNER INVITED</span>
        <button class="bm-close" onclick="document.getElementById('partner-result-modal').classList.remove('active')">&#x2715;</button>
      </div>
      <div class="bm-body">
        <p id="partner-result-text" style="color:var(--archie-text-secondary);font-size:0.85rem;line-height:1.7;"></p>
      </div>
    </div>
  </div>
</div>
```

- [ ] **Step 3: Add partner JS before `{% endblock %}`**

Add before the closing `{% endblock %}` tag:

```javascript
<script>
// ---- Partner Admin ----
var _partnerStep = 1;
var _partnerSlugOk = false;
var _partnerSlugTimer = null;

function partnerLoadList() {
  var wrap = document.getElementById('partner-table-wrap');
  if (!wrap) return;
  fetch('/tools/account-center/api/admin/partners')
    .then(function(r) { return r.json(); })
    .then(function(data) {
      while (wrap.firstChild) wrap.removeChild(wrap.firstChild);
      if (!data.partners || !data.partners.length) {
        var msg = document.createElement('div');
        msg.style.cssText = 'color:var(--archie-text-secondary);padding:12px;font-size:0.8rem;';
        msg.textContent = 'No partners yet. Add one above.';
        wrap.appendChild(msg);
        return;
      }
      var tbl = document.createElement('table');
      tbl.style.cssText = 'width:100%;border-collapse:collapse;font-size:0.8rem;';
      var thead = tbl.createTHead();
      var hrow = thead.insertRow();
      ['Name', 'Subdomain', 'Status', 'Fleet', ''].forEach(function(h) {
        var th = document.createElement('th');
        th.style.cssText = 'padding:6px 12px;text-align:left;color:var(--archie-text-secondary);';
        th.textContent = h;
        hrow.appendChild(th);
      });
      var tbody = tbl.createTBody();
      data.partners.forEach(function(p) {
        var tr = tbody.insertRow();
        tr.style.cssText = 'border-bottom:1px solid rgba(255,255,255,0.05);';
        var tdName = tr.insertCell(); tdName.style.padding = '8px 12px';
        tdName.textContent = p.display_name;
        var tdSub = tr.insertCell(); tdSub.style.cssText = 'padding:8px 12px;font-size:0.77rem;color:#00d4ff;';
        tdSub.textContent = p.slug + '.kytranempowerment.com';
        var tdStatus = tr.insertCell(); tdStatus.style.padding = '8px 12px';
        var badge = document.createElement('span');
        badge.style.color = p.is_active === false ? '#ef4444' : (p.onboarding_complete ? '#22c55e' : '#f59e0b');
        badge.style.fontSize = '0.75rem';
        badge.textContent = p.is_active === false ? 'REVOKED' : (p.onboarding_complete ? 'ACTIVE' : 'PENDING');
        tdStatus.appendChild(badge);
        var tdFleet = tr.insertCell(); tdFleet.style.padding = '8px 12px';
        tdFleet.textContent = p.fleet_node_id ? 'LINKED' : '—';
        tdFleet.style.color = p.fleet_node_id ? '#22c55e' : 'var(--archie-text-secondary)';
        var tdAct = tr.insertCell(); tdAct.style.padding = '8px 12px';
        if (p.is_active !== false) {
          var revokeBtn = document.createElement('button');
          revokeBtn.className = 'btn btn-sm';
          revokeBtn.style.cssText = 'background:#ef4444;color:#fff;padding:2px 8px;font-size:0.7rem;';
          revokeBtn.textContent = 'REVOKE';
          (function(id) { revokeBtn.addEventListener('click', function() { partnerRevoke(id); }); })(p.id);
          tdAct.appendChild(revokeBtn);
        }
      });
      wrap.appendChild(tbl);
    })
    .catch(function() {
      var wrap = document.getElementById('partner-table-wrap');
      if (wrap) { wrap.textContent = 'Failed to load partners.'; }
    });
}

function partnerOpenWizard() {
  _partnerStep = 1;
  _partnerSlugOk = false;
  document.getElementById('partner-wizard-title').textContent = 'ADD PARTNER — STEP 1 OF 3';
  document.getElementById('partner-step-1').style.display = '';
  document.getElementById('partner-step-2').style.display = 'none';
  document.getElementById('partner-step-3').style.display = 'none';
  document.getElementById('partner-back-btn').style.display = 'none';
  document.getElementById('partner-next-btn').textContent = 'NEXT';
  document.getElementById('partner-wizard-modal').classList.add('active');
}
function partnerCloseWizard() {
  document.getElementById('partner-wizard-modal').classList.remove('active');
}

function partnerAutoSlug() {
  var name = document.getElementById('partner-display-name').value;
  var slug = name.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '').slice(0, 50);
  document.getElementById('partner-slug').value = slug;
  partnerCheckSlug();
}

function partnerCheckSlug() {
  clearTimeout(_partnerSlugTimer);
  var slug = document.getElementById('partner-slug').value.trim();
  var status = document.getElementById('partner-slug-status');
  _partnerSlugOk = false;
  if (!slug) { status.textContent = ''; return; }
  _partnerSlugTimer = setTimeout(function() {
    fetch('/tools/account-center/api/admin/partners/check-slug?slug=' + encodeURIComponent(slug))
      .then(function(r) { return r.json(); })
      .then(function(data) {
        if (data.available) {
          status.textContent = slug + '.kytranempowerment.com — available';
          status.style.color = '#22c55e';
          _partnerSlugOk = true;
        } else {
          status.textContent = data.reason || 'Slug unavailable';
          status.style.color = '#ef4444';
          _partnerSlugOk = false;
        }
      });
  }, 400);
}

function partnerNext() {
  if (_partnerStep === 1) {
    var name = document.getElementById('partner-display-name').value.trim();
    var email = document.getElementById('partner-email').value.trim();
    var slug = document.getElementById('partner-slug').value.trim();
    if (!name || !email || !slug) { alert('All fields are required.'); return; }
    if (!_partnerSlugOk) { alert('Please fix the slug before continuing.'); return; }
    document.getElementById('partner-subdomain-preview').textContent = slug + '.kytranempowerment.com';
    _partnerStep = 2;
    document.getElementById('partner-step-1').style.display = 'none';
    document.getElementById('partner-step-2').style.display = '';
    document.getElementById('partner-wizard-title').textContent = 'ADD PARTNER — STEP 2 OF 3';
    document.getElementById('partner-back-btn').style.display = '';
    return;
  }
  if (_partnerStep === 2) {
    var name = document.getElementById('partner-display-name').value.trim();
    var email = document.getElementById('partner-email').value.trim();
    var slug = document.getElementById('partner-slug').value.trim();
    var reviewBox = document.getElementById('partner-review-box');
    reviewBox.textContent = '';
    var rows = [['Name', name], ['Email', email], ['Subdomain', slug + '.kytranempowerment.com']];
    rows.forEach(function(r) {
      var line = document.createElement('div');
      var label = document.createElement('span');
      label.style.color = 'var(--archie-text-secondary)';
      label.textContent = r[0] + ': ';
      var val = document.createElement('span');
      val.textContent = r[1];
      line.appendChild(label);
      line.appendChild(val);
      reviewBox.appendChild(line);
    });
    _partnerStep = 3;
    document.getElementById('partner-step-2').style.display = 'none';
    document.getElementById('partner-step-3').style.display = '';
    document.getElementById('partner-wizard-title').textContent = 'ADD PARTNER — STEP 3 OF 3';
    document.getElementById('partner-next-btn').textContent = 'SEND INVITE';
    return;
  }
  if (_partnerStep === 3) {
    var btn = document.getElementById('partner-next-btn');
    btn.disabled = true;
    btn.textContent = 'SENDING...';
    fetch('/tools/account-center/api/admin/partners', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        display_name: document.getElementById('partner-display-name').value.trim(),
        email: document.getElementById('partner-email').value.trim(),
        slug: document.getElementById('partner-slug').value.trim()
      })
    })
    .then(function(r) { return r.json(); })
    .then(function(data) {
      partnerCloseWizard();
      var txt = document.getElementById('partner-result-text');
      txt.textContent = data.error
        ? 'Error: ' + data.error
        : 'Partner invited. Subdomain: ' + (data.subdomain || '') + '. Invite email ' + (data.invite_sent ? 'sent.' : 'failed — check logs.');
      document.getElementById('partner-result-modal').classList.add('active');
      partnerLoadList();
      btn.disabled = false;
      btn.textContent = 'SEND INVITE';
    })
    .catch(function() {
      alert('Request failed. Check logs.');
      btn.disabled = false;
      btn.textContent = 'SEND INVITE';
    });
  }
}

function partnerBack() {
  if (_partnerStep === 2) {
    _partnerStep = 1;
    document.getElementById('partner-step-2').style.display = 'none';
    document.getElementById('partner-step-1').style.display = '';
    document.getElementById('partner-wizard-title').textContent = 'ADD PARTNER — STEP 1 OF 3';
    document.getElementById('partner-back-btn').style.display = 'none';
    document.getElementById('partner-next-btn').textContent = 'NEXT';
  } else if (_partnerStep === 3) {
    _partnerStep = 2;
    document.getElementById('partner-step-3').style.display = 'none';
    document.getElementById('partner-step-2').style.display = '';
    document.getElementById('partner-wizard-title').textContent = 'ADD PARTNER — STEP 2 OF 3';
    document.getElementById('partner-next-btn').textContent = 'NEXT';
  }
}

function partnerRevoke(id) {
  if (!confirm('Revoke this partner? Their account will be deactivated and subdomain removed.')) return;
  fetch('/tools/account-center/api/admin/partners/' + id, { method: 'DELETE' })
    .then(function() { partnerLoadList(); });
}

document.addEventListener('DOMContentLoaded', function() { partnerLoadList(); });
</script>
```

- [ ] **Step 4: Restart and browser-verify**

```bash
docker compose restart archie_platform && sleep 8
```

Navigate to `http://192.168.1.200:3000/tools/account-center` → look for PARTNER COLLABORATORS section with "+ ADD PARTNER" button.

- [ ] **Step 5: Commit**

```bash
git add platform_v2/templates/tools/account_center.html
git commit -m "feat(partners): Partner admin UI — 3-step wizard + table in Account Center"
```

---

### Task 8: End-to-end verify + PR

- [ ] **Step 1: Verify all partner routes exist**

```bash
docker exec archie_platform python3 -c "
import sys; sys.path.insert(0,'/app')
from app import app
rules = sorted([r.rule for r in app.url_map.iter_rules() if 'partner' in r.rule.lower() or 'welcome' in r.rule.lower()])
for r in rules: print(r)
"
```

Expected routes:
- `/partner-welcome`
- `/api/partner/onboarding-complete`
- `/tools/account-center/api/admin/partners`
- `/tools/account-center/api/admin/partners/<int:partner_id>`
- `/tools/account-center/api/admin/partners/check-slug`

- [ ] **Step 2: Test check-slug endpoint**

```bash
docker exec archie_platform python3 -c "
import sys, urllib.request, json; sys.path.insert(0,'/app')
# Note: This needs a valid admin session; test the logic via direct DB check instead
from database import get_db_cursor
with get_db_cursor() as (conn, cur):
    cur.execute('SELECT COUNT(*) FROM partner_profiles')
    print('partner_profiles rows:', cur.fetchone()[0])
    cur.execute('SELECT column_name FROM information_schema.columns WHERE table_name = %s', ('user_invites',))
    cols = [r[0] for r in cur.fetchall()]
    print('user_invites has partner_profile_id:', 'partner_profile_id' in cols)
"
```

Expected: `partner_profiles rows: 0`, `user_invites has partner_profile_id: True`

- [ ] **Step 3: Test partner-welcome redirect for unauthenticated**

```bash
docker exec archie_platform python3 -c "
import sys; sys.path.insert(0,'/app')
from app import app
with app.test_client() as c:
    r = c.get('/partner-welcome', follow_redirects=False)
    print('Unauth redirect status:', r.status_code, '(expect 302)')
"
```

Expected: `302`

- [ ] **Step 4: Create PR**

```bash
git push -u origin feat/partner-collaborator-system
```

Then run `/commit-push-pr` with title: `feat(partners): partner/collaborator system — admin wizard, subdomain, ARCHIE chat context (#2690)`

---

## Self-Review

**Spec coverage:**
- [x] `partner_profiles` table with all columns (Task 1)
- [x] `user_invites.partner_profile_id` FK (Task 1)
- [x] `POST /api/admin/partners` — slug validation, npm provisioning, invite send (Task 2)
- [x] `GET /api/admin/partners` — list with user join (Task 2)
- [x] `PATCH /api/admin/partners/<id>` — link fleet_node_id (Task 2)
- [x] `DELETE /api/admin/partners/<id>` — deactivate user + remove NPM host (Task 2)
- [x] `GET /api/admin/partners/check-slug` — slug availability (Task 2)
- [x] Register partner_routes in __init__.py (Task 3)
- [x] accept_invite sets partner_profiles.user_id (Task 4)
- [x] enforce_partner_onboarding before_request hook (Task 4)
- [x] GET /partner-welcome route (Task 4)
- [x] POST /api/partner/onboarding-complete (Task 4)
- [x] partner_welcome.html — subdomain copy, fleet instructions, enter button (Task 5)
- [x] A.R.C.H.I.E. Chat COLLABORATOR context injection (Task 6)
- [x] PARTNERS admin section + 3-step wizard in account_center.html (Task 7)

**No placeholders.** Task 6 explicitly instructs implementer to grep for the system_prompt variable name since the file is large — this is intentional guidance, not a placeholder.

**Type consistency:** `partner_profile_id` used consistently across Tasks 1, 2, 4. `partner_profiles.user_id` set in Task 4, read in Task 4 (before_request), Task 5 (welcome route), Task 6 (chat injection). All reference the same column name.
