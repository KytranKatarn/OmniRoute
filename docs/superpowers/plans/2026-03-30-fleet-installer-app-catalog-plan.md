# Fleet Installer + KSO App Catalog Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn KSO into the fleet's universal node OS with a bootstrap installer, app catalog for one-click deployment of standalone products, satellite PWA for mobile fleet presence, and hub Fleet API extensions.

**Architecture:** Hub serves an app registry (YAML catalog entries) and fleet registration/heartbeat API. The installer bootstraps Linux nodes with Docker + Tailscale + KSO. KSO's new App Catalog tab fetches the registry and manages Docker containers. Satellite PWA is served from hub for mobile nodes (Tailscale mesh + heartbeats only).

**Tech Stack:** Bash (installer), Python/Flask (KSO routes + hub API), YAML (catalog entries), vanilla HTML/CSS/JS (PWA), PostgreSQL (hub fleet tables), SQLite (KSO local state), Docker Compose (app deployment)

**Spec:** `docs/superpowers/specs/2026-03-30-fleet-installer-app-catalog-design.md`

---

## File Structure

### New Files

```
# Hub Fleet API
platform_v2/tools/starbase/fleet_routes.py          — registration, tokens, catalog, approval endpoints
database/migrations/031_fleet_registration_tokens.sql — token + remote_nodes column additions

# App Registry
fleet/catalog/apps/gov-watch.yml       — catalog entry
fleet/catalog/apps/news.yml            — catalog entry
fleet/catalog/apps/business-suite.yml  — catalog entry
fleet/catalog/apps/market-watch.yml    — catalog entry
fleet/catalog/apps/smtp-relay.yml      — catalog entry
fleet/catalog/apps/monitoring.yml      — catalog entry

# KSO App Catalog
kytran-server-manager/kytran_server_manager/routes/app_catalog_routes.py  — catalog API routes
kytran-server-manager/kytran_server_manager/services/app_catalog_service.py — deploy/manage logic
kytran-server-manager/kytran_server_manager/templates/apps.html           — catalog browser UI

# Fleet Installer
fleet/installer/install.sh             — bootstrap script

# Satellite PWA
platform_v2/static/fleet/satellite/index.html       — PWA entry point
platform_v2/static/fleet/satellite/manifest.json     — PWA manifest
platform_v2/static/fleet/satellite/sw.js             — service worker
platform_v2/static/fleet/satellite/satellite.js      — main app logic
platform_v2/static/fleet/satellite/satellite.css     — LCARS mobile styles
```

### Modified Files

```
platform_v2/tools/starbase/__init__.py    — register fleet_routes
platform_v2/tools/starbase/node_routes.py — extend heartbeat with apps_running
kytran-server-manager/kytran_server_manager/routes/__init__.py — register app_catalog_routes
```

---

## Task 1: Hub Fleet API — Database Migration

**Files:**
- Create: `database/migrations/031_fleet_registration_tokens.sql`

- [ ] **Step 1: Write the migration SQL**

```sql
-- 031_fleet_registration_tokens.sql
-- Fleet registration tokens + remote_nodes extensions

-- Registration tokens table
CREATE TABLE IF NOT EXISTS fleet_registration_tokens (
    id SERIAL PRIMARY KEY,
    token VARCHAR(64) NOT NULL UNIQUE,
    node_type VARCHAR(20) NOT NULL CHECK (node_type IN ('outpost', 'starship', 'satellite')),
    created_by INTEGER REFERENCES users(id),
    created_at TIMESTAMP DEFAULT NOW(),
    expires_at TIMESTAMP NOT NULL,
    used_at TIMESTAMP,
    used_by_node_id VARCHAR(50)
);

CREATE INDEX IF NOT EXISTS idx_fleet_tokens_token ON fleet_registration_tokens(token);
CREATE INDEX IF NOT EXISTS idx_fleet_tokens_expires ON fleet_registration_tokens(expires_at);

-- Extend remote_nodes with fleet fields
ALTER TABLE remote_nodes ADD COLUMN IF NOT EXISTS registration_method VARCHAR(20) DEFAULT 'approval';
ALTER TABLE remote_nodes ADD COLUMN IF NOT EXISTS device_info JSONB DEFAULT '{}';
ALTER TABLE remote_nodes ADD COLUMN IF NOT EXISTS apps_running JSONB DEFAULT '[]';
ALTER TABLE remote_nodes ADD COLUMN IF NOT EXISTS node_name VARCHAR(100);
```

- [ ] **Step 2: Run the migration**

```bash
docker exec archie_database psql -U archie -d archie -f /docker-entrypoint-initdb.d/031_fleet_registration_tokens.sql
```

Copy it into the container first:
```bash
docker cp database/migrations/031_fleet_registration_tokens.sql archie_database:/docker-entrypoint-initdb.d/
docker exec archie_database psql -U archie -d archie -f /docker-entrypoint-initdb.d/031_fleet_registration_tokens.sql
```

Expected: `CREATE TABLE`, `CREATE INDEX`, `ALTER TABLE` with no errors.

- [ ] **Step 3: Verify columns exist**

```bash
docker exec archie_database psql -U archie -d archie -c "\d fleet_registration_tokens"
docker exec archie_database psql -U archie -d archie -c "SELECT column_name FROM information_schema.columns WHERE table_name='remote_nodes' AND column_name IN ('registration_method','device_info','apps_running','node_name');"
```

Expected: Table exists with all columns; 4 rows returned for remote_nodes.

- [ ] **Step 4: Commit**

```bash
git add database/migrations/031_fleet_registration_tokens.sql
git commit -m "feat(fleet): add registration tokens table and remote_nodes extensions"
```

---

## Task 2: Hub Fleet API — Registration, Tokens, Catalog Endpoints

**Files:**
- Create: `platform_v2/tools/starbase/fleet_routes.py`
- Modify: `platform_v2/tools/starbase/__init__.py`

- [ ] **Step 1: Create fleet_routes.py with all endpoints**

Create `platform_v2/tools/starbase/fleet_routes.py`:

```python
"""Fleet API routes — registration, tokens, catalog, approval."""

import hashlib
import os
import secrets
from datetime import datetime, timedelta

import yaml
from flask import jsonify, request
from flask_login import current_user

from database import get_db_cursor


CATALOG_DIR = os.path.join(
    os.path.dirname(__file__), "..", "..", "..", "fleet", "catalog", "apps"
)


def register_fleet_routes(bp, admin_required):
    """Register fleet management routes on the starbase blueprint."""

    # ── Token Generation ─────────────────────────────────────────────
    @bp.route("/api/fleet/token/generate", methods=["POST"])
    @admin_required
    def fleet_generate_token():
        """Generate a single-use registration token."""
        data = request.get_json() or {}
        node_type = data.get("node_type", "outpost")
        expires_hours = data.get("expires_in_hours", 24)

        if node_type not in ("outpost", "starship", "satellite"):
            return jsonify({"success": False, "error": "Invalid node_type"}), 400

        token = secrets.token_urlsafe(32)
        expires_at = datetime.utcnow() + timedelta(hours=expires_hours)

        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                """INSERT INTO fleet_registration_tokens
                   (token, node_type, created_by, expires_at)
                   VALUES (%s, %s, %s, %s)
                   RETURNING id""",
                (token, node_type, current_user.id, expires_at),
            )
            token_id = cur.fetchone()[0]

        return jsonify({
            "success": True,
            "token": token,
            "token_id": token_id,
            "node_type": node_type,
            "expires_at": expires_at.isoformat(),
        })

    # ── Node Registration ────────────────────────────────────────────
    @bp.route("/api/fleet/register", methods=["POST"])
    def fleet_register_node():
        """Register a new fleet node. Token = instant approve, no token = pending."""
        data = request.get_json() or {}
        name = data.get("name", "unnamed-node")
        node_type = data.get("type", "outpost")
        token = data.get("token")
        device_info = data.get("device_info", {})

        if node_type not in ("outpost", "starship", "satellite"):
            return jsonify({"success": False, "error": "Invalid node type"}), 400

        node_id = f"node_{secrets.token_hex(8)}"
        api_key = secrets.token_urlsafe(32)
        api_key_hash = hashlib.sha256(api_key.encode()).hexdigest()
        registration_method = "approval"
        approval_status = "pending"

        # Validate token if provided
        if token:
            with get_db_cursor(commit=True) as (conn, cur):
                cur.execute(
                    """SELECT id, node_type FROM fleet_registration_tokens
                       WHERE token = %s AND used_at IS NULL AND expires_at > NOW()""",
                    (token,),
                )
                row = cur.fetchone()
                if not row:
                    return jsonify({"success": False, "error": "Invalid or expired token"}), 401
                if row[1] != node_type:
                    return jsonify({
                        "success": False,
                        "error": f"Token is for {row[1]}, not {node_type}",
                    }), 400
                # Mark token used
                cur.execute(
                    "UPDATE fleet_registration_tokens SET used_at = NOW(), used_by_node_id = %s WHERE id = %s",
                    (node_id, row[0]),
                )
            registration_method = "token"
            approval_status = "approved"

        # Insert node
        import psycopg2.extras

        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                """INSERT INTO remote_nodes
                   (node_id, api_key_hash, hostname, status, deployment_mode,
                    approval_status, registration_method, device_info, node_name)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                   ON CONFLICT (node_id) DO NOTHING
                   RETURNING node_id""",
                (
                    node_id, api_key_hash, request.remote_addr, "offline",
                    node_type, approval_status, registration_method,
                    psycopg2.extras.Json(device_info), name,
                ),
            )

        return jsonify({
            "success": True,
            "node_id": node_id,
            "api_key": api_key if approval_status == "approved" else None,
            "status": approval_status,
        })

    # ── Node Status (for polling) ────────────────────────────────────
    @bp.route("/api/fleet/status/<node_id>", methods=["GET"])
    def fleet_node_status(node_id):
        """Check registration status (used by nodes polling for approval)."""
        with get_db_cursor() as (conn, cur):
            cur.execute(
                "SELECT approval_status, api_key_hash FROM remote_nodes WHERE node_id = %s",
                (node_id,),
            )
            row = cur.fetchone()
        if not row:
            return jsonify({"success": False, "error": "Node not found"}), 404

        result = {"success": True, "status": row[0]}
        # On approval, generate a fresh api_key
        if row[0] == "approved" and request.args.get("need_key") == "true":
            api_key = secrets.token_urlsafe(32)
            api_key_hash = hashlib.sha256(api_key.encode()).hexdigest()
            with get_db_cursor(commit=True) as (conn, cur):
                cur.execute(
                    "UPDATE remote_nodes SET api_key_hash = %s WHERE node_id = %s",
                    (api_key_hash, node_id),
                )
            result["api_key"] = api_key

        return jsonify(result)

    # ── Approve / Deny ───────────────────────────────────────────────
    @bp.route("/api/fleet/approve/<node_id>", methods=["POST"])
    @admin_required
    def fleet_approve_node(node_id):
        """Approve a pending node registration."""
        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                "UPDATE remote_nodes SET approval_status = 'approved' WHERE node_id = %s AND approval_status = 'pending' RETURNING node_id",
                (node_id,),
            )
            row = cur.fetchone()
        if not row:
            return jsonify({"success": False, "error": "Node not found or not pending"}), 404
        return jsonify({"success": True, "node_id": node_id, "status": "approved"})

    @bp.route("/api/fleet/deny/<node_id>", methods=["POST"])
    @admin_required
    def fleet_deny_node(node_id):
        """Deny a pending node registration."""
        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                "UPDATE remote_nodes SET approval_status = 'denied' WHERE node_id = %s AND approval_status = 'pending' RETURNING node_id",
                (node_id,),
            )
            row = cur.fetchone()
        if not row:
            return jsonify({"success": False, "error": "Node not found or not pending"}), 404
        return jsonify({"success": True, "node_id": node_id, "status": "denied"})

    # ── App Catalog ──────────────────────────────────────────────────
    @bp.route("/api/fleet/catalog", methods=["GET"])
    def fleet_catalog():
        """Return app catalog, optionally filtered by node type."""
        node_type = request.args.get("node_type")
        apps = _load_catalog()
        if node_type:
            apps = [a for a in apps if node_type in a.get("compatible_nodes", [])]
        return jsonify({"success": True, "apps": apps, "count": len(apps)})


def _load_catalog():
    """Load all YAML catalog entries from fleet/catalog/apps/."""
    apps = []
    if not os.path.isdir(CATALOG_DIR):
        return apps
    for fname in sorted(os.listdir(CATALOG_DIR)):
        if not fname.endswith((".yml", ".yaml")):
            continue
        try:
            with open(os.path.join(CATALOG_DIR, fname)) as f:
                entry = yaml.safe_load(f)
            if entry and isinstance(entry, dict):
                apps.append(entry)
        except Exception:
            continue
    return apps
```

- [ ] **Step 2: Register fleet_routes in starbase __init__.py**

Read `platform_v2/tools/starbase/__init__.py` and add the import + registration call. Add this line alongside the other `register_*_routes` calls:

```python
from .fleet_routes import register_fleet_routes
# ... in the registration block:
register_fleet_routes(bp, admin_required)
```

- [ ] **Step 3: Test endpoints manually**

Restart platform:
```bash
docker compose restart archie_platform
```

Test token generation:
```bash
curl -s -b cookies.txt http://192.168.1.200:3000/starbase/api/fleet/token/generate \
  -H "Content-Type: application/json" \
  -d '{"node_type": "outpost", "expires_in_hours": 24}' | python3 -m json.tool
```

Test catalog:
```bash
curl -s http://192.168.1.200:3000/starbase/api/fleet/catalog | python3 -m json.tool
```

Expected: Token returns with token string; catalog returns empty list (no YAML files yet).

- [ ] **Step 4: Commit**

```bash
git add platform_v2/tools/starbase/fleet_routes.py platform_v2/tools/starbase/__init__.py
git commit -m "feat(fleet): add Fleet API — registration, tokens, catalog, approval endpoints"
```

---

## Task 3: App Registry — Catalog YAML Entries

**Files:**
- Create: `fleet/catalog/apps/gov-watch.yml`
- Create: `fleet/catalog/apps/news.yml`
- Create: `fleet/catalog/apps/business-suite.yml`
- Create: `fleet/catalog/apps/market-watch.yml`
- Create: `fleet/catalog/apps/smtp-relay.yml`
- Create: `fleet/catalog/apps/monitoring.yml`

- [ ] **Step 1: Create catalog directory**

```bash
mkdir -p fleet/catalog/apps
```

- [ ] **Step 2: Create gov-watch.yml**

```yaml
name: Kytran Gov Watch
id: gov-watch
description: Government procurement tender monitoring — auto-syncs SAM.gov, GETS, BuyAndSell
image: ghcr.io/kytrankatarn/gov-watch:latest
version: "1.0.0"
port: 8097
env:
  - name: FLASK_SECRET_KEY
    required: true
    generate: true
  - name: DATABASE_URL
    required: false
    default: "sqlite:///data/gov-watch.db"
volumes:
  - name: data
    path: /app/data
resources:
  min_ram_mb: 256
  min_disk_mb: 500
  gpu: false
compatible_nodes:
  - outpost
  - starship
category: products
health_endpoint: /api/health
depends_on: []
```

- [ ] **Step 3: Create news.yml**

```yaml
name: Kytran News
id: news
description: Global intelligence dashboard — 18 news layers, deck.gl visualization, PWA
image: ghcr.io/kytrankatarn/kytran-news:latest
version: "1.0.0"
port: 8098
env:
  - name: FLASK_SECRET_KEY
    required: true
    generate: true
  - name: DATABASE_URL
    required: false
    default: "sqlite:///data/news.db"
volumes:
  - name: data
    path: /app/data
resources:
  min_ram_mb: 256
  min_disk_mb: 500
  gpu: false
compatible_nodes:
  - outpost
  - starship
category: products
health_endpoint: /api/health
depends_on: []
```

- [ ] **Step 4: Create business-suite.yml**

```yaml
name: Kytran Business Suite
id: business-suite
description: Modular SaaS platform — CRM, invoicing, website builder, communications, AI tools
image: ghcr.io/kytrankatarn/kytran-business-suite:latest
version: "1.0.0"
port: 8091
env:
  - name: FLASK_SECRET_KEY
    required: true
    generate: true
  - name: DATABASE_URL
    required: false
    default: "sqlite:///data/kbs.db"
  - name: STRIPE_SECRET_KEY
    required: false
    default: ""
volumes:
  - name: data
    path: /app/data
resources:
  min_ram_mb: 512
  min_disk_mb: 1000
  gpu: false
compatible_nodes:
  - starship
category: products
health_endpoint: /api/health
depends_on: []
```

- [ ] **Step 5: Create market-watch.yml**

```yaml
name: Kytran Market Watch
id: market-watch
description: Autonomous trading intelligence — M.A.R.K.E.T. agent, 8 analysis tabs, paper trading
image: ghcr.io/kytrankatarn/market-watch:latest
version: "1.0.0"
port: 8101
env:
  - name: FLASK_SECRET_KEY
    required: true
    generate: true
  - name: DATABASE_URL
    required: false
    default: "sqlite:///data/market-watch.db"
  - name: ALPHA_VANTAGE_KEY
    required: false
    default: ""
volumes:
  - name: data
    path: /app/data
resources:
  min_ram_mb: 512
  min_disk_mb: 500
  gpu: false
compatible_nodes:
  - starship
category: products
health_endpoint: /api/health
depends_on: []
```

- [ ] **Step 6: Create smtp-relay.yml**

```yaml
name: SMTP Relay
id: smtp-relay
description: Lightweight Postfix relay for outbound email through fleet mesh
image: ghcr.io/kytrankatarn/smtp-relay:latest
version: "1.0.0"
port: 587
env:
  - name: RELAY_HOST
    required: true
    default: ""
  - name: RELAY_PORT
    required: false
    default: "587"
  - name: RELAY_USER
    required: false
    default: ""
  - name: RELAY_PASSWORD
    required: false
    default: ""
volumes: []
resources:
  min_ram_mb: 64
  min_disk_mb: 100
  gpu: false
compatible_nodes:
  - outpost
  - starship
category: infrastructure
health_endpoint: null
depends_on: []
```

- [ ] **Step 7: Create monitoring.yml**

```yaml
name: Nagios Monitoring
id: monitoring
description: Infrastructure monitoring with Nagios Core — service checks, alerts, status dashboard
image: ghcr.io/kytrankatarn/nagios:latest
version: "1.0.0"
port: 8080
env:
  - name: NAGIOS_ADMIN_PASSWORD
    required: true
    generate: true
volumes:
  - name: config
    path: /opt/nagios/etc
  - name: data
    path: /opt/nagios/var
resources:
  min_ram_mb: 128
  min_disk_mb: 200
  gpu: false
compatible_nodes:
  - outpost
  - starship
category: infrastructure
health_endpoint: null
depends_on: []
```

- [ ] **Step 8: Verify catalog loads via API**

```bash
docker compose restart archie_platform
curl -s http://192.168.1.200:3000/starbase/api/fleet/catalog | python3 -m json.tool
```

Expected: 6 apps returned with full details.

```bash
curl -s "http://192.168.1.200:3000/starbase/api/fleet/catalog?node_type=outpost" | python3 -m json.tool
```

Expected: 4 apps (gov-watch, news, smtp-relay, monitoring — not business-suite or market-watch).

- [ ] **Step 9: Commit**

```bash
git add fleet/catalog/apps/
git commit -m "feat(fleet): add app catalog entries — 6 standalone products"
```

---

## Task 4: KSO App Catalog — Service Layer

**Files:**
- Create: `kytran-server-manager/kytran_server_manager/services/app_catalog_service.py`

- [ ] **Step 1: Create the app catalog service**

This service handles fetching the catalog from hub, deploying apps via Docker Compose, and tracking installed apps locally.

```python
"""App Catalog service — fetch registry, deploy/manage Docker containers."""

import json
import os
import secrets
import shutil
import subprocess
import time

import requests
import yaml


APPS_DIR = os.environ.get("KSM_APPS_DIR", "/opt/archie-fleet/apps")
HUB_URL = os.environ.get("KSM_HUB_URL", "http://100.64.0.2:3000")
NODE_TYPE = os.environ.get("KSM_NODE_TYPE", "outpost")
CATALOG_CACHE_FILE = os.path.join(APPS_DIR, ".catalog-cache.json")
CATALOG_CACHE_TTL = 1800  # 30 minutes


def get_catalog(force_refresh=False):
    """Fetch app catalog from hub. Uses local cache if fresh."""
    os.makedirs(APPS_DIR, exist_ok=True)

    # Check cache
    if not force_refresh and os.path.exists(CATALOG_CACHE_FILE):
        try:
            with open(CATALOG_CACHE_FILE) as f:
                cache = json.load(f)
            if time.time() - cache.get("fetched_at", 0) < CATALOG_CACHE_TTL:
                return cache.get("apps", [])
        except Exception:
            pass

    # Fetch from hub
    try:
        resp = requests.get(
            f"{HUB_URL}/starbase/api/fleet/catalog",
            params={"node_type": NODE_TYPE},
            timeout=10,
        )
        if resp.status_code == 200:
            data = resp.json()
            apps = data.get("apps", [])
            # Cache locally
            with open(CATALOG_CACHE_FILE, "w") as f:
                json.dump({"fetched_at": time.time(), "apps": apps}, f)
            return apps
    except Exception:
        pass

    # Fallback to stale cache
    if os.path.exists(CATALOG_CACHE_FILE):
        try:
            with open(CATALOG_CACHE_FILE) as f:
                return json.load(f).get("apps", [])
        except Exception:
            pass

    return []


def get_installed_apps():
    """List apps deployed on this node with their container status."""
    installed = []
    if not os.path.isdir(APPS_DIR):
        return installed

    for app_id in sorted(os.listdir(APPS_DIR)):
        app_dir = os.path.join(APPS_DIR, app_id)
        compose_file = os.path.join(app_dir, "docker-compose.yml")
        if not os.path.isfile(compose_file):
            continue

        meta_file = os.path.join(app_dir, ".app-meta.json")
        meta = {}
        if os.path.exists(meta_file):
            try:
                with open(meta_file) as f:
                    meta = json.load(f)
            except Exception:
                pass

        status = _get_container_status(app_id, app_dir)
        installed.append({
            "id": app_id,
            "name": meta.get("name", app_id),
            "version": meta.get("version", "unknown"),
            "image": meta.get("image", "unknown"),
            "port": meta.get("port"),
            "status": status,
            "installed_at": meta.get("installed_at"),
            "health_endpoint": meta.get("health_endpoint"),
        })

    return installed


def deploy_app(app_id, catalog_entry, env_overrides=None):
    """Deploy an app from catalog entry. Returns (success, message)."""
    app_dir = os.path.join(APPS_DIR, app_id)
    os.makedirs(app_dir, exist_ok=True)

    # Generate docker-compose.yml
    compose = _generate_compose(app_id, catalog_entry)
    compose_path = os.path.join(app_dir, "docker-compose.yml")
    with open(compose_path, "w") as f:
        yaml.dump(compose, f, default_flow_style=False)

    # Generate .env
    env_lines = _generate_env(catalog_entry, env_overrides)
    env_path = os.path.join(app_dir, ".env")
    with open(env_path, "w") as f:
        f.write("\n".join(env_lines) + "\n")

    # Save metadata
    meta = {
        "name": catalog_entry.get("name", app_id),
        "version": catalog_entry.get("version", "unknown"),
        "image": catalog_entry.get("image", "unknown"),
        "port": catalog_entry.get("port"),
        "health_endpoint": catalog_entry.get("health_endpoint"),
        "installed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    with open(os.path.join(app_dir, ".app-meta.json"), "w") as f:
        json.dump(meta, f, indent=2)

    # Pull + start
    try:
        subprocess.run(
            ["docker", "compose", "pull"],
            cwd=app_dir, capture_output=True, text=True, timeout=300,
        )
        result = subprocess.run(
            ["docker", "compose", "up", "-d"],
            cwd=app_dir, capture_output=True, text=True, timeout=120,
        )
        if result.returncode != 0:
            return False, f"docker compose up failed: {result.stderr}"
    except subprocess.TimeoutExpired:
        return False, "Docker operation timed out"
    except Exception as e:
        return False, str(e)

    return True, "App deployed successfully"


def stop_app(app_id):
    """Stop a deployed app."""
    app_dir = os.path.join(APPS_DIR, app_id)
    if not os.path.isdir(app_dir):
        return False, "App not installed"
    result = subprocess.run(
        ["docker", "compose", "stop"],
        cwd=app_dir, capture_output=True, text=True, timeout=60,
    )
    if result.returncode != 0:
        return False, result.stderr
    return True, "App stopped"


def start_app(app_id):
    """Start a stopped app."""
    app_dir = os.path.join(APPS_DIR, app_id)
    if not os.path.isdir(app_dir):
        return False, "App not installed"
    result = subprocess.run(
        ["docker", "compose", "up", "-d"],
        cwd=app_dir, capture_output=True, text=True, timeout=60,
    )
    if result.returncode != 0:
        return False, result.stderr
    return True, "App started"


def remove_app(app_id, keep_data=False):
    """Remove a deployed app. Optionally keep data volumes."""
    app_dir = os.path.join(APPS_DIR, app_id)
    if not os.path.isdir(app_dir):
        return False, "App not installed"

    subprocess.run(
        ["docker", "compose", "down", "--remove-orphans"],
        cwd=app_dir, capture_output=True, text=True, timeout=60,
    )

    if keep_data:
        # Remove compose + meta, keep data/
        for f in ("docker-compose.yml", ".env", ".app-meta.json"):
            path = os.path.join(app_dir, f)
            if os.path.exists(path):
                os.remove(path)
    else:
        shutil.rmtree(app_dir, ignore_errors=True)

    return True, "App removed"


def update_app(app_id, catalog_entry):
    """Update app to latest image. Pull new image, recreate container."""
    app_dir = os.path.join(APPS_DIR, app_id)
    if not os.path.isdir(app_dir):
        return False, "App not installed"

    try:
        subprocess.run(
            ["docker", "compose", "pull"],
            cwd=app_dir, capture_output=True, text=True, timeout=300,
        )
        result = subprocess.run(
            ["docker", "compose", "up", "-d", "--force-recreate"],
            cwd=app_dir, capture_output=True, text=True, timeout=120,
        )
        if result.returncode != 0:
            return False, result.stderr
    except subprocess.TimeoutExpired:
        return False, "Docker operation timed out"

    # Update metadata
    meta_file = os.path.join(app_dir, ".app-meta.json")
    if os.path.exists(meta_file):
        with open(meta_file) as f:
            meta = json.load(f)
        meta["version"] = catalog_entry.get("version", meta.get("version"))
        meta["image"] = catalog_entry.get("image", meta.get("image"))
        with open(meta_file, "w") as f:
            json.dump(meta, f, indent=2)

    return True, "App updated"


def get_app_logs(app_id, lines=100):
    """Get container logs for a deployed app."""
    app_dir = os.path.join(APPS_DIR, app_id)
    if not os.path.isdir(app_dir):
        return None
    result = subprocess.run(
        ["docker", "compose", "logs", "--tail", str(lines), "--no-color"],
        cwd=app_dir, capture_output=True, text=True, timeout=30,
    )
    return result.stdout


def check_app_health(app_id):
    """Check health endpoint for a deployed app."""
    app_dir = os.path.join(APPS_DIR, app_id)
    meta_file = os.path.join(app_dir, ".app-meta.json")
    if not os.path.exists(meta_file):
        return "unknown"

    with open(meta_file) as f:
        meta = json.load(f)

    endpoint = meta.get("health_endpoint")
    port = meta.get("port")
    if not endpoint or not port:
        return "no_health_check"

    try:
        resp = requests.get(f"http://localhost:{port}{endpoint}", timeout=5)
        return "healthy" if resp.status_code == 200 else "unhealthy"
    except Exception:
        return "unreachable"


# ── Internal helpers ─────────────────────────────────────────────────


def _generate_compose(app_id, entry):
    """Generate a docker-compose.yml dict from a catalog entry."""
    service = {
        "image": entry["image"],
        "container_name": f"archie_fleet_{app_id}",
        "restart": "unless-stopped",
        "env_file": [".env"],
        "deploy": {
            "resources": {
                "limits": {
                    "memory": f"{entry.get('resources', {}).get('min_ram_mb', 256)}M",
                }
            }
        },
    }

    port = entry.get("port")
    if port:
        service["ports"] = [f"{port}:{port}"]

    volumes = entry.get("volumes", [])
    if volumes:
        service["volumes"] = [
            f"./data/{v['name']}:{v['path']}" for v in volumes
        ]

    return {
        "services": {app_id: service},
    }


def _generate_env(entry, overrides=None):
    """Generate .env lines from catalog entry env definitions."""
    lines = []
    overrides = overrides or {}

    for env_def in entry.get("env", []):
        name = env_def["name"]
        if name in overrides:
            value = overrides[name]
        elif env_def.get("generate"):
            value = secrets.token_urlsafe(32)
        else:
            value = env_def.get("default", "")
        lines.append(f"{name}={value}")

    return lines


def _get_container_status(app_id, app_dir):
    """Get Docker container status for an app."""
    try:
        result = subprocess.run(
            ["docker", "compose", "ps", "--format", "json"],
            cwd=app_dir, capture_output=True, text=True, timeout=10,
        )
        if result.returncode != 0:
            return "error"
        output = result.stdout.strip()
        if not output:
            return "stopped"
        # docker compose ps --format json returns one JSON object per line
        for line in output.splitlines():
            try:
                container = json.loads(line)
                state = container.get("State", "unknown")
                return "running" if state == "running" else state
            except json.JSONDecodeError:
                continue
        return "unknown"
    except Exception:
        return "unknown"
```

- [ ] **Step 2: Commit**

```bash
git add kytran-server-manager/kytran_server_manager/services/app_catalog_service.py
git commit -m "feat(kso): add app catalog service — deploy, manage, health check"
```

---

## Task 5: KSO App Catalog — Routes

**Files:**
- Create: `kytran-server-manager/kytran_server_manager/routes/app_catalog_routes.py`
- Modify: `kytran-server-manager/kytran_server_manager/routes/__init__.py`

- [ ] **Step 1: Create app_catalog_routes.py**

```python
"""App Catalog routes — browse, deploy, manage fleet apps."""

from flask import jsonify, render_template, request
from flask_login import login_required

from ..services.app_catalog_service import (
    check_app_health,
    deploy_app,
    get_app_logs,
    get_catalog,
    get_installed_apps,
    remove_app,
    start_app,
    stop_app,
    update_app,
)


def register_app_catalog_routes(bp, admin_required_decorator):
    """Register app catalog routes on the sysops blueprint."""

    @bp.route("/apps")
    @login_required
    @admin_required_decorator
    def apps_page():
        return render_template("apps.html")

    @bp.route("/api/apps/catalog", methods=["GET"])
    @login_required
    @admin_required_decorator
    def api_catalog():
        force = request.args.get("refresh") == "true"
        apps = get_catalog(force_refresh=force)
        installed = {a["id"]: a for a in get_installed_apps()}

        # Merge installed status into catalog
        for app in apps:
            inst = installed.get(app["id"])
            if inst:
                app["installed"] = True
                app["status"] = inst["status"]
                app["installed_at"] = inst.get("installed_at")
            else:
                app["installed"] = False
                app["status"] = "available"

        return jsonify({"success": True, "apps": apps, "count": len(apps)})

    @bp.route("/api/apps/installed", methods=["GET"])
    @login_required
    @admin_required_decorator
    def api_installed():
        apps = get_installed_apps()
        return jsonify({"success": True, "apps": apps, "count": len(apps)})

    @bp.route("/api/apps/<app_id>/deploy", methods=["POST"])
    @login_required
    @admin_required_decorator
    def api_deploy(app_id):
        catalog = get_catalog()
        entry = next((a for a in catalog if a.get("id") == app_id), None)
        if not entry:
            return jsonify({"success": False, "error": "App not found in catalog"}), 404

        env_overrides = (request.get_json() or {}).get("env", {})
        success, message = deploy_app(app_id, entry, env_overrides)
        return jsonify({"success": success, "message": message}), 200 if success else 500

    @bp.route("/api/apps/<app_id>/stop", methods=["POST"])
    @login_required
    @admin_required_decorator
    def api_stop(app_id):
        success, message = stop_app(app_id)
        return jsonify({"success": success, "message": message}), 200 if success else 500

    @bp.route("/api/apps/<app_id>/start", methods=["POST"])
    @login_required
    @admin_required_decorator
    def api_start(app_id):
        success, message = start_app(app_id)
        return jsonify({"success": success, "message": message}), 200 if success else 500

    @bp.route("/api/apps/<app_id>/remove", methods=["POST"])
    @login_required
    @admin_required_decorator
    def api_remove(app_id):
        keep_data = (request.get_json() or {}).get("keep_data", False)
        success, message = remove_app(app_id, keep_data=keep_data)
        return jsonify({"success": success, "message": message}), 200 if success else 500

    @bp.route("/api/apps/<app_id>/update", methods=["POST"])
    @login_required
    @admin_required_decorator
    def api_update(app_id):
        catalog = get_catalog(force_refresh=True)
        entry = next((a for a in catalog if a.get("id") == app_id), None)
        if not entry:
            return jsonify({"success": False, "error": "App not found in catalog"}), 404
        success, message = update_app(app_id, entry)
        return jsonify({"success": success, "message": message}), 200 if success else 500

    @bp.route("/api/apps/<app_id>/logs", methods=["GET"])
    @login_required
    @admin_required_decorator
    def api_logs(app_id):
        lines = int(request.args.get("lines", 100))
        logs = get_app_logs(app_id, lines=lines)
        if logs is None:
            return jsonify({"success": False, "error": "App not installed"}), 404
        return jsonify({"success": True, "logs": logs})

    @bp.route("/api/apps/<app_id>/health", methods=["GET"])
    @login_required
    @admin_required_decorator
    def api_health(app_id):
        status = check_app_health(app_id)
        return jsonify({"success": True, "app_id": app_id, "health": status})
```

- [ ] **Step 2: Register routes in __init__.py**

Read `kytran-server-manager/kytran_server_manager/routes/__init__.py` and add the import + call alongside existing registrations:

```python
from .app_catalog_routes import register_app_catalog_routes
# ... inside register_all_routes():
register_app_catalog_routes(bp, admin_decorator)
```

- [ ] **Step 3: Commit**

```bash
git add kytran-server-manager/kytran_server_manager/routes/app_catalog_routes.py \
       kytran-server-manager/kytran_server_manager/routes/__init__.py
git commit -m "feat(kso): add app catalog routes — browse, deploy, manage, logs, health"
```

---

## Task 6: KSO App Catalog — UI Template

**Files:**
- Create: `kytran-server-manager/kytran_server_manager/templates/apps.html`

- [ ] **Step 1: Create the catalog browser template**

Read `kytran-server-manager/kytran_server_manager/templates/dashboard.html` first for the LCARS layout pattern (base template, nav structure, styles). Then create `apps.html` following the same pattern.

The template should include:
- Extends `base.html`
- LCARS-styled grid of app cards
- Each card shows: app name, description, status badge, port, resource requirements
- Action buttons per card: Deploy / Stop / Start / Remove / Update / Logs
- A refresh button to re-fetch catalog
- A logs modal (LCARS styled) for viewing container output
- Status colors: teal (running), amber (stopped), gray (available), red (error/unhealthy)
- JavaScript that calls the `/api/apps/*` endpoints

Key elements:
```html
<!-- Card grid -->
<div id="app-catalog" class="app-grid"></div>

<!-- Logs modal -->
<div id="logs-modal" class="bm-overlay" style="display:none">
  <div class="bm-shell">
    <div class="bm-frame">
      <div class="bm-content">
        <div class="bm-header"><span id="logs-app-name"></span></div>
        <div class="bm-body"><pre id="logs-content"></pre></div>
        <div class="bm-footer">
          <button onclick="closeLogsModal()">CLOSE</button>
        </div>
      </div>
    </div>
  </div>
</div>
```

JavaScript functions needed:
```javascript
async function loadCatalog() { /* GET /api/apps/catalog */ }
function renderAppCard(app) { /* returns HTML card string */ }
async function deployApp(appId) { /* POST /api/apps/{id}/deploy */ }
async function stopApp(appId) { /* POST /api/apps/{id}/stop */ }
async function startApp(appId) { /* POST /api/apps/{id}/start */ }
async function removeApp(appId) { /* POST /api/apps/{id}/remove with confirm */ }
async function updateApp(appId) { /* POST /api/apps/{id}/update */ }
async function showLogs(appId) { /* GET /api/apps/{id}/logs, show in modal */ }
function closeLogsModal() { /* hide modal */ }
function statusBadge(status) { /* returns styled badge HTML */ }
```

NOTE: Read the existing KSO templates and CSS to match the exact LCARS class names and styling patterns. The card grid, badges, and modal should look consistent with the rest of KSO.

- [ ] **Step 2: Add navigation link**

Read the base template or dashboard template to find where navigation links are defined. Add an "Apps" link pointing to `/dashboard/apps`.

- [ ] **Step 3: Test in browser**

Open `http://192.168.1.200:8085/dashboard/apps` (or whatever port KSO runs on) and verify:
- Catalog grid loads with 6 app cards
- Cards show correct status (all "available" initially)
- Deploy button triggers pull + start
- Logs modal opens and shows output

- [ ] **Step 4: Commit**

```bash
git add kytran-server-manager/kytran_server_manager/templates/apps.html
git commit -m "feat(kso): add App Catalog UI — LCARS grid, deploy, logs modal"
```

---

## Task 7: Fleet Installer Script

**Files:**
- Create: `fleet/installer/install.sh`

- [ ] **Step 1: Create the installer script**

```bash
#!/usr/bin/env bash
# A.R.C.H.I.E. Fleet Installer — bootstraps KSO on any Linux machine
# Usage: curl -fsSL https://raw.githubusercontent.com/KytranKatarn/archie-fleet/main/install.sh | bash
#   or:  ./install.sh --type outpost --token <token>
set -euo pipefail

# ── Config ───────────────────────────────────────────────────────────
FLEET_VERSION="1.0.0"
HUB_URL="${ARCHIE_HUB_URL:-http://100.64.0.2:3000}"
MESH_SERVER="${ARCHIE_MESH_SERVER:-https://mesh.kytranempowerment.com}"
KSO_IMAGE="ghcr.io/kytrankatarn/kso:latest"
INSTALL_DIR="/opt/archie-fleet"
APPS_DIR="${INSTALL_DIR}/apps"

# ── Colors ───────────────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
CYAN='\033[0;36m'
YELLOW='\033[1;33m'
NC='\033[0m'

log()  { echo -e "${CYAN}[ARCHIE]${NC} $1"; }
ok()   { echo -e "${GREEN}[  OK  ]${NC} $1"; }
warn() { echo -e "${YELLOW}[ WARN ]${NC} $1"; }
err()  { echo -e "${RED}[ERROR ]${NC} $1"; }

# ── Parse Args ───────────────────────────────────────────────────────
NODE_TYPE=""
TOKEN=""
FORCE=false
UNINSTALL=false

while [[ $# -gt 0 ]]; do
    case "$1" in
        --type)      NODE_TYPE="$2"; shift 2 ;;
        --token)     TOKEN="$2"; shift 2 ;;
        --hub)       HUB_URL="$2"; shift 2 ;;
        --force)     FORCE=true; shift ;;
        --uninstall) UNINSTALL=true; shift ;;
        *)           err "Unknown option: $1"; exit 1 ;;
    esac
done

# ── Uninstall ────────────────────────────────────────────────────────
if [ "$UNINSTALL" = true ]; then
    log "Uninstalling A.R.C.H.I.E. Fleet..."
    if [ -d "$INSTALL_DIR" ]; then
        # Stop all app containers
        for app_dir in "$APPS_DIR"/*/; do
            [ -f "$app_dir/docker-compose.yml" ] && docker compose -f "$app_dir/docker-compose.yml" down 2>/dev/null || true
        done
        # Stop KSO
        [ -f "$INSTALL_DIR/docker-compose.yml" ] && docker compose -f "$INSTALL_DIR/docker-compose.yml" down 2>/dev/null || true
        rm -rf "$INSTALL_DIR"
        ok "Fleet removed from $INSTALL_DIR"
    else
        warn "No fleet installation found at $INSTALL_DIR"
    fi
    exit 0
fi

# ── Banner ───────────────────────────────────────────────────────────
echo ""
echo -e "${CYAN}╔══════════════════════════════════════════════════╗${NC}"
echo -e "${CYAN}║     A.R.C.H.I.E. Fleet Installer v${FLEET_VERSION}          ║${NC}"
echo -e "${CYAN}║     Autonomous Fleet Node Bootstrap              ║${NC}"
echo -e "${CYAN}╚══════════════════════════════════════════════════╝${NC}"
echo ""

# ── Step 1: Detect OS ────────────────────────────────────────────────
log "Step 1/5: Detecting OS..."

if [ ! -f /etc/os-release ]; then
    err "Cannot detect OS. /etc/os-release not found."
    exit 1
fi

source /etc/os-release
ARCH=$(uname -m)

if [[ "$ID" != "ubuntu" && "$ID" != "debian" ]]; then
    err "Unsupported OS: $ID. Requires Ubuntu 22.04+ or Debian 12+."
    exit 1
fi

if [[ "$ID" == "ubuntu" && "${VERSION_ID%%.*}" -lt 22 ]]; then
    err "Ubuntu $VERSION_ID is too old. Requires 22.04+."
    exit 1
fi

if [[ "$ID" == "debian" && "${VERSION_ID%%.*}" -lt 12 ]]; then
    err "Debian $VERSION_ID is too old. Requires 12+."
    exit 1
fi

ok "OS: $PRETTY_NAME ($ARCH)"

# ── Step 2: Install Dependencies ─────────────────────────────────────
log "Step 2/5: Installing dependencies..."

# Docker
if command -v docker &>/dev/null && [ "$FORCE" = false ]; then
    ok "Docker already installed: $(docker --version)"
else
    log "Installing Docker..."
    apt-get update -qq
    apt-get install -y -qq ca-certificates curl gnupg
    install -m 0755 -d /etc/apt/keyrings
    curl -fsSL https://download.docker.com/linux/$ID/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
    chmod a+r /etc/apt/keyrings/docker.gpg
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/$ID $(. /etc/os-release && echo $VERSION_CODENAME) stable" > /etc/apt/sources.list.d/docker.list
    apt-get update -qq
    apt-get install -y -qq docker-ce docker-ce-cli containerd.io docker-compose-plugin
    systemctl enable docker
    systemctl start docker
    ok "Docker installed: $(docker --version)"
fi

# Tailscale
if command -v tailscale &>/dev/null && [ "$FORCE" = false ]; then
    ok "Tailscale already installed"
else
    log "Installing Tailscale..."
    curl -fsSL https://tailscale.com/install.sh | sh
    ok "Tailscale installed"
fi

# jq
if ! command -v jq &>/dev/null; then
    apt-get install -y -qq jq
fi
ok "Dependencies ready"

# ── Step 3: Node Type ────────────────────────────────────────────────
log "Step 3/5: Configuring node type..."

if [ -z "$NODE_TYPE" ]; then
    echo ""
    echo "  Select node type:"
    echo "    1) outpost   — Lightweight VPS (1 CPU, 2GB RAM min)"
    echo "    2) starship  — Full compute node (4+ CPU, 16GB RAM, GPU recommended)"
    echo ""
    read -rp "  Enter choice [1/2]: " choice
    case "$choice" in
        1|outpost)  NODE_TYPE="outpost" ;;
        2|starship) NODE_TYPE="starship" ;;
        *)          err "Invalid choice"; exit 1 ;;
    esac
fi

if [[ "$NODE_TYPE" != "outpost" && "$NODE_TYPE" != "starship" ]]; then
    err "Invalid node type: $NODE_TYPE. Must be outpost or starship."
    exit 1
fi

ok "Node type: $NODE_TYPE"

# ── Step 4: Fleet Registration ────────────────────────────────────────
log "Step 4/5: Registering with fleet..."

NODE_NAME=""
read -rp "  Node name (e.g., us-east-1, home-lab): " NODE_NAME
NODE_NAME="${NODE_NAME:-unnamed-$(hostname)}"

if [ -z "$TOKEN" ]; then
    echo ""
    echo "  Registration method:"
    echo "    1) Token — paste a pre-generated registration token (instant)"
    echo "    2) Request approval — admin must approve in Starbase"
    echo ""
    read -rp "  Enter choice [1/2]: " reg_choice
    case "$reg_choice" in
        1)
            read -rp "  Paste registration token: " TOKEN
            ;;
        2)
            TOKEN=""
            ;;
        *)
            err "Invalid choice"; exit 1
            ;;
    esac
fi

# Call Fleet API to register
REG_PAYLOAD=$(jq -n \
    --arg name "$NODE_NAME" \
    --arg type "$NODE_TYPE" \
    --arg token "$TOKEN" \
    '{name: $name, type: $type, token: (if $token == "" then null else $token end)}')

REG_RESPONSE=$(curl -sS -X POST "${HUB_URL}/starbase/api/fleet/register" \
    -H "Content-Type: application/json" \
    -d "$REG_PAYLOAD" 2>/dev/null) || {
    err "Cannot reach hub at $HUB_URL. Is the mesh connected?"
    exit 1
}

REG_SUCCESS=$(echo "$REG_RESPONSE" | jq -r '.success')
REG_STATUS=$(echo "$REG_RESPONSE" | jq -r '.status')
NODE_ID=$(echo "$REG_RESPONSE" | jq -r '.node_id')
API_KEY=$(echo "$REG_RESPONSE" | jq -r '.api_key // empty')

if [ "$REG_SUCCESS" != "true" ]; then
    REG_ERROR=$(echo "$REG_RESPONSE" | jq -r '.error')
    err "Registration failed: $REG_ERROR"
    exit 1
fi

if [ "$REG_STATUS" = "pending" ]; then
    log "Waiting for admin approval in Starbase..."
    ATTEMPTS=0
    MAX_ATTEMPTS=60  # 10 minutes at 10s intervals
    while [ $ATTEMPTS -lt $MAX_ATTEMPTS ]; do
        sleep 10
        STATUS_RESP=$(curl -sS "${HUB_URL}/starbase/api/fleet/status/${NODE_ID}?need_key=true" 2>/dev/null) || continue
        STATUS=$(echo "$STATUS_RESP" | jq -r '.status')
        if [ "$STATUS" = "approved" ]; then
            API_KEY=$(echo "$STATUS_RESP" | jq -r '.api_key // empty')
            break
        elif [ "$STATUS" = "denied" ]; then
            err "Registration denied by admin."
            exit 1
        fi
        ATTEMPTS=$((ATTEMPTS + 1))
        echo -ne "\r  Waiting... ($((ATTEMPTS * 10))s / 600s)"
    done
    echo ""
    if [ "$STATUS" != "approved" ]; then
        err "Approval timed out after 10 minutes. Ask admin to approve node $NODE_ID."
        exit 1
    fi
fi

ok "Registered: $NODE_ID (status: approved)"

# ── Step 5: Join Mesh + Start KSO ────────────────────────────────────
log "Step 5/5: Starting KSO..."

# Join Headscale mesh
TAILSCALE_STATUS=$(tailscale status --json 2>/dev/null | jq -r '.BackendState' 2>/dev/null || echo "unknown")
if [ "$TAILSCALE_STATUS" != "Running" ] || [ "$FORCE" = true ]; then
    log "Joining mesh network..."
    # Admin needs to pre-create an auth key in Headscale for this node
    echo ""
    echo "  To join the mesh, you need a Headscale pre-auth key."
    echo "  Generate one on the hub: headscale preauthkeys create --user archie-fleet"
    echo ""
    read -rp "  Paste Headscale auth key (or press Enter to skip mesh): " MESH_KEY
    if [ -n "$MESH_KEY" ]; then
        tailscale up --login-server "$MESH_SERVER" --authkey "$MESH_KEY" --hostname "$NODE_NAME"
        ok "Mesh connected: $(tailscale ip -4)"
    else
        warn "Skipping mesh — KSO will connect to hub via public IP"
    fi
else
    ok "Mesh already connected: $(tailscale ip -4)"
fi

# Create install directory
mkdir -p "$INSTALL_DIR" "$APPS_DIR"

# Write .env
cat > "${INSTALL_DIR}/.env" <<ENVEOF
# A.R.C.H.I.E. Fleet Node Configuration
# Generated by install.sh — $(date -u +%Y-%m-%dT%H:%M:%SZ)
NODE_ID=${NODE_ID}
NODE_TYPE=${NODE_TYPE}
NODE_NAME=${NODE_NAME}

# Hub Connection
KSM_HUB_URL=${HUB_URL}
KSM_HUB_API_KEY=${API_KEY}
KSM_NODE_TYPE=${NODE_TYPE}

# App Catalog
KSM_APPS_DIR=/opt/archie-fleet/apps

# KSO Config
KSM_SECRET_KEY=$(openssl rand -hex 32)
ENVEOF

# Write docker-compose.yml for KSO
cat > "${INSTALL_DIR}/docker-compose.yml" <<COMPOSEEOF
services:
  kso:
    image: ${KSO_IMAGE}
    container_name: archie_kso
    restart: unless-stopped
    ports:
      - "8085:8080"
    env_file:
      - .env
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock:ro
      - /proc:/host/proc:ro
      - /sys:/host/sys:ro
      - ./data:/data
      - ${APPS_DIR}:/opt/archie-fleet/apps
    deploy:
      resources:
        limits:
          memory: 256M
          cpus: "0.5"
COMPOSEEOF

# Pull and start
log "Pulling KSO image..."
cd "$INSTALL_DIR"
docker compose pull
docker compose up -d

# Wait for KSO to be healthy
log "Waiting for KSO to start..."
for i in $(seq 1 30); do
    if curl -sS http://localhost:8085/api/health &>/dev/null; then
        break
    fi
    sleep 2
done

if curl -sS http://localhost:8085/api/health &>/dev/null; then
    ok "KSO is running at http://localhost:8085"
else
    warn "KSO may still be starting — check: docker logs archie_kso"
fi

# ── Done ─────────────────────────────────────────────────────────────
echo ""
echo -e "${GREEN}╔══════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║     A.R.C.H.I.E. Fleet Node — INSTALLED         ║${NC}"
echo -e "${GREEN}╠══════════════════════════════════════════════════╣${NC}"
echo -e "${GREEN}║  Node ID:   ${NODE_ID}$(printf '%*s' $((26 - ${#NODE_ID})) '')║${NC}"
echo -e "${GREEN}║  Type:      ${NODE_TYPE}$(printf '%*s' $((26 - ${#NODE_TYPE})) '')║${NC}"
echo -e "${GREEN}║  KSO:       http://localhost:8085$(printf '%*s' 5 '')║${NC}"
echo -e "${GREEN}║  Apps Dir:  /opt/archie-fleet/apps$(printf '%*s' 4 '')║${NC}"
echo -e "${GREEN}╚══════════════════════════════════════════════════╝${NC}"
echo ""
echo "  Next steps:"
echo "    1. Open KSO at http://$(hostname -I | awk '{print $1}'):8085"
echo "    2. Go to the Apps tab to browse and deploy products"
echo "    3. View this node in Starbase on the hub"
echo ""
```

- [ ] **Step 2: Make executable**

```bash
chmod +x fleet/installer/install.sh
```

- [ ] **Step 3: Commit**

```bash
git add fleet/installer/install.sh
git commit -m "feat(fleet): add bootstrap installer — Docker, Tailscale, KSO, fleet registration"
```

---

## Task 8: Satellite PWA — Static Files + Hub Route

**Files:**
- Create: `platform_v2/static/fleet/satellite/manifest.json`
- Create: `platform_v2/static/fleet/satellite/sw.js`
- Create: `platform_v2/static/fleet/satellite/satellite.css`
- Create: `platform_v2/static/fleet/satellite/satellite.js`
- Create: `platform_v2/static/fleet/satellite/index.html`

- [ ] **Step 1: Create directory structure**

```bash
mkdir -p platform_v2/static/fleet/satellite/icons
```

- [ ] **Step 2: Create manifest.json**

```json
{
  "name": "A.R.C.H.I.E. Satellite",
  "short_name": "Satellite",
  "start_url": "/fleet/satellite/",
  "display": "standalone",
  "background_color": "#0a0e17",
  "theme_color": "#00e5ff",
  "description": "Fleet satellite node — mobile presence for A.R.C.H.I.E. mesh network",
  "icons": [
    { "src": "icons/icon-192.png", "sizes": "192x192", "type": "image/png" },
    { "src": "icons/icon-512.png", "sizes": "512x512", "type": "image/png" }
  ]
}
```

- [ ] **Step 3: Create sw.js (service worker)**

```javascript
const CACHE_NAME = 'satellite-v1';
const STATIC_ASSETS = [
  '/fleet/satellite/',
  '/fleet/satellite/satellite.css',
  '/fleet/satellite/satellite.js',
  '/fleet/satellite/manifest.json'
];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME)
      .then(cache => cache.addAll(STATIC_ASSETS))
      .then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then(keys =>
      Promise.all(keys.filter(k => k !== CACHE_NAME).map(k => caches.delete(k)))
    ).then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', (event) => {
  // Network-first for API calls, cache-first for static assets
  if (event.request.url.includes('/api/')) {
    event.respondWith(
      fetch(event.request).catch(() => caches.match(event.request))
    );
  } else {
    event.respondWith(
      caches.match(event.request).then(r => r || fetch(event.request))
    );
  }
});
```

- [ ] **Step 4: Create satellite.css**

LCARS-themed mobile styles. Read `platform_v2/static/css/lcars-panels.css` first for the design language (colors, fonts, borders). Key styles:

```css
/* ── Base ─────────────────────────────────────────── */
:root {
  --bg-dark: #0a0e17;
  --bg-panel: #111827;
  --accent: #00e5ff;
  --accent-dim: rgba(0, 229, 255, 0.15);
  --text: #e0e0e0;
  --text-dim: #6b7280;
  --green: #10b981;
  --amber: #f59e0b;
  --red: #ef4444;
  --purple: #8b5cf6;
  --font-title: 'Orbitron', monospace;
  --font-body: 'IBM Plex Mono', monospace;
}

* { box-sizing: border-box; margin: 0; padding: 0; }

body {
  font-family: var(--font-body);
  background: var(--bg-dark);
  color: var(--text);
  min-height: 100vh;
  -webkit-font-smoothing: antialiased;
}

/* ── Header ──────────────────────────────────────── */
.sat-header {
  background: var(--bg-panel);
  border-bottom: 2px solid var(--accent);
  padding: 16px 20px;
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.sat-header h1 {
  font-family: var(--font-title);
  font-size: 16px;
  color: var(--accent);
  letter-spacing: 2px;
}

.sat-status-dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  background: var(--red);
}

.sat-status-dot.online { background: var(--green); box-shadow: 0 0 8px var(--green); }
.sat-status-dot.pending { background: var(--amber); animation: pulse 2s infinite; }

@keyframes pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.4; }
}

/* ── Screens ─────────────────────────────────────── */
.sat-screen { display: none; padding: 20px; }
.sat-screen.active { display: block; }

/* ── Registration ────────────────────────────────── */
.sat-register {
  max-width: 400px;
  margin: 60px auto;
  text-align: center;
}

.sat-register h2 {
  font-family: var(--font-title);
  color: var(--accent);
  margin-bottom: 24px;
  font-size: 18px;
}

.sat-input {
  width: 100%;
  padding: 12px 16px;
  background: var(--bg-dark);
  border: 1px solid var(--accent-dim);
  border-radius: 4px;
  color: var(--text);
  font-family: var(--font-body);
  font-size: 14px;
  margin-bottom: 16px;
}

.sat-input:focus {
  outline: none;
  border-color: var(--accent);
  box-shadow: 0 0 8px var(--accent-dim);
}

.sat-btn {
  width: 100%;
  padding: 14px;
  background: var(--accent);
  color: var(--bg-dark);
  border: none;
  border-radius: 4px;
  font-family: var(--font-title);
  font-size: 14px;
  letter-spacing: 2px;
  cursor: pointer;
  text-transform: uppercase;
}

.sat-btn:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

.sat-waiting {
  margin-top: 32px;
  color: var(--amber);
  font-size: 13px;
}

/* ── Dashboard ───────────────────────────────────── */
.sat-stats {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
  margin-bottom: 24px;
}

.sat-stat-card {
  background: var(--bg-panel);
  border: 1px solid var(--accent-dim);
  border-radius: 6px;
  padding: 16px;
  text-align: center;
}

.sat-stat-card .label {
  font-size: 10px;
  color: var(--text-dim);
  text-transform: uppercase;
  letter-spacing: 1px;
}

.sat-stat-card .value {
  font-family: var(--font-title);
  font-size: 24px;
  color: var(--accent);
  margin-top: 4px;
}

/* ── Fleet List ──────────────────────────────────── */
.sat-fleet-list { list-style: none; }

.sat-fleet-item {
  background: var(--bg-panel);
  border: 1px solid var(--accent-dim);
  border-radius: 6px;
  padding: 12px 16px;
  margin-bottom: 8px;
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.sat-fleet-item .node-name {
  font-size: 13px;
  font-weight: 600;
}

.sat-fleet-item .node-type {
  font-size: 10px;
  color: var(--text-dim);
  text-transform: uppercase;
}

.sat-badge {
  font-size: 10px;
  padding: 2px 8px;
  border-radius: 3px;
  text-transform: uppercase;
  letter-spacing: 1px;
}

.sat-badge.online { background: rgba(16,185,129,0.2); color: var(--green); }
.sat-badge.offline { background: rgba(107,114,128,0.2); color: var(--text-dim); }

/* ── Nav ─────────────────────────────────────────── */
.sat-nav {
  position: fixed;
  bottom: 0;
  left: 0;
  right: 0;
  background: var(--bg-panel);
  border-top: 2px solid var(--accent);
  display: flex;
  padding: 8px 0;
  padding-bottom: env(safe-area-inset-bottom, 8px);
}

.sat-nav button {
  flex: 1;
  background: none;
  border: none;
  color: var(--text-dim);
  font-family: var(--font-body);
  font-size: 11px;
  padding: 8px 0;
  cursor: pointer;
  text-transform: uppercase;
  letter-spacing: 1px;
}

.sat-nav button.active {
  color: var(--accent);
  border-top: 2px solid var(--accent);
  margin-top: -2px;
}
```

- [ ] **Step 5: Create satellite.js**

```javascript
/* A.R.C.H.I.E. Satellite PWA */
(function() {
  'use strict';

  // ── State ───────────────────────────────────────────────────
  const HUB_URL = localStorage.getItem('sat_hub_url') || location.origin;
  let nodeId = localStorage.getItem('sat_node_id');
  let authToken = localStorage.getItem('sat_auth_token');
  let status = localStorage.getItem('sat_status') || 'unregistered';
  let heartbeatTimer = null;

  // ── Init ────────────────────────────────────────────────────
  function init() {
    if (status === 'approved' && nodeId) {
      showScreen('dashboard');
      startHeartbeat();
      loadFleetStatus();
    } else if (status === 'pending' && nodeId) {
      showScreen('register');
      showWaiting();
      pollApproval();
    } else {
      showScreen('register');
    }
  }

  // ── Screens ─────────────────────────────────────────────────
  function showScreen(name) {
    document.querySelectorAll('.sat-screen').forEach(s => s.classList.remove('active'));
    const el = document.getElementById('screen-' + name);
    if (el) el.classList.add('active');

    // Nav highlight
    document.querySelectorAll('.sat-nav button').forEach(b => b.classList.remove('active'));
    const navBtn = document.querySelector(`.sat-nav button[data-screen="${name}"]`);
    if (navBtn) navBtn.classList.add('active');

    // Show/hide nav
    const nav = document.querySelector('.sat-nav');
    if (nav) nav.style.display = (status === 'approved') ? 'flex' : 'none';
  }

  // ── Registration ────────────────────────────────────────────
  async function register() {
    const nameInput = document.getElementById('node-name');
    const name = nameInput ? nameInput.value.trim() : 'satellite';
    if (!name) return;

    const btn = document.getElementById('register-btn');
    btn.disabled = true;
    btn.textContent = 'REGISTERING...';

    try {
      const resp = await fetch(HUB_URL + '/starbase/api/fleet/register', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          name: name,
          type: 'satellite',
          device_info: getDeviceInfo()
        })
      });
      const data = await resp.json();

      if (!data.success) {
        alert('Registration failed: ' + (data.error || 'Unknown error'));
        btn.disabled = false;
        btn.textContent = 'JOIN FLEET';
        return;
      }

      nodeId = data.node_id;
      localStorage.setItem('sat_node_id', nodeId);

      if (data.status === 'approved' && data.api_key) {
        authToken = data.api_key;
        localStorage.setItem('sat_auth_token', authToken);
        status = 'approved';
        localStorage.setItem('sat_status', 'approved');
        showScreen('dashboard');
        startHeartbeat();
        loadFleetStatus();
      } else {
        status = 'pending';
        localStorage.setItem('sat_status', 'pending');
        showWaiting();
        pollApproval();
      }
    } catch (e) {
      alert('Cannot reach hub. Are you connected to the mesh?');
      btn.disabled = false;
      btn.textContent = 'JOIN FLEET';
    }
  }

  function showWaiting() {
    const w = document.getElementById('waiting-msg');
    if (w) {
      w.style.display = 'block';
      w.textContent = 'Waiting for admin approval... (' + nodeId + ')';
    }
    const btn = document.getElementById('register-btn');
    if (btn) btn.style.display = 'none';
    const input = document.getElementById('node-name');
    if (input) input.style.display = 'none';
  }

  async function pollApproval() {
    const check = async () => {
      try {
        const resp = await fetch(
          HUB_URL + '/starbase/api/fleet/status/' + nodeId + '?need_key=true'
        );
        const data = await resp.json();

        if (data.status === 'approved') {
          if (data.api_key) {
            authToken = data.api_key;
            localStorage.setItem('sat_auth_token', authToken);
          }
          status = 'approved';
          localStorage.setItem('sat_status', 'approved');
          showScreen('dashboard');
          startHeartbeat();
          loadFleetStatus();
          return;
        } else if (data.status === 'denied') {
          const w = document.getElementById('waiting-msg');
          if (w) w.textContent = 'Registration denied by admin.';
          localStorage.removeItem('sat_node_id');
          localStorage.removeItem('sat_status');
          return;
        }
      } catch (e) { /* retry */ }
      setTimeout(check, 10000);
    };
    check();
  }

  // ── Heartbeat ───────────────────────────────────────────────
  function startHeartbeat() {
    if (heartbeatTimer) clearInterval(heartbeatTimer);
    sendHeartbeat();
    heartbeatTimer = setInterval(sendHeartbeat, 60000);
  }

  async function sendHeartbeat() {
    const payload = {
      node_id: nodeId,
      auth_token: authToken,
      online: true,
      timestamp: new Date().toISOString(),
      device_info: getDeviceInfo()
    };

    try {
      const resp = await fetch(HUB_URL + '/starbase/api/fleet/heartbeat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });
      const data = await resp.json();
      updateStatusDot('online');

      // Future: handle tasks in data.tasks
    } catch (e) {
      updateStatusDot('offline');
    }
  }

  function getDeviceInfo() {
    const info = { platform: navigator.platform, userAgent: navigator.userAgent };
    if (navigator.connection) {
      info.network_type = navigator.connection.effectiveType;
      info.downlink = navigator.connection.downlink;
    }
    // Battery API (async, best-effort)
    if (navigator.getBattery) {
      navigator.getBattery().then(b => {
        info.battery_level = Math.round(b.level * 100);
        info.battery_charging = b.charging;
      }).catch(() => {});
    }
    return info;
  }

  // ── Fleet Status ────────────────────────────────────────────
  async function loadFleetStatus() {
    // For now, display basic self-status
    // Future: fetch fleet-wide node list from hub
    const el = document.getElementById('stat-status');
    if (el) el.textContent = status === 'approved' ? 'ONLINE' : 'OFFLINE';

    const idEl = document.getElementById('stat-node-id');
    if (idEl) idEl.textContent = nodeId || '-';

    const typeEl = document.getElementById('stat-type');
    if (typeEl) typeEl.textContent = 'SATELLITE';
  }

  // ── UI Helpers ──────────────────────────────────────────────
  function updateStatusDot(state) {
    const dot = document.getElementById('status-dot');
    if (dot) {
      dot.className = 'sat-status-dot ' + state;
    }
  }

  // ── Settings ────────────────────────────────────────────────
  function disconnect() {
    if (!confirm('Disconnect from fleet? You will need to re-register.')) return;
    localStorage.removeItem('sat_node_id');
    localStorage.removeItem('sat_auth_token');
    localStorage.removeItem('sat_status');
    if (heartbeatTimer) clearInterval(heartbeatTimer);
    status = 'unregistered';
    nodeId = null;
    authToken = null;
    location.reload();
  }

  // ── Exports ─────────────────────────────────────────────────
  window.satellite = { register, showScreen, disconnect };

  // ── Boot ────────────────────────────────────────────────────
  document.addEventListener('DOMContentLoaded', init);

  // Register service worker
  if ('serviceWorker' in navigator) {
    navigator.serviceWorker.register('/fleet/satellite/sw.js')
      .catch(err => console.warn('SW registration failed:', err));
  }
})();
```

- [ ] **Step 6: Create index.html**

```html
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
  <meta name="theme-color" content="#00e5ff">
  <meta name="apple-mobile-web-app-capable" content="yes">
  <meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
  <title>A.R.C.H.I.E. Satellite</title>
  <link rel="manifest" href="/fleet/satellite/manifest.json">
  <link rel="stylesheet" href="/fleet/satellite/satellite.css">
  <link href="https://fonts.googleapis.com/css2?family=Orbitron:wght@400;700&family=IBM+Plex+Mono:wght@400;600&display=swap" rel="stylesheet">
</head>
<body>

  <!-- Header -->
  <header class="sat-header">
    <h1>A.R.C.H.I.E. SATELLITE</h1>
    <div id="status-dot" class="sat-status-dot"></div>
  </header>

  <!-- Registration Screen -->
  <div id="screen-register" class="sat-screen active">
    <div class="sat-register">
      <h2>JOIN FLEET</h2>
      <p style="color: var(--text-dim); margin-bottom: 24px; font-size: 13px;">
        Register this device as a satellite node in the A.R.C.H.I.E. mesh network.
      </p>
      <input id="node-name" class="sat-input" type="text" placeholder="Satellite name (e.g., my-phone)">
      <button id="register-btn" class="sat-btn" onclick="satellite.register()">JOIN FLEET</button>
      <div id="waiting-msg" class="sat-waiting" style="display:none"></div>
    </div>
  </div>

  <!-- Dashboard Screen -->
  <div id="screen-dashboard" class="sat-screen">
    <div class="sat-stats">
      <div class="sat-stat-card">
        <div class="label">Status</div>
        <div class="value" id="stat-status">-</div>
      </div>
      <div class="sat-stat-card">
        <div class="label">Type</div>
        <div class="value" id="stat-type">-</div>
      </div>
    </div>
    <div class="sat-stat-card" style="margin-bottom: 24px;">
      <div class="label">Node ID</div>
      <div class="value" id="stat-node-id" style="font-size: 12px; word-break: break-all;">-</div>
    </div>
  </div>

  <!-- Fleet Screen -->
  <div id="screen-fleet" class="sat-screen">
    <h3 style="font-family: var(--font-title); color: var(--accent); font-size: 14px; margin-bottom: 16px;">FLEET NODES</h3>
    <ul id="fleet-list" class="sat-fleet-list">
      <li class="sat-fleet-item">
        <div>
          <div class="node-name" style="color: var(--text-dim);">Fleet data loading...</div>
        </div>
      </li>
    </ul>
  </div>

  <!-- Settings Screen -->
  <div id="screen-settings" class="sat-screen">
    <h3 style="font-family: var(--font-title); color: var(--accent); font-size: 14px; margin-bottom: 16px;">SETTINGS</h3>
    <div class="sat-stat-card" style="margin-bottom: 12px; text-align: left;">
      <div class="label">Hub URL</div>
      <div style="font-size: 12px; margin-top: 4px; word-break: break-all;" id="settings-hub-url"></div>
    </div>
    <button class="sat-btn" style="background: var(--red); margin-top: 24px;" onclick="satellite.disconnect()">
      DISCONNECT FROM FLEET
    </button>
  </div>

  <!-- Bottom Nav -->
  <nav class="sat-nav" style="display:none">
    <button data-screen="dashboard" class="active" onclick="satellite.showScreen('dashboard')">STATUS</button>
    <button data-screen="fleet" onclick="satellite.showScreen('fleet')">FLEET</button>
    <button data-screen="settings" onclick="satellite.showScreen('settings')">SETTINGS</button>
  </nav>

  <script src="/fleet/satellite/satellite.js"></script>
</body>
</html>
```

- [ ] **Step 7: Add hub route to serve PWA**

Add a route in `fleet_routes.py` (created in Task 2) to serve the satellite PWA:

```python
# Add to fleet_routes.py register_fleet_routes():
from flask import send_from_directory
import os

SATELLITE_DIR = os.path.join(
    os.path.dirname(__file__), "..", "..", "static", "fleet", "satellite"
)

@bp.route("/fleet/satellite/")
@bp.route("/fleet/satellite/<path:filename>")
def fleet_satellite(filename="index.html"):
    """Serve satellite PWA static files."""
    return send_from_directory(SATELLITE_DIR, filename)
```

- [ ] **Step 8: Test PWA**

Restart platform:
```bash
docker compose restart archie_platform
```

Open in mobile browser: `http://192.168.1.200:3000/fleet/satellite/`

Verify:
- LCARS dark theme loads
- Registration form shows
- "Add to Home Screen" prompt appears (Android Chrome)

- [ ] **Step 9: Commit**

```bash
git add platform_v2/static/fleet/satellite/ platform_v2/tools/starbase/fleet_routes.py
git commit -m "feat(fleet): add Satellite PWA — mobile fleet presence with LCARS theme"
```

---

## Task 9: Extend Heartbeat to Report Installed Apps

**Files:**
- Modify: `platform_v2/tools/starbase/node_routes.py`

- [ ] **Step 1: Read existing heartbeat handler**

Read `platform_v2/tools/starbase/node_routes.py` to find the heartbeat endpoint. Locate the `POST /api/nodes/<node_id>/heartbeat` handler.

- [ ] **Step 2: Extend heartbeat to accept and store apps_running**

In the heartbeat handler, after processing existing fields, add:

```python
# In the heartbeat handler, after existing field updates:
apps_running = data.get("apps_running", [])
if apps_running:
    import psycopg2.extras
    cur.execute(
        "UPDATE remote_nodes SET apps_running = %s WHERE node_id = %s",
        (psycopg2.extras.Json(apps_running), node_id),
    )
```

- [ ] **Step 3: Extend heartbeat to accept satellite device_info**

```python
# Also in the heartbeat handler:
device_info = data.get("device_info")
if device_info:
    import psycopg2.extras
    cur.execute(
        "UPDATE remote_nodes SET device_info = %s WHERE node_id = %s",
        (psycopg2.extras.Json(device_info), node_id),
    )
```

- [ ] **Step 4: Test heartbeat extension**

```bash
docker compose restart archie_platform
curl -s -X POST http://192.168.1.200:3000/starbase/api/nodes/node_test123/heartbeat \
  -H "Content-Type: application/json" \
  -H "X-Node-API-Key: test" \
  -d '{"apps_running": ["gov-watch", "news"], "device_info": {"platform": "Android"}}' | python3 -m json.tool
```

- [ ] **Step 5: Commit**

```bash
git add platform_v2/tools/starbase/node_routes.py
git commit -m "feat(fleet): extend heartbeat to report installed apps and device info"
```

---

## Task 10: Integration Test — End-to-End Verification

- [ ] **Step 1: Verify catalog API returns all 6 apps**

```bash
curl -s http://192.168.1.200:3000/starbase/api/fleet/catalog | python3 -m json.tool
```

Expected: 6 apps with full details.

- [ ] **Step 2: Verify catalog filtering**

```bash
curl -s "http://192.168.1.200:3000/starbase/api/fleet/catalog?node_type=outpost" | python3 -m json.tool
```

Expected: 4 apps (gov-watch, news, smtp-relay, monitoring).

- [ ] **Step 3: Test token generation + registration flow**

```bash
# Generate token (requires auth)
TOKEN=$(curl -s -b cookies.txt http://192.168.1.200:3000/starbase/api/fleet/token/generate \
  -H "Content-Type: application/json" \
  -d '{"node_type": "outpost"}' | jq -r '.token')
echo "Token: $TOKEN"

# Register with token
curl -s -X POST http://192.168.1.200:3000/starbase/api/fleet/register \
  -H "Content-Type: application/json" \
  -d "{\"name\": \"test-node\", \"type\": \"outpost\", \"token\": \"$TOKEN\"}" | python3 -m json.tool
```

Expected: status = "approved", api_key returned.

- [ ] **Step 4: Test approval flow**

```bash
# Register without token
RESP=$(curl -s -X POST http://192.168.1.200:3000/starbase/api/fleet/register \
  -H "Content-Type: application/json" \
  -d '{"name": "test-satellite", "type": "satellite"}')
echo "$RESP" | python3 -m json.tool

NODE_ID=$(echo "$RESP" | jq -r '.node_id')

# Check status (should be pending)
curl -s "http://192.168.1.200:3000/starbase/api/fleet/status/$NODE_ID" | python3 -m json.tool

# Approve (requires auth)
curl -s -b cookies.txt -X POST "http://192.168.1.200:3000/starbase/api/fleet/approve/$NODE_ID" | python3 -m json.tool

# Check status again (should be approved)
curl -s "http://192.168.1.200:3000/starbase/api/fleet/status/$NODE_ID?need_key=true" | python3 -m json.tool
```

Expected: pending → approved with api_key.

- [ ] **Step 5: Test Satellite PWA in browser**

Open `http://192.168.1.200:3000/fleet/satellite/` in mobile browser or Chrome DevTools mobile simulation.

Verify:
- Registration form renders with LCARS theme
- Service worker registers (check DevTools > Application > Service Workers)
- Manifest detected (check DevTools > Application > Manifest)

- [ ] **Step 6: Clean up test data**

```bash
docker exec archie_database psql -U archie -d archie -c "DELETE FROM fleet_registration_tokens WHERE used_by_node_id LIKE 'node_%' OR used_at IS NULL;"
docker exec archie_database psql -U archie -d archie -c "DELETE FROM remote_nodes WHERE node_name IN ('test-node', 'test-satellite');"
```

- [ ] **Step 7: Final commit — update project understanding**

Log decisions and update project understanding via MCP after all tasks pass.
