# KSM Tier 2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Complete Tier 2 of the Kytran System Operations standalone — SSO with ARCHIE, compliance scanning with live badges, subdomain, launch page, health endpoint, responsive polish, and tier progress tracking.

**Architecture:** ARCHIE becomes an OAuth provider; standalone authenticates via "Sign in with Kytran" redirect flow. Standalone runs its own compliance scans and reports results back to ARCHIE hub. ARCHIE's System Ops module becomes a launch page showing standalone health. Infrastructure wired via AdGuard DNS + NPM proxy.

**Tech Stack:** Python/Flask (both apps), SQLite (standalone), PostgreSQL (ARCHIE), JWT (PyJWT), APScheduler (background scans), SVG generation (badges), AdGuard API, NPM API

---

## File Map

### ARCHIE Platform (`/mnt/archie_brain/platform_v2/`)
| Action | File | Responsibility |
|--------|------|---------------|
| Create | `oauth_provider.py` | OAuth authorize + token endpoints |
| Create | `api_standalone.py` | Receive compliance reports from standalones |
| Modify | `app.py` | Register OAuth + standalone API routes |
| Create | `database/migrations/200_oauth_clients.sql` | oauth_clients + oauth_codes tables |
| Modify | `tools/system_operations/routes.py` | Replace module with launch page route |
| Create | `tools/system_operations/templates/system_operations_launch.html` | Launch page template |
| Modify | `tools/consciousness/code_health_routes.py` | Extend standalone-status with tier data |
| Modify | `static/js/consciousness.js` | Dynamic tier progress badge |

### Standalone (`/mnt/archie_brain/kytran-server-manager/kytran_server_manager/`)
| Action | File | Responsibility |
|--------|------|---------------|
| Modify | `auth.py` | SSO redirect + callback, upgrade from stub |
| Modify | `templates/login.html` | SSO button (conditional) |
| Create | `routes/health_routes.py` | `/api/health` + tier progress |
| Create | `routes/badge_routes.py` | `/api/compliance/badge/<pack>.svg` |
| Create | `services/scheduler.py` | Background compliance scan every 6h |
| Create | `services/hub_client.py` | ARCHIE hub communication |
| Modify | `routes/compliance_routes.py` | Manual scan trigger enhancement |
| Modify | `routes/__init__.py` | Register new routes |
| Modify | `app.py` | Start scheduler, hub config |
| Modify | `config.py` | Add ARCHIE_HUB_URL, CLIENT_ID, CLIENT_SECRET |
| Modify | `templates/dashboard.html` | Compliance summary bar |
| Modify | `static/css/lcars-frames.css` | Responsive polish |

---

## Phase 1: Foundation (No Dependencies)

### Task 1: Database Migration — OAuth Tables

**Files:**
- Create: `database/migrations/200_oauth_clients.sql`

- [ ] **Step 1: Create the migration file**

```sql
-- OAuth provider tables for "Sign in with Kytran" standalone authentication
-- Run: docker exec archie_database psql -U archie -d archie -f /mnt/archie_brain/database/migrations/200_oauth_clients.sql

CREATE TABLE IF NOT EXISTS oauth_clients (
    id SERIAL PRIMARY KEY,
    client_id VARCHAR(64) UNIQUE NOT NULL,
    client_secret VARCHAR(128) NOT NULL,
    redirect_uri VARCHAR(512) NOT NULL,
    name VARCHAR(128) NOT NULL,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS oauth_codes (
    id SERIAL PRIMARY KEY,
    code VARCHAR(128) UNIQUE NOT NULL,
    client_id VARCHAR(64) NOT NULL REFERENCES oauth_clients(client_id),
    user_id INTEGER NOT NULL,
    redirect_uri VARCHAR(512) NOT NULL,
    expires_at TIMESTAMP NOT NULL,
    used BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_oauth_codes_code ON oauth_codes(code);
CREATE INDEX IF NOT EXISTS idx_oauth_codes_expires ON oauth_codes(expires_at);

-- Pre-register Kytran System Operations as OAuth client
INSERT INTO oauth_clients (client_id, client_secret, redirect_uri, name)
VALUES (
    'kytran-sysops',
    encode(gen_random_bytes(32), 'hex'),
    'http://192.168.1.200:8085/auth/sso/callback',
    'Kytran System Operations'
) ON CONFLICT (client_id) DO NOTHING;
```

- [ ] **Step 2: Run the migration**

```bash
docker exec archie_database psql -U archie -d archie -f /mnt/archie_brain/database/migrations/200_oauth_clients.sql
```

Expected: `CREATE TABLE` x2, `CREATE INDEX` x2, `INSERT 0 1`

- [ ] **Step 3: Retrieve the generated client_secret for standalone config**

```bash
docker exec archie_database psql -U archie -d archie -t -c "SELECT client_secret FROM oauth_clients WHERE client_id = 'kytran-sysops';"
```

Save the output — this goes in the standalone's `.env` as `ARCHIE_CLIENT_SECRET`.

- [ ] **Step 4: Commit**

```bash
git add database/migrations/200_oauth_clients.sql
git commit -m "feat(oauth): add OAuth provider tables + register KSM client"
```

---

### Task 2: Standalone Config — Hub Environment Variables

**Files:**
- Modify: `kytran-server-manager/kytran_server_manager/config.py`

- [ ] **Step 1: Read current config.py**

Read `/mnt/archie_brain/kytran-server-manager/kytran_server_manager/config.py` to understand the Config class structure and env var pattern.

- [ ] **Step 2: Add hub configuration variables**

Add these to the `Config` class:

```python
    # ARCHIE Hub connection (for SSO + compliance reporting)
    ARCHIE_HUB_URL = os.environ.get("ARCHIE_HUB_URL", "")  # e.g., http://192.168.1.200:3000
    ARCHIE_CLIENT_ID = os.environ.get("ARCHIE_CLIENT_ID", "kytran-sysops")
    ARCHIE_CLIENT_SECRET = os.environ.get("ARCHIE_CLIENT_SECRET", "")
    SERVER_SUBDOMAIN = os.environ.get("SERVER_SUBDOMAIN", "")  # e.g., server.kytranempowerment.com

    # Compliance scanning schedule
    COMPLIANCE_SCAN_INTERVAL = int(os.environ.get("COMPLIANCE_SCAN_INTERVAL", "21600"))  # 6 hours in seconds
```

- [ ] **Step 3: Commit**

```bash
cd /mnt/archie_brain/kytran-server-manager
git add kytran_server_manager/config.py
git commit -m "feat(config): add ARCHIE hub + compliance schedule config vars"
```

---

### Task 3: Health Endpoint

**Files:**
- Create: `kytran-server-manager/kytran_server_manager/routes/health_routes.py`
- Modify: `kytran-server-manager/kytran_server_manager/routes/__init__.py`

- [ ] **Step 1: Read the routes __init__.py**

Read `/mnt/archie_brain/kytran-server-manager/kytran_server_manager/routes/__init__.py` to match the registration pattern.

- [ ] **Step 2: Create health_routes.py**

```python
"""Health check and tier progress endpoints."""

import time
from flask import jsonify, current_app


_start_time = time.time()


def _check_db():
    """Check database connectivity."""
    try:
        from db import get_db
        conn = get_db()
        conn.execute("SELECT 1")
        conn.close()
        return "ok"
    except Exception:
        return "error"


def _get_tier_progress():
    """Auto-detect Tier 2 completion status."""
    config = current_app.config
    hub_url = config.get("ARCHIE_HUB_URL", "")

    items = {
        "sso": bool(hub_url and config.get("ARCHIE_CLIENT_SECRET")),
        "compliance_scanning": False,
        "badges": True,  # badge_routes exist after this deploy
        "subdomain": bool(config.get("SERVER_SUBDOMAIN")),
        "redirect": bool(hub_url),
        "health_endpoint": True,  # this endpoint exists
        "responsive": True,  # LCARS frames responsive since Tier 1
        "code_health_badge": bool(hub_url),
    }

    # Check if compliance scan ran recently
    try:
        from db import get_db
        conn = get_db()
        cur = conn.execute(
            "SELECT scanned_at FROM compliance_scans ORDER BY scanned_at DESC LIMIT 1"
        )
        row = cur.fetchone()
        conn.close()
        if row:
            from datetime import datetime, timedelta
            last_scan = datetime.fromisoformat(row[0]) if isinstance(row[0], str) else row[0]
            items["compliance_scanning"] = (datetime.utcnow() - last_scan) < timedelta(hours=24)
    except Exception:
        pass

    completed = sum(1 for v in items.values() if v)
    return {
        "current_tier": 2,
        "completed": completed,
        "total": len(items),
        "items": items,
    }


def _get_compliance_score():
    """Get latest overall compliance score."""
    try:
        from db import get_db
        conn = get_db()
        cur = conn.execute(
            "SELECT overall_score, scanned_at FROM compliance_scans ORDER BY scanned_at DESC LIMIT 1"
        )
        row = cur.fetchone()
        conn.close()
        if row:
            return {
                "score": row[0] if isinstance(row[0], (int, float)) else float(row[0]) if row[0] else None,
                "last_scan": row[1] if isinstance(row[1], str) else str(row[1]) if row[1] else None,
            }
    except Exception:
        pass
    return {"score": None, "last_scan": None}


def register_health_routes(bp, admin_required):
    @bp.route("/api/health", methods=["GET"])
    def health_check():
        """Public health endpoint — no auth required."""
        compliance = _get_compliance_score()
        config = current_app.config
        return jsonify({
            "status": "healthy",
            "version": config.get("VERSION", "1.0.0"),
            "uptime_seconds": int(time.time() - _start_time),
            "database": _check_db(),
            "last_compliance_scan": compliance["last_scan"],
            "compliance_score": compliance["score"],
            "connected_to_hub": bool(config.get("ARCHIE_HUB_URL")),
            "tier_progress": _get_tier_progress(),
        })
```

- [ ] **Step 3: Register health routes in __init__.py**

Add import and registration call matching the existing pattern:

```python
from .health_routes import register_health_routes
```

And in `register_all_routes()`:

```python
register_health_routes(bp, admin_required_decorator)
```

- [ ] **Step 4: Verify**

```bash
cd /mnt/archie_brain/kytran-server-manager
python3 -c "from kytran_server_manager.routes.health_routes import register_health_routes; print('OK')"
```

- [ ] **Step 5: Commit**

```bash
cd /mnt/archie_brain/kytran-server-manager
git add kytran_server_manager/routes/health_routes.py kytran_server_manager/routes/__init__.py
git commit -m "feat(health): add /api/health endpoint with tier progress"
```

---

### Task 4: SVG Badge Generator

**Files:**
- Create: `kytran-server-manager/kytran_server_manager/routes/badge_routes.py`
- Modify: `kytran-server-manager/kytran_server_manager/routes/__init__.py`

- [ ] **Step 1: Create badge_routes.py**

```python
"""Live SVG compliance badge generator."""

from flask import Response


def _score_to_grade(score):
    """Convert percentage to letter grade."""
    if score >= 95: return "A+"
    if score >= 90: return "A"
    if score >= 85: return "B+"
    if score >= 80: return "B"
    if score >= 70: return "C"
    if score >= 60: return "D"
    return "F"


def _score_to_color(score):
    """Convert percentage to badge color."""
    if score >= 90: return "#22c55e"  # green
    if score >= 80: return "#3b82f6"  # blue
    if score >= 70: return "#f59e0b"  # yellow
    return "#ef4444"  # red


def _generate_badge_svg(label, score):
    """Generate an SVG badge matching ARCHIE's format."""
    if score is None:
        grade = "N/A"
        color = "#6b7280"
        pct = "—"
    else:
        grade = _score_to_grade(score)
        color = _score_to_color(score)
        pct = f"{score:.0f}%"

    label_width = max(len(label) * 7 + 12, 60)
    value_width = max(len(f"{grade} {pct}") * 7 + 12, 60)
    total_width = label_width + value_width

    svg = f'''<svg xmlns="http://www.w3.org/2000/svg" width="{total_width}" height="20">
  <linearGradient id="b" x2="0" y2="100%">
    <stop offset="0" stop-color="#bbb" stop-opacity=".1"/>
    <stop offset="1" stop-opacity=".1"/>
  </linearGradient>
  <clipPath id="a"><rect width="{total_width}" height="20" rx="3" fill="#fff"/></clipPath>
  <g clip-path="url(#a)">
    <rect width="{label_width}" height="20" fill="#555"/>
    <rect x="{label_width}" width="{value_width}" height="20" fill="{color}"/>
    <rect width="{total_width}" height="20" fill="url(#b)"/>
  </g>
  <g fill="#fff" text-anchor="middle" font-family="Verdana,Geneva,DejaVu Sans,sans-serif" font-size="11">
    <text x="{label_width/2}" y="15" fill="#010101" fill-opacity=".3">{label}</text>
    <text x="{label_width/2}" y="14">{label}</text>
    <text x="{label_width + value_width/2}" y="15" fill="#010101" fill-opacity=".3">{grade} {pct}</text>
    <text x="{label_width + value_width/2}" y="14">{grade} {pct}</text>
  </g>
</svg>'''
    return svg


def register_badge_routes(bp, admin_required):
    @bp.route("/api/compliance/badge/<pack_id>.svg", methods=["GET"])
    def compliance_badge(pack_id):
        """Generate live SVG compliance badge. No auth — public endpoint."""
        score = None
        label = pack_id.replace("-", " ").upper()

        try:
            from db import get_db
            conn = get_db()

            if pack_id == "overall":
                label = "COMPLIANCE"
                cur = conn.execute(
                    "SELECT overall_score FROM compliance_scans ORDER BY scanned_at DESC LIMIT 1"
                )
                row = cur.fetchone()
                if row and row[0] is not None:
                    score = float(row[0])
            else:
                cur = conn.execute(
                    """SELECT AVG(CASE WHEN status = 'pass' THEN 100.0 ELSE 0.0 END) as score
                       FROM compliance_scan_results r
                       JOIN compliance_scans s ON r.scan_id = s.id
                       WHERE s.id = (SELECT id FROM compliance_scans ORDER BY scanned_at DESC LIMIT 1)
                       AND r.pack_id = ?""",
                    (pack_id,),
                )
                row = cur.fetchone()
                if row and row[0] is not None:
                    score = float(row[0])
            conn.close()
        except Exception:
            pass

        svg = _generate_badge_svg(label, score)
        return Response(svg, mimetype="image/svg+xml", headers={
            "Cache-Control": "no-cache, max-age=3600",
        })
```

- [ ] **Step 2: Register badge routes in __init__.py**

```python
from .badge_routes import register_badge_routes
```

And in `register_all_routes()`:

```python
register_badge_routes(bp, admin_required_decorator)
```

- [ ] **Step 3: Commit**

```bash
cd /mnt/archie_brain/kytran-server-manager
git add kytran_server_manager/routes/badge_routes.py kytran_server_manager/routes/__init__.py
git commit -m "feat(compliance): add live SVG badge generator endpoint"
```

---

## Phase 2: Compliance Automation

### Task 5: Background Compliance Scanner

**Files:**
- Create: `kytran-server-manager/kytran_server_manager/services/scheduler.py`
- Modify: `kytran-server-manager/kytran_server_manager/app.py`

- [ ] **Step 1: Read existing app.py**

Read `/mnt/archie_brain/kytran-server-manager/kytran_server_manager/app.py` to understand startup sequence.

- [ ] **Step 2: Create scheduler.py**

```python
"""Background compliance scan scheduler."""

import threading
import logging
import time

logger = logging.getLogger(__name__)

_scheduler_thread = None
_stop_event = threading.Event()


def _run_scheduled_scan(app):
    """Execute a compliance scan within app context."""
    with app.app_context():
        try:
            from services.compliance_service import run_scan
            logger.info("Scheduled compliance scan starting...")
            result = run_scan(triggered_by="scheduler")
            score = result.get("overall_score", "N/A") if isinstance(result, dict) else "N/A"
            logger.info(f"Scheduled compliance scan complete. Score: {score}")

            # Report to hub if configured
            hub_url = app.config.get("ARCHIE_HUB_URL")
            if hub_url and isinstance(result, dict):
                try:
                    from services.hub_client import report_compliance
                    report_compliance(result)
                except Exception as e:
                    logger.warning(f"Failed to report to hub: {e}")
        except Exception as e:
            logger.error(f"Scheduled compliance scan failed: {e}")


def _scheduler_loop(app, interval):
    """Background loop that runs scans at fixed intervals."""
    # Wait 60 seconds before first scan
    if _stop_event.wait(60):
        return
    while not _stop_event.is_set():
        _run_scheduled_scan(app)
        if _stop_event.wait(interval):
            return


def start_scheduler(app):
    """Start the background compliance scan scheduler."""
    global _scheduler_thread
    interval = app.config.get("COMPLIANCE_SCAN_INTERVAL", 21600)
    if interval <= 0:
        logger.info("Compliance scheduler disabled (interval <= 0)")
        return

    _stop_event.clear()
    _scheduler_thread = threading.Thread(
        target=_scheduler_loop,
        args=(app, interval),
        daemon=True,
        name="compliance-scheduler",
    )
    _scheduler_thread.start()
    logger.info(f"Compliance scheduler started (interval: {interval}s)")


def stop_scheduler():
    """Stop the background scheduler."""
    _stop_event.set()
    if _scheduler_thread:
        _scheduler_thread.join(timeout=5)
```

- [ ] **Step 3: Add scheduler startup to app.py**

At the end of the `create_app()` function (or after route registration), add:

```python
    # Start background compliance scanner
    from services.scheduler import start_scheduler
    start_scheduler(app)
```

- [ ] **Step 4: Commit**

```bash
cd /mnt/archie_brain/kytran-server-manager
git add kytran_server_manager/services/scheduler.py kytran_server_manager/app.py
git commit -m "feat(compliance): add background compliance scan scheduler (6h interval)"
```

---

### Task 6: Hub Client — Report Compliance to ARCHIE

**Files:**
- Create: `kytran-server-manager/kytran_server_manager/services/hub_client.py`

- [ ] **Step 1: Create hub_client.py**

```python
"""ARCHIE Hub communication client for compliance reporting and SSO."""

import logging
import base64
import requests
from flask import current_app

logger = logging.getLogger(__name__)


def _get_hub_config():
    """Get hub connection config from Flask app config."""
    config = current_app.config
    return {
        "hub_url": config.get("ARCHIE_HUB_URL", ""),
        "client_id": config.get("ARCHIE_CLIENT_ID", "kytran-sysops"),
        "client_secret": config.get("ARCHIE_CLIENT_SECRET", ""),
    }


def _hub_auth_header():
    """Build Authorization header for hub API calls."""
    cfg = _get_hub_config()
    credentials = f"{cfg['client_id']}:{cfg['client_secret']}"
    encoded = base64.b64encode(credentials.encode()).decode()
    return {"Authorization": f"Bearer {encoded}"}


def is_hub_configured():
    """Check if ARCHIE hub connection is configured."""
    cfg = _get_hub_config()
    return bool(cfg["hub_url"] and cfg["client_secret"])


def report_compliance(scan_result):
    """Report compliance scan results to ARCHIE hub."""
    cfg = _get_hub_config()
    if not cfg["hub_url"] or not cfg["client_secret"]:
        logger.debug("Hub not configured, skipping compliance report")
        return False

    url = f"{cfg['hub_url']}/api/standalone/compliance-report"
    payload = {
        "product_name": "Kytran System Operations",
        "client_id": cfg["client_id"],
        "overall_score": scan_result.get("overall_score"),
        "pack_scores": scan_result.get("pack_scores", {}),
        "total_rules": scan_result.get("total_rules", 0),
        "passed": scan_result.get("passed", 0),
        "failed": scan_result.get("failed", 0),
        "findings_summary": scan_result.get("findings_summary", []),
    }

    try:
        resp = requests.post(url, json=payload, headers=_hub_auth_header(), timeout=15)
        if resp.status_code == 200:
            logger.info(f"Compliance report sent to hub (score: {payload['overall_score']})")
            return True
        else:
            logger.warning(f"Hub returned {resp.status_code}: {resp.text[:200]}")
            return False
    except Exception as e:
        logger.warning(f"Failed to report to hub: {e}")
        return False


def exchange_code_for_token(code, redirect_uri):
    """Exchange OAuth authorization code for JWT token."""
    cfg = _get_hub_config()
    url = f"{cfg['hub_url']}/oauth/token"

    try:
        resp = requests.post(url, json={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
            "client_id": cfg["client_id"],
            "client_secret": cfg["client_secret"],
        }, timeout=10)

        if resp.status_code == 200:
            return resp.json()
        else:
            logger.error(f"Token exchange failed: {resp.status_code} {resp.text[:200]}")
            return None
    except Exception as e:
        logger.error(f"Token exchange error: {e}")
        return None
```

- [ ] **Step 2: Commit**

```bash
cd /mnt/archie_brain/kytran-server-manager
git add kytran_server_manager/services/hub_client.py
git commit -m "feat(hub): add ARCHIE hub client for compliance reporting and SSO"
```

---

## Phase 3: OAuth Provider (ARCHIE Side)

### Task 7: ARCHIE OAuth Provider

**Files:**
- Create: `platform_v2/oauth_provider.py`
- Modify: `platform_v2/app.py`

- [ ] **Step 1: Read app.py route registration pattern**

Read `/mnt/archie_brain/platform_v2/app.py` — find where Blueprints or routes are registered to match the pattern.

- [ ] **Step 2: Create oauth_provider.py**

```python
"""OAuth 2.0 Provider for 'Sign in with Kytran' standalone authentication."""

import secrets
import jwt
import time
from datetime import datetime, timedelta
from flask import Blueprint, request, redirect, jsonify, render_template_string, session
from flask_login import current_user, login_required
from database import get_db_cursor

oauth_bp = Blueprint("oauth", __name__)

JWT_SECRET = None  # Set from app.config["SECRET_KEY"] in init


def init_oauth(app):
    """Initialize OAuth provider with app config."""
    global JWT_SECRET
    JWT_SECRET = app.config.get("SECRET_KEY", "fallback-secret")
    app.register_blueprint(oauth_bp)


@oauth_bp.route("/oauth/authorize")
@login_required
def oauth_authorize():
    """OAuth authorization endpoint — redirect user to consent, generate code."""
    client_id = request.args.get("client_id")
    redirect_uri = request.args.get("redirect_uri")
    response_type = request.args.get("response_type", "code")

    if response_type != "code":
        return jsonify({"error": "unsupported_response_type"}), 400

    # Validate client
    with get_db_cursor() as (conn, cur):
        cur.execute(
            "SELECT name, redirect_uri FROM oauth_clients WHERE client_id = %s AND is_active = TRUE",
            (client_id,),
        )
        client = cur.fetchone()

    if not client:
        return jsonify({"error": "invalid_client", "message": "Unknown client_id"}), 400

    if redirect_uri != client["redirect_uri"]:
        return jsonify({"error": "invalid_redirect_uri"}), 400

    # Generate authorization code
    code = secrets.token_urlsafe(48)
    expires_at = datetime.utcnow() + timedelta(minutes=5)

    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            """INSERT INTO oauth_codes (code, client_id, user_id, redirect_uri, expires_at)
               VALUES (%s, %s, %s, %s, %s)""",
            (code, client_id, current_user.id, redirect_uri, expires_at),
        )

    # Redirect back to standalone with code
    separator = "&" if "?" in redirect_uri else "?"
    return redirect(f"{redirect_uri}{separator}code={code}")


@oauth_bp.route("/oauth/token", methods=["POST"])
def oauth_token():
    """Exchange authorization code for JWT token."""
    data = request.get_json() or {}
    grant_type = data.get("grant_type")
    code = data.get("code")
    client_id = data.get("client_id")
    client_secret = data.get("client_secret")
    redirect_uri = data.get("redirect_uri")

    if grant_type != "authorization_code":
        return jsonify({"error": "unsupported_grant_type"}), 400

    if not all([code, client_id, client_secret, redirect_uri]):
        return jsonify({"error": "invalid_request", "message": "Missing required fields"}), 400

    # Validate client credentials
    with get_db_cursor() as (conn, cur):
        cur.execute(
            "SELECT client_secret FROM oauth_clients WHERE client_id = %s AND is_active = TRUE",
            (client_id,),
        )
        client = cur.fetchone()

    if not client or client["client_secret"] != client_secret:
        return jsonify({"error": "invalid_client"}), 401

    # Validate and consume authorization code
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            """SELECT user_id, redirect_uri, expires_at, used FROM oauth_codes
               WHERE code = %s AND client_id = %s""",
            (code, client_id),
        )
        auth_code = cur.fetchone()

        if not auth_code:
            return jsonify({"error": "invalid_grant", "message": "Unknown code"}), 400
        if auth_code["used"]:
            return jsonify({"error": "invalid_grant", "message": "Code already used"}), 400
        if auth_code["expires_at"] < datetime.utcnow():
            return jsonify({"error": "invalid_grant", "message": "Code expired"}), 400
        if auth_code["redirect_uri"] != redirect_uri:
            return jsonify({"error": "invalid_grant", "message": "Redirect URI mismatch"}), 400

        # Mark code as used
        cur.execute("UPDATE oauth_codes SET used = TRUE WHERE code = %s", (code,))

        # Fetch user details
        cur.execute(
            "SELECT id, username, email, role FROM users WHERE id = %s",
            (auth_code["user_id"],),
        )
        user = cur.fetchone()

    if not user:
        return jsonify({"error": "invalid_grant", "message": "User not found"}), 400

    # Generate JWT
    token_payload = {
        "sub": user["id"],
        "username": user["username"],
        "email": user.get("email", ""),
        "role": user.get("role", "user"),
        "iat": int(time.time()),
        "exp": int(time.time()) + 3600,  # 1 hour
        "iss": "archie",
    }

    token = jwt.encode(token_payload, JWT_SECRET, algorithm="HS256")

    return jsonify({
        "access_token": token,
        "token_type": "bearer",
        "expires_in": 3600,
        "user": {
            "id": user["id"],
            "username": user["username"],
            "email": user.get("email", ""),
            "role": user.get("role", "user"),
        },
    })
```

- [ ] **Step 3: Register OAuth in app.py**

Find the route registration section in `app.py` and add:

```python
from oauth_provider import init_oauth
init_oauth(app)
```

- [ ] **Step 4: Verify PyJWT is available in Docker**

```bash
docker exec archie_platform pip show PyJWT 2>/dev/null || echo "NEED TO INSTALL"
```

If not installed, add `PyJWT` to requirements and rebuild, or install directly:
```bash
docker exec archie_platform pip install PyJWT
```

- [ ] **Step 5: Commit**

```bash
git add platform_v2/oauth_provider.py platform_v2/app.py
git commit -m "feat(oauth): add OAuth provider — authorize + token endpoints for standalone SSO"
```

---

### Task 8: ARCHIE Compliance Report Receiver

**Files:**
- Create: `platform_v2/api_standalone.py`
- Modify: `platform_v2/app.py`

- [ ] **Step 1: Create api_standalone.py**

```python
"""API endpoints for standalone product integration with ARCHIE hub."""

import base64
from flask import Blueprint, request, jsonify
from database import get_db_cursor

standalone_bp = Blueprint("standalone_api", __name__)


def _validate_client_auth():
    """Validate standalone client authentication from Authorization header."""
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return None

    try:
        encoded = auth_header[7:]
        decoded = base64.b64decode(encoded).decode()
        client_id, client_secret = decoded.split(":", 1)
    except Exception:
        return None

    with get_db_cursor() as (conn, cur):
        cur.execute(
            "SELECT client_id FROM oauth_clients WHERE client_id = %s AND client_secret = %s AND is_active = TRUE",
            (client_id, client_secret),
        )
        client = cur.fetchone()

    return client["client_id"] if client else None


@standalone_bp.route("/api/standalone/compliance-report", methods=["POST"])
def receive_compliance_report():
    """Receive compliance scan results from a standalone product."""
    client_id = _validate_client_auth()
    if not client_id:
        return jsonify({"error": "unauthorized"}), 401

    data = request.get_json() or {}
    product_name = data.get("product_name", "Unknown")
    overall_score = data.get("overall_score")
    pack_scores = data.get("pack_scores", {})
    total_rules = data.get("total_rules", 0)
    passed = data.get("passed", 0)
    failed = data.get("failed", 0)

    try:
        import json
        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                """INSERT INTO compliance_scans
                   (scan_target, overall_score, total_rules, passed, failed, pack_scores, scanned_at)
                   VALUES (%s, %s, %s, %s, %s, %s, NOW())
                   RETURNING id""",
                (product_name, overall_score, total_rules, passed, failed, json.dumps(pack_scores)),
            )
            scan_id = cur.fetchone()["id"]

        return jsonify({"success": True, "scan_id": scan_id})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


def init_standalone_api(app):
    """Register standalone API blueprint."""
    app.register_blueprint(standalone_bp)
```

- [ ] **Step 2: Register in app.py**

Add alongside the OAuth registration:

```python
from api_standalone import init_standalone_api
init_standalone_api(app)
```

- [ ] **Step 3: Verify compliance_scans table accepts the columns**

```bash
docker exec archie_database psql -U archie -d archie -c "\d compliance_scans" 2>/dev/null | head -20
```

If the table doesn't have `scan_target`, `total_rules`, `passed`, `failed`, `pack_scores` columns, create a migration to add them. Adapt the INSERT to match the actual schema.

- [ ] **Step 4: Commit**

```bash
git add platform_v2/api_standalone.py platform_v2/app.py
git commit -m "feat(standalone): add compliance report receiver endpoint"
```

---

## Phase 4: SSO on Standalone

### Task 9: Upgrade SSO Stub to Real OAuth Flow

**Files:**
- Modify: `kytran-server-manager/kytran_server_manager/auth.py`
- Modify: `kytran-server-manager/kytran_server_manager/templates/login.html`

- [ ] **Step 1: Read current auth.py**

Read `/mnt/archie_brain/kytran-server-manager/kytran_server_manager/auth.py` to understand the full current implementation including the SSO stub.

- [ ] **Step 2: Upgrade SSO routes**

Replace the SSO stub routes with real OAuth flow:

```python
@app.route("/auth/sso", methods=["GET"])
def sso_login():
    """Redirect to ARCHIE OAuth authorization."""
    hub_url = app.config.get("ARCHIE_HUB_URL")
    client_id = app.config.get("ARCHIE_CLIENT_ID", "kytran-sysops")
    if not hub_url:
        return jsonify({"error": "SSO not configured", "message": "ARCHIE_HUB_URL not set"}), 501

    # Build standalone callback URL
    callback_url = request.url_root.rstrip("/") + "/auth/sso/callback"
    authorize_url = (
        f"{hub_url}/oauth/authorize"
        f"?client_id={client_id}"
        f"&redirect_uri={callback_url}"
        f"&response_type=code"
    )
    return redirect(authorize_url)


@app.route("/auth/sso/callback", methods=["GET"])
def sso_callback():
    """Handle OAuth callback from ARCHIE — exchange code for token, create session."""
    code = request.args.get("code")
    error = request.args.get("error")

    if error:
        flash(f"SSO error: {error}", "error")
        return redirect(url_for("login"))

    if not code:
        flash("No authorization code received", "error")
        return redirect(url_for("login"))

    # Exchange code for token
    callback_url = request.url_root.rstrip("/") + "/auth/sso/callback"

    from services.hub_client import exchange_code_for_token
    token_data = exchange_code_for_token(code, callback_url)

    if not token_data:
        flash("Failed to authenticate with ARCHIE", "error")
        return redirect(url_for("login"))

    user_info = token_data.get("user", {})
    username = user_info.get("username", "")
    email = user_info.get("email", "")
    role = user_info.get("role", "user")

    # Create or link local user
    from db import get_db
    conn = get_db()

    cur = conn.execute("SELECT * FROM users WHERE username = ?", (username,))
    existing = cur.fetchone()

    if existing:
        user_id = existing["id"] if isinstance(existing, dict) else existing[0]
    else:
        cur = conn.execute(
            "INSERT INTO users (username, password_hash, role, sso_provider) VALUES (?, ?, ?, ?)",
            (username, "", role if role == "admin" else "user", "kytran"),
        )
        conn.commit()
        user_id = cur.lastrowid

    conn.close()

    # Log in the user
    user = User.get(user_id)
    if user:
        login_user(user)
        return redirect(url_for("sysops.dashboard_home"))

    flash("Failed to create local user", "error")
    return redirect(url_for("login"))


@app.route("/auth/sso/status", methods=["GET"])
def sso_status():
    """Check SSO configuration status."""
    hub_url = app.config.get("ARCHIE_HUB_URL", "")
    return jsonify({
        "sso_enabled": bool(hub_url and app.config.get("ARCHIE_CLIENT_SECRET")),
        "provider": "kytran",
        "auth_url": f"{hub_url}/oauth/authorize" if hub_url else None,
        "message": "SSO active" if hub_url else "SSO pending configuration",
    })
```

IMPORTANT: Read the existing auth.py first. The exact implementation must match the existing User class, login_user import, flash import, url_for names, and DB access pattern. Adapt the code above to use whatever is already there.

- [ ] **Step 3: Add sso_provider column to users table if needed**

Check the standalone's SQLite schema for a `sso_provider` column:
```bash
cd /mnt/archie_brain/kytran-server-manager
python3 -c "
import sqlite3
conn = sqlite3.connect('data/kytran_server_manager.db')
cur = conn.execute('PRAGMA table_info(users)')
for col in cur.fetchall(): print(col)
conn.close()
"
```

If `sso_provider` doesn't exist, add it:
```python
conn.execute("ALTER TABLE users ADD COLUMN sso_provider VARCHAR(32) DEFAULT NULL")
```

- [ ] **Step 4: Update login.html — SSO button**

Read the current `login.html`. Replace the "Coming Soon" SSO indicator with a real button when hub is configured. The template should check for a variable like `sso_enabled`:

```html
{% if sso_enabled %}
<div style="text-align:center;margin-top:20px;padding-top:16px;border-top:1px solid rgba(var(--frame-rgb),0.2);">
    <a href="/auth/sso" style="display:inline-block;min-height:44px;padding:10px 24px;background:rgba(139,92,246,0.15);border:1px solid rgba(139,92,246,0.4);color:#8b5cf6;border-radius:8px;text-decoration:none;font-weight:600;font-size:13px;transition:all 0.2s ease;">
        Sign in with Kytran
    </a>
</div>
{% else %}
<div style="text-align:center;margin-top:20px;padding-top:16px;border-top:1px solid rgba(var(--frame-rgb),0.2);">
    <p style="color:#666;font-size:12px;">Sign in with Kytran &mdash; Coming Soon</p>
</div>
{% endif %}
```

Pass `sso_enabled` from the login route:
```python
return render_template("login.html", sso_enabled=bool(app.config.get("ARCHIE_HUB_URL")))
```

- [ ] **Step 5: Commit**

```bash
cd /mnt/archie_brain/kytran-server-manager
git add kytran_server_manager/auth.py kytran_server_manager/templates/login.html
git commit -m "feat(auth): upgrade SSO stub to real OAuth flow with ARCHIE"
```

---

## Phase 5: ARCHIE Launch Page + Integration

### Task 10: ARCHIE Launch Page (Replace System Ops Module)

**Files:**
- Modify: `platform_v2/tools/system_operations/routes.py`
- Create: `platform_v2/tools/system_operations/templates/system_operations_launch.html`

- [ ] **Step 1: Read current system_operations routes.py**

Read `/mnt/archie_brain/platform_v2/tools/system_operations/routes.py` — find the main dashboard route (likely the first route, serving the template).

- [ ] **Step 2: Create launch page template**

Create `platform_v2/tools/system_operations/templates/system_operations_launch.html`:

```html
{% extends "base.html" %}
{% block title %}System Operations{% endblock %}
{% block content %}
<style>
.so-launch {
    max-width: 600px;
    margin: 40px auto;
    padding: 32px;
    background: rgba(15, 23, 42, 0.6);
    border: 1px solid rgba(139, 92, 246, 0.2);
    border-radius: 12px;
    text-align: center;
}
.so-launch-title {
    font-family: 'Antonio', 'Orbitron', sans-serif;
    font-size: 1.6rem;
    color: #f59e0b;
    letter-spacing: 2px;
    text-transform: uppercase;
    margin-bottom: 8px;
}
.so-launch-subtitle {
    color: rgba(255,255,255,0.5);
    font-size: 0.85rem;
    margin-bottom: 24px;
}
.so-health-row {
    display: flex;
    justify-content: center;
    gap: 24px;
    margin-bottom: 24px;
    flex-wrap: wrap;
}
.so-health-item {
    text-align: center;
}
.so-health-value {
    font-size: 1.4rem;
    font-weight: 700;
}
.so-health-label {
    font-size: 0.65rem;
    letter-spacing: 1px;
    color: rgba(255,255,255,0.4);
    text-transform: uppercase;
    margin-top: 2px;
}
.so-status-dot {
    width: 10px; height: 10px;
    border-radius: 50%;
    display: inline-block;
    margin-right: 6px;
}
.so-status-dot.healthy { background: #22c55e; box-shadow: 0 0 6px rgba(34,197,94,0.5); }
.so-status-dot.unhealthy { background: #ef4444; box-shadow: 0 0 6px rgba(239,68,68,0.5); }
.so-launch-btn {
    display: inline-block;
    min-height: 48px;
    padding: 14px 32px;
    background: rgba(245, 158, 11, 0.15);
    border: 1px solid #f59e0b;
    color: #f59e0b;
    border-radius: 8px;
    text-decoration: none;
    font-weight: 700;
    font-size: 14px;
    letter-spacing: 1px;
    text-transform: uppercase;
    transition: all 0.2s ease;
    cursor: pointer;
}
.so-launch-btn:hover {
    background: rgba(245, 158, 11, 0.25);
    box-shadow: 0 0 16px rgba(245, 158, 11, 0.3);
}
.so-tier-bar {
    height: 6px;
    background: rgba(255,255,255,0.1);
    border-radius: 3px;
    margin: 16px 0;
    overflow: hidden;
}
.so-tier-fill {
    height: 100%;
    border-radius: 3px;
    transition: width 0.5s ease;
}
.so-sso-note {
    margin-top: 16px;
    font-size: 0.75rem;
    color: rgba(255,255,255,0.3);
}
</style>

<div class="so-launch">
    <div class="so-launch-title">Kytran System Operations</div>
    <div class="so-launch-subtitle">Standalone Server Management + Compliance Engine</div>

    <div class="so-health-row">
        <div class="so-health-item">
            <div class="so-health-value" id="soStatus">
                <span class="so-status-dot" id="soStatusDot"></span>
                <span id="soStatusText">Loading...</span>
            </div>
            <div class="so-health-label">Status</div>
        </div>
        <div class="so-health-item">
            <div class="so-health-value" id="soVersion" style="color:#8b5cf6;">—</div>
            <div class="so-health-label">Version</div>
        </div>
        <div class="so-health-item">
            <div class="so-health-value" id="soCompliance" style="color:#22c55e;">—</div>
            <div class="so-health-label">Compliance</div>
        </div>
    </div>

    <div style="font-size:0.75rem;color:rgba(255,255,255,0.4);margin-bottom:4px;">
        Tier Progress: <span id="soTierText">—</span>
    </div>
    <div class="so-tier-bar">
        <div class="so-tier-fill" id="soTierFill" style="width:0%;background:#f59e0b;"></div>
    </div>

    <a href="{{ standalone_url }}" target="_blank" rel="noopener" class="so-launch-btn">
        Launch System Operations
    </a>

    <div class="so-sso-note">
        Sign in with your Kytran account for seamless access
    </div>
</div>

<script>
(function() {
    var url = "{{ standalone_url }}";
    function refresh() {
        fetch(url + "/dashboard/api/health", {mode: "cors"}).then(function(r) { return r.json(); }).then(function(d) {
            var dot = document.getElementById("soStatusDot");
            var txt = document.getElementById("soStatusText");
            dot.className = "so-status-dot " + (d.status === "healthy" ? "healthy" : "unhealthy");
            txt.textContent = d.status === "healthy" ? "Online" : "Offline";
            txt.style.color = d.status === "healthy" ? "#22c55e" : "#ef4444";

            document.getElementById("soVersion").textContent = d.version || "—";

            var score = d.compliance_score;
            var el = document.getElementById("soCompliance");
            el.textContent = score != null ? score.toFixed(0) + "%" : "—";
            el.style.color = score >= 90 ? "#22c55e" : score >= 70 ? "#f59e0b" : "#ef4444";

            var tp = d.tier_progress || {};
            document.getElementById("soTierText").textContent = "Tier " + (tp.current_tier || "?") + ": " + (tp.completed || 0) + "/" + (tp.total || 0);
            var pct = tp.total ? (tp.completed / tp.total * 100) : 0;
            var fill = document.getElementById("soTierFill");
            fill.style.width = pct + "%";
            fill.style.background = pct >= 75 ? "#22c55e" : pct >= 25 ? "#f59e0b" : "#ef4444";
        }).catch(function() {
            document.getElementById("soStatusDot").className = "so-status-dot unhealthy";
            document.getElementById("soStatusText").textContent = "Offline";
            document.getElementById("soStatusText").style.color = "#ef4444";
        });
    }
    refresh();
    setInterval(refresh, 30000);
})();
</script>
{% endblock %}
```

- [ ] **Step 3: Update the main dashboard route**

In `routes.py`, find the route that serves the System Operations dashboard (likely `@bp.route("/")` or the first route). Replace it to serve the launch page:

```python
@bp.route("/")
@login_required
@admin_required
def system_operations_dashboard():
    """Launch page for standalone Kytran System Operations."""
    import os
    standalone_url = os.getenv("STANDALONE_SYSOPS_URL", "http://192.168.1.200:8085")
    return render_template(
        "tools/system_operations/system_operations_launch.html",
        standalone_url=standalone_url,
    )
```

IMPORTANT: Read the existing route first to understand the exact function name, decorators, and any other parameters. Keep the existing route's function signature — just change what it renders.

All other System Operations routes (docker, network, firewall, etc.) should stay — they still work for direct platform access. Only the main dashboard changes.

- [ ] **Step 4: Commit**

```bash
git add platform_v2/tools/system_operations/routes.py platform_v2/tools/system_operations/templates/system_operations_launch.html
git commit -m "feat(sysops): replace module dashboard with standalone launch page"
```

---

### Task 11: Subdomain Setup (AdGuard + NPM)

**Files:** None (infrastructure configuration via API/UI)

- [ ] **Step 1: Add AdGuard DNS rewrite**

Use the AdGuard API or UI to add DNS rewrite:
- Domain: `server.kytranempowerment.com`
- Answer: `192.168.1.200`

Via API:
```bash
curl -s -u "admin:PASSWORD" -X POST "http://192.168.1.200:8080/control/rewrite/add" \
  -H "Content-Type: application/json" \
  -d '{"domain":"server.kytranempowerment.com","answer":"192.168.1.200"}'
```

(Replace PASSWORD with AdGuard admin password from .env)

- [ ] **Step 2: Add NPM Proxy Host**

Via NPM UI at `http://192.168.1.200:81`:
1. Add Proxy Host
2. Domain: `server.kytranempowerment.com`
3. Forward Host: `192.168.1.200`
4. Forward Port: `8085`
5. SSL tab: Request new Let's Encrypt certificate, Force SSL

Or via API (requires NPM token):
```bash
# Get token first, then create proxy host
```

- [ ] **Step 3: Test subdomain resolves**

```bash
curl -s -k https://server.kytranempowerment.com/ -o /dev/null -w "HTTP %{http_code}"
```

Expected: `HTTP 302` (redirect to login)

- [ ] **Step 4: Set standalone env var**

Add to standalone's environment (systemd service or .env):
```
SERVER_SUBDOMAIN=server.kytranempowerment.com
```

Restart: `sudo systemctl restart kytran-server-manager`

---

### Task 12: Dashboard Compliance Summary Bar

**Files:**
- Modify: `kytran-server-manager/kytran_server_manager/templates/dashboard.html`

- [ ] **Step 1: Read current dashboard.html**

Read the dashboard template to find where the compliance summary bar should go — below the LCARS header bar, above the tab navigation.

- [ ] **Step 2: Add compliance summary bar**

After the LCARS header bar and before the tab nav, add:

```html
<!-- Compliance Summary Bar -->
<div id="complianceSummaryBar" style="display:flex;align-items:center;gap:12px;padding:8px 16px;background:rgba(15,23,42,0.6);border-bottom:1px solid rgba(34,197,94,0.15);flex-wrap:wrap;">
    <span style="font-size:11px;color:rgba(255,255,255,0.4);text-transform:uppercase;letter-spacing:1px;">Compliance</span>
    <span id="compOverallBadge" style="font-size:13px;font-weight:700;color:#22c55e;">—</span>
    <div id="compPackBadges" style="display:flex;gap:6px;flex-wrap:wrap;"></div>
    <button onclick="triggerComplianceScan()" id="compScanBtn" style="margin-left:auto;padding:4px 12px;border:1px solid rgba(139,92,246,0.3);background:rgba(139,92,246,0.05);color:#8b5cf6;border-radius:6px;cursor:pointer;font-size:11px;min-height:32px;">Run Scan</button>
</div>

<script>
function loadComplianceSummary() {
    fetch("/dashboard/api/compliance/scans?limit=1").then(function(r){ return r.json(); }).then(function(d) {
        var scans = d.scans || d.history || [];
        if (!scans.length) { document.getElementById("compOverallBadge").textContent = "No scans yet"; return; }
        var latest = scans[0];
        var score = latest.overall_score || latest.score;
        var el = document.getElementById("compOverallBadge");
        if (score != null) {
            el.textContent = parseFloat(score).toFixed(1) + "%";
            el.style.color = score >= 90 ? "#22c55e" : score >= 70 ? "#f59e0b" : "#ef4444";
        }
        // Pack badges
        var packs = latest.pack_scores || {};
        var container = document.getElementById("compPackBadges");
        container.textContent = "";
        Object.keys(packs).forEach(function(k) {
            var s = packs[k];
            var badge = document.createElement("span");
            badge.style.cssText = "padding:2px 8px;border-radius:4px;font-size:10px;font-weight:600;background:rgba(255,255,255,0.05);border:1px solid rgba(255,255,255,0.1);";
            badge.style.color = s >= 90 ? "#22c55e" : s >= 70 ? "#f59e0b" : "#ef4444";
            badge.textContent = k.replace(/-/g," ").toUpperCase() + " " + parseFloat(s).toFixed(0) + "%";
            container.appendChild(badge);
        });
    }).catch(function(){});
}
function triggerComplianceScan() {
    var btn = document.getElementById("compScanBtn");
    btn.disabled = true; btn.textContent = "Scanning...";
    fetch("/dashboard/api/compliance/scan", {method:"POST"}).then(function(r){ return r.json(); }).then(function(d) {
        btn.disabled = false; btn.textContent = "Run Scan";
        loadComplianceSummary();
    }).catch(function(){ btn.disabled = false; btn.textContent = "Run Scan"; });
}
loadComplianceSummary();
</script>
```

- [ ] **Step 3: Commit**

```bash
cd /mnt/archie_brain/kytran-server-manager
git add kytran_server_manager/templates/dashboard.html
git commit -m "feat(compliance): add compliance summary bar with badges and scan trigger"
```

---

## Phase 6: Polish + Verification

### Task 13: Code Health — Dynamic Tier Progress Badge

**Files:**
- Modify: `platform_v2/static/js/consciousness.js`
- Modify: `platform_v2/tools/consciousness/code_health_routes.py`

- [ ] **Step 1: Update standalone-status endpoint to include tier data**

In `code_health_routes.py`, in the `code_health_standalone_status()` function, after building the results list, add a call to the standalone's health endpoint to get tier progress:

```python
        # Fetch tier progress from standalone health endpoint
        tier_progress = None
        try:
            import requests as req
            health_resp = req.get(f"{product['path'].replace('/mnt/archie_brain/kytran-server-manager', 'http://192.168.1.200:8085')}/dashboard/api/health", timeout=5)
            if health_resp.status_code == 200:
                tier_progress = health_resp.json().get("tier_progress")
        except Exception:
            pass

        results[-1]["tier_progress"] = tier_progress
```

IMPORTANT: Read the existing endpoint first. The standalone URL should come from config, not hardcoded. Check if `STANDALONE_SYSOPS_URL` env var is available in the container.

- [ ] **Step 2: Update _renderStandaloneTable in consciousness.js**

Replace the static TIER 1 badge with a dynamic tier progress badge. Read the current function first, then update the tier cell to show progress:

```javascript
// Replace the static TIER 1 badge with dynamic progress
var tierHtml;
var tp = m.tier_progress;
if (tp) {
    var pct = tp.total ? Math.round(tp.completed / tp.total * 100) : 0;
    var barColor = pct >= 75 ? "#22c55e" : pct >= 25 ? "#f59e0b" : "#ef4444";
    tierHtml = '<div style="text-align:center;">'
        + '<span style="font-size:10px;font-weight:600;color:' + barColor + ';">TIER ' + tp.current_tier + ': ' + tp.completed + '/' + tp.total + '</span>'
        + '<div style="height:4px;background:rgba(255,255,255,0.1);border-radius:2px;margin-top:3px;width:60px;display:inline-block;">'
        + '<div style="height:100%;width:' + pct + '%;background:' + barColor + ';border-radius:2px;"></div>'
        + '</div></div>';
} else {
    tierHtml = '<span style="background:#f59e0b;color:#000;padding:2px 8px;border-radius:4px;font-size:11px;font-weight:bold;">TIER 1</span>';
}
```

- [ ] **Step 3: Commit**

```bash
git add platform_v2/static/js/consciousness.js platform_v2/tools/consciousness/code_health_routes.py
git commit -m "feat(code-health): dynamic tier progress badge with live standalone data"
```

---

### Task 14: Responsive Polish on Standalone

**Files:**
- Modify: `kytran-server-manager/kytran_server_manager/static/css/lcars-frames.css`
- Modify: `kytran-server-manager/kytran_server_manager/templates/dashboard.html`

- [ ] **Step 1: Read current responsive CSS and dashboard**

Check the current LCARS frames CSS responsive sections and the dashboard tab navigation.

- [ ] **Step 2: Add responsive enhancements**

In `lcars-frames.css`, add/extend mobile styles:

```css
/* Tab navigation — horizontal scroll on mobile */
.tab-nav {
    display: flex;
    overflow-x: auto;
    -webkit-overflow-scrolling: touch;
    scroll-snap-type: x mandatory;
    gap: 4px;
    padding-bottom: 4px;
}
.tab-nav button {
    scroll-snap-align: start;
    flex-shrink: 0;
    min-height: 44px;
    min-width: 44px;
}

/* Data tables — horizontal scroll */
.data-table-scroll {
    overflow-x: auto;
    -webkit-overflow-scrolling: touch;
}

/* Compliance badges — stack on mobile */
@media (max-width: 480px) {
    #complianceSummaryBar {
        flex-direction: column;
        align-items: flex-start;
        gap: 8px;
    }
    #compScanBtn { margin-left: 0; width: 100%; }
    .tab-nav button { font-size: 11px; padding: 8px 12px; }
}

/* Login form — full width on mobile */
@media (max-width: 480px) {
    .lcars-frame--tablet .lcars-body { padding: 16px; }
    .lcars-frame--tablet input[type="text"],
    .lcars-frame--tablet input[type="password"] { width: 100%; }
}
```

- [ ] **Step 3: Wrap data tables in scroll containers in dashboard.html**

Find any data tables in the dashboard that aren't already scrollable and wrap them:

```html
<div class="data-table-scroll">
    <!-- existing table content -->
</div>
```

- [ ] **Step 4: Commit**

```bash
cd /mnt/archie_brain/kytran-server-manager
git add kytran_server_manager/static/css/lcars-frames.css kytran_server_manager/templates/dashboard.html
git commit -m "feat(responsive): mobile polish — scroll tabs, stacked badges, touch targets"
```

---

### Task 15: Deploy + Configure + Verify

**Files:** None (deployment + configuration)

- [ ] **Step 1: Set standalone environment variables**

Get the client secret from Task 1 Step 3, then configure the standalone:

```bash
# Edit systemd service or .env file
sudo systemctl edit kytran-server-manager --force
```

Add environment:
```
[Service]
Environment="ARCHIE_HUB_URL=http://192.168.1.200:3000"
Environment="ARCHIE_CLIENT_ID=kytran-sysops"
Environment="ARCHIE_CLIENT_SECRET=<secret_from_task_1>"
Environment="SERVER_SUBDOMAIN=server.kytranempowerment.com"
```

- [ ] **Step 2: Deploy ARCHIE platform**

```bash
docker compose restart archie_platform
```

- [ ] **Step 3: Restart standalone**

```bash
sudo systemctl restart kytran-server-manager
```

- [ ] **Step 4: Verification checklist**

Test each Tier 2 requirement:

- [ ] `curl http://192.168.1.200:8085/dashboard/api/health` — returns health JSON with tier_progress
- [ ] `curl http://192.168.1.200:8085/dashboard/api/compliance/badge/overall.svg` — returns SVG badge
- [ ] Open `http://192.168.1.200:8085` — click "Sign in with Kytran" — redirects to ARCHIE login — returns logged in
- [ ] Open `http://192.168.1.200:3000/tools/system-operations` — shows launch page with health status
- [ ] `https://server.kytranempowerment.com` loads over SSL
- [ ] Code Health tab shows dynamic tier progress badge
- [ ] Standalone dashboard shows compliance summary bar
- [ ] All views work at 480px / 768px / 1024px

- [ ] **Step 5: Log decision + complete task**

```python
mcp__archie__log_decision(
    title="KSM Tier 2 Complete — SSO, Compliance, Subdomain, Launch Page",
    decision="Tier 2 of standalone extraction playbook completed. ARCHIE OAuth provider enables 'Sign in with Kytran'. Standalone runs self-contained compliance scans and reports to hub. Launch page replaces System Ops module in ARCHIE.",
    context="Following standalone-extraction.md Tier 2 requirements (30-day target).",
    project_id=193
)
mcp__archie__complete_task(task_id=..., notes="Tier 2 complete: SSO, compliance scanning+badges, subdomain, launch page, health endpoint, responsive, tier progress")
```

---

## Task Summary

| Task | Phase | Description | Codebase |
|------|-------|-------------|----------|
| 1 | Foundation | OAuth tables migration | ARCHIE DB |
| 2 | Foundation | Standalone hub config vars | Standalone |
| 3 | Foundation | Health endpoint + tier progress | Standalone |
| 4 | Foundation | SVG badge generator | Standalone |
| 5 | Compliance | Background scan scheduler | Standalone |
| 6 | Compliance | Hub client for reporting | Standalone |
| 7 | OAuth | ARCHIE OAuth provider | ARCHIE |
| 8 | OAuth | Compliance report receiver | ARCHIE |
| 9 | SSO | Upgrade SSO stub to real flow | Standalone |
| 10 | Integration | Launch page replaces module | ARCHIE |
| 11 | Integration | Subdomain (AdGuard + NPM) | Infrastructure |
| 12 | Integration | Dashboard compliance bar | Standalone |
| 13 | Polish | Dynamic tier progress badge | ARCHIE |
| 14 | Polish | Responsive mobile polish | Standalone |
| 15 | Deploy | Configure + verify all | Both |

**Total: 15 tasks across 6 phases**
