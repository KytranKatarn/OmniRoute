# Market Watch — OAuth + Subscription Gating Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add "Sign in with Kytran" OAuth authentication and tiered subscription gating (Free/Viewer/AI Trader) to Market Watch, plus wire the hub dispatch bridge for VPS deployment.

**Architecture:** Integrate existing KytranAuth SDK into Flask app. Add a thin `auth.py` module with tier-aware decorators. Frontend SPA gets a `/api/me` endpoint for tier-based UI gating. New `hub_client.py` bridges agent dispatch to ARCHIE hub over mesh/LAN.

**Tech Stack:** Flask 3.1, KytranAuth SDK, SQLite, flask-limiter, vanilla HTML/JS (existing SPA)

**Spec:** `docs/superpowers/specs/2026-03-31-market-watch-oauth-subscription-design.md`

**Security Note:** Landing page renders API data into DOM. Use `textContent` for plain text values and DOMPurify or manual escaping for any HTML content. Never use raw `innerHTML` with untrusted data.

---

## File Structure

| Action | File | Responsibility |
|--------|------|----------------|
| Copy | `kytran_auth.py` | OAuth SDK — login/callback/session (from `/mnt/archie_brain/kytran-auth/`) |
| Create | `auth.py` | Tier resolution, `@tier_required()`, `@admin_required`, `/api/me`, `/auth/logout` |
| Create | `services/hub_client.py` | Machine-to-machine dispatch bridge to ARCHIE hub agents |
| Create | `templates/landing.html` | LCARS teaser landing page with public track record |
| Create | `routes/public.py` | Public API routes (track record) — no auth required |
| Create | `.env.example` | Documented env var template |
| Modify | `schema.sql` | Add `users` table |
| Modify | `db.py` | No changes needed — `init_db()` auto-runs schema.sql |
| Modify | `app.py` | Wire SDK, session config, auth routes, landing route, remove wildcard CORS |
| Modify | `requirements.txt` | Add `flask-limiter` |
| Modify | `static/index.html` | Add `/api/me` call, tier-based UI gating, user menu, login redirect |
| Modify | `routes/stocks.py` | Add `@tier_required("viewer")` to all routes |
| Modify | `routes/charts.py` | Add `@tier_required("viewer")` to all routes |
| Modify | `routes/analysis.py` | Add `@tier_required("viewer")` to GET, `@tier_required("ai")` to POST |
| Modify | `routes/watchlist.py` | Add `@tier_required("viewer")` to GET, `@tier_required("ai")` to POST/DELETE |
| Modify | `routes/portfolio.py` | Add `@tier_required("viewer")` to all routes |
| Modify | `routes/trading.py` | Add `@tier_required("ai")` to all routes, `@admin_required` to toggle-live |
| Modify | `routes/alerts.py` | Add `@tier_required("viewer")` to GET, `@tier_required("ai")` to POST/DELETE |
| Modify | `routes/backtest.py` | Add `@tier_required("ai")` to all routes |
| Modify | `routes/strategy_routes.py` | Add `@tier_required("viewer")` to GET, `@tier_required("ai")` to POST |

---

### Task 1: Schema — Add Users Table

**Files:**
- Modify: `schema.sql` (append to end)

- [ ] **Step 1: Add users table to schema.sql**

Append to the end of `/mnt/archie_brain/market-watch/schema.sql`:

```sql
-- Local user cache (populated on OAuth login)
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kytran_sub TEXT NOT NULL UNIQUE,
    username TEXT,
    email TEXT,
    name TEXT,
    role TEXT DEFAULT 'user',
    tier TEXT DEFAULT 'viewer',
    last_login TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

- [ ] **Step 2: Verify schema loads cleanly**

```bash
cd /mnt/archie_brain/market-watch
rm -f /tmp/test_schema.db
sqlite3 /tmp/test_schema.db < schema.sql
sqlite3 /tmp/test_schema.db ".tables"
```

Expected: All existing tables plus `users` listed.

- [ ] **Step 3: Commit**

```bash
cd /mnt/archie_brain/market-watch
git add schema.sql
git commit -m "feat(auth): add users table to schema for OAuth user cache"
```

---

### Task 2: Copy KytranAuth SDK + Add Dependencies

**Files:**
- Copy: `kytran_auth.py` (from `/mnt/archie_brain/kytran-auth/kytran_auth.py`)
- Modify: `requirements.txt`
- Create: `.env.example`

- [ ] **Step 1: Copy the SDK into Market Watch root**

```bash
cp /mnt/archie_brain/kytran-auth/kytran_auth.py /mnt/archie_brain/market-watch/kytran_auth.py
```

- [ ] **Step 2: Add flask-limiter to requirements.txt**

Add this line to `/mnt/archie_brain/market-watch/requirements.txt`:

```
flask-limiter==3.12
```

- [ ] **Step 3: Create .env.example**

Create `/mnt/archie_brain/market-watch/.env.example`:

```bash
# Flask
SECRET_KEY=change-me-to-random-64-char-string
MW_DB_PATH=/app/data/market.db

# Kytran OAuth
KYTRAN_CLIENT_ID=market-watch-viewer
KYTRAN_CLIENT_SECRET=change-me
KYTRAN_AUTH_URL=http://192.168.1.200:3000
KYTRAN_REDIRECT_URI=http://192.168.1.200:8080/auth/kytran/callback

# Hub Dispatch (for agent pipeline)
ARCHIE_HUB_URL=http://192.168.1.200:3000
ARCHIE_SERVICE_TOKEN=change-me

# VPS overrides (uncomment for production)
# KYTRAN_AUTH_URL=http://100.64.0.1:3000
# KYTRAN_REDIRECT_URI=https://market.kytranempowerment.com/auth/kytran/callback
# ARCHIE_HUB_URL=http://100.64.0.1:3000

# Rate limiting
RATELIMIT_STORAGE_URI=memory://
```

- [ ] **Step 4: Install flask-limiter**

```bash
cd /mnt/archie_brain/market-watch
pip install flask-limiter==3.12
```

- [ ] **Step 5: Commit**

```bash
cd /mnt/archie_brain/market-watch
git add kytran_auth.py requirements.txt .env.example
git commit -m "feat(auth): add KytranAuth SDK, flask-limiter dep, env template"
```

---

### Task 3: Auth Module — Tier Decorators + Routes

**Files:**
- Create: `auth.py`

- [ ] **Step 1: Create auth.py with tier resolution and decorators**

Create `/mnt/archie_brain/market-watch/auth.py`:

```python
"""Market Watch auth — tier-based access control using KytranAuth SDK."""

import os
import sqlite3
from functools import wraps

from flask import Blueprint, jsonify, redirect, request, session, url_for

from db import get_db

auth_bp = Blueprint("auth", __name__)

# Tier hierarchy (higher index = more access)
TIER_LEVELS = {"free": 0, "viewer": 1, "ai": 2}


def resolve_tier(user):
    """Resolve the highest tier from user entitlements."""
    if not user:
        return "free"
    entitlements = user.get("entitlements", [])
    if "market-watch-ai" in entitlements:
        return "ai"
    if "market-watch-viewer" in entitlements:
        return "viewer"
    return "free"


def get_current_tier():
    """Get the current user's tier from session."""
    user = session.get("kytran_user")
    if not user:
        return "free"
    return resolve_tier(user)


def is_admin():
    """Check if the current user is an admin."""
    user = session.get("kytran_user")
    if not user:
        return False
    return user.get("role") == "admin"


def tier_required(min_tier):
    """Decorator: require a minimum subscription tier.

    Usage:
        @tier_required("viewer")   # viewer + ai + admin
        @tier_required("ai")       # ai + admin only
    """
    def decorator(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            user = session.get("kytran_user")
            if not user:
                if request.is_json or request.path.startswith("/api/"):
                    return jsonify({"success": False, "error": "Authentication required"}), 401
                return redirect(url_for("kytran_login", next=request.url))

            current_tier = resolve_tier(user)
            current_level = TIER_LEVELS.get(current_tier, 0)
            required_level = TIER_LEVELS.get(min_tier, 0)

            if current_level < required_level:
                return jsonify({
                    "success": False,
                    "error": f"Requires {min_tier} tier",
                    "current_tier": current_tier,
                }), 403

            return f(*args, **kwargs)
        return decorated
    return decorator


def admin_required(f):
    """Decorator: require admin role."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if not is_admin():
            return jsonify({"success": False, "error": "Admin access required"}), 403
        return f(*args, **kwargs)
    return decorated


def upsert_local_user(user_data):
    """Cache user profile in local SQLite on login."""
    tier = resolve_tier(user_data)
    conn = get_db()
    try:
        conn.execute(
            """INSERT INTO users (kytran_sub, username, email, name, role, tier, last_login)
               VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
               ON CONFLICT(kytran_sub) DO UPDATE SET
                   username=excluded.username, email=excluded.email,
                   name=excluded.name, role=excluded.role,
                   tier=excluded.tier, last_login=CURRENT_TIMESTAMP""",
            (
                user_data.get("sub"),
                user_data.get("username"),
                user_data.get("email"),
                user_data.get("name"),
                user_data.get("role", "user"),
                tier,
            ),
        )
        conn.commit()
    finally:
        conn.close()


# --- Routes ---

@auth_bp.route("/api/me")
def api_me():
    """Return current user profile and tier."""
    user = session.get("kytran_user")
    if not user:
        return jsonify({"authenticated": False, "tier": "free"})
    return jsonify({
        "authenticated": True,
        "username": user.get("username"),
        "name": user.get("name"),
        "email": user.get("email"),
        "role": user.get("role"),
        "tier": resolve_tier(user),
        "is_admin": user.get("role") == "admin",
    })


@auth_bp.route("/auth/logout")
def logout():
    """Clear session and redirect to landing."""
    session.clear()
    return redirect("/")
```

- [ ] **Step 2: Verify the module imports cleanly**

```bash
cd /mnt/archie_brain/market-watch
python -c "from auth import tier_required, admin_required, resolve_tier, auth_bp; print('OK')"
```

Expected: `OK`

- [ ] **Step 3: Commit**

```bash
cd /mnt/archie_brain/market-watch
git add auth.py
git commit -m "feat(auth): tier decorators, /api/me, /auth/logout, local user cache"
```

---

### Task 4: Wire Auth into App

**Files:**
- Modify: `app.py`

- [ ] **Step 1: Update app.py — add SDK, session config, auth blueprint, landing route**

Replace the entire contents of `/mnt/archie_brain/market-watch/app.py` with:

```python
"""Kytran Market Watch — M.A.R.K.E.T. Autonomous Trading Dashboard."""

import os
import time
import threading
import logging

from flask import Flask, send_from_directory, render_template, request, redirect, session
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def create_app():
    app = Flask(
        __name__,
        static_folder="static",
        static_url_path="/static",
        template_folder="templates",
    )

    # --- Session & Security Config ---
    app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-change-me")
    app.config["SESSION_COOKIE_HTTPONLY"] = True
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
    if os.environ.get("FLASK_ENV") == "production":
        app.config["SESSION_COOKIE_SECURE"] = True

    # --- Rate Limiter ---
    limiter = Limiter(
        get_remote_address,
        app=app,
        storage_uri=os.environ.get("RATELIMIT_STORAGE_URI", "memory://"),
        default_limits=[],
    )
    app.limiter = limiter

    # --- Database ---
    from db import init_db
    init_db()

    # --- KytranAuth SDK ---
    from kytran_auth import KytranAuth
    from auth import auth_bp, upsert_local_user

    kytran_auth = KytranAuth()
    app.config["KYTRAN_CLIENT_ID"] = os.environ.get("KYTRAN_CLIENT_ID", "market-watch-viewer")
    kytran_auth.init_app(app)

    @kytran_auth.on_login
    def on_login(user_data):
        """Cache user locally and resolve tier on every login."""
        upsert_local_user(user_data)
        logger.info("User logged in: %s", user_data.get("username"))

    # --- Auth + Public Blueprints ---
    app.register_blueprint(auth_bp)
    limiter.limit("10/minute")(auth_bp)

    from routes.public import public_bp
    app.register_blueprint(public_bp)
    limiter.limit("30/minute")(public_bp)

    from routes.health import health_bp
    app.register_blueprint(health_bp)

    # --- Protected Route Blueprints ---
    from routes.stocks import stocks_bp
    from routes.watchlist import watchlist_bp
    from routes.charts import charts_bp
    app.register_blueprint(stocks_bp)
    app.register_blueprint(watchlist_bp)
    app.register_blueprint(charts_bp)

    from routes.portfolio import portfolio_bp
    app.register_blueprint(portfolio_bp)

    from routes.trading import trading_bp
    app.register_blueprint(trading_bp)

    from routes.alerts import alerts_bp
    app.register_blueprint(alerts_bp)

    from routes.backtest import backtest_bp
    app.register_blueprint(backtest_bp)

    from routes.analysis import analysis_bp
    app.register_blueprint(analysis_bp)

    from routes.strategy_routes import bp as strategy_bp
    app.register_blueprint(strategy_bp)

    # --- CORS (locked down) ---
    allowed_origins = os.environ.get(
        "CORS_ORIGINS",
        "https://market.kytranempowerment.com,http://192.168.1.200:8080"
    ).split(",")

    @app.after_request
    def add_cors(response):
        origin = request.headers.get("Origin", "")
        if origin in allowed_origins:
            response.headers["Access-Control-Allow-Origin"] = origin
            response.headers["Access-Control-Allow-Headers"] = "Content-Type"
            response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, PATCH"
            response.headers["Access-Control-Allow-Credentials"] = "true"
        return response

    # --- Landing Page (public) ---
    @app.route("/")
    def landing():
        return render_template("landing.html")

    # --- Dashboard (authenticated) ---
    @app.route("/dashboard")
    def dashboard():
        if "kytran_user" not in session:
            return redirect("/auth/kytran/login?next=/dashboard")
        return send_from_directory("static", "index.html")

    return app


def _background_ingest(app):
    """Background thread for market data ingestion."""
    time.sleep(10)
    with app.app_context():
        logger.info("Background ingest thread started")
        while True:
            try:
                from ingest.price_ingest import run_price_ingest
                run_price_ingest()
            except Exception as e:
                logger.error("Price ingest failed: %s", e)
            time.sleep(300)  # 5 minutes


if __name__ == "__main__":
    app = create_app()
    ingest_thread = threading.Thread(target=_background_ingest, args=(app,), daemon=True)
    ingest_thread.start()
    app.run(host="0.0.0.0", port=8080, debug=False)
```

- [ ] **Step 2: Create templates directory**

```bash
mkdir -p /mnt/archie_brain/market-watch/templates
```

- [ ] **Step 3: Verify app creates without errors**

```bash
cd /mnt/archie_brain/market-watch
python -c "from app import create_app; app = create_app(); print('App created OK')"
```

Expected: `App created OK`

- [ ] **Step 4: Commit**

```bash
cd /mnt/archie_brain/market-watch
git add app.py templates/
git commit -m "feat(auth): wire KytranAuth SDK, session config, CORS lockdown, landing route"
```

---

### Task 5: Public Routes — Track Record API

**Files:**
- Create: `routes/public.py`

- [ ] **Step 1: Create public routes blueprint**

Create `/mnt/archie_brain/market-watch/routes/public.py`:

```python
"""Public API routes — no authentication required."""

from flask import Blueprint, jsonify

from db import get_db

public_bp = Blueprint("public", __name__)


@public_bp.route("/api/public/track-record")
def track_record():
    """Return W.A.T.C.H. agent's paper trading performance summary."""
    conn = get_db()
    try:
        # Overall stats from paper account
        account = conn.execute(
            "SELECT cash_balance, initial_balance FROM paper_account WHERE id = 1"
        ).fetchone()

        # Recent completed cycles
        cycles = conn.execute(
            """SELECT COUNT(*) as total_cycles,
                      SUM(trades_made) as total_trades,
                      SUM(stocks_analyzed) as total_analyzed
               FROM cycle_log WHERE status = 'completed'"""
        ).fetchone()

        # Trade count and basic win tracking
        sell_count = conn.execute(
            "SELECT COUNT(*) as cnt FROM transactions WHERE action = 'sell'"
        ).fetchone()

        # Recent analyses (last 5)
        recent = conn.execute(
            """SELECT ticker, recommendation, director_sentiment,
                      director_confidence, oracle_confidence, created_at
               FROM analyses ORDER BY created_at DESC LIMIT 5"""
        ).fetchall()

        cash = account["cash_balance"] if account else 100000.0
        initial = account["initial_balance"] if account else 100000.0
        total_return = ((cash - initial) / initial) * 100 if initial > 0 else 0.0

        return jsonify({
            "success": True,
            "track_record": {
                "total_return_pct": round(total_return, 2),
                "cash_balance": round(cash, 2),
                "initial_balance": round(initial, 2),
                "total_trades": sell_count["cnt"] if sell_count else 0,
                "total_cycles": cycles["total_cycles"] or 0,
                "total_analyzed": cycles["total_analyzed"] or 0,
                "recent_calls": [
                    {
                        "ticker": r["ticker"],
                        "recommendation": r["recommendation"],
                        "sentiment": r["director_sentiment"],
                        "confidence": r["director_confidence"],
                        "oracle_confidence": r["oracle_confidence"],
                        "date": r["created_at"],
                    }
                    for r in recent
                ],
            },
        })
    finally:
        conn.close()
```

- [ ] **Step 2: Verify import**

```bash
cd /mnt/archie_brain/market-watch
python -c "from routes.public import public_bp; print('OK')"
```

Expected: `OK`

- [ ] **Step 3: Commit**

```bash
cd /mnt/archie_brain/market-watch
git add routes/public.py
git commit -m "feat(api): public track-record endpoint for teaser landing"
```

---

### Task 6: Teaser Landing Page

**Files:**
- Create: `templates/landing.html`

- [ ] **Step 1: Create LCARS teaser landing page**

Create `/mnt/archie_brain/market-watch/templates/landing.html` with:
- LCARS-themed dark background (#0a0a1a)
- Hero section: title "KYTRAN MARKET WATCH", W.A.T.C.H. acronym, subtitle, "Sign in with Kytran" CTA button linking to `/auth/kytran/login?next=/dashboard`
- Stats grid (4 cards): Total Return, Win Rate, Total Trades, Stocks Analyzed — populated from `/api/public/track-record`
- Recent AI Calls section: last 5 analyses with ticker, recommendation (color-coded), sentiment, confidence, date
- Subscription tiers section: Viewer (cyan) and AI Trader (gold) feature lists
- Fonts: Orbitron for headings, IBM Plex Mono for body (Google Fonts CDN)
- Responsive: 3 breakpoints (480px single-col, 768px 2-col stats, 1024px full)
- **SECURITY:** Use `textContent` for all data values from API. Use DOM element creation (createElement + appendChild) instead of string interpolation for HTML. Escape any data that must be rendered as HTML.

Example safe DOM rendering pattern for stats:

```javascript
function renderStats(tr) {
    const grid = document.getElementById('stats-grid');
    grid.textContent = '';  // Clear loading text

    const stats = [
        { value: (tr.total_return_pct >= 0 ? '+' : '') + tr.total_return_pct + '%', label: 'Total Return', color: tr.total_return_pct >= 0 ? 'var(--mw-green)' : 'var(--mw-red)' },
        { value: tr.total_trades.toString(), label: 'Total Trades', color: 'var(--mw-purple)' },
        { value: (tr.total_cycles || 0).toString(), label: 'Analysis Cycles', color: 'var(--mw-cyan)' },
        { value: (tr.total_analyzed || 0).toString(), label: 'Stocks Analyzed', color: 'var(--mw-gold)' },
    ];

    stats.forEach(s => {
        const card = document.createElement('div');
        card.className = 'stat-card';

        const val = document.createElement('div');
        val.className = 'value';
        val.textContent = s.value;
        val.style.color = s.color;

        const lbl = document.createElement('div');
        lbl.className = 'label';
        lbl.textContent = s.label;

        card.appendChild(val);
        card.appendChild(lbl);
        grid.appendChild(card);
    });
}
```

Apply the same safe DOM pattern for recent calls rendering.

- [ ] **Step 2: Verify template renders**

```bash
cd /mnt/archie_brain/market-watch
python -c "
from app import create_app
app = create_app()
with app.test_client() as c:
    resp = c.get('/')
    print(f'Status: {resp.status_code}')
    print('KYTRAN MARKET WATCH' in resp.data.decode())
"
```

Expected: `Status: 200` and `True`

- [ ] **Step 3: Commit**

```bash
cd /mnt/archie_brain/market-watch
git add templates/landing.html
git commit -m "feat(ui): LCARS teaser landing page with public track record"
```

---

### Task 7: Protect Existing Routes with Tier Decorators

**Files:**
- Modify: `routes/stocks.py`
- Modify: `routes/charts.py`
- Modify: `routes/analysis.py`
- Modify: `routes/watchlist.py`
- Modify: `routes/portfolio.py`
- Modify: `routes/trading.py`
- Modify: `routes/alerts.py`
- Modify: `routes/backtest.py`
- Modify: `routes/strategy_routes.py`

This task adds the `@tier_required()` decorator to every route in every blueprint. The pattern is:
- **GET routes (read):** `@tier_required("viewer")`
- **POST/PUT/DELETE routes (write):** `@tier_required("ai")`
- **Trading toggle-live:** `@admin_required`
- **Health routes:** No decorator (keep public)

- [ ] **Step 1: Add tier decorators to stocks.py**

Add this import at the top of `/mnt/archie_brain/market-watch/routes/stocks.py`:

```python
from auth import tier_required
```

Then add `@tier_required("viewer")` immediately after each `@stocks_bp.route(...)` decorator on every route function. Example pattern:

```python
@stocks_bp.route("/api/stocks/<ticker>")
@tier_required("viewer")
def get_stock(ticker):
    ...
```

Apply to ALL route functions in the file.

- [ ] **Step 2: Add tier decorators to charts.py**

Add import and `@tier_required("viewer")` to all routes in `/mnt/archie_brain/market-watch/routes/charts.py`. Same pattern as Step 1.

- [ ] **Step 3: Add tier decorators to analysis.py**

Add import at top of `/mnt/archie_brain/market-watch/routes/analysis.py`:

```python
from auth import tier_required
```

- GET routes: `@tier_required("viewer")`
- POST routes (`/api/analysis/run`, `/api/analysis/cycle`): `@tier_required("ai")`

- [ ] **Step 4: Add tier decorators to watchlist.py**

Add import at top of `/mnt/archie_brain/market-watch/routes/watchlist.py`:

```python
from auth import tier_required
```

- GET routes: `@tier_required("viewer")`
- POST routes: `@tier_required("ai")`
- DELETE routes: `@tier_required("ai")`

- [ ] **Step 5: Add tier decorators to portfolio.py**

Add import and `@tier_required("viewer")` to all routes in `/mnt/archie_brain/market-watch/routes/portfolio.py`.

- [ ] **Step 6: Add tier decorators to trading.py**

Add imports at top of `/mnt/archie_brain/market-watch/routes/trading.py`:

```python
from auth import tier_required, admin_required
```

- All trade routes (`/api/trading/buy`, `/api/trading/sell`, etc.): `@tier_required("ai")`
- If a `/api/trading/toggle-live` route exists, add `@admin_required` after `@tier_required("ai")`
- If it doesn't exist yet, add it:

```python
@trading_bp.route("/api/trading/toggle-live", methods=["POST"])
@tier_required("ai")
@admin_required
def toggle_live_trading():
    """Toggle between paper and live Alpaca trading (admin only)."""
    data = request.get_json() or {}
    enabled = data.get("enabled", False)
    return jsonify({"success": True, "live_trading": enabled, "message": "Not yet implemented — Sub-project 3"})
```

- [ ] **Step 7: Add tier decorators to alerts.py**

Add import at top of `/mnt/archie_brain/market-watch/routes/alerts.py`:

```python
from auth import tier_required
```

- GET routes: `@tier_required("viewer")`
- POST/DELETE routes: `@tier_required("ai")`

- [ ] **Step 8: Add tier decorators to backtest.py**

Add import and `@tier_required("ai")` to ALL routes in `/mnt/archie_brain/market-watch/routes/backtest.py`.

- [ ] **Step 9: Add tier decorators to strategy_routes.py**

Add import at top of `/mnt/archie_brain/market-watch/routes/strategy_routes.py`:

```python
from auth import tier_required
```

- GET routes: `@tier_required("viewer")`
- POST/PUT/DELETE routes: `@tier_required("ai")`

- [ ] **Step 10: Verify all routes load without import errors**

```bash
cd /mnt/archie_brain/market-watch
python -c "from app import create_app; app = create_app(); print(f'{len(list(app.url_map.iter_rules()))} routes loaded OK')"
```

Expected: Route count printed with `OK` (no import errors).

- [ ] **Step 11: Commit**

```bash
cd /mnt/archie_brain/market-watch
git add routes/
git commit -m "feat(auth): protect all routes with tier-based access decorators"
```

---

### Task 8: Frontend — Tier-Based UI Gating + User Menu

**Files:**
- Modify: `static/index.html`

- [ ] **Step 1: Add auth state variables to head**

Add this script block to the `<head>` section of `/mnt/archie_brain/market-watch/static/index.html`, before the closing `</head>`:

```html
<script>
    window.MW_USER = null;
    window.MW_TIER = 'free';
    window.MW_IS_ADMIN = false;
</script>
```

- [ ] **Step 2: Add user menu HTML**

Insert near the top of the `<body>`, inside the existing header/nav area:

```html
<div id="user-menu" style="position:fixed;top:10px;right:20px;z-index:1000;display:none;">
    <div style="display:flex;align-items:center;gap:10px;">
        <span id="user-tier-badge" style="padding:3px 10px;border-radius:3px;font-size:0.75rem;font-weight:700;text-transform:uppercase;"></span>
        <span id="user-name" style="color:#e0e0e0;font-size:0.85rem;"></span>
        <a href="/auth/logout" style="color:#6b7280;font-size:0.8rem;text-decoration:none;margin-left:8px;">Logout</a>
    </div>
</div>
```

- [ ] **Step 3: Add auth initialization script**

Add this script block before the closing `</body>` tag in `static/index.html`:

```javascript
(async function initAuth() {
    try {
        const resp = await fetch('/api/me');
        const data = await resp.json();

        if (!data.authenticated) {
            window.location.href = '/';
            return;
        }

        window.MW_USER = data;
        window.MW_TIER = data.tier;
        window.MW_IS_ADMIN = data.is_admin;

        // Show user menu
        const menu = document.getElementById('user-menu');
        menu.style.display = 'block';
        document.getElementById('user-name').textContent = data.name || data.username;

        const badge = document.getElementById('user-tier-badge');
        if (data.tier === 'ai') {
            badge.textContent = 'AI TRADER';
            badge.style.background = '#fbbf24';
            badge.style.color = '#000';
        } else {
            badge.textContent = 'VIEWER';
            badge.style.background = '#00e5ff';
            badge.style.color = '#000';
        }

        // Hide AI-only elements for viewers
        if (data.tier === 'viewer') {
            document.querySelectorAll('[data-tier="ai"]').forEach(function(el) {
                el.style.display = 'none';
            });
            document.querySelectorAll('[data-tier-disable="ai"]').forEach(function(el) {
                el.disabled = true;
                el.title = 'Upgrade to AI Trader tier';
                el.style.opacity = '0.4';
                el.style.cursor = 'not-allowed';
            });
        }

        // Show admin-only elements
        if (data.is_admin) {
            document.querySelectorAll('[data-tier="admin"]').forEach(function(el) {
                el.style.display = '';
            });
        }
    } catch (e) {
        console.error('Auth check failed:', e);
        window.location.href = '/';
    }
})();
```

- [ ] **Step 4: Tag interactive elements with data-tier attributes**

Read through `static/index.html` and find all action buttons/forms. Tag them:

```html
<!-- Hide entirely for viewers -->
<button data-tier="ai" onclick="runAnalysis()">Run Analysis</button>

<!-- Disable for viewers (grayed out with tooltip) -->
<button data-tier-disable="ai" onclick="executeTrade()">Execute Trade</button>

<!-- Admin only (hidden by default, shown by JS for admins) -->
<div data-tier="admin" style="display:none;">
    <label>Live Trading <input type="checkbox" onchange="toggleLive(this.checked)"></label>
</div>
```

Apply to: trade buttons, watchlist add/remove, alert create/delete, backtest run, analysis run, strategy create/edit. The exact elements depend on the current HTML — read and tag each one.

- [ ] **Step 5: Commit**

```bash
cd /mnt/archie_brain/market-watch
git add static/index.html
git commit -m "feat(ui): tier-based UI gating, user menu, auth redirect"
```

---

### Task 9: Hub Client — Agent Dispatch Bridge

**Files:**
- Create: `services/hub_client.py`

- [ ] **Step 1: Create hub_client.py**

Create `/mnt/archie_brain/market-watch/services/hub_client.py`:

```python
"""Hub Client — machine-to-machine dispatch bridge to ARCHIE Department HQ agents."""

import os
import logging

import requests

logger = logging.getLogger(__name__)

HUB_URL = os.environ.get("ARCHIE_HUB_URL", "http://192.168.1.200:3000")
SERVICE_TOKEN = os.environ.get("ARCHIE_SERVICE_TOKEN", "")
TIMEOUT = int(os.environ.get("HUB_DISPATCH_TIMEOUT", "120"))


def dispatch_to_agent(agent_name, prompt, model=None):
    """Dispatch a prompt to an ARCHIE hub agent and return the response.

    Args:
        agent_name: Name of the agent (e.g., "Quant", "Oracle")
        prompt: The prompt/task for the agent
        model: Optional model override

    Returns:
        dict with keys: success, response, agent_name, duration_ms
        Falls back to mock response if hub unreachable.
    """
    if not SERVICE_TOKEN:
        logger.warning("No ARCHIE_SERVICE_TOKEN set — using mock response")
        return _mock_response(agent_name, prompt)

    payload = {
        "agent_name": agent_name,
        "prompt": prompt,
        "source": "market-watch",
    }
    if model:
        payload["model"] = model

    try:
        resp = requests.post(
            f"{HUB_URL}/api/bridge/dispatch",
            json=payload,
            headers={
                "Authorization": f"Bearer {SERVICE_TOKEN}",
                "Content-Type": "application/json",
            },
            timeout=TIMEOUT,
        )
        if resp.status_code != 200:
            logger.error("Hub dispatch failed (%d): %s", resp.status_code, resp.text[:200])
            return _mock_response(agent_name, prompt)

        data = resp.json()
        return {
            "success": True,
            "response": data.get("response", ""),
            "agent_name": agent_name,
            "model": data.get("model"),
            "duration_ms": data.get("duration_ms", 0),
        }
    except requests.exceptions.ConnectionError:
        logger.warning("Hub unreachable at %s — falling back to mock", HUB_URL)
        return _mock_response(agent_name, prompt)
    except requests.exceptions.Timeout:
        logger.warning("Hub dispatch timed out after %ds", TIMEOUT)
        return _mock_response(agent_name, prompt)
    except Exception as e:
        logger.error("Hub dispatch error: %s", e)
        return _mock_response(agent_name, prompt)


def check_hub_health():
    """Check if ARCHIE hub is reachable."""
    try:
        resp = requests.get(f"{HUB_URL}/api/health", timeout=5)
        return resp.status_code == 200
    except Exception:
        return False


def _mock_response(agent_name, prompt):
    """Return a mock response when hub is unavailable (graceful degradation)."""
    return {
        "success": False,
        "response": f"[MOCK] {agent_name} agent unavailable — hub offline. Analysis pending.",
        "agent_name": agent_name,
        "model": None,
        "duration_ms": 0,
        "mock": True,
    }
```

- [ ] **Step 2: Verify import**

```bash
cd /mnt/archie_brain/market-watch
python -c "from services.hub_client import dispatch_to_agent, check_hub_health; print('OK')"
```

Expected: `OK`

- [ ] **Step 3: Commit**

```bash
cd /mnt/archie_brain/market-watch
git add services/hub_client.py
git commit -m "feat(dispatch): hub client bridge for ARCHIE agent dispatch over mesh/LAN"
```

---

### Task 10: ARCHIE Side — Register OAuth Client + Entitlement Products

**Files:**
- Run SQL on ARCHIE database (no file changes)

- [ ] **Step 1: Register Market Watch as OAuth client on ARCHIE**

```bash
docker exec -it archie_database psql -U archie -d archie -c "
INSERT INTO oauth_clients (client_id, client_secret, redirect_uri, name)
VALUES (
    'market-watch-viewer',
    '$(python3 -c "import secrets; print(secrets.token_urlsafe(32))")',
    'http://192.168.1.200:8080/auth/kytran/callback',
    'Kytran Market Watch'
)
ON CONFLICT (client_id) DO UPDATE SET
    redirect_uri = EXCLUDED.redirect_uri,
    name = EXCLUDED.name;
"
```

**IMPORTANT:** Save the generated `client_secret` — you'll need it for Market Watch's `.env` file.

- [ ] **Step 2: Verify the client exists**

```bash
docker exec -it archie_database psql -U archie -d archie -c "
SELECT client_id, name, redirect_uri FROM oauth_clients WHERE client_id = 'market-watch-viewer';
"
```

Expected: One row with Market Watch client data.

- [ ] **Step 3: Add entitlement subscriptions for admin user**

```bash
docker exec -it archie_database psql -U archie -d archie -c "
INSERT INTO billing_subscriptions (user_id, module, status)
SELECT id, 'market-watch-ai', 'active'
FROM users WHERE role = 'admin'
ON CONFLICT DO NOTHING;
"
```

- [ ] **Step 4: Document in task notes**

No files to commit — database-only configuration. Note the client_secret for .env setup in Task 11.

---

### Task 11: Integration Test — Full Auth Flow

- [ ] **Step 1: Create .env file for Market Watch**

Create `/mnt/archie_brain/market-watch/.env` (DO NOT commit this file):

```bash
SECRET_KEY=<generate with: python3 -c "import secrets; print(secrets.token_urlsafe(48))">
MW_DB_PATH=./market.db
KYTRAN_CLIENT_ID=market-watch-viewer
KYTRAN_CLIENT_SECRET=<from Task 10 Step 1>
KYTRAN_AUTH_URL=http://192.168.1.200:3000
KYTRAN_REDIRECT_URI=http://192.168.1.200:8080/auth/kytran/callback
ARCHIE_HUB_URL=http://192.168.1.200:3000
ARCHIE_SERVICE_TOKEN=<generate or use existing service token>
CORS_ORIGINS=https://market.kytranempowerment.com,http://192.168.1.200:8080
RATELIMIT_STORAGE_URI=memory://
```

- [ ] **Step 2: Ensure .env is gitignored**

```bash
echo ".env" >> /mnt/archie_brain/market-watch/.gitignore
```

- [ ] **Step 3: Restart Market Watch**

```bash
cd /mnt/archie_brain/market-watch
pkill -f "python.*app.py.*8080" || true
set -a; source .env; set +a
python app.py &
sleep 3
```

- [ ] **Step 4: Test landing page (no auth)**

```bash
curl -s http://192.168.1.200:8080/ | grep -o "KYTRAN MARKET WATCH"
```

Expected: `KYTRAN MARKET WATCH`

- [ ] **Step 5: Test public track record API**

```bash
curl -s http://192.168.1.200:8080/api/public/track-record | python3 -m json.tool | head -5
```

Expected: JSON with `"success": true` and `track_record` data.

- [ ] **Step 6: Test protected route returns 401**

```bash
curl -s http://192.168.1.200:8080/api/stocks/AAPL | python3 -m json.tool
```

Expected: `{"success": false, "error": "Authentication required"}` with 401 status.

- [ ] **Step 7: Test /api/me returns unauthenticated**

```bash
curl -s http://192.168.1.200:8080/api/me | python3 -m json.tool
```

Expected: `{"authenticated": false, "tier": "free"}`

- [ ] **Step 8: Test OAuth redirect**

```bash
curl -s -o /dev/null -w "%{http_code} %{redirect_url}" http://192.168.1.200:8080/auth/kytran/login
```

Expected: `302` redirect to `http://192.168.1.200:3000/oauth/authorize?...`

- [ ] **Step 9: Browser test — full login flow**

1. Open `http://192.168.1.200:8080` in browser
2. Verify teaser landing page loads with track record stats
3. Click "Sign in with Kytran"
4. Login with ARCHIE credentials
5. Verify redirect to `/dashboard`
6. Verify user menu shows name + tier badge (gold "AI TRADER" for admin)
7. Verify all dashboard tabs load data
8. Click Logout, verify return to landing page

- [ ] **Step 10: Test hub client connectivity**

```bash
cd /mnt/archie_brain/market-watch
set -a; source .env; set +a
python -c "
from services.hub_client import check_hub_health
print('Hub healthy:', check_hub_health())
"
```

Expected: `Hub healthy: True`

- [ ] **Step 11: Commit gitignore**

```bash
cd /mnt/archie_brain/market-watch
git add .gitignore
git commit -m "chore: gitignore .env file"
```

---

## Summary

| Task | What | Files | Commits |
|------|------|-------|---------|
| 1 | Users table schema | schema.sql | 1 |
| 2 | SDK + deps + env template | kytran_auth.py, requirements.txt, .env.example | 1 |
| 3 | Auth module (decorators + routes) | auth.py | 1 |
| 4 | Wire auth into Flask app | app.py | 1 |
| 5 | Public track record API | routes/public.py | 1 |
| 6 | Teaser landing page | templates/landing.html | 1 |
| 7 | Protect all routes | routes/*.py (9 files) | 1 |
| 8 | Frontend tier gating + user menu | static/index.html | 1 |
| 9 | Hub dispatch client | services/hub_client.py | 1 |
| 10 | ARCHIE OAuth client + entitlements | Database only | 0 |
| 11 | Integration test | .env + .gitignore + manual testing | 1 |

**Total: 11 tasks, ~10 commits, 5 new files, 12 modified files**
