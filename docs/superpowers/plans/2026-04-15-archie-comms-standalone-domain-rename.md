# A.R.C.H.I.E. Comms Standalone + Domain Rename — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extract A.R.C.H.I.E.'s communication layer into an independent Docker container (`archie_comms` on :3001) and rename domains so `archie.kytranempowerment.com` becomes her domain while `platform.kytranempowerment.com` serves the web app.

**Architecture:** Copy+Adapt extraction of ~3,750 lines into `/mnt/archie_brain/archie-comms/`. New container shares DB + Ollama with platform. HTTP API + DB queue for inter-container communication. Platform watchdog monitors archie_platform health.

**Tech Stack:** Python 3.12-slim Docker image, Flask-minimal (chat UI only), PostgreSQL, Ollama HTTP, python-telegram-bot, Hostinger DNS API, NPM Proxy Manager.

**Spec:** `docs/superpowers/specs/2026-04-15-archie-comms-standalone-domain-rename-design.md`
**Decision:** #442

---

## File Map

| File | Action | Purpose |
|------|--------|---------|
| `archie-comms/Dockerfile` | Create | Container image |
| `archie-comms/requirements.txt` | Create | Python deps |
| `archie-comms/app_comms.py` | Create | Entrypoint — Flask minimal for chat UI + API |
| `archie-comms/database.py` | Create | DB connection (adapted from platform) |
| `archie-comms/services/archie_voice_service.py` | Copy | Personality engine |
| `archie-comms/services/telegram_service.py` | Copy+Adapt | Telegram send/receive |
| `archie-comms/services/watchdog_service.py` | Create | Platform health monitor |
| `archie-comms/services/queue_service.py` | Create | DB queue poller for outbound_messages |
| `archie-comms/chat/api_routes.py` | Copy+Adapt | Chat API endpoints |
| `archie-comms/chat/chat_service.py` | Copy+Adapt | Chat orchestration |
| `archie-comms/chat/auth_middleware.py` | Copy+Adapt | Auth for chat |
| `archie-comms/chat/ha_bridge.py` | Copy | Home Assistant voice |
| `archie-comms/collaboration/collaboration_engine.py` | Copy | Claude collaboration |
| `archie-comms/collaboration/claude_bridge.py` | Copy | Claude HTTP proxy |
| `archie-comms/templates/chat.html` | Copy+Adapt | Chat UI template |
| `archie-comms/static/` | Create | Minimal CSS/JS for chat |
| `database/migrations/109_outbound_messages.sql` | Create | Message queue table |
| `docker-compose.yml` | Modify | Add archie_comms service |
| `platform_v2/services/code_metrics_service.py` | Modify | Register in Code Health |
| Multiple files | Modify | Domain rename (see Task 8) |

---

## Phase A: Container Build

### Task 1: Create Directory Structure + Database Module

**Files:**
- Create: `archie-comms/database.py`
- Create: `archie-comms/requirements.txt`
- Create: `archie-comms/services/__init__.py`
- Create: `archie-comms/chat/__init__.py`
- Create: `archie-comms/collaboration/__init__.py`
- Create: `archie-comms/templates/` (dir)
- Create: `archie-comms/static/` (dir)

- [ ] **Step 1: Create directory structure**

```bash
mkdir -p /mnt/archie_brain/archie-comms/{services,chat,collaboration,templates,static/css,static/js}
touch /mnt/archie_brain/archie-comms/services/__init__.py
touch /mnt/archie_brain/archie-comms/chat/__init__.py
touch /mnt/archie_brain/archie-comms/collaboration/__init__.py
```

- [ ] **Step 2: Create database.py**

Create `archie-comms/database.py` — standalone DB connection, no Flask dependency:

```python
"""Database connection for archie_comms — standalone, no Flask."""

import os
import psycopg2
import psycopg2.extras
from contextlib import contextmanager

_DB_CONFIG = {
    "host": os.getenv("DB_HOST", "archie_database"),
    "database": os.getenv("DB_NAME", "archie"),
    "user": os.getenv("DB_USER", "archie"),
    "password": os.getenv("DB_PASSWORD", ""),
}


def _get_db_password():
    """Read password from Docker secret or env var."""
    secret_path = "/run/secrets/db_password"
    if os.path.exists(secret_path):
        with open(secret_path) as f:
            return f.read().strip()
    return os.getenv("DB_PASSWORD", "")


def get_db():
    """Get a raw psycopg2 connection."""
    config = {**_DB_CONFIG, "password": _get_db_password()}
    return psycopg2.connect(**config)


@contextmanager
def get_db_cursor(commit=False):
    """Context manager yielding (conn, cursor) with RealDictCursor."""
    conn = get_db()
    conn.cursor_factory = psycopg2.extras.RealDictCursor
    cur = conn.cursor()
    try:
        yield conn, cur
        if commit:
            conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()
        conn.close()
```

- [ ] **Step 3: Create requirements.txt**

Create `archie-comms/requirements.txt`:

```
flask==3.1.*
psycopg2-binary==2.9.*
requests==2.32.*
python-telegram-bot==21.*
gunicorn==23.*
```

- [ ] **Step 4: Commit**

```bash
git add archie-comms/
git commit -m "feat: archie-comms directory structure + database module"
```

---

### Task 2: Copy + Adapt Core Services

**Files:**
- Copy: `archie-comms/services/archie_voice_service.py`
- Copy+Adapt: `archie-comms/services/telegram_service.py`

- [ ] **Step 1: Copy voice service (no changes needed — already Flask-free)**

```bash
cp /mnt/archie_brain/platform_v2/services/archie_voice_service.py /mnt/archie_brain/archie-comms/services/
```

- [ ] **Step 2: Copy and adapt telegram_service.py**

```bash
cp /mnt/archie_brain/platform_v2/services/telegram_service.py /mnt/archie_brain/archie-comms/services/
```

Then edit `archie-comms/services/telegram_service.py`:
- Change `from database import get_db_cursor` to `from database import get_db_cursor` (same — the local database.py has the same API)
- Verify no Flask imports exist (there shouldn't be any)
- The voice service import `from services.archie_voice_service import format_message` works as-is since the directory structure matches

- [ ] **Step 3: Verify imports work**

```bash
cd /mnt/archie_brain/archie-comms && python3 -c "from services.archie_voice_service import format_message, _template_fallback; print('Voice service OK')"
```

- [ ] **Step 4: Commit**

```bash
git add archie-comms/services/
git commit -m "feat: archie-comms voice + telegram services (copied from platform)"
```

---

### Task 3: Copy + Adapt Chat Module

**Files:**
- Copy+Adapt: `archie-comms/chat/api_routes.py`
- Copy+Adapt: `archie-comms/chat/chat_service.py`
- Copy: `archie-comms/chat/auth_middleware.py`
- Copy: `archie-comms/chat/ha_bridge.py`
- Copy+Adapt: `archie-comms/templates/chat.html`

- [ ] **Step 1: Copy chat module files**

```bash
cp /mnt/archie_brain/platform_v2/tools/archie_chat/api_routes.py /mnt/archie_brain/archie-comms/chat/
cp /mnt/archie_brain/platform_v2/tools/archie_chat/chat_service.py /mnt/archie_brain/archie-comms/chat/
cp /mnt/archie_brain/platform_v2/tools/archie_chat/auth_middleware.py /mnt/archie_brain/archie-comms/chat/
cp /mnt/archie_brain/platform_v2/tools/archie_chat/ha_bridge.py /mnt/archie_brain/archie-comms/chat/
cp /mnt/archie_brain/platform_v2/tools/archie_chat/templates/archie_chat.html /mnt/archie_brain/archie-comms/templates/chat.html
```

- [ ] **Step 2: Adapt imports in api_routes.py**

In `archie-comms/chat/api_routes.py`, update imports:
- `from tools.archie_chat.chat_service import ...` → `from chat.chat_service import ...`
- `from tools.archie_chat.auth_middleware import ...` → `from chat.auth_middleware import ...`
- `from database import ...` → `from database import ...` (same)
- Remove any `from tools.department_hq.services.bridge_dispatcher import ...` — replace with direct Ollama calls or HTTP to platform

- [ ] **Step 3: Adapt imports in chat_service.py**

Similar import path updates. Any dispatcher calls should route to `archie_platform:3000/api/dispatch` via HTTP instead of direct Python import.

- [ ] **Step 4: Adapt template paths in chat.html**

Update any references to platform static assets. The chat template should be self-contained with its own CSS/JS.

- [ ] **Step 5: Commit**

```bash
git add archie-comms/chat/ archie-comms/templates/
git commit -m "feat: archie-comms chat module (adapted from platform archie_chat)"
```

---

### Task 4: Copy Collaboration Engine + Claude Bridge

**Files:**
- Copy: `archie-comms/collaboration/collaboration_engine.py`
- Copy: `archie-comms/collaboration/claude_bridge.py`

- [ ] **Step 1: Copy collaboration files**

```bash
cp /mnt/archie_brain/platform_v2/tools/consciousness/collaboration_engine.py /mnt/archie_brain/archie-comms/collaboration/
cp /mnt/archie_brain/platform_v2/tools/consciousness/claude_bridge.py /mnt/archie_brain/archie-comms/collaboration/
```

- [ ] **Step 2: Adapt imports**

In `collaboration_engine.py`:
- `from database import _get_db_password` → `from database import _get_db_password` (same API)
- Remove any Flask-specific imports
- Verify `claude_bridge.py` CLAUDE_PROXY_URL works from inside container (host.docker.internal:7682)

- [ ] **Step 3: Commit**

```bash
git add archie-comms/collaboration/
git commit -m "feat: archie-comms collaboration engine + claude bridge"
```

---

### Task 5: Create Watchdog + Queue Services

**Files:**
- Create: `archie-comms/services/watchdog_service.py`
- Create: `archie-comms/services/queue_service.py`
- Create: `database/migrations/109_outbound_messages.sql`

- [ ] **Step 1: Create outbound_messages migration**

Create `database/migrations/109_outbound_messages.sql`:

```sql
BEGIN;

CREATE TABLE IF NOT EXISTS outbound_messages (
    id SERIAL PRIMARY KEY,
    category VARCHAR(50) NOT NULL,
    title VARCHAR(500) NOT NULL,
    message TEXT NOT NULL,
    source_agent VARCHAR(100),
    source_department VARCHAR(100),
    source_module VARCHAR(100),
    channel VARCHAR(20) DEFAULT 'telegram',
    priority VARCHAR(20) DEFAULT 'medium',
    status VARCHAR(20) DEFAULT 'pending',
    created_at TIMESTAMP DEFAULT NOW(),
    processed_at TIMESTAMP,
    result JSONB
);

CREATE INDEX IF NOT EXISTS idx_outbound_pending
    ON outbound_messages(status) WHERE status = 'pending';

COMMIT;
```

- [ ] **Step 2: Run migration**

```bash
docker exec -i archie_database psql -U archie -d archie < /mnt/archie_brain/database/migrations/109_outbound_messages.sql
```

- [ ] **Step 3: Create watchdog_service.py**

Create `archie-comms/services/watchdog_service.py`:

```python
"""Platform Health Watchdog — monitors archie_platform from archie_comms.

Pings platform health endpoint every 30s. After 3 consecutive failures,
alerts Kytran via Telegram. Can attempt restart with Docker API.
"""

import logging
import os
import time
import threading
import urllib.request
import json

logger = logging.getLogger(__name__)

PLATFORM_URL = os.getenv("PLATFORM_URL", "http://archie_platform:3000")
CHECK_INTERVAL = 30  # seconds
FAILURE_THRESHOLD = 3  # consecutive failures before alert


class PlatformWatchdog:
    def __init__(self):
        self._failures = 0
        self._alerted = False
        self._running = False
        self._thread = None

    def start(self):
        """Start the watchdog background thread."""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True, name="platform-watchdog")
        self._thread.start()
        logger.info("Platform watchdog started (checking %s every %ds)", PLATFORM_URL, CHECK_INTERVAL)

    def stop(self):
        self._running = False

    def _check_health(self):
        """Ping platform health endpoint. Returns True if healthy."""
        try:
            req = urllib.request.Request(f"{PLATFORM_URL}/api/health", method="GET")
            with urllib.request.urlopen(req, timeout=10) as resp:
                if resp.status == 200:
                    return True
        except Exception:
            pass
        return False

    def _loop(self):
        """Main watchdog loop."""
        while self._running:
            time.sleep(CHECK_INTERVAL)
            if self._check_health():
                if self._failures > 0:
                    logger.info("Platform recovered after %d failures", self._failures)
                    if self._alerted:
                        self._send_recovery_alert()
                self._failures = 0
                self._alerted = False
            else:
                self._failures += 1
                logger.warning("Platform health check failed (%d/%d)", self._failures, FAILURE_THRESHOLD)
                if self._failures >= FAILURE_THRESHOLD and not self._alerted:
                    self._send_down_alert()
                    self._alerted = True

    def _send_down_alert(self):
        """Alert Kytran that the platform is down."""
        try:
            from services.telegram_service import send_system
            send_system(
                "Platform Down",
                f"archie_platform has been unreachable for {self._failures * CHECK_INTERVAL}s. "
                f"I'm still here and monitoring. Will notify you when it recovers.",
                source_module="watchdog_service",
            )
        except Exception as e:
            logger.error("Watchdog: failed to send down alert: %s", e)

    def _send_recovery_alert(self):
        """Alert Kytran that the platform recovered."""
        try:
            from services.telegram_service import send_system
            send_system(
                "Platform Recovered",
                f"archie_platform is back online after ~{self._failures * CHECK_INTERVAL}s downtime.",
                source_module="watchdog_service",
            )
        except Exception as e:
            logger.error("Watchdog: failed to send recovery alert: %s", e)
```

- [ ] **Step 4: Create queue_service.py**

Create `archie-comms/services/queue_service.py`:

```python
"""Outbound Message Queue — polls DB for messages from archie_platform.

Platform writes to outbound_messages table. This service polls every 5s,
processes pending messages through the voice service, and sends via Telegram.
"""

import logging
import time
import threading

logger = logging.getLogger(__name__)

POLL_INTERVAL = 5  # seconds


class QueueProcessor:
    def __init__(self):
        self._running = False
        self._thread = None

    def start(self):
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True, name="queue-processor")
        self._thread.start()
        logger.info("Queue processor started (polling every %ds)", POLL_INTERVAL)

    def stop(self):
        self._running = False

    def _loop(self):
        while self._running:
            time.sleep(POLL_INTERVAL)
            try:
                self._process_pending()
            except Exception as e:
                logger.warning("Queue processor error: %s", e)

    def _process_pending(self):
        """Fetch and process pending outbound messages."""
        from database import get_db_cursor
        import json

        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute("""
                SELECT id, category, title, message, source_agent, source_department,
                       source_module, channel, priority
                FROM outbound_messages
                WHERE status = 'pending'
                ORDER BY
                    CASE priority
                        WHEN 'critical' THEN 0
                        WHEN 'high' THEN 1
                        WHEN 'medium' THEN 2
                        WHEN 'low' THEN 3
                    END,
                    created_at ASC
                LIMIT 10
            """)
            rows = cur.fetchall()

            for row in rows:
                try:
                    from services.telegram_service import send
                    result = send(
                        category=row["category"],
                        title=row["title"],
                        message=row["message"],
                        source_agent=row.get("source_agent"),
                        source_department=row.get("source_department"),
                        source_module=row.get("source_module"),
                    )
                    cur.execute(
                        "UPDATE outbound_messages SET status = 'sent', processed_at = NOW(), result = %s WHERE id = %s",
                        (json.dumps(result), row["id"]),
                    )
                except Exception as e:
                    cur.execute(
                        "UPDATE outbound_messages SET status = 'failed', processed_at = NOW(), result = %s WHERE id = %s",
                        (json.dumps({"error": str(e)}), row["id"]),
                    )
                    logger.warning("Queue: failed to process message %d: %s", row["id"], e)
```

- [ ] **Step 5: Commit**

```bash
git add archie-comms/services/watchdog_service.py archie-comms/services/queue_service.py database/migrations/109_outbound_messages.sql
git commit -m "feat: watchdog + queue services + outbound_messages migration"
```

---

### Task 6: Create Entrypoint + Dockerfile

**Files:**
- Create: `archie-comms/app_comms.py`
- Create: `archie-comms/Dockerfile`

- [ ] **Step 1: Create app_comms.py**

Create `archie-comms/app_comms.py`:

```python
"""A.R.C.H.I.E. Comms — Independent Communication Layer.

Runs as archie_comms container on :3001. Provides:
- Chat UI and API (A.R.C.H.I.E.'s face to the world)
- Telegram send/receive with personality voice
- Platform health watchdog
- Outbound message queue processor
- Collaboration engine (Claude bridge)
"""

import logging
import os

from flask import Flask

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger("archie_comms")

app = Flask(__name__, template_folder="templates", static_folder="static")
app.secret_key = os.getenv("SECRET_KEY", os.urandom(32).hex())


# Health endpoint
@app.route("/api/health")
def health():
    return {"status": "ok", "service": "archie_comms", "version": "1.0.0"}


# Register chat routes
from chat.api_routes import register_chat_routes
register_chat_routes(app)


# Internal API for platform to send messages
@app.route("/api/send", methods=["POST"])
def api_send():
    """Platform calls this to send a message through A.R.C.H.I.E.'s voice."""
    from flask import request, jsonify
    from services.telegram_service import send

    data = request.get_json() or {}
    result = send(
        category=data.get("category", "info"),
        title=data.get("title", ""),
        message=data.get("message", ""),
        source_agent=data.get("source_agent"),
        source_department=data.get("source_department"),
        source_module=data.get("source_module"),
        force=data.get("force", False),
    )
    return jsonify(result)


# Start background services
def start_background_services():
    """Start watchdog and queue processor."""
    from services.watchdog_service import PlatformWatchdog
    from services.queue_service import QueueProcessor

    watchdog = PlatformWatchdog()
    watchdog.start()

    queue = QueueProcessor()
    queue.start()

    logger.info("Background services started (watchdog + queue)")


start_background_services()


if __name__ == "__main__":
    port = int(os.getenv("COMMS_PORT", "3001"))
    app.run(host="0.0.0.0", port=port, debug=False)
```

- [ ] **Step 2: Create Dockerfile**

Create `archie-comms/Dockerfile`:

```dockerfile
FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

RUN groupadd -r archie && useradd -r -g archie -m archie

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN chown -R archie:archie /app

USER archie

EXPOSE 3001

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD curl -f http://localhost:3001/api/health || exit 1

CMD ["gunicorn", "--bind", "0.0.0.0:3001", "--workers", "2", "--timeout", "120", "app_comms:app"]
```

- [ ] **Step 3: Commit**

```bash
git add archie-comms/app_comms.py archie-comms/Dockerfile
git commit -m "feat: archie-comms entrypoint + Dockerfile"
```

---

### Task 7: Add to docker-compose.yml + Code Health + Build & Test

**Files:**
- Modify: `docker-compose.yml`
- Modify: `platform_v2/services/code_metrics_service.py`

- [ ] **Step 1: Add archie_comms to docker-compose.yml**

Add after the `archie_platform` service block:

```yaml
  archie_comms:
    build:
      context: ./archie-comms
      dockerfile: Dockerfile
    container_name: archie_comms
    restart: unless-stopped
    read_only: true
    tmpfs:
      - /tmp
    cap_drop:
      - ALL
    cap_add:
      - NET_BIND_SERVICE
    environment:
      - DB_HOST=archie_database
      - DB_NAME=archie
      - DB_USER=archie
      - OLLAMA_HOST=host.docker.internal:11434
      - ARCHIE_VOICE_MODEL=dolphin3-8k:latest
      - PLATFORM_URL=http://archie_platform:3000
      - CLAUDE_PROXY_URL=http://host.docker.internal:7682
      - COMMS_PORT=3001
    env_file:
      - .env
    ports:
      - "3001:3001"
    networks:
      - archie_internal
    depends_on:
      archie_database:
        condition: service_healthy
    secrets:
      - db_password
    deploy:
      resources:
        limits:
          memory: 256M
          cpus: "2"
```

- [ ] **Step 2: Register in Code Health**

In `platform_v2/services/code_metrics_service.py`, add to `_STANDALONE_DEFS`:

```python
{"name": "A.R.C.H.I.E. Comms", "dir_name": "archie-comms", "module_key": "archie_comms"},
```

- [ ] **Step 3: Open firewall**

```bash
sudo ufw allow 3001/tcp comment "archie_comms"
```

- [ ] **Step 4: Build and start**

```bash
cd /mnt/archie_brain
docker compose build archie_comms
docker compose up -d archie_comms
```

- [ ] **Step 5: Verify health**

```bash
curl http://192.168.1.200:3001/api/health
```

Expected: `{"status": "ok", "service": "archie_comms", "version": "1.0.0"}`

- [ ] **Step 6: Verify watchdog is running**

```bash
docker logs archie_comms 2>&1 | grep watchdog
```

Expected: "Platform watchdog started"

- [ ] **Step 7: Commit**

```bash
git add docker-compose.yml platform_v2/services/code_metrics_service.py
git commit -m "feat: archie_comms in docker-compose + Code Health registration"
```

---

## Phase B: Domain Rename

### Task 8: DNS + NPM + AdGuard Changes

**Files:** Infrastructure only (no code files)

- [ ] **Step 1: Add platform.kytranempowerment.com DNS record at Hostinger**

Use the Hostinger DNS API (MCP tool) to add an A record:
- Name: `platform`
- Type: A
- Content: `153.68.195.85` (hub public IP)
- TTL: 14400

- [ ] **Step 2: Add AdGuard split DNS rewrite**

```python
# Add platform.kytranempowerment.com -> 192.168.1.200
import urllib.request, json, base64
url = "http://127.0.0.1:5354/control/rewrite/add"
creds = base64.b64encode(b"kytran:Kyt$13ran2025").decode()
payload = json.dumps({"domain": "platform.kytranempowerment.com", "answer": "192.168.1.200"}).encode()
req = urllib.request.Request(url, data=payload, headers={"Authorization": f"Basic {creds}", "Content-Type": "application/json"}, method="POST")
urllib.request.urlopen(req, timeout=10)
```

- [ ] **Step 3: Add NPM proxy host for platform.kytranempowerment.com**

In NPM (192.168.1.200:81):
- New proxy host: `platform.kytranempowerment.com` → `192.168.1.200:3000`
- SSL: Request new Let's Encrypt certificate
- Force SSL: Yes

- [ ] **Step 4: Update NPM proxy host for archie.kytranempowerment.com**

Change existing proxy host:
- `archie.kytranempowerment.com` → `192.168.1.200:3001` (was :3000)

- [ ] **Step 5: Add platform to DDNS script**

Edit `/mnt/archie_brain/scripts/ddns_updater.sh` — add `platform` to the SUBDOMAINS array.

- [ ] **Step 6: Test both URLs**

```bash
curl -sI https://platform.kytranempowerment.com | head -5
curl -sI https://archie.kytranempowerment.com | head -5
```

Expected: Both return 200 OK with correct content.

---

### Task 9: Code File Updates (15 active files)

**Files:** See list below

- [ ] **Step 1: Update .env files**

In `.env` and `platform_v2/.env`:
```
GOOGLE_REDIRECT_URI=https://platform.kytranempowerment.com/tools/google-work-suite/oauth/callback
```

- [ ] **Step 2: Update platform code files**

For each file, replace `archie.kytranempowerment.com` with `platform.kytranempowerment.com` EXCEPT where the URL is for A.R.C.H.I.E.'s services (chat, voice, roster API):

Files to change to `platform.kytranempowerment.com`:
- `platform_v2/tools/directory/routes.py`
- `platform_v2/tools/department_hq/fleet_node_routes.py`
- `platform_v2/services/github_deployment.py`
- `platform_v2/static/js/security-network-app.js`
- `platform_v2/static/downloads/install.sh`
- `platform_v2/tools/security_network/rule_packs/hipaa-security.json`
- `kytran-auth/kytran_auth.py` + `kytran-auth/template/kytran_auth.py`
- `node_client/installer/archie_node_installer.py`
- `node_client/install.sh`
- `node_client/install-node.sh`
- `node_client/config.example.json`

Files that KEEP `archie.kytranempowerment.com` (it's her domain now):
- `platform_v2/services/archie_voice_service.py` — "More details at archie.kytranempowerment.com"
- `platform_v2/tools/department_hq/roster_routes.py` — public roster API stays on her domain

- [ ] **Step 3: Update website files**

- `website/kytranempowerment.com/js/ai-directors.js` line 171: API_URL stays as `archie.kytranempowerment.com` (roster is her API)
- `website/kytranempowerment.com/blocked.html` line 93: update to `platform.kytranempowerment.com`
- `website/code.kytranempowerment.com/index.html` lines 687/691: update to `platform.kytranempowerment.com`

- [ ] **Step 4: Update rules + CLAUDE.md**

- `.claude/rules/operational-state.md` — update Platform URL to `platform.kytranempowerment.com`
- `.claude/commands/archie-boot.md` — update URL
- `CLAUDE.md` — update Quick Reference table

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "feat: domain rename — platform.kytranempowerment.com for web app, archie.* for A.R.C.H.I.E."
```

---

## Phase C: Redirect Safety Net

### Task 10: Platform Redirect for Old URLs

**Files:**
- Modify: `platform_v2/app.py`

- [ ] **Step 1: Add redirect middleware to archie_platform**

In `platform_v2/app.py`, add a before_request handler that redirects `archie.kytranempowerment.com` requests to `platform.kytranempowerment.com` (except the routes that now belong to archie_comms):

```python
@app.before_request
def redirect_old_archie_domain():
    """Redirect archie.kytranempowerment.com to platform.kytranempowerment.com.
    Safety net for bookmarks and hardcoded links during domain transition.
    Remove after 30 days (2026-05-15).
    """
    host = request.host.split(":")[0]
    if host == "archie.kytranempowerment.com":
        new_url = request.url.replace("archie.kytranempowerment.com", "platform.kytranempowerment.com", 1)
        return redirect(new_url, code=301)
```

- [ ] **Step 2: Commit**

```bash
git add platform_v2/app.py
git commit -m "feat: 301 redirect archie.* → platform.* (safety net, remove after 2026-05-15)"
```

---

## Summary

| Task | Phase | What | New Files |
|------|-------|------|-----------|
| 1 | A | Directory structure + DB module | 4 |
| 2 | A | Voice + Telegram services | 2 (copied) |
| 3 | A | Chat module | 5 (copied+adapted) |
| 4 | A | Collaboration engine | 2 (copied) |
| 5 | A | Watchdog + Queue + migration | 3 |
| 6 | A | Entrypoint + Dockerfile | 2 |
| 7 | A | docker-compose + Code Health + build | 2 (modified) |
| 8 | B | DNS + NPM + AdGuard + firewall | Infra only |
| 9 | B | 15 code files domain rename | 15+ (modified) |
| 10 | C | Redirect safety net | 1 (modified) |
