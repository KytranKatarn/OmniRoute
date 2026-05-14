# Guest Experience / Demo Mode Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Magic-link guest sessions that log a prospect into a read-only GUEST (Level 5) view of the platform, with an amber demo banner, a 403-toast for blocked writes, and an admin UI in Account Center to generate/revoke links.

**Architecture:** Ephemeral `users` rows (role=GUEST) tied to `demo_sessions` tokens — standard Flask-Login works transparently everywhere. A `before_request` hook on `app.py` blocks all write methods for GUEST role. The admin UI lives in Account Center; guest entry is a public `/demo?token=<token>` route.

**Tech Stack:** Flask-Login, PostgreSQL, Jinja2, vanilla JS, existing LCARS bm-overlay modals.

---

## File Map

| File | Action |
|------|--------|
| `database/migrations/379_demo_sessions.sql` | Create `demo_sessions` table |
| `platform_v2/tools/account_center/demo_routes.py` | **Create** — 4 endpoints |
| `platform_v2/tools/account_center/__init__.py` | Register demo_routes |
| `platform_v2/app.py` | Add `enforce_guest_readonly` before_request hook |
| `platform_v2/templates/base.html` | Demo banner + fetch-patch script |
| `platform_v2/templates/demo_expired.html` | **Create** — expired link page |
| `platform_v2/tools/account_center/templates/account_center.html` | Demo Links admin UI section |

---

### Task 1: DB Migration

**Files:**
- Create: `database/migrations/379_demo_sessions.sql`

- [ ] **Step 1: Write the migration file**

Create `database/migrations/379_demo_sessions.sql`:

```sql
CREATE TABLE IF NOT EXISTS demo_sessions (
    id SERIAL PRIMARY KEY,
    token VARCHAR(64) UNIQUE NOT NULL,
    label VARCHAR(200),
    expires_at TIMESTAMP NOT NULL,
    created_by INTEGER REFERENCES users(id),
    ephemeral_user_id INTEGER REFERENCES users(id),
    used_count INTEGER DEFAULT 0,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_demo_sessions_token ON demo_sessions(token);
```

- [ ] **Step 2: Apply the migration**

```bash
docker exec archie_database psql -U archie -d archie \
  -f /migrations/379_demo_sessions.sql
```

If the file isn't mounted, run inline:
```bash
docker exec archie_database psql -U archie -d archie -c "
CREATE TABLE IF NOT EXISTS demo_sessions (
    id SERIAL PRIMARY KEY,
    token VARCHAR(64) UNIQUE NOT NULL,
    label VARCHAR(200),
    expires_at TIMESTAMP NOT NULL,
    created_by INTEGER REFERENCES users(id),
    ephemeral_user_id INTEGER REFERENCES users(id),
    used_count INTEGER DEFAULT 0,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_demo_sessions_token ON demo_sessions(token);"
```

Expected: `CREATE TABLE` then `CREATE INDEX`

- [ ] **Step 3: Verify**

```bash
docker exec archie_database psql -U archie -d archie -c "\d demo_sessions"
```

Expected: 9 columns including `ephemeral_user_id INTEGER`

- [ ] **Step 4: Commit**

```bash
git checkout -b feat/guest-demo-mode
git add database/migrations/379_demo_sessions.sql
git commit -m "feat(demo): migration 379 — demo_sessions table"
```

---

### Task 2: demo_routes.py

**Files:**
- Create: `platform_v2/tools/account_center/demo_routes.py`

- [ ] **Step 1: Create the file**

```python
"""Demo session routes — magic-link guest access."""
import secrets
from datetime import datetime, timedelta

from flask import redirect, render_template, request, session
from flask_login import current_user, login_user

from database import get_db_cursor


def register_demo_routes(bp, admin_required):
    """Register demo session routes on the account_center blueprint."""

    @bp.route("/demo")
    def demo_entry():
        """Public — validates token, creates or reuses ephemeral user, logs them in."""
        token = request.args.get("token", "").strip()
        if not token:
            return render_template("demo_expired.html"), 404

        with get_db_cursor() as (conn, cur):
            cur.execute(
                """
                SELECT id, label, expires_at, ephemeral_user_id
                FROM demo_sessions
                WHERE token = %s AND is_active = TRUE AND expires_at > NOW()
                """,
                (token,),
            )
            row = cur.fetchone()

        if not row:
            return render_template("demo_expired.html"), 410

        session_id = row["id"]
        expires_at = row["expires_at"]
        existing_uid = row["ephemeral_user_id"]

        with get_db_cursor(commit=True) as (conn, cur):
            # Reuse ephemeral user if still valid
            if existing_uid:
                cur.execute("SELECT id FROM users WHERE id = %s", (existing_uid,))
                if not cur.fetchone():
                    existing_uid = None

            if not existing_uid:
                email = f"demo-{session_id}@kytranempowerment.com"
                cur.execute(
                    """
                    INSERT INTO users
                        (email, username, role, subscription_tier, is_active, password_hash)
                    VALUES (%s, %s, 'GUEST', 'guest', TRUE, 'demo-no-login')
                    ON CONFLICT (email) DO UPDATE SET is_active = TRUE
                    RETURNING id
                    """,
                    (email, f"demo-{session_id}"),
                )
                existing_uid = cur.fetchone()["id"]
                cur.execute(
                    "UPDATE demo_sessions SET ephemeral_user_id = %s WHERE id = %s",
                    (existing_uid, session_id),
                )

            cur.execute(
                "UPDATE demo_sessions SET used_count = used_count + 1 WHERE id = %s",
                (session_id,),
            )

        # Load via Flask-Login user_loader
        from app import app  # noqa: PLC0415

        with app.app_context():
            user = app.extensions["login_manager"]._user_callback(str(existing_uid))

        if not user:
            return render_template("demo_expired.html"), 500

        login_user(user, remember=False)
        session["demo_session_id"] = session_id
        session["demo_expires"] = expires_at.isoformat()

        return redirect("/")

    @bp.route("/api/admin/demo/link", methods=["POST"])
    @admin_required
    def demo_create_link():
        """Generate a new demo link."""
        data = request.get_json(silent=True) or {}
        label = (data.get("label") or "").strip()[:200]
        try:
            expires_hours = max(1, min(int(data.get("expires_hours", 24)), 720))
        except (TypeError, ValueError):
            expires_hours = 24

        token = secrets.token_urlsafe(32)
        expires_at = datetime.utcnow() + timedelta(hours=expires_hours)

        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                """
                INSERT INTO demo_sessions (token, label, expires_at, created_by)
                VALUES (%s, %s, %s, %s)
                RETURNING id
                """,
                (token, label or None, expires_at, current_user.id),
            )
            new_id = cur.fetchone()["id"]

        base = request.host_url.rstrip("/")
        url = f"{base}/tools/account-center/demo?token={token}"

        return {
            "token": token,
            "url": url,
            "label": label,
            "expires_at": expires_at.isoformat(),
            "id": new_id,
        }

    @bp.route("/api/admin/demo/links")
    @admin_required
    def demo_list_links():
        """List all demo sessions ordered by newest first."""
        with get_db_cursor() as (conn, cur):
            cur.execute(
                """
                SELECT id, token, label, expires_at, used_count, is_active, created_at
                FROM demo_sessions
                ORDER BY created_at DESC
                """
            )
            rows = cur.fetchall()

        return {
            "links": [
                {
                    "id": r["id"],
                    "label": r["label"],
                    "token": r["token"],
                    "expires_at": r["expires_at"].isoformat() if r["expires_at"] else None,
                    "used_count": r["used_count"],
                    "is_active": r["is_active"],
                    "created_at": r["created_at"].isoformat() if r["created_at"] else None,
                }
                for r in rows
            ]
        }

    @bp.route("/api/admin/demo/link/<int:link_id>", methods=["DELETE"])
    @admin_required
    def demo_revoke_link(link_id):
        """Deactivate a demo session."""
        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                "UPDATE demo_sessions SET is_active = FALSE WHERE id = %s RETURNING id",
                (link_id,),
            )
            row = cur.fetchone()
        if not row:
            return {"error": "not found"}, 404
        return {"revoked": True, "id": link_id}
```

- [ ] **Step 2: Verify load_user path**

The `login_manager._user_callback` approach may vary. Check what the app's user_loader looks like:

```bash
grep -n "user_loader\|def load_user" /mnt/archie_brain/platform_v2/app.py | head -10
```

If there's a `load_user(user_id)` function registered with `@login_manager.user_loader`, import and call that directly:

```python
# Replace the app.extensions block with:
from app import load_user as _load_user  # noqa: PLC0415
user = _load_user(str(existing_uid))
```

Update `demo_routes.py` accordingly based on what `grep` returns.

- [ ] **Step 3: Syntax check**

```bash
docker exec archie_platform python3 -c "
import sys; sys.path.insert(0,'/app')
import py_compile
py_compile.compile('/app/tools/account_center/demo_routes.py', doraise=True)
print('OK')
"
```

Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git add platform_v2/tools/account_center/demo_routes.py
git commit -m "feat(demo): demo_routes.py — GET /demo + 3 admin API endpoints"
```

---

### Task 3: Register in account_center/__init__.py

**Files:**
- Modify: `platform_v2/tools/account_center/__init__.py`

`admin_required` is defined at line 29 of `routes.py`. Import it and pass it through.

- [ ] **Step 1: Edit __init__.py**

Current content:
```python
from flask import Blueprint

account_center_bp = Blueprint("account_center", __name__, url_prefix="/tools/account-center")

from . import routes
from .notify_routes import register_notify_routes
from .email_link_routes import register_email_link_routes

register_notify_routes(account_center_bp)
register_email_link_routes(account_center_bp)
```

Add two lines at the end:
```python
from .routes import admin_required
from .demo_routes import register_demo_routes

register_demo_routes(account_center_bp, admin_required)
```

- [ ] **Step 2: Restart and verify no import errors**

```bash
docker compose restart archie_platform && sleep 6
docker logs archie_platform 2>&1 | grep -iE "error|traceback|importerror" | tail -20
```

Expected: no errors in last 20 lines.

- [ ] **Step 3: Verify demo routes registered**

```bash
docker exec archie_platform python3 -c "
import sys; sys.path.insert(0,'/app')
from app import app
rules = [r.rule for r in app.url_map.iter_rules() if 'demo' in r.rule]
print(rules)
"
```

Expected:
```
['/tools/account-center/demo', '/tools/account-center/api/admin/demo/link',
 '/tools/account-center/api/admin/demo/links', '/tools/account-center/api/admin/demo/link/<int:link_id>']
```

- [ ] **Step 4: Commit**

```bash
git add platform_v2/tools/account_center/__init__.py
git commit -m "feat(demo): register demo_routes in account_center blueprint"
```

---

### Task 4: enforce_guest_readonly in app.py

**Files:**
- Modify: `platform_v2/app.py`

- [ ] **Step 1: Find insertion point**

```bash
grep -n "def enforce_2fa_verification" /mnt/archie_brain/platform_v2/app.py
```

Note the line number. Read ~15 lines after it to find the end of that function.

- [ ] **Step 2: Add the hook after enforce_2fa_verification**

Insert this after the closing `return` of `enforce_2fa_verification`:

```python
@app.before_request
def enforce_guest_readonly():
    """Block all write operations for GUEST role (Level 5 — demo mode)."""
    if not current_user.is_authenticated:
        return
    if getattr(current_user, "role_value", 100) != 5:
        return
    if request.method in ("POST", "PUT", "DELETE", "PATCH"):
        # Allow the demo token entry route itself
        if request.path.startswith("/tools/account-center/demo"):
            return
        if request.is_json:
            return jsonify({"error": "demo_mode", "message": "Read-only in demo mode"}), 403
        return "Demo mode: read-only", 403
```

- [ ] **Step 3: Restart and verify**

```bash
docker compose restart archie_platform && sleep 6
docker logs archie_platform 2>&1 | grep -iE "error|traceback" | tail -20
```

Expected: no errors.

- [ ] **Step 4: Test middleware with a GUEST session (quick DB test)**

```bash
docker exec archie_database psql -U archie -d archie -c "
SELECT id, role, subscription_tier FROM users WHERE email LIKE 'demo-%' LIMIT 5;"
```

(This just confirms the users table has the right columns — GUEST users will appear here after a demo link is used in Task 7.)

- [ ] **Step 5: Commit**

```bash
git add platform_v2/app.py
git commit -m "feat(demo): enforce_guest_readonly before_request hook — blocks writes for role_value=5"
```

---

### Task 5: Demo banner + demo_expired.html

**Files:**
- Modify: `platform_v2/templates/base.html`
- Create: `platform_v2/templates/demo_expired.html`

**Part A — base.html banner:**

- [ ] **Step 1: Find `<body>` tag in base.html** (line 72)

```bash
grep -n "<body " /mnt/archie_brain/platform_v2/templates/base.html
```

- [ ] **Step 2: Insert after the `<body>` opening tag**

Add immediately after the `<body ...>` line:

```html
{% if current_user.is_authenticated and current_user.role_value == 5 %}
<div id="demo-mode-banner" style="
  position:fixed;top:0;left:0;right:0;z-index:10000;
  background:#f59e0b;color:#1c1917;
  padding:8px 16px;font-family:'IBM Plex Mono',monospace;font-size:0.8rem;
  display:flex;align-items:center;justify-content:space-between;">
  <span>&#128065; DEMO MODE &mdash; Read-only preview. Changes are not saved.</span>
  <span style="opacity:0.7;font-size:0.7rem;">
    Expires: <span id="demo-expires">{{ session.get('demo_expires', '')[:16] }}</span>
  </span>
</div>
<style>body { padding-top: 40px !important; }</style>
<script>
(function() {
  var _origFetch = window.fetch;
  window.fetch = function() {
    return _origFetch.apply(this, arguments).then(function(resp) {
      if (resp.status === 403) {
        resp.clone().json().then(function(data) {
          if (data && data.error === 'demo_mode') { _showDemoToast(); }
        }).catch(function() {});
      }
      return resp;
    });
  };
  function _showDemoToast() {
    var t = document.getElementById('_demo_toast');
    if (t) { clearTimeout(t._timer); t.remove(); }
    t = document.createElement('div');
    t.id = '_demo_toast';
    t.textContent = '\u{1F441} Demo mode — this action is disabled in preview';
    t.style.cssText = 'position:fixed;bottom:24px;left:50%;transform:translateX(-50%);' +
      'background:#1c1917;color:#f59e0b;padding:10px 20px;border-radius:6px;' +
      'font-family:IBM Plex Mono,monospace;font-size:0.8rem;z-index:99999;pointer-events:none;';
    document.body.appendChild(t);
    t._timer = setTimeout(function() { if (t.parentNode) t.parentNode.removeChild(t); }, 3000);
  }
})();
</script>
{% endif %}
```

**Part B — demo_expired.html:**

- [ ] **Step 3: Create `platform_v2/templates/demo_expired.html`**

```html
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Demo Link Expired &mdash; A.R.C.H.I.E.</title>
  <style>
    *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      background: #0a0a0f;
      color: #e2e8f0;
      font-family: 'IBM Plex Mono', monospace;
      display: flex;
      align-items: center;
      justify-content: center;
      min-height: 100vh;
    }
    .card {
      background: #12121a;
      border: 1px solid #f59e0b;
      border-radius: 8px;
      padding: 40px 48px;
      text-align: center;
      max-width: 440px;
      width: 90%;
    }
    .icon { font-size: 3rem; margin-bottom: 16px; }
    h1 { color: #f59e0b; font-size: 1.1rem; letter-spacing: 0.1em; margin-bottom: 12px; }
    p { color: #94a3b8; font-size: 0.85rem; line-height: 1.7; }
    .hint { margin-top: 24px; font-size: 0.7rem; color: #475569; }
  </style>
</head>
<body>
  <div class="card">
    <div class="icon">&#128683;</div>
    <h1>DEMO LINK EXPIRED</h1>
    <p>This demo link is no longer active.<br>
       Please contact your A.R.C.H.I.E. representative<br>
       to request a new preview link.</p>
    <p class="hint">platform.kytranempowerment.com</p>
  </div>
</body>
</html>
```

- [ ] **Step 4: Restart and spot-check**

```bash
docker compose restart archie_platform && sleep 6
```

Visit `http://192.168.1.200:3000/tools/account-center/demo?token=invalid` → should render the expired page.
Visit `http://192.168.1.200:3000` as admin → banner should NOT appear.

- [ ] **Step 5: Commit**

```bash
git add platform_v2/templates/base.html platform_v2/templates/demo_expired.html
git commit -m "feat(demo): amber banner + fetch-patch toast in base.html + demo_expired.html"
```

---

### Task 6: Admin UI in account_center.html

**Files:**
- Modify: `platform_v2/tools/account_center/templates/account_center.html`

- [ ] **Step 1: Find Overview tab panel in account_center.html**

```bash
grep -n "OVERVIEW\|ac-overview\|demo-links" \
  /mnt/archie_brain/platform_v2/tools/account_center/templates/account_center.html | head -20
```

Identify where the Overview tab content ends (look for closing `</div>` of the overview panel or last section before a tab boundary).

- [ ] **Step 2: Insert Demo Links section in the Overview tab**

Add before the closing `</div>` of the overview panel:

```html
<!-- DEMO LINKS SECTION -->
<div class="ac-section" id="demo-links-section">
  <div class="ac-section-header">
    <span class="ac-section-title">DEMO LINKS</span>
    <button class="ac-btn ac-btn-primary" onclick="demoOpenGenerate()">+ GENERATE LINK</button>
  </div>
  <div id="demo-links-table-wrap">
    <p class="ac-empty-state">Loading demo links...</p>
  </div>
</div>

<!-- Demo Generate Modal -->
<div class="bm-overlay" id="demo-generate-modal">
  <div class="bm-shell" style="--bm-accent:#f59e0b;max-width:480px;">
    <div class="bm-frame"></div>
    <div class="bm-content">
      <div class="bm-header">
        <span>GENERATE DEMO LINK</span>
        <button class="bm-close" onclick="demoCloseGenerate()">&#x2715;</button>
      </div>
      <div class="bm-body">
        <div class="ac-field">
          <label>Label (e.g. "John Smith demo")</label>
          <input type="text" id="demo-label" placeholder="Prospect name" maxlength="200" />
        </div>
        <div class="ac-field">
          <label>Expires in (hours)</label>
          <input type="number" id="demo-hours" value="24" min="1" max="720" />
        </div>
      </div>
      <div class="bm-footer">
        <button class="ac-btn ac-btn-secondary" onclick="demoCloseGenerate()">CANCEL</button>
        <button class="ac-btn ac-btn-primary" onclick="demoGenerate()">GENERATE</button>
      </div>
    </div>
  </div>
</div>

<!-- Demo Result Modal -->
<div class="bm-overlay" id="demo-result-modal">
  <div class="bm-shell" style="--bm-accent:#f59e0b;max-width:560px;">
    <div class="bm-frame"></div>
    <div class="bm-content">
      <div class="bm-header">
        <span>DEMO LINK CREATED</span>
        <button class="bm-close"
          onclick="document.getElementById('demo-result-modal').classList.remove('active')">
          &#x2715;
        </button>
      </div>
      <div class="bm-body">
        <p style="color:#94a3b8;font-size:0.8rem;margin-bottom:8px;">Share this link with your prospect:</p>
        <div style="display:flex;gap:8px;align-items:center;">
          <input type="text" id="demo-result-url" readonly
            style="flex:1;background:#0a0a0f;border:1px solid #f59e0b;color:#f59e0b;
                   padding:8px;font-family:'IBM Plex Mono',monospace;font-size:0.75rem;border-radius:4px;" />
          <button class="ac-btn ac-btn-primary" onclick="demoCopyUrl()">COPY</button>
        </div>
        <p id="demo-result-meta" style="color:#64748b;font-size:0.75rem;margin-top:8px;"></p>
      </div>
    </div>
  </div>
</div>
```

- [ ] **Step 3: Add demo JS** — add before the closing `</script>` of the main script block, or in a new script block:

```javascript
// ---- Demo Links Admin ----
function _demoEsc(s) {
  var d = document.createElement('div');
  d.textContent = s == null ? '' : String(s);
  return d.innerHTML;
}

function demoLoadLinks() {
  fetch('/tools/account-center/api/admin/demo/links')
    .then(function(r) { return r.json(); })
    .then(function(data) {
      var wrap = document.getElementById('demo-links-table-wrap');
      if (!data.links || !data.links.length) {
        wrap.textContent = 'No demo links yet. Generate one above.';
        return;
      }
      var rows = data.links.map(function(l) {
        var badge = l.is_active
          ? '<span class="ac-badge ac-badge-green">ACTIVE</span>'
          : '<span class="ac-badge ac-badge-red">REVOKED</span>';
        var exp = l.expires_at ? l.expires_at.slice(0, 16).replace('T', ' ') : '—';
        var revokeBtn = l.is_active
          ? '<button class="ac-btn ac-btn-danger-sm" onclick="demoRevoke(' + l.id + ')">REVOKE</button>'
          : '';
        return '<tr>' +
          '<td>' + _demoEsc(l.label || '—') + '</td>' +
          '<td>' + _demoEsc(exp) + '</td>' +
          '<td>' + _demoEsc(l.used_count) + '</td>' +
          '<td>' + badge + '</td>' +
          '<td>' + revokeBtn + '</td>' +
          '</tr>';
      }).join('');
      wrap.innerHTML = '<table class="ac-table"><thead><tr>' +
        '<th>Label</th><th>Expires</th><th>Uses</th><th>Status</th><th></th>' +
        '</tr></thead><tbody>' + rows + '</tbody></table>';
    })
    .catch(function() {
      var wrap = document.getElementById('demo-links-table-wrap');
      if (wrap) wrap.textContent = 'Failed to load demo links.';
    });
}

function demoOpenGenerate() {
  document.getElementById('demo-generate-modal').classList.add('active');
}
function demoCloseGenerate() {
  document.getElementById('demo-generate-modal').classList.remove('active');
}

function demoGenerate() {
  var label = document.getElementById('demo-label').value.trim();
  var hours = parseInt(document.getElementById('demo-hours').value, 10) || 24;
  fetch('/tools/account-center/api/admin/demo/link', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ label: label, expires_hours: hours })
  })
    .then(function(r) { return r.json(); })
    .then(function(data) {
      demoCloseGenerate();
      document.getElementById('demo-result-url').value = data.url || '';
      document.getElementById('demo-result-meta').textContent =
        'Expires: ' + (data.expires_at || '').slice(0, 16).replace('T', ' ') +
        (data.label ? ' · ' + data.label : '');
      document.getElementById('demo-result-modal').classList.add('active');
      demoLoadLinks();
    });
}

function demoCopyUrl() {
  var inp = document.getElementById('demo-result-url');
  if (!inp) return;
  inp.select();
  navigator.clipboard.writeText(inp.value).catch(function() {});
}

function demoRevoke(id) {
  if (!confirm('Revoke this demo link? It will stop working immediately.')) return;
  fetch('/tools/account-center/api/admin/demo/link/' + id, { method: 'DELETE' })
    .then(function() { demoLoadLinks(); });
}

document.addEventListener('DOMContentLoaded', function() { demoLoadLinks(); });
```

Note: `_demoEsc()` uses `textContent` assignment (safe) then reads back `innerHTML` — standard browser escaping with no unsafe input.

- [ ] **Step 4: Restart and browser-verify**

```bash
docker compose restart archie_platform && sleep 6
```

Navigate to `http://192.168.1.200:3000/tools/account-center` — look for DEMO LINKS section with a "+ GENERATE LINK" button.

- [ ] **Step 5: Commit**

```bash
git add platform_v2/tools/account_center/templates/account_center.html
git commit -m "feat(demo): Demo Links admin UI in Account Center — generate/revoke LCARS modals"
```

---

### Task 7: End-to-end verify + PR

- [ ] **Step 1: Generate a demo link via the admin UI**

1. Open `http://192.168.1.200:3000/tools/account-center`
2. Scroll to DEMO LINKS section
3. Click "+ GENERATE LINK" → Label = "Test prospect", Expires = 1 hour → click GENERATE
4. Copy the URL from the result modal

- [ ] **Step 2: Open demo link in incognito**

1. Open new incognito/private browser window
2. Paste the demo URL
3. Verify: amber banner "DEMO MODE — Read-only preview. Changes are not saved." appears at top
4. Verify: expiry time shown in banner
5. Verify: you can navigate to other pages (banner persists)

- [ ] **Step 3: Trigger a write to verify the toast**

1. Attempt any button that fires a POST request (e.g. A.R.C.H.I.E. Chat send)
2. Verify: amber toast at bottom: "Demo mode — this action is disabled in preview"
3. Verify: toast disappears after 3 seconds

- [ ] **Step 4: Test expired link**

```bash
docker exec archie_database psql -U archie -d archie -c \
  "UPDATE demo_sessions SET expires_at = NOW() - INTERVAL '1 hour' WHERE used_count > 0;"
```

Re-visit the demo URL in incognito → should show the "DEMO LINK EXPIRED" page.

- [ ] **Step 5: Test revoke**

1. Restore expiry first:
```bash
docker exec archie_database psql -U archie -d archie -c \
  "UPDATE demo_sessions SET expires_at = NOW() + INTERVAL '23 hours', is_active = TRUE WHERE used_count > 0;"
```
2. In Account Center, click REVOKE on the link
3. Badge changes to REVOKED
4. Re-visit demo URL → "DEMO LINK EXPIRED" page

- [ ] **Step 6: Create PR**

```bash
git push -u origin feat/guest-demo-mode
```

Run `/commit-push-pr` with title: `feat(demo): magic-link guest sessions — read-only GUEST mode with admin link management (#2691)`

---

## Self-Review

**Spec coverage:**
- [x] `demo_sessions` table with all 9 columns including `ephemeral_user_id`
- [x] `GET /demo?token=` — validates, creates ephemeral user, `login_user()`, `redirect('/')`
- [x] Ephemeral user reuse on repeat visits (idempotent)
- [x] `POST /api/admin/demo/link` — generates token, inserts, returns URL
- [x] `GET /api/admin/demo/links` — lists all sessions
- [x] `DELETE /api/admin/demo/link/<id>` — sets `is_active = FALSE`
- [x] `enforce_guest_readonly` before_request blocks POST/PUT/DELETE/PATCH for `role_value == 5`
- [x] `/tools/account-center/demo` path exempted from write-block
- [x] Demo banner in `base.html` conditional on `role_value == 5`
- [x] `session['demo_expires']` rendered in banner
- [x] Fetch-patch script for 403 `demo_mode` toast
- [x] `demo_expired.html` on invalid/expired/missing token
- [x] Admin UI: generate form + copy button + revoke table in Account Center

**No placeholders.** All code is complete. Load_user import has a verification step (Task 2 Step 2) that catches the actual function name before committing.

**XSS safety:** Admin table uses `_demoEsc()` helper (textContent→innerHTML escape) for all user-supplied fields. Static badge HTML is not escaped (contains no user input). `bm-overlay` modals use no innerHTML with user content.
