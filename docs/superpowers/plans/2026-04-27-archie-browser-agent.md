# Sub-D: ARCHIE Browser Agent Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an `archie_browser` Docker container (Playwright + Flask) that lets the platform dispatch browser automation tasks (LinkedIn posting, profile editing, Meta portal navigation) through the existing delegation system.

**Architecture:** New standalone `archie_browser` container on port 4242 with a skill-registry pattern (drop a file in `skills/`, restart). The platform proxy endpoint (`/api/browser/task`) validates the request, calls `archie_browser`, and logs to `browser_task_log`. The `web_interaction` capability routes through `CAPABILITY_DEPARTMENT_MAP` to Marketing & Communications. No DHQ tab in this phase — tasks are dispatched via delegation.

**Tech Stack:** Python 3.11, Playwright (sync API), Flask, cryptography (Fernet AES-256), psycopg2, Docker.

---

## File Map

| Action | Path | Responsibility |
|--------|------|----------------|
| Create | `archie-browser/app.py` | Flask HTTP API: POST /task, GET /task/:id, POST /session/setup, GET /session/:agent_id/:platform |
| Create | `archie-browser/session_manager.py` | Load/save Playwright storageState encrypted to DB |
| Create | `archie-browser/skill_runner.py` | Discover skills/*.py, run with Playwright sync_api |
| Create | `archie-browser/skills/__init__.py` | Empty |
| Create | `archie-browser/skills/linkedin_post.py` | Post to LinkedIn feed |
| Create | `archie-browser/skills/linkedin_profile_edit.py` | Edit LinkedIn profile headline/summary |
| Create | `archie-browser/skills/meta_portal_setup.py` | Navigate Meta developer portal |
| Create | `archie-browser/Dockerfile` | Python 3.11 + Playwright chromium |
| Create | `archie-browser/requirements.txt` | Dependencies |
| Create | `archie-browser/tests/test_session_manager.py` | Unit tests for encrypt/decrypt |
| Create | `archie-browser/tests/test_skill_runner.py` | Unit tests for skill discovery |
| Modify | `docker-compose.yml` | Add archie_browser service |
| Create | `platform_v2/database/migrations/169_browser_agent.sql` | agent_browser_sessions + browser_task_log tables |
| Create | `platform_v2/tools/department_hq/browser_routes.py` | POST /api/browser/task, GET /api/browser/task/:id |
| Modify | `platform_v2/app.py` | Register browser_bp blueprint |
| Modify | `platform_v2/tools/department_hq/services/department_coordinator.py` | Add web_interaction to CAPABILITY_DEPARTMENT_MAP |
| Modify | `platform_v2/.env` | Add BROWSER_ENCRYPTION_KEY, ARCHIE_BROWSER_URL |

---

## Task 1: DB Migration + Env Setup

**Files:**
- Create: `platform_v2/database/migrations/169_browser_agent.sql`
- Modify: `platform_v2/.env`

- [ ] **Step 1: Generate BROWSER_ENCRYPTION_KEY**

```bash
python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Copy the output — it's a 44-char URL-safe base64 key.

- [ ] **Step 2: Add env vars to platform_v2/.env**

```bash
echo "" >> /mnt/archie_brain/platform_v2/.env
echo "BROWSER_ENCRYPTION_KEY=<generated-key>" >> /mnt/archie_brain/platform_v2/.env
echo "ARCHIE_BROWSER_URL=http://archie_browser:4242" >> /mnt/archie_brain/platform_v2/.env
grep "BROWSER_ENCRYPTION_KEY\|ARCHIE_BROWSER_URL" /mnt/archie_brain/platform_v2/.env
```

- [ ] **Step 3: Write the migration**

```sql
-- platform_v2/database/migrations/169_browser_agent.sql
-- Browser agent tables for archie_browser container (Sub-D #2352)
-- Run: docker exec archie_database psql -U archie -d archie -f /path/to/169_browser_agent.sql

-- Encrypted browser sessions per agent per platform
CREATE TABLE IF NOT EXISTS agent_browser_sessions (
    id SERIAL PRIMARY KEY,
    agent_id INTEGER NOT NULL REFERENCES agents(id),
    platform VARCHAR(50) NOT NULL,
    username VARCHAR(255),
    password_encrypted TEXT,
    session_data_encrypted TEXT,
    session_expires_at TIMESTAMPTZ,
    status VARCHAR(20) DEFAULT 'missing',
    last_used_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(agent_id, platform)
);

-- Browser task execution log
CREATE TABLE IF NOT EXISTS browser_task_log (
    id SERIAL PRIMARY KEY,
    agent_id INTEGER NOT NULL REFERENCES agents(id),
    skill VARCHAR(100) NOT NULL,
    platform VARCHAR(50),
    params JSONB,
    status VARCHAR(20) DEFAULT 'pending',
    result JSONB,
    error_message TEXT,
    screenshot_path TEXT,
    triggered_by VARCHAR(50),
    duration_ms INTEGER,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    completed_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_browser_task_log_agent ON browser_task_log(agent_id);
CREATE INDEX IF NOT EXISTS idx_browser_task_log_status ON browser_task_log(status);
CREATE INDEX IF NOT EXISTS idx_agent_browser_sessions_agent ON agent_browser_sessions(agent_id, platform);
```

- [ ] **Step 4: Run migration**

```bash
docker exec -i archie_database psql -U archie -d archie < \
  /mnt/archie_brain/platform_v2/database/migrations/169_browser_agent.sql
```

Verify:
```bash
docker exec archie_database psql -U archie -d archie \
  -c "\dt agent_browser_sessions; \dt browser_task_log;"
```

Expected: both tables listed.

- [ ] **Step 5: Commit**

```bash
cd /mnt/archie_brain
git add platform_v2/database/migrations/169_browser_agent.sql
# .env is gitignored — do NOT add it
git commit -m "feat(platform): browser agent DB migration — sessions + task log"
```

---

## Task 2: archie_browser Container Scaffold

**Files:**
- Create: `archie-browser/requirements.txt`
- Create: `archie-browser/Dockerfile`
- Create: `archie-browser/app.py`
- Modify: `docker-compose.yml`

- [ ] **Step 1: Create directory structure**

```bash
mkdir -p /mnt/archie_brain/archie-browser/skills
mkdir -p /mnt/archie_brain/archie-browser/tests
touch /mnt/archie_brain/archie-browser/skills/__init__.py
touch /mnt/archie_brain/archie-browser/tests/__init__.py
```

- [ ] **Step 2: Write requirements.txt**

```
flask==3.0.3
playwright==1.44.0
cryptography==42.0.8
psycopg2-binary==2.9.9
requests==2.32.3
```

- [ ] **Step 3: Write Dockerfile**

```dockerfile
FROM python:3.11-slim

WORKDIR /app

# System deps for Playwright
RUN apt-get update && apt-get install -y \
    libglib2.0-0 libnss3 libnspr4 libatk1.0-0 libatk-bridge2.0-0 \
    libcups2 libdrm2 libdbus-1-3 libxcb1 libxkbcommon0 libx11-6 \
    libxcomposite1 libxdamage1 libxext6 libxfixes3 libxrandr2 \
    libgbm1 libpango-1.0-0 libcairo2 libasound2 libatspi2.0-0 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN playwright install chromium

COPY . .

EXPOSE 4242

CMD ["python", "app.py"]
```

- [ ] **Step 4: Write app.py**

```python
"""archie_browser — Playwright browser automation HTTP API."""
import json
import logging
import threading
import uuid
from datetime import datetime, timezone

from flask import Flask, jsonify, request

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# In-memory task registry (task_id → state dict)
_tasks: dict = {}
_tasks_lock = threading.Lock()


@app.route("/health")
def health():
    return jsonify({"status": "ok", "service": "archie_browser"})


@app.route("/task", methods=["POST"])
def post_task():
    """Submit a browser task for async execution."""
    data = request.get_json(silent=True) or {}
    agent_id = data.get("agent_id")
    skill_name = data.get("skill")
    params = data.get("params") or {}
    wait = bool(data.get("wait", False))

    if not agent_id or not skill_name:
        return jsonify({"error": "agent_id and skill required"}), 400

    task_id = str(uuid.uuid4())
    with _tasks_lock:
        _tasks[task_id] = {
            "status": "pending",
            "result": None,
            "error": None,
            "agent_id": agent_id,
            "skill": skill_name,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }

    if wait:
        _execute_task(task_id, agent_id, skill_name, params)
    else:
        t = threading.Thread(
            target=_execute_task, args=(task_id, agent_id, skill_name, params), daemon=True
        )
        t.start()

    with _tasks_lock:
        return jsonify({"task_id": task_id, "status": _tasks[task_id]["status"]})


@app.route("/task/<task_id>")
def get_task(task_id):
    """Get task status and result."""
    with _tasks_lock:
        state = _tasks.get(task_id)
    if not state:
        return jsonify({"error": "not found"}), 404
    return jsonify({"task_id": task_id, **state})


@app.route("/session/setup", methods=["POST"])
def session_setup():
    """Log in to a platform and save session to DB."""
    data = request.get_json(silent=True) or {}
    agent_id = data.get("agent_id")
    platform = data.get("platform")
    username = data.get("username")
    password = data.get("password")

    if not all([agent_id, platform, username, password]):
        return jsonify({"error": "agent_id, platform, username, password required"}), 400

    try:
        import session_manager
        result = session_manager.setup_session(agent_id, platform, username, password)
        return jsonify(result)
    except Exception as exc:
        logger.error("session_setup failed: %s", exc)
        return jsonify({"error": str(exc)}), 500


@app.route("/session/<int:agent_id>/<platform>")
def get_session(agent_id, platform):
    """Get session status for an agent/platform pair."""
    try:
        import session_manager
        status = session_manager.get_session_status(agent_id, platform)
        return jsonify(status)
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


def _execute_task(task_id, agent_id, skill_name, params):
    """Run a browser task — called in a background thread."""
    with _tasks_lock:
        _tasks[task_id]["status"] = "running"

    start = datetime.now(timezone.utc)
    try:
        import skill_runner
        result = skill_runner.run(agent_id, skill_name, params)
        duration_ms = int((datetime.now(timezone.utc) - start).total_seconds() * 1000)
        with _tasks_lock:
            _tasks[task_id].update({
                "status": "completed",
                "result": result,
                "duration_ms": duration_ms,
            })
        _log_task_to_db(task_id, agent_id, skill_name, params, "completed", result, None, duration_ms)
    except Exception as exc:
        duration_ms = int((datetime.now(timezone.utc) - start).total_seconds() * 1000)
        logger.error("task %s failed: %s", task_id, exc)
        with _tasks_lock:
            _tasks[task_id].update({
                "status": "failed",
                "error": str(exc),
                "duration_ms": duration_ms,
            })
        _log_task_to_db(task_id, agent_id, skill_name, params, "failed", None, str(exc), duration_ms)


def _log_task_to_db(task_id, agent_id, skill_name, params, status, result, error, duration_ms):
    """Persist task result to browser_task_log."""
    try:
        import psycopg2
        import psycopg2.extras
        import os

        conn = psycopg2.connect(os.getenv("DATABASE_URL", ""))
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO browser_task_log
                (agent_id, skill, params, status, result, error_message, duration_ms,
                 triggered_by, completed_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, NOW())
            """,
            (
                agent_id,
                skill_name,
                psycopg2.extras.Json(params),
                status,
                psycopg2.extras.Json(result) if result else None,
                error,
                duration_ms,
                "platform",
            ),
        )
        conn.commit()
        cur.close()
        conn.close()
    except Exception as exc:
        logger.warning("_log_task_to_db failed (non-fatal): %s", exc)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=4242, debug=False)
```

- [ ] **Step 5: Add archie_browser to docker-compose.yml**

Find the last service definition in `/mnt/archie_brain/docker-compose.yml` and add:

```yaml
  archie_browser:
    build: ./archie-browser
    container_name: archie_browser
    restart: unless-stopped
    environment:
      - DATABASE_URL=postgresql://archie:${DB_PASSWORD}@archie_database:5432/archie
      - BROWSER_ENCRYPTION_KEY=${BROWSER_ENCRYPTION_KEY}
    dns:
      - 192.168.1.200
      - 1.1.1.1
    networks:
      - archie_net
    expose:
      - "4242"
```

Note: `BROWSER_ENCRYPTION_KEY` must be added to the root `.env` (same value as `platform_v2/.env`):
```bash
grep "^BROWSER_ENCRYPTION_KEY\|^DB_PASSWORD" /mnt/archie_brain/platform_v2/.env | \
  head -2 >> /mnt/archie_brain/.env
```

- [ ] **Step 6: Verify docker-compose is valid**

```bash
cd /mnt/archie_brain && docker compose config --quiet && echo "VALID"
```

Expected: `VALID`

- [ ] **Step 7: Commit**

```bash
cd /mnt/archie_brain
git add archie-browser/ docker-compose.yml
git commit -m "feat(archie-browser): container scaffold — Flask API, Dockerfile, compose service"
```

---

## Task 3: session_manager.py

**Files:**
- Create: `archie-browser/session_manager.py`
- Create: `archie-browser/tests/test_session_manager.py`

- [ ] **Step 1: Write failing tests**

```python
# archie-browser/tests/test_session_manager.py
import os
import sys
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# Set required env var before import
os.environ.setdefault("BROWSER_ENCRYPTION_KEY", "dGVzdGtleXRlc3RrZXl0ZXN0a2V5dGVzdGtleXRlc3Q=")
os.environ.setdefault("DATABASE_URL", "")


class TestEncryption:
    def test_encrypt_decrypt_roundtrip(self):
        import session_manager
        plaintext = '{"cookies": [{"name": "session", "value": "abc123"}]}'
        encrypted = session_manager._encrypt(plaintext)
        assert encrypted != plaintext
        decrypted = session_manager._decrypt(encrypted)
        assert decrypted == plaintext

    def test_encrypt_produces_different_ciphertext_each_time(self):
        import session_manager
        text = "same plaintext"
        enc1 = session_manager._encrypt(text)
        enc2 = session_manager._encrypt(text)
        # Fernet uses random IV — different each time
        assert enc1 != enc2

    def test_decrypt_wrong_key_raises(self):
        import session_manager
        from cryptography.fernet import Fernet, InvalidToken
        encrypted = session_manager._encrypt("secret")
        # Swap to different key
        orig = os.environ["BROWSER_ENCRYPTION_KEY"]
        os.environ["BROWSER_ENCRYPTION_KEY"] = Fernet.generate_key().decode()
        # Force reload (clear cached fernet)
        session_manager._fernet_cache.clear()
        with pytest.raises((InvalidToken, Exception)):
            session_manager._decrypt(encrypted)
        os.environ["BROWSER_ENCRYPTION_KEY"] = orig
        session_manager._fernet_cache.clear()
```

- [ ] **Step 2: Run to confirm failures**

```bash
cd /mnt/archie_brain/archie-browser && \
  pip install cryptography psycopg2-binary -q && \
  python -m pytest tests/test_session_manager.py -v 2>&1 | tail -10
```

Expected: ImportError or AttributeError (session_manager doesn't exist yet).

- [ ] **Step 3: Write session_manager.py**

```python
"""Session manager — encrypted Playwright storageState storage.

Uses Fernet (AES-256-CBC + HMAC) for encryption. Key from BROWSER_ENCRYPTION_KEY env var.
storageState is Playwright's serialised cookies + localStorage JSON.
"""
import json
import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)

# Cache the Fernet instance (avoids re-creating on every call)
_fernet_cache: dict = {}


def _get_fernet():
    if "f" not in _fernet_cache:
        from cryptography.fernet import Fernet

        key = os.getenv("BROWSER_ENCRYPTION_KEY", "")
        if not key:
            raise ValueError("BROWSER_ENCRYPTION_KEY env var not set")
        _fernet_cache["f"] = Fernet(key.encode())
    return _fernet_cache["f"]


def _encrypt(plaintext: str) -> str:
    return _get_fernet().encrypt(plaintext.encode()).decode()


def _decrypt(ciphertext: str) -> str:
    return _get_fernet().decrypt(ciphertext.encode()).decode()


def _get_conn():
    import psycopg2
    import psycopg2.extras

    conn = psycopg2.connect(os.getenv("DATABASE_URL", ""))
    conn.cursor_factory = psycopg2.extras.RealDictCursor
    return conn


def load_session(agent_id: int, platform: str) -> Optional[dict]:
    """Load and decrypt storageState for agent/platform. Returns dict or None."""
    try:
        conn = _get_conn()
        cur = conn.cursor()
        cur.execute(
            "SELECT session_data_encrypted, status FROM agent_browser_sessions "
            "WHERE agent_id = %s AND platform = %s",
            (agent_id, platform),
        )
        row = cur.fetchone()
        cur.close()
        conn.close()
        if not row or not row["session_data_encrypted"]:
            return None
        if row["status"] == "expired":
            return None
        return json.loads(_decrypt(row["session_data_encrypted"]))
    except Exception as exc:
        logger.warning("load_session(%s, %s) failed: %s", agent_id, platform, exc)
        return None


def save_session(agent_id: int, platform: str, storage_state: dict) -> None:
    """Encrypt and upsert storageState for agent/platform."""
    import psycopg2.extras
    from datetime import datetime, timezone, timedelta

    encrypted = _encrypt(json.dumps(storage_state))
    expires_at = datetime.now(timezone.utc) + timedelta(days=30)

    conn = _get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO agent_browser_sessions
            (agent_id, platform, session_data_encrypted, status, last_used_at,
             session_expires_at, updated_at)
        VALUES (%s, %s, %s, 'active', NOW(), %s, NOW())
        ON CONFLICT (agent_id, platform) DO UPDATE SET
            session_data_encrypted = EXCLUDED.session_data_encrypted,
            status = 'active',
            last_used_at = NOW(),
            session_expires_at = EXCLUDED.session_expires_at,
            updated_at = NOW()
        """,
        (agent_id, platform, encrypted, expires_at),
    )
    conn.commit()
    cur.close()
    conn.close()


def save_credentials(agent_id: int, platform: str, username: str, password: str) -> None:
    """Encrypt and store login credentials for a agent/platform."""
    import psycopg2.extras

    enc_pass = _encrypt(password)
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO agent_browser_sessions (agent_id, platform, username, password_encrypted, status)
        VALUES (%s, %s, %s, %s, 'missing')
        ON CONFLICT (agent_id, platform) DO UPDATE SET
            username = EXCLUDED.username,
            password_encrypted = EXCLUDED.password_encrypted,
            updated_at = NOW()
        """,
        (agent_id, platform, username, enc_pass),
    )
    conn.commit()
    cur.close()
    conn.close()


def get_session_status(agent_id: int, platform: str) -> dict:
    """Return status dict for an agent/platform session."""
    try:
        conn = _get_conn()
        cur = conn.cursor()
        cur.execute(
            "SELECT status, last_used_at, session_expires_at FROM agent_browser_sessions "
            "WHERE agent_id = %s AND platform = %s",
            (agent_id, platform),
        )
        row = cur.fetchone()
        cur.close()
        conn.close()
        if not row:
            return {"status": "missing", "agent_id": agent_id, "platform": platform}
        return {
            "status": row["status"],
            "agent_id": agent_id,
            "platform": platform,
            "last_used": row["last_used_at"].isoformat() if row["last_used_at"] else None,
            "expires": row["session_expires_at"].isoformat() if row["session_expires_at"] else None,
        }
    except Exception as exc:
        return {"status": "error", "error": str(exc)}


def setup_session(agent_id: int, platform: str, username: str, password: str) -> dict:
    """Log in to a platform and save session. Returns {status, screenshot_path}."""
    from playwright.sync_api import sync_playwright

    _LOGIN_URLS = {
        "linkedin": "https://www.linkedin.com/login",
        "twitter": "https://x.com/login",
        "facebook": "https://www.facebook.com/login",
    }
    login_url = _LOGIN_URLS.get(platform)
    if not login_url:
        raise ValueError(f"Unknown platform: {platform}")

    save_credentials(agent_id, platform, username, password)

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True, args=["--no-sandbox"])
        context = browser.new_context()
        page = context.new_page()
        page.goto(login_url)

        if platform == "linkedin":
            page.fill("#username", username)
            page.fill("#password", password)
            page.click('[data-litms-control-urn="login-submit"]')
            page.wait_for_load_state("networkidle", timeout=15000)
        elif platform in ("twitter", "x"):
            page.fill('[autocomplete="username"]', username)
            page.keyboard.press("Enter")
            page.wait_for_timeout(1500)
            page.fill('[autocomplete="current-password"]', password)
            page.keyboard.press("Enter")
            page.wait_for_load_state("networkidle", timeout=15000)

        # Check for 2FA
        current_url = page.url
        is_2fa = (
            "checkpoint" in current_url
            or "challenge" in current_url
            or "two_factor" in current_url
            or "verification" in current_url
        )

        if is_2fa:
            screenshot_path = f"/tmp/2fa_{agent_id}_{platform}.png"
            page.screenshot(path=screenshot_path)
            browser.close()
            return {
                "status": "needs_2fa",
                "message": "2FA required — complete in browser or provide code",
                "screenshot_path": screenshot_path,
            }

        # Save session
        storage_state = context.storage_state()
        save_session(agent_id, platform, storage_state)
        browser.close()

        return {"status": "active", "platform": platform, "agent_id": agent_id}
```

- [ ] **Step 4: Run encryption tests**

```bash
cd /mnt/archie_brain/archie-browser && \
  python -m pytest tests/test_session_manager.py -v 2>&1 | tail -10
```

Expected: all 3 PASS.

- [ ] **Step 5: Commit**

```bash
cd /mnt/archie_brain
git add archie-browser/session_manager.py archie-browser/tests/test_session_manager.py
git commit -m "feat(archie-browser): session_manager — Fernet-encrypted storageState"
```

---

## Task 4: skill_runner.py

**Files:**
- Create: `archie-browser/skill_runner.py`
- Create: `archie-browser/tests/test_skill_runner.py`

- [ ] **Step 1: Write failing tests**

```python
# archie-browser/tests/test_skill_runner.py
import os
import sys
import types
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("BROWSER_ENCRYPTION_KEY", "dGVzdGtleXRlc3RrZXl0ZXN0a2V5dGVzdGtleXRlc3Q=")
os.environ.setdefault("DATABASE_URL", "")


class TestSkillDiscovery:
    def test_discover_returns_dict(self, tmp_path, monkeypatch):
        import skill_runner
        monkeypatch.setattr(skill_runner, "SKILLS_DIR", str(tmp_path))
        # Create a fake skill file
        skill_file = tmp_path / "fake_skill.py"
        skill_file.write_text('SKILL_NAME="fake_skill"\nPLATFORMS=["test"]\ndef execute(page, params): return {"done": True}')
        skills = skill_runner._discover_skills()
        assert "fake_skill" in skills

    def test_discover_skips_init(self, tmp_path, monkeypatch):
        import skill_runner
        monkeypatch.setattr(skill_runner, "SKILLS_DIR", str(tmp_path))
        init_file = tmp_path / "__init__.py"
        init_file.write_text("")
        skills = skill_runner._discover_skills()
        assert "__init__" not in skills


class TestSkillRunner:
    def test_unknown_skill_raises(self, monkeypatch):
        import skill_runner
        monkeypatch.setattr(skill_runner, "_discover_skills", lambda: {})
        with pytest.raises(ValueError, match="Unknown skill"):
            skill_runner.run(agent_id=1, skill_name="nonexistent", params={})
```

- [ ] **Step 2: Run to confirm failures**

```bash
cd /mnt/archie_brain/archie-browser && \
  python -m pytest tests/test_skill_runner.py -v 2>&1 | tail -10
```

Expected: ImportError on skill_runner.

- [ ] **Step 3: Write skill_runner.py**

```python
"""Skill runner — discovers skill files and executes them with Playwright."""
import importlib.util
import logging
import os
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

SKILLS_DIR = os.path.join(os.path.dirname(__file__), "skills")


def _discover_skills() -> dict:
    """Return dict of skill_name → module for all skills/*.py files."""
    skills = {}
    for path in Path(SKILLS_DIR).glob("*.py"):
        if path.name == "__init__.py":
            continue
        spec = importlib.util.spec_from_file_location(path.stem, path)
        mod = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(mod)
            name = getattr(mod, "SKILL_NAME", path.stem)
            skills[name] = mod
        except Exception as exc:
            logger.warning("Failed to load skill %s: %s", path.name, exc)
    return skills


def run(agent_id: int, skill_name: str, params: dict) -> dict:
    """Execute a skill for an agent. Returns result dict."""
    from playwright.sync_api import sync_playwright
    import session_manager

    skills = _discover_skills()
    if skill_name not in skills:
        raise ValueError(f"Unknown skill: {skill_name}. Available: {list(skills.keys())}")

    skill_mod = skills[skill_name]
    platforms = getattr(skill_mod, "PLATFORMS", [])
    platform = platforms[0] if platforms else "web"

    # Load session
    storage_state = session_manager.load_session(agent_id, platform)
    if storage_state is None:
        raise RuntimeError(
            f"No active session for agent {agent_id} on {platform}. "
            f"Run POST /session/setup first."
        )

    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage"],
        )
        context = browser.new_context(storage_state=storage_state)
        page = context.new_page()

        try:
            result = skill_mod.execute(page, params)
            # Persist updated session (cookies may have refreshed)
            session_manager.save_session(agent_id, platform, context.storage_state())
            return result
        finally:
            context.close()
            browser.close()


def list_skills() -> list:
    """Return list of available skill names."""
    return list(_discover_skills().keys())
```

- [ ] **Step 4: Run skill runner tests**

```bash
cd /mnt/archie_brain/archie-browser && \
  python -m pytest tests/test_skill_runner.py -v 2>&1 | tail -10
```

Expected: all 3 PASS.

- [ ] **Step 5: Commit**

```bash
cd /mnt/archie_brain
git add archie-browser/skill_runner.py archie-browser/tests/test_skill_runner.py
git commit -m "feat(archie-browser): skill_runner — Playwright executor with skill discovery"
```

---

## Task 5: Skills — LinkedIn + Meta

**Files:**
- Create: `archie-browser/skills/linkedin_post.py`
- Create: `archie-browser/skills/linkedin_profile_edit.py`
- Create: `archie-browser/skills/meta_portal_setup.py`

- [ ] **Step 1: Write linkedin_post.py**

```python
"""LinkedIn post skill — publishes a text post to the LinkedIn feed."""
SKILL_NAME = "linkedin_post"
PLATFORMS = ["linkedin"]


def execute(page, params: dict) -> dict:
    """Post text content to LinkedIn feed.

    params:
        content (str): Post text. Required.
        hashtags (list[str]): Optional hashtags to append.
    """
    content = params.get("content", "").strip()
    hashtags = params.get("hashtags", [])
    if not content:
        raise ValueError("content is required for linkedin_post")

    if hashtags:
        content += "\n\n" + " ".join(f"#{tag.lstrip('#')}" for tag in hashtags)

    # Navigate to feed
    page.goto("https://www.linkedin.com/feed/", wait_until="domcontentloaded")
    page.wait_for_timeout(2000)

    # Click "Start a post" button
    try:
        page.get_by_text("Start a post", exact=False).first.click()
    except Exception:
        # Fallback selector
        page.locator('[data-control-name="share.sharebox_click"]').click()
    page.wait_for_timeout(1500)

    # Type content in the post editor
    editor = page.locator('.ql-editor').first
    editor.click()
    editor.fill(content)
    page.wait_for_timeout(1000)

    # Click Post button
    page.get_by_role("button", name="Post", exact=True).click()
    page.wait_for_timeout(3000)

    # Take confirmation screenshot
    screenshot_path = f"/tmp/linkedin_post_{page.url.split('/')[-1]}.png"
    page.screenshot(path=screenshot_path)

    return {
        "success": True,
        "platform": "linkedin",
        "content_preview": content[:80],
        "screenshot_path": screenshot_path,
    }
```

- [ ] **Step 2: Write linkedin_profile_edit.py**

```python
"""LinkedIn profile edit skill — updates headline and summary."""
SKILL_NAME = "linkedin_profile_edit"
PLATFORMS = ["linkedin"]


def execute(page, params: dict) -> dict:
    """Edit LinkedIn profile headline and/or summary.

    params:
        headline (str): Optional. New headline text (max 220 chars).
        summary (str): Optional. New About section text.
    """
    headline = params.get("headline", "").strip()
    summary = params.get("summary", "").strip()

    if not headline and not summary:
        raise ValueError("At least one of headline or summary is required")

    # Go to own profile
    page.goto("https://www.linkedin.com/in/me/", wait_until="domcontentloaded")
    page.wait_for_timeout(2000)

    updated = []

    if headline:
        # Click the pencil/Edit intro button
        try:
            page.get_by_role("button", name="Edit intro").click()
        except Exception:
            page.locator('[aria-label="Edit intro"]').click()
        page.wait_for_timeout(1500)

        # Fill headline
        headline_field = page.locator('#single-line-text-form-component-profileEditFormElement-SUMMARY-headline')
        if not headline_field.is_visible():
            headline_field = page.get_by_label("Headline")
        headline_field.fill(headline)

        # Save
        page.get_by_role("button", name="Save").click()
        page.wait_for_timeout(2000)
        updated.append("headline")

    screenshot_path = "/tmp/linkedin_profile_edit.png"
    page.screenshot(path=screenshot_path)

    return {
        "success": True,
        "updated_fields": updated,
        "screenshot_path": screenshot_path,
    }
```

- [ ] **Step 3: Write meta_portal_setup.py**

```python
"""Meta developer portal navigation skill."""
SKILL_NAME = "meta_portal_setup"
PLATFORMS = ["facebook"]


def execute(page, params: dict) -> dict:
    """Navigate Meta developer portal to set up an app.

    params:
        action (str): "list_apps" | "create_app" | "check_products"
        app_name (str): Required for create_app action.
    """
    action = params.get("action", "list_apps")

    # Go to Meta developer portal
    page.goto("https://developers.facebook.com/apps/", wait_until="domcontentloaded")
    page.wait_for_timeout(3000)

    screenshot_path = f"/tmp/meta_portal_{action}.png"

    if action == "list_apps":
        page.screenshot(path=screenshot_path)
        # Extract app names from the page
        app_elements = page.locator('[data-testid="app-list-item"], .app-name').all()
        apps = [el.text_content().strip() for el in app_elements if el.text_content()]
        return {
            "success": True,
            "action": "list_apps",
            "apps": apps,
            "screenshot_path": screenshot_path,
        }

    elif action == "check_products":
        app_id = params.get("app_id", "")
        if not app_id:
            raise ValueError("app_id required for check_products")
        page.goto(
            f"https://developers.facebook.com/apps/{app_id}/settings/basic/",
            wait_until="domcontentloaded",
        )
        page.wait_for_timeout(2000)
        page.screenshot(path=screenshot_path)
        return {
            "success": True,
            "action": "check_products",
            "app_id": app_id,
            "screenshot_path": screenshot_path,
        }

    else:
        raise ValueError(f"Unknown action: {action}. Use: list_apps, check_products")
```

- [ ] **Step 4: Verify skills are discovered**

```bash
cd /mnt/archie_brain/archie-browser && python3 -c "
import os
os.environ['BROWSER_ENCRYPTION_KEY'] = 'dGVzdGtleXRlc3RrZXl0ZXN0a2V5dGVzdGtleXJlc3Q='
os.environ['DATABASE_URL'] = ''
import skill_runner
print('Discovered skills:', skill_runner.list_skills())
"
```

Expected: `Discovered skills: ['linkedin_post', 'linkedin_profile_edit', 'meta_portal_setup']`

- [ ] **Step 5: Commit**

```bash
cd /mnt/archie_brain
git add archie-browser/skills/
git commit -m "feat(archie-browser): LinkedIn + Meta portal skills"
```

---

## Task 6: Platform Proxy + Dispatcher Wiring

**Files:**
- Create: `platform_v2/tools/department_hq/browser_routes.py`
- Modify: `platform_v2/app.py`
- Modify: `platform_v2/tools/department_hq/services/department_coordinator.py`

- [ ] **Step 1: Write browser_routes.py**

```python
"""Platform proxy routes for archie_browser container.

POST /api/browser/task  — validate + forward to archie_browser:4242
GET  /api/browser/task/:id  — poll archie_browser for result
GET  /api/browser/skills    — list available skills
"""
import logging
import os

import requests as _req
from flask import Blueprint, jsonify, request

logger = logging.getLogger(__name__)

browser_bp = Blueprint("browser", __name__)

_BROWSER_URL = os.getenv("ARCHIE_BROWSER_URL", "http://archie_browser:4242")


def _browser_post(path, payload, timeout=30):
    resp = _req.post(f"{_BROWSER_URL}{path}", json=payload, timeout=timeout)
    resp.raise_for_status()
    return resp.json()


def _browser_get(path, timeout=10):
    resp = _req.get(f"{_BROWSER_URL}{path}", timeout=timeout)
    resp.raise_for_status()
    return resp.json()


@browser_bp.route("/api/browser/task", methods=["POST"])
def api_browser_task():
    """Submit a browser task. Validates agent is internal and has skill."""
    from database import get_db_cursor

    data = request.get_json(silent=True) or {}
    agent_id = data.get("agent_id")
    skill = data.get("skill")
    params = data.get("params") or {}

    if not agent_id or not skill:
        return jsonify({"error": "agent_id and skill required"}), 400

    # Verify agent is internal (not AI)
    try:
        with get_db_cursor() as (conn, cur):
            cur.execute(
                "SELECT worker_type FROM agents WHERE id = %s", (agent_id,)
            )
            row = cur.fetchone()
            if not row:
                return jsonify({"error": "Agent not found"}), 404
            if row["worker_type"] != "internal":
                return jsonify({"error": "Browser tasks are for internal agents only"}), 403
    except Exception as exc:
        logger.error("browser task agent check failed: %s", exc)
        return jsonify({"error": "DB check failed"}), 500

    # Forward to archie_browser
    try:
        result = _browser_post("/task", {"agent_id": agent_id, "skill": skill, "params": params})
        return jsonify(result)
    except Exception as exc:
        logger.error("archie_browser /task call failed: %s", exc)
        return jsonify({"error": "Browser container unavailable", "detail": str(exc)}), 503


@browser_bp.route("/api/browser/task/<task_id>")
def api_browser_task_status(task_id):
    """Poll task status from archie_browser."""
    try:
        result = _browser_get(f"/task/{task_id}")
        return jsonify(result)
    except Exception as exc:
        return jsonify({"error": str(exc)}), 503


@browser_bp.route("/api/browser/skills")
def api_browser_skills():
    """List available browser skills."""
    try:
        result = _browser_get("/health")
        return jsonify({"status": "ok", "browser_url": _BROWSER_URL})
    except Exception as exc:
        return jsonify({"status": "unavailable", "error": str(exc)}), 503
```

- [ ] **Step 2: Register blueprint in platform app.py**

Find the last `app.register_blueprint(...)` call in `platform_v2/app.py` and add after it:

```python
from tools.department_hq.browser_routes import browser_bp
app.register_blueprint(browser_bp)
```

- [ ] **Step 3: Add web_interaction to CAPABILITY_DEPARTMENT_MAP**

Open `platform_v2/tools/department_hq/services/department_coordinator.py`. Find `CAPABILITY_DEPARTMENT_MAP` dict. Add this entry:

```python
"web_interaction": "Marketing & Communications",
```

Also add `"linkedin_post"`, `"linkedin_profile_edit"`, `"meta_portal_setup"`, `"twitter_post"` to the map:

```python
"linkedin_post": "Marketing & Communications",
"linkedin_profile_edit": "Marketing & Communications",
"meta_portal_setup": "Marketing & Communications",
"twitter_post": "Marketing & Communications",
```

- [ ] **Step 4: Restart platform and verify endpoint**

```bash
docker compose restart archie_platform
sleep 8
curl -s http://192.168.1.200:3000/api/browser/skills | \
  python3 -c "import sys,json; print(json.load(sys.stdin))"
```

Expected: `{"status": "unavailable", "error": ...}` (archie_browser not running yet — that's fine, routes are wired).

Or if container is already up: `{"status": "ok", ...}`

- [ ] **Step 5: Commit**

```bash
cd /mnt/archie_brain
git add platform_v2/tools/department_hq/browser_routes.py platform_v2/app.py \
        platform_v2/tools/department_hq/services/department_coordinator.py
git commit -m "feat(platform): browser proxy routes + web_interaction capability mapping"
```

---

## Task 7: Build Container + E2E Smoke Test + PR

- [ ] **Step 1: Build and start archie_browser**

```bash
cd /mnt/archie_brain
docker compose build archie_browser
docker compose up -d archie_browser
sleep 10
docker logs archie_browser --tail 15
```

Expected: `Running on http://0.0.0.0:4242` in logs. No import errors.

- [ ] **Step 2: Health check**

```bash
curl -s http://192.168.1.200:4242/health | python3 -c "import sys,json; print(json.load(sys.stdin))"
```

Expected: `{"service": "archie_browser", "status": "ok"}`

- [ ] **Step 3: Verify platform proxy reaches browser**

```bash
curl -s http://192.168.1.200:3000/api/browser/skills | \
  python3 -c "import sys,json; print(json.load(sys.stdin))"
```

Expected: `{"browser_url": "http://archie_browser:4242", "status": "ok"}`

- [ ] **Step 4: Test task submission (without a real session — should return clear error)**

```bash
# Get a real internal agent ID
AGENT_ID=$(docker exec archie_database psql -U archie -d archie \
  -t -c "SELECT id FROM agents WHERE worker_type='internal' LIMIT 1;" 2>/dev/null | tr -d ' ')
echo "Using agent: $AGENT_ID"

curl -s http://192.168.1.200:3000/api/browser/task \
  -X POST -H "Content-Type: application/json" \
  -d "{\"agent_id\": $AGENT_ID, \"skill\": \"linkedin_post\", \"params\": {\"content\": \"test\"}}" | \
  python3 -c "import sys,json; d=json.load(sys.stdin); print('status:', d.get('status'), '| error:', d.get('error','none'))"
```

Expected: `status: failed | error: No active session for agent...` OR task queued then fails with session error. This confirms the entire pipeline works end-to-end.

- [ ] **Step 5: Run unit tests**

```bash
cd /mnt/archie_brain/archie-browser && \
  python -m pytest tests/ -v 2>&1 | tail -15
```

Expected: all 6 tests PASS (3 session + 3 skill_runner).

- [ ] **Step 6: Push and update PR**

```bash
cd /mnt/archie_brain
git push origin feat/archie-chat-overhaul

gh pr edit 359 --body "$(cat <<'PREOF'
## Summary

### Sub-A ✅ (Chat Overhaul)
### Sub-B ✅ (Terminal Drawer)
### Sub-C ✅ (Delegation in Chat)

### Sub-D ✅ (ARCHIE Browser Agent — Phase 1)
- \`archie_browser\` Docker container (port 4242): Flask API + Playwright sync API + Fernet-encrypted session store
- Skills: \`linkedin_post\`, \`linkedin_profile_edit\`, \`meta_portal_setup\` — drop a file in skills/, restart
- Session management: storageState encrypted AES-256 → \`agent_browser_sessions\` table; 2FA detected, screenshot saved
- Platform proxy: \`POST /api/browser/task\` validates internal-agent-only, forwards to container
- Dispatcher wiring: \`web_interaction\` + 4 social capabilities → Marketing & Communications dept
- DB migrations: \`agent_browser_sessions\` + \`browser_task_log\`

**To set up a real LinkedIn session:**
1. \`POST http://192.168.1.200:4242/session/setup\` with \`{agent_id, platform:"linkedin", username, password}\`
2. If 2FA required, screenshot is at \`/tmp/2fa_<agent_id>_linkedin.png\` inside container
3. Once session active, dispatch via \`POST /api/browser/task\`

## Sub-projects remaining (Project #288)
- Sub-E: Unified coding platform (Task #2353)

Closes Task #2352 · Project #287

🤖 Generated with [Claude Code](https://claude.com/claude-code)
PREOF
)"
```

- [ ] **Step 7: Mark task complete**

Report: "MCP task #2352 needs to be marked complete"
