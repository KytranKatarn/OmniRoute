# Kytran Mail Phase A — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a branded, fleet-deployable mail server product — Stalwart under the hood, LCARS Flask dashboard on top, deployable via KSO App Catalog.

**Architecture:** Single Docker container running Stalwart Mail Server + a thin Flask dashboard. The Flask app (port 8025) talks to Stalwart's REST API (localhost:443 inside container) for mailbox CRUD. An entrypoint script starts both processes. Config is templated via environment variables.

**Tech Stack:** Stalwart Mail v0.11.8, Python 3.12/Flask, Jinja2, LCARS CSS, Docker

**Spec:** `docs/superpowers/specs/2026-03-30-kytran-mail-design.md`

---

## File Structure

### New Files

```
kytran-mail/
  Dockerfile                              — multi-stage: stalwart + python dashboard
  docker-compose.yml                      — local dev compose
  entrypoint.sh                           — starts stalwart + flask dashboard
  config.toml.template                    — stalwart config (envsubst at startup)
  dashboard/
    __init__.py                           — package marker
    app.py                                — Flask app factory
    config.py                             — config from env vars
    stalwart_client.py                    — Stalwart management API client
    routes.py                             — dashboard + API routes
    templates/
      base.html                           — LCARS base template
      dashboard.html                      — main page (3 tabs inline)
    static/
      css/kytran-mail.css                 — LCARS theme
      js/kytran-mail.js                   — dashboard interactivity
  requirements.txt                        — Python deps
fleet/catalog/apps/kytran-mail.yml        — catalog entry
```

---

## Task 1: Project Scaffold + Stalwart Config Template

**Files:**
- Create: `kytran-mail/config.toml.template`
- Create: `kytran-mail/requirements.txt`
- Create: `kytran-mail/entrypoint.sh`

- [ ] **Step 1: Create project directory**

```bash
mkdir -p kytran-mail/dashboard/templates kytran-mail/dashboard/static/css kytran-mail/dashboard/static/js
```

- [ ] **Step 2: Create config.toml.template**

Read `stalwart-mail/config.toml` first. Create `kytran-mail/config.toml.template` with environment variable placeholders replacing hardcoded values:
- Domain references → `${MAIL_DOMAIN}`
- Admin password → `${MAIL_ADMIN_PASSWORD}`
- Hostname → `${MAIL_HOSTNAME}`
- Relay host → `${MAIL_RELAY_HOST}`
- Relay port → `${MAIL_RELAY_PORT}`
- DKIM selector stays `stalwart` (standard)

Keep all listener configs, TLS paths, DKIM paths, and storage config as-is (they reference paths inside the container).

- [ ] **Step 3: Create requirements.txt**

```
flask==3.1.1
requests==2.32.3
gunicorn==23.0.0
```

- [ ] **Step 4: Create entrypoint.sh**

```bash
#!/usr/bin/env bash
set -e

# Substitute env vars into Stalwart config template
envsubst < /opt/stalwart-mail/etc/config.toml.template > /opt/stalwart-mail/etc/config.toml

# Start Stalwart in background
/opt/stalwart-mail/bin/stalwart-mail --config /opt/stalwart-mail/etc/config.toml &
STALWART_PID=$!

# Wait for Stalwart API to be ready
echo "[Kytran Mail] Waiting for Stalwart..."
for i in $(seq 1 30); do
    if curl -sk https://localhost:443/api/principal -u "admin:${MAIL_ADMIN_PASSWORD}" > /dev/null 2>&1; then
        echo "[Kytran Mail] Stalwart ready."
        break
    fi
    sleep 2
done

# Start Flask dashboard
echo "[Kytran Mail] Starting dashboard on :8025..."
cd /app/dashboard
exec gunicorn --bind 0.0.0.0:8025 --workers 2 --threads 2 --timeout 120 "app:create_app()" &
FLASK_PID=$!

# Wait for either process to exit
wait -n $STALWART_PID $FLASK_PID
exit $?
```

- [ ] **Step 5: Make entrypoint executable and commit**

```bash
chmod +x kytran-mail/entrypoint.sh
git add kytran-mail/
git commit -m "feat(kytran-mail): scaffold project — config template, requirements, entrypoint"
```

---

## Task 2: Stalwart API Client

**Files:**
- Create: `kytran-mail/dashboard/stalwart_client.py`

- [ ] **Step 1: Create the Stalwart API client**

This module wraps Stalwart's REST API. The API uses:
- HTTPS on localhost:443 (inside container) with self-signed cert
- Basic auth: `admin:{MAIL_ADMIN_PASSWORD}`
- `GET /api/principal?type=individual` — list mailboxes
- `GET /api/principal/<name>` — get single account
- `POST /api/principal` — create account (JSON body)
- `DELETE /api/principal/<name>` — delete account
- `PATCH /api/principal/<name>` — update account
- `GET /api/queue/messages` — mail queue
- Response format: `{"data": {...}}` on success

```python
"""Stalwart Mail Server API client."""

import os

import requests
from requests.auth import HTTPBasicAuth

STALWART_URL = os.environ.get("STALWART_API_URL", "https://localhost:443")
ADMIN_USER = "admin"
ADMIN_PASS = os.environ.get("MAIL_ADMIN_PASSWORD", "")


def _auth():
    return HTTPBasicAuth(ADMIN_USER, ADMIN_PASS)


def _get(path, params=None):
    """GET request to Stalwart API."""
    try:
        resp = requests.get(
            f"{STALWART_URL}{path}",
            params=params,
            auth=_auth(),
            verify=False,
            timeout=10,
        )
        resp.raise_for_status()
        return resp.json().get("data", resp.json())
    except requests.RequestException as e:
        return {"error": str(e)}


def _post(path, data):
    """POST request to Stalwart API."""
    try:
        resp = requests.post(
            f"{STALWART_URL}{path}",
            json=data,
            auth=_auth(),
            verify=False,
            timeout=10,
        )
        resp.raise_for_status()
        return resp.json() if resp.text else {"success": True}
    except requests.RequestException as e:
        return {"error": str(e)}


def _patch(path, data):
    """PATCH request to Stalwart API."""
    try:
        resp = requests.patch(
            f"{STALWART_URL}{path}",
            json=data,
            auth=_auth(),
            verify=False,
            timeout=10,
        )
        resp.raise_for_status()
        return resp.json() if resp.text else {"success": True}
    except requests.RequestException as e:
        return {"error": str(e)}


def _delete(path):
    """DELETE request to Stalwart API."""
    try:
        resp = requests.delete(
            f"{STALWART_URL}{path}",
            auth=_auth(),
            verify=False,
            timeout=10,
        )
        resp.raise_for_status()
        return {"success": True}
    except requests.RequestException as e:
        return {"error": str(e)}


# ── Public API ───────────────────────────────────────────────────


def get_server_status():
    """Get Stalwart server health and version info."""
    result = _get("/api/principal", params={"limit": 1})
    if "error" in result:
        return {"online": False, "error": result["error"]}
    return {"online": True}


def list_mailboxes():
    """List all individual (non-admin) mailboxes."""
    result = _get("/api/principal", params={"type": "individual", "limit": 100})
    if "error" in result:
        return []
    items = result.get("items", [])
    mailboxes = []
    for item in items:
        mailboxes.append({
            "id": item.get("id"),
            "name": item.get("name", ""),
            "email": item.get("emails", ""),
            "display_name": item.get("description", ""),
            "roles": item.get("roles", []),
            "quota_used": item.get("usedQuota", 0),
            "enabled": "user" in item.get("roles", []),
        })
    return mailboxes


def create_mailbox(name, display_name, password, quota_mb=0):
    """Create a new mailbox account."""
    domain = os.environ.get("MAIL_DOMAIN", "kytranempowerment.com")
    data = {
        "type": "individual",
        "name": name,
        "description": display_name,
        "secrets": [password],
        "emails": [f"{name}@{domain}"],
        "roles": ["user"],
    }
    if quota_mb > 0:
        data["quota"] = quota_mb * 1024 * 1024
    return _post("/api/principal", data)


def delete_mailbox(name):
    """Delete a mailbox account."""
    return _delete(f"/api/principal/{name}")


def reset_password(name, new_password):
    """Reset a mailbox password."""
    return _patch(f"/api/principal/{name}", {"secrets": [new_password]})


def toggle_mailbox(name, enabled):
    """Enable or disable a mailbox."""
    roles = ["user"] if enabled else []
    return _patch(f"/api/principal/{name}", {"roles": roles})


def get_queue_status():
    """Get mail queue summary."""
    result = _get("/api/queue/messages", params={"limit": 100})
    if "error" in result:
        return {"pending": 0, "error": result["error"]}
    items = result.get("items", []) if isinstance(result, dict) else []
    return {"pending": len(items), "items": items[:10]}
```

- [ ] **Step 2: Commit**

```bash
git add kytran-mail/dashboard/stalwart_client.py
git commit -m "feat(kytran-mail): add Stalwart management API client"
```

---

## Task 3: Flask App + Config + Routes

**Files:**
- Create: `kytran-mail/dashboard/__init__.py`
- Create: `kytran-mail/dashboard/config.py`
- Create: `kytran-mail/dashboard/app.py`
- Create: `kytran-mail/dashboard/routes.py`

- [ ] **Step 1: Create __init__.py**

Empty file:
```bash
touch kytran-mail/dashboard/__init__.py
```

- [ ] **Step 2: Create config.py**

```python
"""Configuration from environment variables."""

import os


class Config:
    SECRET_KEY = os.environ.get("FLASK_SECRET_KEY", "dev-key-change-me")
    MAIL_DOMAIN = os.environ.get("MAIL_DOMAIN", "kytranempowerment.com")
    MAIL_HOSTNAME = os.environ.get("MAIL_HOSTNAME", "mail.kytranempowerment.com")
    MAIL_ADMIN_PASSWORD = os.environ.get("MAIL_ADMIN_PASSWORD", "")
    STALWART_ADMIN_URL = os.environ.get("STALWART_API_URL", "https://localhost:443")
```

- [ ] **Step 3: Create app.py**

```python
"""Kytran Mail — Flask app factory."""

from flask import Flask, redirect, url_for

from .config import Config


def create_app(config=None):
    app = Flask(
        __name__,
        template_folder="templates",
        static_folder="static",
    )
    app.config.from_object(Config)
    if config:
        app.config.update(config)

    from .routes import register_routes

    register_routes(app)

    @app.route("/")
    def index():
        return redirect(url_for("dashboard"))

    return app
```

- [ ] **Step 4: Create routes.py**

```python
"""Kytran Mail dashboard routes + API endpoints."""

from flask import jsonify, render_template, request

from . import stalwart_client


def register_routes(app):
    """Register all dashboard and API routes."""

    @app.route("/dashboard")
    def dashboard():
        return render_template(
            "dashboard.html",
            domain=app.config["MAIL_DOMAIN"],
            hostname=app.config["MAIL_HOSTNAME"],
        )

    # ── Health ───────────────────────────────────────────────────

    @app.route("/api/health")
    def api_health():
        status = stalwart_client.get_server_status()
        return jsonify({
            "status": "healthy" if status.get("online") else "unhealthy",
            "mail_server": status,
            "domain": app.config["MAIL_DOMAIN"],
        }), 200 if status.get("online") else 503

    @app.route("/api/status")
    def api_status():
        server = stalwart_client.get_server_status()
        queue = stalwart_client.get_queue_status()
        mailboxes = stalwart_client.list_mailboxes()
        return jsonify({
            "success": True,
            "server": server,
            "queue": queue,
            "mailbox_count": len(mailboxes),
            "domain": app.config["MAIL_DOMAIN"],
        })

    # ── Mailboxes ────────────────────────────────────────────────

    @app.route("/api/mailboxes")
    def api_list_mailboxes():
        mailboxes = stalwart_client.list_mailboxes()
        return jsonify({"success": True, "mailboxes": mailboxes, "count": len(mailboxes)})

    @app.route("/api/mailboxes", methods=["POST"])
    def api_create_mailbox():
        data = request.get_json() or {}
        name = data.get("name", "").strip().lower()
        display_name = data.get("display_name", name)
        password = data.get("password", "")
        quota_mb = data.get("quota_mb", 0)

        if not name:
            return jsonify({"success": False, "error": "Name is required"}), 400
        if not password or len(password) < 8:
            return jsonify({"success": False, "error": "Password must be at least 8 characters"}), 400

        result = stalwart_client.create_mailbox(name, display_name, password, quota_mb)
        if "error" in result:
            return jsonify({"success": False, "error": result["error"]}), 400
        return jsonify({"success": True, "message": f"Mailbox {name}@{app.config['MAIL_DOMAIN']} created"})

    @app.route("/api/mailboxes/<name>", methods=["DELETE"])
    def api_delete_mailbox(name):
        result = stalwart_client.delete_mailbox(name)
        if "error" in result:
            return jsonify({"success": False, "error": result["error"]}), 400
        return jsonify({"success": True, "message": f"Mailbox {name} deleted"})

    @app.route("/api/mailboxes/<name>/password", methods=["POST"])
    def api_reset_password(name):
        data = request.get_json() or {}
        password = data.get("password", "")
        if not password or len(password) < 8:
            return jsonify({"success": False, "error": "Password must be at least 8 characters"}), 400
        result = stalwart_client.reset_password(name, password)
        if "error" in result:
            return jsonify({"success": False, "error": result["error"]}), 400
        return jsonify({"success": True, "message": f"Password reset for {name}"})

    @app.route("/api/mailboxes/<name>/toggle", methods=["POST"])
    def api_toggle_mailbox(name):
        data = request.get_json() or {}
        enabled = data.get("enabled", True)
        result = stalwart_client.toggle_mailbox(name, enabled)
        if "error" in result:
            return jsonify({"success": False, "error": result["error"]}), 400
        state = "enabled" if enabled else "disabled"
        return jsonify({"success": True, "message": f"Mailbox {name} {state}"})

    # ── Queue ────────────────────────────────────────────────────

    @app.route("/api/queue")
    def api_queue():
        queue = stalwart_client.get_queue_status()
        return jsonify({"success": True, "queue": queue})
```

- [ ] **Step 5: Commit**

```bash
git add kytran-mail/dashboard/
git commit -m "feat(kytran-mail): add Flask app factory, routes, config"
```

---

## Task 4: LCARS Dashboard UI

**Files:**
- Create: `kytran-mail/dashboard/templates/base.html`
- Create: `kytran-mail/dashboard/templates/dashboard.html`
- Create: `kytran-mail/dashboard/static/css/kytran-mail.css`
- Create: `kytran-mail/dashboard/static/js/kytran-mail.js`

- [ ] **Step 1: Create base.html**

Follow the KSO base template pattern. Blocks: `title`, `styles`, `content`, `scripts`. Include:
- Google Fonts (Orbitron + IBM Plex Mono)
- Nav bar with "KYTRAN MAIL" branding + teal accent
- Link to `kytran-mail.css`
- Domain display in nav
- Link to Stalwart admin (8443) in nav

- [ ] **Step 2: Create kytran-mail.css**

LCARS dark theme matching KSO and other Kytran products:
- Root variables: `--bg-dark: #0a0e17`, `--bg-panel: #111827`, `--accent: #00e5ff`, `--green: #10b981`, `--amber: #f59e0b`, `--red: #ef4444`
- Nav bar (`.km-nav`), main area (`.km-main`)
- Tab system (`.km-tabs`, `.km-tab`, `.km-tab-panel`)
- Hero stats (`.km-stats`, `.km-stat-card`)
- Table (`.km-table`) for mailbox listing
- LCARS modal (`.km-modal-overlay`, `.km-modal`)
- Form inputs (`.km-input`, `.km-btn`, `.km-btn-sm`)
- Status badges (`.km-badge.active`, `.km-badge.disabled`)
- Toast notifications (`.km-toast`)
- Responsive at 768px and 480px

- [ ] **Step 3: Create dashboard.html**

Extends `base.html`. Three tabs inline:

**Dashboard tab:** Hero stats (Mailboxes, Storage, Queue, Status), status indicator card.

**Mailboxes tab:** Search bar + "Create Mailbox" button, table with columns (Name, Email, Display Name, Status, Storage, Actions), action buttons (Reset Password, Toggle, Delete). Create mailbox LCARS modal with fields: name, display name, password, quota.

**Settings tab:** Domain (read-only), DKIM status, TLS status, relay config, link to Stalwart admin. Toast container.

All DOM rendering MUST use `textContent` and `createElement` — NO `innerHTML` with dynamic data (XSS prevention). Use a `_buildRow(mb)` function that creates `<tr>` via DOM API.

- [ ] **Step 4: Create kytran-mail.js**

Dashboard interactivity — IIFE pattern, exports to `window.kmail`:
- `switchTab(name)` — show/hide tab panels
- `loadStatus()` — GET /api/status, update stat cards via `textContent`
- `loadMailboxes()` — GET /api/mailboxes, render table via DOM API (createElement, not innerHTML)
- `createMailbox()` — POST /api/mailboxes from modal form
- `deleteMailbox(name)` — DELETE with confirm()
- `resetPassword(name)` — POST with prompt()
- `toggleMailbox(name, enabled)` — POST with confirm()
- `showCreateModal()` / `closeModal()`
- `toast(message, type)` — notification toast
- Auto-refresh status every 30s

All table row building MUST use `document.createElement` + `textContent` — never set `innerHTML` with user data.

- [ ] **Step 5: Commit**

```bash
git add kytran-mail/dashboard/templates/ kytran-mail/dashboard/static/
git commit -m "feat(kytran-mail): add LCARS dashboard UI — tabs, mailbox CRUD, status"
```

---

## Task 5: Dockerfile

**Files:**
- Create: `kytran-mail/Dockerfile`
- Create: `kytran-mail/docker-compose.yml`

- [ ] **Step 1: Create Dockerfile**

Multi-stage build: Stalwart base + Python dashboard layer.

```dockerfile
FROM stalwartlabs/mail-server:v0.11.8 AS stalwart

FROM python:3.12-slim

# Install system deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl gettext-base ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Copy Stalwart binary and default config
COPY --from=stalwart /opt/stalwart-mail/bin/ /opt/stalwart-mail/bin/
COPY --from=stalwart /opt/stalwart-mail/etc/ /opt/stalwart-mail/etc/

# Create data directories
RUN mkdir -p /opt/stalwart-mail/data /opt/stalwart-mail/dkim /opt/stalwart-mail/certs /opt/stalwart-mail/logs

# Install Python deps
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy dashboard app
COPY dashboard/ /app/dashboard/

# Copy config template + entrypoint
COPY config.toml.template /opt/stalwart-mail/etc/config.toml.template
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# Ports: SMTP(25), Submission(587), SMTPS(465), IMAPS(993), Sieve(4190), Dashboard(8025), Admin(443)
EXPOSE 25 587 465 993 4190 8025 443

# Data volume
VOLUME ["/opt/stalwart-mail"]

ENTRYPOINT ["/entrypoint.sh"]
```

- [ ] **Step 2: Create docker-compose.yml for local dev**

```yaml
services:
  kytran-mail:
    build: .
    container_name: kytran_mail_dev
    ports:
      - "25:25"
      - "587:587"
      - "465:465"
      - "993:993"
      - "8025:8025"
      - "8443:443"
    environment:
      - MAIL_DOMAIN=kytranempowerment.com
      - MAIL_ADMIN_PASSWORD=KytranMail2026!
      - MAIL_HOSTNAME=mail.kytranempowerment.com
      - FLASK_SECRET_KEY=dev-secret-key
      - MAIL_RELAY_HOST=
      - MAIL_RELAY_PORT=587
    volumes:
      - mail-data:/opt/stalwart-mail
      - ./dkim:/opt/stalwart-mail/dkim:ro
      - ./certs:/opt/stalwart-mail/certs:ro
    restart: unless-stopped
    deploy:
      resources:
        limits:
          memory: 512M
          cpus: "1.0"

volumes:
  mail-data:
```

- [ ] **Step 3: Commit**

```bash
git add kytran-mail/Dockerfile kytran-mail/docker-compose.yml
git commit -m "feat(kytran-mail): add Dockerfile and docker-compose for local dev"
```

---

## Task 6: Fleet Catalog Entry

**Files:**
- Create: `fleet/catalog/apps/kytran-mail.yml`

- [ ] **Step 1: Create catalog entry**

```yaml
name: Kytran Mail
id: kytran-mail
description: Branded mail server with LCARS admin — mailbox management, health monitoring, fleet-deployable
image: ghcr.io/kytrankatarn/kytran-mail:latest
version: "1.0.0"
port: 8025
env:
  - name: MAIL_DOMAIN
    required: true
    default: "kytranempowerment.com"
  - name: MAIL_ADMIN_PASSWORD
    required: true
    generate: true
  - name: MAIL_HOSTNAME
    required: false
    default: ""
  - name: MAIL_RELAY_HOST
    required: false
    default: ""
  - name: MAIL_RELAY_PORT
    required: false
    default: "587"
  - name: MAIL_RELAY_USER
    required: false
    default: ""
  - name: MAIL_RELAY_PASSWORD
    required: false
    default: ""
  - name: FLASK_SECRET_KEY
    required: true
    generate: true
volumes:
  - name: mail
    path: /opt/stalwart-mail
resources:
  min_ram_mb: 512
  min_disk_mb: 1000
  gpu: false
compatible_nodes:
  - outpost
  - starship
category: products
health_endpoint: /api/health
depends_on: []
```

- [ ] **Step 2: Commit**

```bash
git add fleet/catalog/apps/kytran-mail.yml
git commit -m "feat(kytran-mail): add fleet catalog entry"
```

---

## Task 7: Build + Integration Test

- [ ] **Step 1: Build the Docker image**

```bash
cd kytran-mail && docker build -t kytran-mail:latest .
```

Expected: Image builds successfully.

- [ ] **Step 2: Start locally**

```bash
docker compose up -d
```

Wait 15 seconds for Stalwart to initialize.

- [ ] **Step 3: Test health endpoint**

```bash
curl -s http://localhost:8025/api/health | python3 -m json.tool
```

Expected: `{"status": "healthy", "mail_server": {"online": true}, "domain": "kytranempowerment.com"}`

- [ ] **Step 4: Test dashboard loads**

Open `http://localhost:8025/dashboard` in browser. Verify:
- LCARS dark theme renders
- Three tabs visible (Dashboard, Mailboxes, Settings)
- Status shows ONLINE
- Mailbox count matches existing accounts

- [ ] **Step 5: Test mailbox CRUD**

```bash
# Create
curl -s -X POST http://localhost:8025/api/mailboxes \
  -H "Content-Type: application/json" \
  -d '{"name": "testuser", "display_name": "Test User", "password": "TestPass2026!"}' | python3 -m json.tool

# List (should include testuser)
curl -s http://localhost:8025/api/mailboxes | python3 -c "import sys,json; d=json.load(sys.stdin); print(f'Count: {d[\"count\"]}')"

# Delete
curl -s -X DELETE http://localhost:8025/api/mailboxes/testuser | python3 -m json.tool
```

- [ ] **Step 6: Verify catalog shows 7 apps**

```bash
docker compose restart archie_platform
curl -s http://192.168.1.200:3000/tools/starbase/api/fleet/catalog | python3 -c "import sys,json; d=json.load(sys.stdin); print(f'Count: {d[\"count\"]}')"
```

Expected: 7 (was 6, now includes kytran-mail).

- [ ] **Step 7: Stop dev container**

```bash
cd kytran-mail && docker compose down
```

- [ ] **Step 8: Final commit**

```bash
git add -A && git commit -m "feat(kytran-mail): Kytran Mail Phase A complete — branded fleet mail product"
```
