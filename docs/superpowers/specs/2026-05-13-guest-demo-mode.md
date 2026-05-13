# Guest Experience / Demo Mode

**Date:** 2026-05-13
**Task:** #2691 — Project Alpha
**Scope:** Magic-link guest sessions with read-only enforcement and demo banner.

---

## Context

GUEST role (Level 5) is already defined in `rbac.py` as "Demo/tour mode — view-only, no modifications" and the tier system maps `subscription_tier='guest'` to `Role.GUEST`. No demo session infrastructure exists yet.

Goal: Kytran shares a time-limited URL with a prospect. They click it, land on the platform as a read-only GUEST, see a banner explaining demo mode, and can navigate freely but cannot make changes.

---

## Data

### New table: `demo_sessions`

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

---

## Backend

### 1. New route file: `platform_v2/tools/account_center/demo_routes.py`

Register as `register_demo_routes(bp, admin_required)` — follows ADR-045 pattern.

**Endpoints:**

#### `GET /demo` (public — no auth required)
Query param: `?token=<token>`

Logic:
1. Look up `token` in `demo_sessions` WHERE `is_active=TRUE` AND `expires_at > NOW()`
2. If not found → render `templates/demo_expired.html` ("This demo link has expired.")
3. If found → increment `used_count`, create an ephemeral `users` row:
   - `email = f"demo-{row['id']}@kytranempowerment.com"` (or reuse if already exists for this session)
   - `role = 'GUEST'`, `subscription_tier = 'guest'`, `is_active = True`
   - Store `user_id` back in `demo_sessions.ephemeral_user_id`
4. Log the ephemeral user in via `login_user(user, remember=False)`
5. Store in Flask session: `session['demo_session_id'] = row['id']`, `session['demo_expires'] = row['expires_at'].isoformat()`
6. `redirect('/')`

This approach uses standard Flask-Login — `current_user.role_value == 5` works throughout the app without any patching. The ephemeral user row is reused on subsequent visits to the same demo link (idempotent insert on `demo_sessions.ephemeral_user_id`).

**Cleanup:** A weekly job or on-revoke: `DELETE FROM users WHERE email LIKE 'demo-%@kytranempowerment.com' AND id IN (SELECT ephemeral_user_id FROM demo_sessions WHERE is_active = FALSE OR expires_at < NOW())`

Add `ephemeral_user_id INTEGER REFERENCES users(id)` to `demo_sessions` table.

#### `POST /api/admin/demo/link` (admin required)
Body: `{"label": "John Smith demo", "expires_hours": 24}`

Logic:
1. Generate `token = secrets.token_urlsafe(32)`
2. Insert into `demo_sessions`
3. Return: `{"token": token, "url": "https://platform.kytranempowerment.com/demo?token={token}", "expires_at": ...}`

#### `GET /api/admin/demo/links` (admin required)
Returns all active demo sessions ordered by `created_at DESC`.

#### `DELETE /api/admin/demo/link/<int:id>` (admin required)
Sets `is_active = FALSE` for that session.

### 2. Register in `account_center/__init__.py`

```python
from .demo_routes import register_demo_routes
register_demo_routes(account_center_bp, admin_required)
```

### 3. Middleware — `app.py`

New `before_request` hook added after existing hooks:

```python
@app.before_request
def enforce_guest_readonly():
    """Block all write operations for GUEST role users."""
    if not current_user.is_authenticated:
        return
    if getattr(current_user, 'role_value', 100) != 5:
        return
    if request.method in ('POST', 'PUT', 'DELETE', 'PATCH'):
        if request.path.startswith('/demo'):
            return  # Allow demo session creation
        if request.is_json:
            return jsonify({"error": "demo_mode", "message": "Read-only in demo mode"}), 403
        return "Demo mode: read-only", 403
```

---

## Frontend

### 1. Demo banner — `base.html`

Inject immediately after `<body>` tag, conditional on GUEST role:

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
<style>body { padding-top: 40px; }</style>
{% endif %}
```

### 2. Global write-intercept toast — `base.js` or inline script

When any 403 with `{"error": "demo_mode"}` is received by `fetch()`, show a toast:

```javascript
// Patch fetch to intercept demo_mode 403s
const _origFetch = window.fetch;
window.fetch = function(...args) {
  return _origFetch.apply(this, args).then(function(resp) {
    if (resp.status === 403) {
      resp.clone().json().then(function(data) {
        if (data && data.error === 'demo_mode') {
          showDemoModeToast();
        }
      }).catch(() => {});
    }
    return resp;
  });
};

function showDemoModeToast() {
  var t = document.createElement('div');
  t.textContent = '👁 Demo mode — this action is disabled in preview';
  t.style.cssText = 'position:fixed;bottom:24px;left:50%;transform:translateX(-50%);' +
    'background:#1c1917;color:#f59e0b;padding:10px 20px;border-radius:6px;' +
    'font-family:IBM Plex Mono,monospace;font-size:0.8rem;z-index:99999;';
  document.body.appendChild(t);
  setTimeout(function() { t.remove(); }, 3000);
}
```

### 3. Admin UI — Account Center "Demo Links" section

Add a new section to the Account Center OVERVIEW tab (or a new "Demo" sub-tab). Minimal UI:
- "Generate Demo Link" button → opens a small form (label, expiry hours) → calls `POST /api/admin/demo/link` → shows the URL with a copy button
- Table of active demo links: label, created, expires, uses, revoke button

---

## Files Changed

| File | Action |
|------|--------|
| `database/migrations/NNN_demo_sessions.sql` | Create `demo_sessions` table |
| `platform_v2/tools/account_center/demo_routes.py` | **Create** — 4 endpoints |
| `platform_v2/tools/account_center/__init__.py` | Register demo_routes |
| `platform_v2/app.py` | Add `enforce_guest_readonly` before_request hook |
| `platform_v2/templates/base.html` | Add demo banner + fetch patch script |
| `platform_v2/templates/demo_expired.html` | **Create** — simple expired link page |
| `platform_v2/tools/account_center/templates/account_center.html` | Add Demo Links admin UI section |

---

## Out of Scope

- Data masking (API keys, emails) — future phase
- Rate limiting demo link visits
- Analytics/tracking per demo session
- Guest user seeing a custom "welcome" modal on first visit

---

## Testing

1. Admin generates demo link → URL with token appears, copy button works
2. Open URL in incognito → lands on platform as GUEST, amber banner visible
3. Try clicking a button that triggers a POST → toast "Demo mode — disabled" appears
4. Try navigating between pages → all work normally
5. Expire the link (set `expires_at` to past in DB) → revisit URL → "link expired" page renders
6. Revoke a link from Account Center → token no longer works
