# Federated Auth — "Sign in with Kytran" Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Enable "Sign in with Kytran" across all standalone products using ARCHIE's existing OAuth provider, adding entitlements from Stripe billing, and a reusable client SDK.

**Architecture:** ARCHIE already has `oauth_provider.py` with `/oauth/authorize` and `/oauth/token`. We add a `/oauth/userinfo` endpoint with subscription entitlements, create a client SDK module, seed OAuth clients for all products, and integrate into KSO as the first client.

**Tech Stack:** Flask, Flask-Login, JWT (existing), Stripe billing_subscriptions table, Python requests

**Spec:** `docs/superpowers/specs/2026-03-30-federated-auth-design.md`

---

## File Structure

### New Files

```
database/migrations/305_oauth_userinfo_and_clients.sql  — seed clients + add missing columns
platform_v2/oauth_userinfo.py                           — /oauth/userinfo endpoint
kytran-auth/kytran_auth.py                              — reusable client SDK
kytran-auth/README.md                                   — SDK usage docs
```

### Modified Files

```
platform_v2/app.py                                                         — register userinfo route
platform_v2/oauth_provider.py                                              — extend token with entitlements
kytran-server-manager/kytran_server_manager/auth.py                        — add Kytran SSO login flow
kytran-server-manager/kytran_server_manager/templates/login.html           — add SSO button
```

---

## Task 1: Database Migration — Seed OAuth Clients

**Files:**
- Create: `database/migrations/305_oauth_userinfo_and_clients.sql`

- [ ] **Step 1: Create migration**

Read `platform_v2/oauth_provider.py` first to understand the existing `oauth_clients` and `oauth_codes` table schemas. Then create the migration that seeds the 6 product clients.

The migration should:
1. Ensure `oauth_clients` table exists (it likely already does from `oauth_provider.py`)
2. Insert 6 pre-registered clients with generated secrets (use `gen_random_uuid()` or a fixed format)
3. Add `entitlements` column to `oauth_tokens` table if not exists (JSONB, for caching)

```sql
-- 305_oauth_userinfo_and_clients.sql
-- Seed OAuth clients for all standalone Kytran products

-- Ensure oauth_clients exists (may already exist from oauth_provider.py)
CREATE TABLE IF NOT EXISTS oauth_clients (
    id SERIAL PRIMARY KEY,
    client_id VARCHAR(50) UNIQUE NOT NULL,
    client_secret VARCHAR(128) NOT NULL,
    client_name VARCHAR(100) NOT NULL,
    redirect_uri TEXT NOT NULL,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT NOW()
);

-- Seed product clients (ON CONFLICT to be idempotent)
INSERT INTO oauth_clients (client_id, client_secret, client_name, redirect_uri)
VALUES
    ('kso', encode(gen_random_bytes(32), 'hex'), 'Kytran System Operations', 'https://server.kytranempowerment.com/auth/callback'),
    ('kbs', encode(gen_random_bytes(32), 'hex'), 'Kytran Business Suite', 'https://business.kytranempowerment.com/auth/callback'),
    ('gov-watch', encode(gen_random_bytes(32), 'hex'), 'Kytran Gov Watch', 'https://gov.kytranempowerment.com/auth/callback'),
    ('news', encode(gen_random_bytes(32), 'hex'), 'Kytran News', 'https://news.kytranempowerment.com/auth/callback'),
    ('market-watch', encode(gen_random_bytes(32), 'hex'), 'Kytran Market Watch', 'https://market.kytranempowerment.com/auth/callback'),
    ('kytran-mail', encode(gen_random_bytes(32), 'hex'), 'Kytran Mail', 'https://mail.kytranempowerment.com/auth/callback')
ON CONFLICT (client_id) DO UPDATE SET
    client_name = EXCLUDED.client_name,
    redirect_uri = EXCLUDED.redirect_uri;
```

IMPORTANT: After running the migration, query the clients to get the generated secrets:
```sql
SELECT client_id, client_secret FROM oauth_clients ORDER BY client_id;
```
Save these — each product needs its secret in env vars.

- [ ] **Step 2: Run migration**

```bash
docker cp database/migrations/305_oauth_userinfo_and_clients.sql archie_database:/tmp/
docker exec archie_database psql -U archie -d archie -f /tmp/305_oauth_userinfo_and_clients.sql
```

- [ ] **Step 3: Verify and capture secrets**

```bash
docker exec archie_database psql -U archie -d archie -c "SELECT client_id, client_secret, redirect_uri FROM oauth_clients ORDER BY client_id;"
```

Save the output — you'll need client_secret values for product env configs.

- [ ] **Step 4: Commit**

```bash
git add database/migrations/305_oauth_userinfo_and_clients.sql
git commit -m "feat(auth): seed OAuth clients for 6 standalone products"
```

---

## Task 2: Userinfo Endpoint with Entitlements

**Files:**
- Create: `platform_v2/oauth_userinfo.py`
- Modify: `platform_v2/app.py`

- [ ] **Step 1: Read existing oauth_provider.py**

Read `platform_v2/oauth_provider.py` to understand:
- How tokens are validated
- The JWT secret and decode pattern
- The `oauth_codes` and `oauth_tokens` table usage

- [ ] **Step 2: Create oauth_userinfo.py**

```python
"""OAuth userinfo endpoint — returns user profile + subscription entitlements."""

import jwt
from flask import Blueprint, jsonify, request, current_app
from database import get_db_cursor

oauth_userinfo_bp = Blueprint("oauth_userinfo", __name__, url_prefix="/oauth")


@oauth_userinfo_bp.route("/userinfo", methods=["GET"])
def userinfo():
    """Return user profile + subscription entitlements. Requires Bearer token."""
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return jsonify({"error": "Bearer token required"}), 401

    token = auth_header[7:]

    # Decode JWT
    try:
        secret = current_app.config.get("SECRET_KEY", "fallback-secret")
        payload = jwt.decode(token, secret, algorithms=["HS256"])
    except jwt.ExpiredSignatureError:
        return jsonify({"error": "Token expired"}), 401
    except jwt.InvalidTokenError:
        return jsonify({"error": "Invalid token"}), 401

    user_id = payload.get("sub")
    if not user_id:
        return jsonify({"error": "Invalid token payload"}), 401

    # Fetch user details
    with get_db_cursor() as (conn, cur):
        cur.execute(
            "SELECT id, username, email, role FROM users WHERE id = %s AND is_active = TRUE",
            (user_id,),
        )
        user = cur.fetchone()

    if not user:
        return jsonify({"error": "User not found"}), 404

    # Fetch entitlements from billing_subscriptions
    entitlements = []
    with get_db_cursor() as (conn, cur):
        cur.execute(
            """SELECT DISTINCT module FROM billing_subscriptions
               WHERE user_id = %s AND status = 'active'""",
            (user_id,),
        )
        rows = cur.fetchall()
        entitlements = [row["module"] for row in rows if row["module"]]

    # Admin users get all entitlements
    if user["role"] == "admin":
        entitlements = ["kso", "kbs", "gov-watch", "news", "market-watch", "kytran-mail"]

    # Fetch Stripe customer ID if available
    stripe_customer_id = None
    with get_db_cursor() as (conn, cur):
        cur.execute(
            "SELECT stripe_customer_id FROM billing_customers WHERE user_id = %s LIMIT 1",
            (user_id,),
        )
        row = cur.fetchone()
        if row:
            stripe_customer_id = row["stripe_customer_id"]

    return jsonify({
        "sub": str(user["id"]),
        "username": user["username"],
        "email": user["email"] or "",
        "name": user["username"],
        "role": user["role"],
        "entitlements": entitlements,
        "stripe_customer_id": stripe_customer_id,
    })
```

- [ ] **Step 3: Register in app.py**

Read `platform_v2/app.py` and find where other OAuth blueprints are registered. Add:

```python
from oauth_userinfo import oauth_userinfo_bp
app.register_blueprint(oauth_userinfo_bp)
```

Place it near the existing `oauth_provider` and `oauth_routes` registrations.

- [ ] **Step 4: Commit**

```bash
git add platform_v2/oauth_userinfo.py platform_v2/app.py
git commit -m "feat(auth): add /oauth/userinfo endpoint with subscription entitlements"
```

---

## Task 3: Client SDK — kytran_auth.py

**Files:**
- Create: `kytran-auth/kytran_auth.py`

- [ ] **Step 1: Create the client SDK**

This is a single-file Python module that any Flask app can import to add "Sign in with Kytran" support.

```python
"""Kytran Auth SDK — "Sign in with Kytran" OAuth client for Flask apps.

Usage:
    from kytran_auth import KytranAuth

    kytran_auth = KytranAuth()
    kytran_auth.init_app(app)

    # In templates: <a href="/auth/kytran/login">Sign in with Kytran</a>

Env vars required:
    KYTRAN_CLIENT_ID      — OAuth client ID (e.g., "kso")
    KYTRAN_CLIENT_SECRET   — OAuth client secret
    KYTRAN_AUTH_URL        — ARCHIE hub URL (e.g., "http://192.168.1.200:3000")
    KYTRAN_REDIRECT_URI    — Callback URL for this product
"""

import os
import secrets

import requests
from flask import redirect, request, session, url_for, jsonify
from functools import wraps


class KytranAuth:
    def __init__(self, app=None):
        self.client_id = None
        self.client_secret = None
        self.auth_url = None
        self.redirect_uri = None
        self.app = None
        if app:
            self.init_app(app)

    def init_app(self, app):
        """Configure OAuth settings and register auth routes."""
        self.app = app
        self.client_id = app.config.get("KYTRAN_CLIENT_ID") or os.environ.get("KYTRAN_CLIENT_ID", "")
        self.client_secret = app.config.get("KYTRAN_CLIENT_SECRET") or os.environ.get("KYTRAN_CLIENT_SECRET", "")
        self.auth_url = app.config.get("KYTRAN_AUTH_URL") or os.environ.get("KYTRAN_AUTH_URL", "http://192.168.1.200:3000")
        self.redirect_uri = app.config.get("KYTRAN_REDIRECT_URI") or os.environ.get("KYTRAN_REDIRECT_URI", "")

        self._register_routes(app)

    def _register_routes(self, app):
        """Register /auth/kytran/login and /auth/kytran/callback routes."""

        @app.route("/auth/kytran/login")
        def kytran_login():
            state = secrets.token_urlsafe(32)
            session["oauth_state"] = state
            session["oauth_next"] = request.args.get("next", "/")

            authorize_url = (
                f"{self.auth_url}/oauth/authorize"
                f"?client_id={self.client_id}"
                f"&redirect_uri={self.redirect_uri}"
                f"&response_type=code"
                f"&state={state}"
            )
            return redirect(authorize_url)

        @app.route("/auth/kytran/callback")
        def kytran_callback():
            # Verify state
            state = request.args.get("state")
            if state != session.pop("oauth_state", None):
                return "Invalid state parameter", 400

            code = request.args.get("code")
            if not code:
                error = request.args.get("error", "unknown")
                return f"Authorization failed: {error}", 400

            # Exchange code for token
            try:
                token_resp = requests.post(
                    f"{self.auth_url}/oauth/token",
                    data={
                        "grant_type": "authorization_code",
                        "code": code,
                        "client_id": self.client_id,
                        "client_secret": self.client_secret,
                        "redirect_uri": self.redirect_uri,
                    },
                    timeout=10,
                )
                if token_resp.status_code != 200:
                    return f"Token exchange failed: {token_resp.text}", 400
                token_data = token_resp.json()
            except Exception as e:
                return f"Token exchange error: {e}", 500

            access_token = token_data.get("access_token")
            if not access_token:
                return "No access token received", 400

            # Get user info
            try:
                userinfo_resp = requests.get(
                    f"{self.auth_url}/oauth/userinfo",
                    headers={"Authorization": f"Bearer {access_token}"},
                    timeout=10,
                )
                if userinfo_resp.status_code != 200:
                    return f"Userinfo failed: {userinfo_resp.text}", 400
                userinfo = userinfo_resp.json()
            except Exception as e:
                return f"Userinfo error: {e}", 500

            # Check entitlements
            entitlements = userinfo.get("entitlements", [])
            if self.client_id not in entitlements:
                return (
                    f"<h2>Subscription Required</h2>"
                    f"<p>Your account does not have access to this product.</p>"
                    f"<p>Subscribed products: {', '.join(entitlements) or 'none'}</p>"
                    f"<p><a href='{self.auth_url}'>Manage subscriptions</a></p>"
                ), 403

            # Store in session for the app to use
            session["kytran_user"] = {
                "sub": userinfo.get("sub"),
                "username": userinfo.get("username"),
                "email": userinfo.get("email"),
                "name": userinfo.get("name"),
                "role": userinfo.get("role"),
                "entitlements": entitlements,
                "access_token": access_token,
            }

            # Call the app's user creation/login hook if registered
            if hasattr(self, "_on_login"):
                self._on_login(session["kytran_user"])

            next_url = session.pop("oauth_next", "/")
            return redirect(next_url)

    def on_login(self, callback):
        """Register a callback for when SSO login succeeds.

        The callback receives the userinfo dict and should create/update
        the local user and call flask_login.login_user().
        """
        self._on_login = callback
        return callback

    def login_required(self, f):
        """Decorator: check session for Kytran SSO user, redirect if not found."""
        @wraps(f)
        def decorated(*args, **kwargs):
            if "kytran_user" not in session:
                return redirect(url_for("kytran_login", next=request.url))
            return f(*args, **kwargs)
        return decorated

    def get_current_user(self):
        """Return current Kytran user from session, or None."""
        return session.get("kytran_user")

    def has_entitlement(self, entitlement):
        """Check if current user has a specific product entitlement."""
        user = self.get_current_user()
        if not user:
            return False
        return entitlement in user.get("entitlements", [])
```

- [ ] **Step 2: Commit**

```bash
mkdir -p kytran-auth
git add kytran-auth/kytran_auth.py
git commit -m "feat(auth): add Kytran Auth client SDK — reusable SSO for Flask products"
```

---

## Task 4: KSO Integration — First Client

**Files:**
- Modify: `kytran-server-manager/kytran_server_manager/auth.py`
- Modify: `kytran-server-manager/kytran_server_manager/templates/login.html`

- [ ] **Step 1: Read existing KSO auth.py and login.html**

Read both files to understand the current login flow, SSO callback structure, and login template HTML.

- [ ] **Step 2: Copy SDK into KSO**

```bash
cp kytran-auth/kytran_auth.py kytran-server-manager/kytran_server_manager/kytran_auth.py
```

- [ ] **Step 3: Integrate SDK into KSO auth.py**

Read `auth.py` and add Kytran Auth initialization. Find where the Flask app is configured (likely in `init_auth()` or `create_app()`). Add:

```python
from .kytran_auth import KytranAuth

kytran_auth = KytranAuth()

def init_auth(app):
    # ... existing auth setup ...

    # Initialize Kytran SSO
    kytran_auth.init_app(app)

    @kytran_auth.on_login
    def handle_kytran_login(userinfo):
        """Create/update local user from Kytran SSO."""
        from .db import get_db
        db = get_db()
        cur = db.cursor()

        # Check if SSO user exists
        cur.execute("SELECT id FROM users WHERE username = ? AND sso_provider = 'kytran'", (userinfo["username"],))
        existing = cur.fetchone()

        if existing:
            # Update existing SSO user
            cur.execute(
                "UPDATE users SET role = ? WHERE id = ?",
                (userinfo.get("role", "admin"), existing["id"]),
            )
        else:
            # Create new SSO user
            import secrets
            from werkzeug.security import generate_password_hash
            cur.execute(
                "INSERT INTO users (username, password_hash, role, sso_provider) VALUES (?, ?, ?, 'kytran')",
                (userinfo["username"], generate_password_hash(secrets.token_urlsafe(32)), userinfo.get("role", "admin")),
            )

        db.commit()

        # Log in with Flask-Login
        cur.execute("SELECT * FROM users WHERE username = ? AND sso_provider = 'kytran'", (userinfo["username"],))
        user_row = cur.fetchone()
        if user_row:
            from flask_login import login_user
            from .auth import User  # or however the User class is defined
            user = User(user_row["id"], user_row["username"], user_row["role"])
            login_user(user)
```

NOTE: The exact User class and login_user pattern must match KSO's existing auth.py. Read the file first and follow its patterns exactly.

- [ ] **Step 4: Add SSO button to login.html**

Read the existing `login.html` template. After the existing login form, add a divider and SSO button:

```html
<!-- After the existing login form -->
<div style="text-align: center; margin: 24px 0; color: var(--text-dim, #6b7280);">
    <span>or</span>
</div>

<a href="/auth/kytran/login" class="km-btn" style="display: block; text-align: center; text-decoration: none; background: var(--accent, #00e5ff); color: #0a0e17; padding: 14px; border-radius: 4px; font-family: 'Orbitron', monospace; font-size: 13px; letter-spacing: 2px; text-transform: uppercase;">
    SIGN IN WITH KYTRAN
</a>
```

Style should match KSO's existing LCARS theme. Read login.html to find the exact CSS classes used.

- [ ] **Step 5: Add env vars to KSO**

Add to `kytran-server-manager/.env.example` (or document):
```
KYTRAN_CLIENT_ID=kso
KYTRAN_CLIENT_SECRET=<from migration step>
KYTRAN_AUTH_URL=http://192.168.1.200:3000
KYTRAN_REDIRECT_URI=https://server.kytranempowerment.com/auth/callback
```

- [ ] **Step 6: Commit**

```bash
git add kytran-server-manager/kytran_server_manager/kytran_auth.py \
       kytran-server-manager/kytran_server_manager/auth.py \
       kytran-server-manager/kytran_server_manager/templates/login.html
git commit -m "feat(auth): integrate Sign in with Kytran into KSO — first OAuth client"
```

---

## Task 5: Integration Test

- [ ] **Step 1: Deploy**

```bash
docker compose restart archie_platform
```

- [ ] **Step 2: Test userinfo endpoint**

First, get a valid token by using the existing OAuth flow or creating one manually:

```bash
# Check the authorize endpoint works
curl -s -o /dev/null -w "%{http_code}" "http://192.168.1.200:3000/oauth/authorize?client_id=kso&redirect_uri=https://server.kytranempowerment.com/auth/callback&response_type=code&state=test123"
```

Expected: 302 (redirect to login) or 302 (redirect to callback if already logged in).

- [ ] **Step 3: Test userinfo with a manually-created token**

```bash
# Create a test JWT token
docker exec archie_platform python3 -c "
import jwt, time
secret = open('/app/config.py').read()  # or get SECRET_KEY
# Use a simpler approach: call the token endpoint from inside
print('Test the flow via browser at http://192.168.1.200:3000/oauth/authorize?client_id=kso&response_type=code&redirect_uri=https://server.kytranempowerment.com/auth/callback&state=test')
"
```

The full flow is best tested via browser:
1. Open `http://192.168.1.200:3000/oauth/authorize?client_id=kso&response_type=code&redirect_uri=https://server.kytranempowerment.com/auth/callback&state=test`
2. Login with admin credentials
3. Should redirect to callback URL with `?code=...&state=test`
4. Capture the code from the URL

- [ ] **Step 4: Verify clients are registered**

```bash
docker exec archie_database psql -U archie -d archie -c "SELECT client_id, client_name, is_active FROM oauth_clients ORDER BY client_id;"
```

Expected: 6 clients, all active.

- [ ] **Step 5: Verify userinfo endpoint responds**

```bash
# This requires a valid JWT — test after getting one from the full flow
curl -s http://192.168.1.200:3000/oauth/userinfo -H "Authorization: Bearer VALID_TOKEN_HERE" | python3 -m json.tool
```

Expected: Returns user profile with entitlements.

- [ ] **Step 6: Commit any fixes**

```bash
git add -A && git commit -m "feat(auth): Federated Auth complete — Sign in with Kytran OAuth 2.0"
```
