# Browser Persona System -- Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development
> (recommended) or superpowers:executing-plans to implement this plan task-by-task.
> Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the `archie_browser` Docker container and wire it into the ARCHIE platform so
human agents can post, engage, and navigate the web using their own encrypted browser sessions.

**Architecture:** Standalone Flask container (`archie_browser:4242`) holds encrypted Playwright
sessions per agent per platform. Skills are auto-discovered Python modules. ARCHIE platform
proxies tasks via a new `browser_routes.py` endpoint. DHQ gains an "Online Presence" tab for
session management and task history.

**Tech Stack:** Python 3.12, Playwright (sync_api), Flask, Fernet (cryptography), psycopg2, Docker

**Spec:** `docs/superpowers/specs/2026-04-27-browser-persona-design.md`
**Project:** #287

---

## Scope

Phase 1 only -- foundation. Phase 2 (campaigns) and Phase 3 (geo-distribution) are separate plans.

Two independent modules -- build and test Module 1 before touching Module 2:

- **Module 1** (Tasks 1-9): `archie_browser` standalone container
- **Module 2** (Tasks 10-15): Platform integration (DB, DHQ tab, routes, dispatch, KBS)

---

## File Map

### Created

```
archie-browser/
  app.py                           Task 1  Flask API -- health, /task, /session endpoints
  session_manager.py               Task 2  Fernet encrypt/decrypt, DB session store/load
  skill_runner.py                  Task 3  Skill discovery, Playwright execution
  skills/__init__.py               Task 3  Empty marker
  skills/linkedin_post.py          Task 4  Post to LinkedIn feed
  skills/linkedin_profile_edit.py  Task 5  Edit headline + About section
  skills/twitter_post.py           Task 6  Post tweet on X
  skills/meta_portal_setup.py      Task 7  Navigate Meta developer portal
  skills/web_form_fill.py          Task 8  Generic form fill
  tests/__init__.py                Task 1
  tests/test_app.py                Task 1  API: health, task submit, session status
  tests/test_session_manager.py    Task 2  Unit: encrypt/decrypt, DB ops
  tests/test_skill_runner.py       Task 3  Unit: discovery, routing
  Dockerfile                       Task 9  Python 3.12 + Playwright chromium
  docker-compose.yml               Task 9  Service def, env vars, volumes
  requirements.txt                 Task 1  flask, playwright, cryptography, psycopg2

database/migrations/browser_persona_tables.sql     Task 10  4 new tables
platform_v2/tools/department_hq/browser_routes.py  Task 11  Proxy endpoint + session mgmt API
platform_v2/tools/department_hq/static/js/browser_presence.js  Task 13  Online Presence tab JS
```

### Modified

```
platform_v2/tools/department_hq/__init__.py              Task 12  Register browser_routes
platform_v2/services/department_coordinator.py           Task 12  Add web_interaction capability
platform_v2/tools/department_hq/templates/department_hq.html  Task 13  Add Online Presence tab
platform_v2/tools/agent_academy/competency_routes.py     Task 14  web_interaction category
kytran-business-suite/plugins/kbs_social_media/publishing_service.py  Task 15  publish_via_browser
docker-compose.yml                                       Task 9   Add archie_browser service
```

---

## Module 1 -- archie_browser Container

---

### Task 1: Flask skeleton + requirements + API tests

**Files:**
- Create: `archie-browser/requirements.txt`
- Create: `archie-browser/app.py`
- Create: `archie-browser/tests/__init__.py`
- Create: `archie-browser/tests/test_app.py`

- [ ] **Step 1: Create directory structure**

```bash
mkdir -p /mnt/archie_brain/archie-browser/tests
mkdir -p /mnt/archie_brain/archie-browser/skills
touch /mnt/archie_brain/archie-browser/tests/__init__.py
```

- [ ] **Step 2: Create requirements.txt**

Create `archie-browser/requirements.txt`:
```
flask==3.0.3
playwright==1.44.0
cryptography==42.0.8
psycopg2-binary==2.9.9
pytest==8.2.0
pytest-flask==1.3.0
```

- [ ] **Step 3: Write the failing API tests**

Create `archie-browser/tests/test_app.py`:
```python
import pytest
from unittest.mock import patch, MagicMock


@pytest.fixture
def client():
    import sys, os
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
    from app import create_app
    app = create_app(testing=True)
    with app.test_client() as c:
        yield c


def test_health(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["status"] == "ok"
    assert "skills" in data


def test_submit_task_missing_fields(client):
    resp = client.post("/task", json={})
    assert resp.status_code == 400
    assert "error" in resp.get_json()


def test_get_task_not_found(client):
    resp = client.get("/task/nonexistent-id")
    assert resp.status_code == 404


def test_get_session_status_missing(client):
    import sys, os
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
    import app as app_module
    app_module.session_manager.get_status.return_value = {
        "status": "missing", "last_used": None
    }
    resp = client.get("/session/1/linkedin")
    assert resp.status_code == 200
    assert resp.get_json()["status"] == "missing"
```

- [ ] **Step 4: Run tests -- verify they fail**

```bash
cd /mnt/archie_brain/archie-browser
python -m pytest tests/test_app.py -v 2>&1 | head -20
```
Expected: `ModuleNotFoundError: No module named 'app'`

- [ ] **Step 5: Create app.py**

Create `archie-browser/app.py`:
```python
import uuid
import threading
from flask import Flask, request, jsonify

_tasks = {}
_tasks_lock = threading.Lock()

session_manager = None
skill_runner = None


def create_app(testing=False):
    app = Flask(__name__)
    app.config["TESTING"] = testing

    global session_manager, skill_runner
    if not testing:
        from session_manager import SessionManager
        from skill_runner import SkillRunner
        session_manager = SessionManager()
        skill_runner = SkillRunner(session_manager)
    else:
        from unittest.mock import MagicMock
        session_manager = MagicMock()
        skill_runner = MagicMock()
        skill_runner.list_skills.return_value = []

    @app.get("/health")
    def health():
        skills = [] if testing else skill_runner.list_skills()
        return jsonify({"status": "ok", "skills": skills})

    @app.post("/task")
    def submit_task():
        body = request.get_json() or {}
        agent_id = body.get("agent_id")
        skill = body.get("skill")
        if not agent_id or not skill:
            return jsonify({"error": "agent_id and skill are required"}), 400

        task_id = str(uuid.uuid4())
        params = body.get("params", {})

        with _tasks_lock:
            _tasks[task_id] = {"status": "pending", "result": None, "error": None}

        def run():
            with _tasks_lock:
                _tasks[task_id]["status"] = "running"
            try:
                result = skill_runner.execute(agent_id, skill, params)
                with _tasks_lock:
                    _tasks[task_id].update({"status": "completed", "result": result})
            except Exception as exc:
                with _tasks_lock:
                    _tasks[task_id].update({"status": "failed", "error": str(exc)})

        if body.get("wait"):
            run()
        else:
            threading.Thread(target=run, daemon=True).start()

        with _tasks_lock:
            current_status = _tasks[task_id]["status"]
        return jsonify({"task_id": task_id, "status": current_status})

    @app.get("/task/<task_id>")
    def get_task(task_id):
        with _tasks_lock:
            task = _tasks.get(task_id)
        if task is None:
            return jsonify({"error": "task not found"}), 404
        return jsonify({"task_id": task_id, **task})

    @app.get("/session/<int:agent_id>/<platform>")
    def get_session(agent_id, platform):
        status = session_manager.get_status(agent_id, platform)
        return jsonify(status)

    @app.post("/session/setup")
    def setup_session():
        body = request.get_json() or {}
        required = ["agent_id", "platform", "username", "password"]
        missing = [f for f in required if not body.get(f)]
        if missing:
            return jsonify({"error": f"Missing: {', '.join(missing)}"}), 400
        result = session_manager.setup(
            body["agent_id"], body["platform"],
            body["username"], body["password"],
        )
        return jsonify(result)

    @app.post("/session/<int:agent_id>/<platform>/refresh")
    def refresh_session(agent_id, platform):
        result = session_manager.refresh(agent_id, platform)
        return jsonify(result)

    return app


if __name__ == "__main__":
    app = create_app()
    app.run(host="0.0.0.0", port=4242)
```

- [ ] **Step 6: Run tests -- verify they pass**

```bash
cd /mnt/archie_brain/archie-browser
python -m pytest tests/test_app.py -v
```
Expected: `4 passed`

- [ ] **Step 7: Commit**

```bash
cd /mnt/archie_brain
git add archie-browser/
git commit -m "feat(browser): archie_browser Flask skeleton + API tests (#287)"
```

---

### Task 2: Session manager -- encrypt/decrypt + DB store/load

**Files:**
- Create: `archie-browser/session_manager.py`
- Create: `archie-browser/tests/test_session_manager.py`

- [ ] **Step 1: Write failing tests**

Create `archie-browser/tests/test_session_manager.py`:
```python
import os
import json
import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime, timezone

os.environ.setdefault("BROWSER_ENCRYPTION_KEY", "")
os.environ.setdefault("DB_HOST", "localhost")
os.environ.setdefault("DB_NAME", "archie")
os.environ.setdefault("DB_USER", "archie")
os.environ.setdefault("DB_PASSWORD", "test")


def _make_manager():
    from session_manager import SessionManager
    sm = SessionManager.__new__(SessionManager)
    from cryptography.fernet import Fernet
    sm._fernet = Fernet(Fernet.generate_key())
    return sm


def test_encrypt_decrypt_roundtrip():
    sm = _make_manager()
    original = json.dumps({"cookies": [{"name": "li_at", "value": "abc123"}]})
    encrypted = sm.encrypt(original)
    assert encrypted != original
    assert sm.decrypt(encrypted) == original


def test_encrypt_returns_string():
    sm = _make_manager()
    assert isinstance(sm.encrypt("hello"), str)


def test_get_status_missing(monkeypatch):
    sm = _make_manager()
    mock_cur = MagicMock()
    mock_cur.__enter__ = lambda s: mock_cur
    mock_cur.__exit__ = MagicMock(return_value=False)
    mock_cur.fetchone.return_value = None
    monkeypatch.setattr(sm, "_cursor", lambda: mock_cur)
    assert sm.get_status(1, "linkedin") == {"status": "missing", "last_used": None}


def test_get_status_active(monkeypatch):
    sm = _make_manager()
    mock_cur = MagicMock()
    mock_cur.__enter__ = lambda s: mock_cur
    mock_cur.__exit__ = MagicMock(return_value=False)
    mock_cur.fetchone.return_value = {
        "status": "active",
        "last_used_at": datetime(2026, 4, 27, tzinfo=timezone.utc),
        "session_expires_at": None,
    }
    monkeypatch.setattr(sm, "_cursor", lambda: mock_cur)
    result = sm.get_status(1, "linkedin")
    assert result["status"] == "active"
```

- [ ] **Step 2: Run -- verify fail**

```bash
cd /mnt/archie_brain/archie-browser
python -m pytest tests/test_session_manager.py -v 2>&1 | head -10
```
Expected: `ModuleNotFoundError: No module named 'session_manager'`

- [ ] **Step 3: Implement session_manager.py**

Create `archie-browser/session_manager.py`:
```python
import os
import json
import logging
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Dict, Optional

import psycopg2
import psycopg2.extras
from cryptography.fernet import Fernet

logger = logging.getLogger(__name__)
_KEY = os.getenv("BROWSER_ENCRYPTION_KEY", "")


class SessionManager:
    def __init__(self):
        if not _KEY:
            raise RuntimeError("BROWSER_ENCRYPTION_KEY env var not set")
        key = _KEY.encode() if isinstance(_KEY, str) else _KEY
        self._fernet = Fernet(key)

    def encrypt(self, plaintext: str) -> str:
        return self._fernet.encrypt(plaintext.encode()).decode()

    def decrypt(self, ciphertext: str) -> str:
        return self._fernet.decrypt(ciphertext.encode()).decode()

    @contextmanager
    def _cursor(self):
        conn = psycopg2.connect(
            host=os.getenv("DB_HOST", "archie_database"),
            port=int(os.getenv("DB_PORT", "5432")),
            dbname=os.getenv("DB_NAME", "archie"),
            user=os.getenv("DB_USER", "archie"),
            password=os.getenv("DB_PASSWORD", ""),
            cursor_factory=psycopg2.extras.RealDictCursor,
        )
        try:
            cur = conn.cursor()
            yield cur
            conn.commit()
        finally:
            conn.close()

    def get_status(self, agent_id: int, platform: str) -> Dict:
        with self._cursor() as cur:
            cur.execute(
                """SELECT status, last_used_at, session_expires_at
                   FROM agent_browser_sessions
                   WHERE agent_id = %s AND platform = %s""",
                (agent_id, platform),
            )
            row = cur.fetchone()
        if not row:
            return {"status": "missing", "last_used": None}
        last = row["last_used_at"]
        exp = row["session_expires_at"]
        return {
            "status": row["status"],
            "last_used": last.isoformat() if last else None,
            "expires_at": exp.isoformat() if exp else None,
        }

    def load_storage_state(self, agent_id: int, platform: str) -> Optional[Dict]:
        with self._cursor() as cur:
            cur.execute(
                """SELECT session_data_encrypted, status
                   FROM agent_browser_sessions
                   WHERE agent_id = %s AND platform = %s""",
                (agent_id, platform),
            )
            row = cur.fetchone()
        if not row or not row["session_data_encrypted"]:
            return None
        return json.loads(self.decrypt(row["session_data_encrypted"]))

    def save_storage_state(self, agent_id: int, platform: str, storage_state: Dict) -> None:
        encrypted = self.encrypt(json.dumps(storage_state))
        now = datetime.now(timezone.utc)
        with self._cursor() as cur:
            cur.execute(
                """INSERT INTO agent_browser_sessions
                       (agent_id, platform, session_data_encrypted, status, last_used_at, updated_at)
                   VALUES (%s, %s, %s, 'active', %s, %s)
                   ON CONFLICT (agent_id, platform) DO UPDATE
                       SET session_data_encrypted = EXCLUDED.session_data_encrypted,
                           status = 'active',
                           last_used_at = EXCLUDED.last_used_at,
                           updated_at = EXCLUDED.updated_at""",
                (agent_id, platform, encrypted, now, now),
            )

    def save_credentials(self, agent_id: int, platform: str,
                         username: str, password: str) -> None:
        enc_pw = self.encrypt(password)
        now = datetime.now(timezone.utc)
        with self._cursor() as cur:
            cur.execute(
                """INSERT INTO agent_browser_sessions
                       (agent_id, platform, username, password_encrypted,
                        status, created_at, updated_at)
                   VALUES (%s, %s, %s, %s, 'missing', %s, %s)
                   ON CONFLICT (agent_id, platform) DO UPDATE
                       SET username = EXCLUDED.username,
                           password_encrypted = EXCLUDED.password_encrypted,
                           updated_at = EXCLUDED.updated_at""",
                (agent_id, platform, username, enc_pw, now, now),
            )

    def get_credentials(self, agent_id: int, platform: str) -> Optional[Dict]:
        with self._cursor() as cur:
            cur.execute(
                """SELECT username, password_encrypted
                   FROM agent_browser_sessions
                   WHERE agent_id = %s AND platform = %s""",
                (agent_id, platform),
            )
            row = cur.fetchone()
        if not row or not row["password_encrypted"]:
            return None
        return {"username": row["username"],
                "password": self.decrypt(row["password_encrypted"])}

    def setup(self, agent_id: int, platform: str,
              username: str, password: str) -> Dict:
        self.save_credentials(agent_id, platform, username, password)
        return {
            "success": True,
            "message": (
                f"Credentials stored for {platform}. "
                f"Call POST /session/{agent_id}/{platform}/refresh to perform first login."
            ),
        }

    def refresh(self, agent_id: int, platform: str) -> Dict:
        creds = self.get_credentials(agent_id, platform)
        if not creds:
            return {"success": False,
                    "error": "No credentials stored. Call POST /session/setup first."}
        return {"success": True, "message": "refresh_pending",
                "agent_id": agent_id, "platform": platform}

    def mark_error(self, agent_id: int, platform: str, error: str) -> None:
        now = datetime.now(timezone.utc)
        with self._cursor() as cur:
            cur.execute(
                """UPDATE agent_browser_sessions
                   SET status = 'error', updated_at = %s
                   WHERE agent_id = %s AND platform = %s""",
                (now, agent_id, platform),
            )
```

- [ ] **Step 4: Run -- verify pass**

```bash
cd /mnt/archie_brain/archie-browser
python -m pytest tests/test_session_manager.py -v
```
Expected: `4 passed`

- [ ] **Step 5: Commit**

```bash
cd /mnt/archie_brain
git add archie-browser/
git commit -m "feat(browser): session manager -- Fernet encrypt + DB store/load (#287)"
```

---

### Task 3: Skill runner -- discovery + Playwright execution

**Files:**
- Create: `archie-browser/skill_runner.py`
- Create: `archie-browser/skills/__init__.py`
- Create: `archie-browser/tests/test_skill_runner.py`

- [ ] **Step 1: Write failing tests**

Create `archie-browser/tests/test_skill_runner.py`:
```python
import os, sys, types
import pytest
from unittest.mock import MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def _fake_skill(name, platforms):
    mod = types.ModuleType(f"skills.{name}")
    mod.SKILL_NAME = name
    mod.PLATFORMS = platforms
    mod.execute = lambda page, params: {"success": True, "result": "ok"}
    return mod


def test_discover_skills(tmp_path):
    skill_code = (
        'SKILL_NAME = "test_skill"\n'
        'PLATFORMS = ["testsite"]\n'
        'def execute(page, params):\n'
        '    return {"success": True, "result": "ok"}\n'
    )
    (tmp_path / "test_skill.py").write_text(skill_code)

    from skill_runner import SkillRunner
    runner = SkillRunner.__new__(SkillRunner)
    runner.session_manager = MagicMock()
    runner._skills = {}
    runner._load_skills_from_dir(str(tmp_path))

    assert "test_skill" in runner._skills
    assert runner._skills["test_skill"]["platforms"] == ["testsite"]


def test_list_skills():
    from skill_runner import SkillRunner
    runner = SkillRunner.__new__(SkillRunner)
    runner.session_manager = MagicMock()
    runner._skills = {
        "linkedin_post": {"platforms": ["linkedin"], "module": MagicMock()},
        "twitter_post": {"platforms": ["twitter"], "module": MagicMock()},
    }
    skills = runner.list_skills()
    assert len(skills) == 2
    assert {s["name"] for s in skills} == {"linkedin_post", "twitter_post"}


def test_execute_unknown_skill():
    from skill_runner import SkillRunner
    runner = SkillRunner.__new__(SkillRunner)
    runner.session_manager = MagicMock()
    runner._skills = {}
    with pytest.raises(ValueError, match="Unknown skill"):
        runner.execute(1, "nonexistent_skill", {})
```

- [ ] **Step 2: Run -- verify fail**

```bash
cd /mnt/archie_brain/archie-browser
python -m pytest tests/test_skill_runner.py -v 2>&1 | head -10
```
Expected: `ModuleNotFoundError: No module named 'skill_runner'`

- [ ] **Step 3: Implement skill_runner.py**

Create `archie-browser/skill_runner.py`:
```python
import importlib.util
import logging
import os
from pathlib import Path
from typing import Dict, List

from playwright.sync_api import sync_playwright

logger = logging.getLogger(__name__)
_SKILLS_DIR = os.path.join(os.path.dirname(__file__), "skills")

_LOGIN_URLS = {
    "linkedin": "https://www.linkedin.com/login",
    "twitter": "https://x.com/login",
    "facebook": "https://www.facebook.com/login",
}


class SkillRunner:
    def __init__(self, session_manager):
        self.session_manager = session_manager
        self._skills: Dict = {}
        self._load_skills_from_dir(_SKILLS_DIR)
        logger.info("SkillRunner loaded %d skills: %s",
                    len(self._skills), list(self._skills))

    def _load_skills_from_dir(self, directory: str) -> None:
        for path in Path(directory).glob("*.py"):
            if path.stem.startswith("_"):
                continue
            spec = importlib.util.spec_from_file_location(path.stem, path)
            mod = importlib.util.module_from_spec(spec)
            try:
                spec.loader.exec_module(mod)
                name = getattr(mod, "SKILL_NAME", None)
                platforms = getattr(mod, "PLATFORMS", [])
                if name and getattr(mod, "execute", None):
                    self._skills[name] = {"platforms": platforms, "module": mod}
            except Exception as exc:
                logger.warning("Failed to load skill %s: %s", path.stem, exc)

    def list_skills(self) -> List[Dict]:
        return [{"name": n, "platforms": m["platforms"]}
                for n, m in self._skills.items()]

    def execute(self, agent_id: int, skill_name: str, params: Dict) -> Dict:
        if skill_name not in self._skills:
            raise ValueError(f"Unknown skill: {skill_name}")
        skill = self._skills[skill_name]
        platform = skill["platforms"][0] if skill["platforms"] else ""
        storage_state = self.session_manager.load_storage_state(agent_id, platform)

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            ctx_kwargs = {"storage_state": storage_state} if storage_state else {}
            context = browser.new_context(**ctx_kwargs)
            page = context.new_page()
            try:
                result = skill["module"].execute(page, params)
                updated = context.storage_state()
                if platform:
                    self.session_manager.save_storage_state(agent_id, platform, updated)
                return result
            except Exception as exc:
                logger.error("Skill %s failed for agent %s: %s",
                             skill_name, agent_id, exc)
                if platform:
                    self.session_manager.mark_error(agent_id, platform, str(exc))
                raise
            finally:
                browser.close()

    def login(self, agent_id: int, platform: str) -> Dict:
        creds = self.session_manager.get_credentials(agent_id, platform)
        if not creds:
            raise ValueError(f"No credentials for agent {agent_id} on {platform}")
        login_url = _LOGIN_URLS.get(platform)
        if not login_url:
            raise ValueError(f"No login URL for platform: {platform}")
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=False)
            context = browser.new_context()
            page = context.new_page()
            page.goto(login_url)
            result = self._do_platform_login(page, platform, creds)
            if result["success"]:
                self.session_manager.save_storage_state(
                    agent_id, platform, context.storage_state()
                )
            browser.close()
        return result

    def _do_platform_login(self, page, platform: str, creds: Dict) -> Dict:
        if platform == "linkedin":
            page.fill("#username", creds["username"])
            page.fill("#password", creds["password"])
            page.click('[data-litms-control-urn="login-submit"]')
            page.wait_for_timeout(3000)
            if "feed" in page.url or "mynetwork" in page.url:
                return {"success": True}
            return {"success": False,
                    "error": "Login failed or 2FA required -- complete manually"}
        if platform == "twitter":
            page.fill('input[autocomplete="username"]', creds["username"])
            page.keyboard.press("Enter")
            page.wait_for_timeout(1000)
            page.fill('input[type="password"]', creds["password"])
            page.keyboard.press("Enter")
            page.wait_for_timeout(3000)
            if "home" in page.url:
                return {"success": True}
            return {"success": False,
                    "error": "Login failed or 2FA required -- complete manually"}
        return {"success": False, "error": f"No login handler for {platform}"}
```

Create `archie-browser/skills/__init__.py` (empty):
```python
```

- [ ] **Step 4: Run -- verify pass**

```bash
cd /mnt/archie_brain/archie-browser
python -m pytest tests/test_skill_runner.py -v
```
Expected: `4 passed`

- [ ] **Step 5: Commit**

```bash
cd /mnt/archie_brain
git add archie-browser/
git commit -m "feat(browser): skill runner -- auto-discovery + Playwright execution (#287)"
```

---

### Task 4: LinkedIn post skill

**Files:**
- Create: `archie-browser/skills/linkedin_post.py`

- [ ] **Step 1: Create skill**

Create `archie-browser/skills/linkedin_post.py`:
```python
"""Post text content to the LinkedIn personal feed."""
import logging
import os
from datetime import datetime

logger = logging.getLogger(__name__)
SKILL_NAME = "linkedin_post"
PLATFORMS = ["linkedin"]
_SCREENSHOTS_DIR = os.getenv("SCREENSHOTS_DIR", "/tmp/browser_screenshots")


def execute(page, params: dict) -> dict:
    """
    params:
        content (str): Post text -- required
        hashtags (list[str]): Optional list of hashtags to append
    returns:
        {success, result, screenshot_path}
    """
    content = params.get("content", "").strip()
    if not content:
        raise ValueError("content is required for linkedin_post")
    hashtags = params.get("hashtags", [])
    if hashtags:
        content += "\n\n" + " ".join(f"#{t.lstrip('#')}" for t in hashtags)

    os.makedirs(_SCREENSHOTS_DIR, exist_ok=True)
    page.goto("https://www.linkedin.com/feed/", wait_until="domcontentloaded")
    page.wait_for_timeout(2000)

    # Open compose dialog
    page.click('[data-control-name="share.sharebox_feed_create_update"]',
               timeout=10000)
    page.wait_for_timeout(1000)

    # Fill content
    editor = page.locator('.ql-editor[data-placeholder]').first
    editor.click()
    editor.fill(content)
    page.wait_for_timeout(500)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    screenshot_path = f"{_SCREENSHOTS_DIR}/linkedin_post_{ts}.png"
    page.screenshot(path=screenshot_path)

    # Submit
    page.click('button[data-control-name="share.post"]', timeout=10000)
    page.wait_for_timeout(3000)

    logger.info("linkedin_post: posted %d chars", len(content))
    return {
        "success": True,
        "result": f"Posted {len(content)} characters to LinkedIn",
        "screenshot_path": screenshot_path,
    }
```

- [ ] **Step 2: Verify discovery**

```bash
cd /mnt/archie_brain/archie-browser
python -c "
from skill_runner import SkillRunner
from unittest.mock import MagicMock
r = SkillRunner(MagicMock())
print([s['name'] for s in r.list_skills()])
"
```
Expected: list including `linkedin_post`

- [ ] **Step 3: Commit**

```bash
cd /mnt/archie_brain
git add archie-browser/skills/linkedin_post.py
git commit -m "feat(browser): linkedin_post skill (#287)"
```

---

### Task 5: LinkedIn profile edit skill

**Files:**
- Create: `archie-browser/skills/linkedin_profile_edit.py`

- [ ] **Step 1: Create skill**

Create `archie-browser/skills/linkedin_profile_edit.py`:
```python
"""Edit LinkedIn profile headline and About/summary section."""
import logging
import os
from datetime import datetime

logger = logging.getLogger(__name__)
SKILL_NAME = "linkedin_profile_edit"
PLATFORMS = ["linkedin"]
_SCREENSHOTS_DIR = os.getenv("SCREENSHOTS_DIR", "/tmp/browser_screenshots")


def execute(page, params: dict) -> dict:
    """
    params:
        headline (str): New headline text (max 220 chars) -- optional
        about (str): New About/summary text -- optional
    At least one field required.
    """
    headline = params.get("headline", "").strip()
    about = params.get("about", "").strip()
    if not headline and not about:
        raise ValueError("At least one of 'headline' or 'about' is required")

    os.makedirs(_SCREENSHOTS_DIR, exist_ok=True)
    page.goto("https://www.linkedin.com/in/me/", wait_until="domcontentloaded")
    page.wait_for_timeout(2000)

    updated_fields = []
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")

    if headline:
        page.locator('button[aria-label="Edit intro"]').first.click()
        page.wait_for_timeout(1000)
        inp = page.locator('input[id*="headline"], input[name="headline"]').first
        inp.clear()
        inp.fill(headline[:220])
        page.locator('button[aria-label="Save"]').first.click()
        page.wait_for_timeout(2000)
        updated_fields.append("headline")

    if about:
        page.locator(
            'section[data-section="summary"] button[aria-label*="Edit"]'
        ).first.click()
        page.wait_for_timeout(1000)
        ta = page.locator(
            'textarea[id*="summary"], div.ql-editor[data-placeholder*="summary"]'
        ).first
        ta.clear()
        ta.fill(about)
        page.locator('button[aria-label="Save"]').first.click()
        page.wait_for_timeout(2000)
        updated_fields.append("about")

    screenshot_path = f"{_SCREENSHOTS_DIR}/linkedin_profile_{ts}.png"
    page.screenshot(path=screenshot_path)

    logger.info("linkedin_profile_edit: updated %s", updated_fields)
    return {
        "success": True,
        "result": f"Updated LinkedIn profile fields: {', '.join(updated_fields)}",
        "updated_fields": updated_fields,
        "screenshot_path": screenshot_path,
    }
```

- [ ] **Step 2: Commit**

```bash
cd /mnt/archie_brain
git add archie-browser/skills/linkedin_profile_edit.py
git commit -m "feat(browser): linkedin_profile_edit skill (#287)"
```

---

### Task 6: Twitter/X post skill

**Files:**
- Create: `archie-browser/skills/twitter_post.py`

- [ ] **Step 1: Create skill**

Create `archie-browser/skills/twitter_post.py`:
```python
"""Post a tweet to X (Twitter) -- bypasses the $100/month API paywall."""
import logging
import os
from datetime import datetime

logger = logging.getLogger(__name__)
SKILL_NAME = "twitter_post"
PLATFORMS = ["twitter"]
_SCREENSHOTS_DIR = os.getenv("SCREENSHOTS_DIR", "/tmp/browser_screenshots")
_MAX_CHARS = 280


def execute(page, params: dict) -> dict:
    """
    params:
        content (str): Tweet text -- required, max 280 chars
    """
    content = params.get("content", "").strip()
    if not content:
        raise ValueError("content is required for twitter_post")
    if len(content) > _MAX_CHARS:
        raise ValueError(
            f"Tweet exceeds {_MAX_CHARS} chars ({len(content)} given)"
        )

    os.makedirs(_SCREENSHOTS_DIR, exist_ok=True)
    page.goto("https://x.com/home", wait_until="domcontentloaded")
    page.wait_for_timeout(2000)

    compose = page.locator('[data-testid="tweetTextarea_0"]').first
    compose.click()
    compose.fill(content)
    page.wait_for_timeout(500)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    screenshot_path = f"{_SCREENSHOTS_DIR}/twitter_post_{ts}.png"
    page.screenshot(path=screenshot_path)

    page.locator('[data-testid="tweetButtonInline"]').first.click()
    page.wait_for_timeout(3000)

    logger.info("twitter_post: posted %d chars", len(content))
    return {
        "success": True,
        "result": f"Posted {len(content)}-character tweet to X",
        "screenshot_path": screenshot_path,
    }
```

- [ ] **Step 2: Commit**

```bash
cd /mnt/archie_brain
git add archie-browser/skills/twitter_post.py
git commit -m "feat(browser): twitter_post skill -- bypass API paywall (#287)"
```

---

### Task 7: Meta portal setup skill

**Files:**
- Create: `archie-browser/skills/meta_portal_setup.py`

- [ ] **Step 1: Create skill**

Create `archie-browser/skills/meta_portal_setup.py`:
```python
"""Navigate Meta developer portal -- create app, check status."""
import logging
import os
from datetime import datetime

logger = logging.getLogger(__name__)
SKILL_NAME = "meta_portal_setup"
PLATFORMS = ["facebook"]
_SCREENSHOTS_DIR = os.getenv("SCREENSHOTS_DIR", "/tmp/browser_screenshots")


def execute(page, params: dict) -> dict:
    """
    params:
        action (str): "create_app" | "check_status" | "screenshot"
                      default: "screenshot"
        app_name (str): Required when action="create_app"
        app_type (str): "consumer" | "business" -- default: "business"
    """
    action = params.get("action", "screenshot")
    os.makedirs(_SCREENSHOTS_DIR, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    screenshot_path = f"{_SCREENSHOTS_DIR}/meta_portal_{ts}.png"

    page.goto("https://developers.facebook.com/apps/",
              wait_until="domcontentloaded")
    page.wait_for_timeout(3000)
    page.screenshot(path=screenshot_path)

    if action == "screenshot":
        return {"success": True,
                "result": "Screenshot of Meta developer portal captured",
                "screenshot_path": screenshot_path}

    if action == "check_status":
        apps = page.locator('.app-item, ._5dz4').all_text_contents()
        return {"success": True,
                "result": f"Found {len(apps)} app(s)",
                "apps": apps,
                "screenshot_path": screenshot_path}

    if action == "create_app":
        app_name = params.get("app_name", "").strip()
        if not app_name:
            raise ValueError("app_name is required for action=create_app")
        app_type = params.get("app_type", "business")

        page.locator('a[href*="create_app"], button:text("Create App")').first.click()
        page.wait_for_timeout(2000)

        type_btn = page.locator(
            f'[data-value="{app_type}"], label:has-text("{app_type.title()}")'
        )
        if type_btn.count() > 0:
            type_btn.first.click()
            page.wait_for_timeout(500)

        page.locator(
            'input[name="app_display_name"], input[placeholder*="app name" i]'
        ).first.fill(app_name)
        page.wait_for_timeout(500)

        page.locator(
            'button:text("Create App"), button[type="submit"]'
        ).first.click()
        page.wait_for_timeout(4000)
        page.screenshot(path=screenshot_path)

        logger.info("meta_portal_setup: created app '%s'", app_name)
        return {"success": True,
                "result": f"Created Meta app: {app_name}",
                "screenshot_path": screenshot_path}

    return {"success": False, "error": f"Unknown action: {action}"}
```

- [ ] **Step 2: Commit**

```bash
cd /mnt/archie_brain
git add archie-browser/skills/meta_portal_setup.py
git commit -m "feat(browser): meta_portal_setup skill (#287)"
```

---

### Task 8: Generic web_form_fill skill

**Files:**
- Create: `archie-browser/skills/web_form_fill.py`

- [ ] **Step 1: Create skill**

Create `archie-browser/skills/web_form_fill.py`:
```python
"""Generic form fill -- navigate to URL and fill named fields."""
import logging
import os
from datetime import datetime

logger = logging.getLogger(__name__)
SKILL_NAME = "web_form_fill"
PLATFORMS = []  # works on any site


def execute(page, params: dict) -> dict:
    """
    params:
        url (str): Page URL -- required
        fields (list[dict]): [{selector, value, action}] -- required
            action: "fill" | "click" | "select" -- default: "fill"
        submit_selector (str): Submit button selector -- optional
        wait_ms (int): Wait after submit -- default 2000
    """
    url = params.get("url", "").strip()
    fields = params.get("fields", [])
    if not url:
        raise ValueError("url is required for web_form_fill")
    if not fields:
        raise ValueError("fields list is required for web_form_fill")

    screenshots_dir = os.getenv("SCREENSHOTS_DIR", "/tmp/browser_screenshots")
    os.makedirs(screenshots_dir, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")

    page.goto(url, wait_until="domcontentloaded")
    page.wait_for_timeout(1500)

    filled_count = 0
    for field in fields:
        selector = field.get("selector", "")
        value = field.get("value", "")
        action = field.get("action", "fill")
        if not selector:
            continue
        try:
            el = page.locator(selector).first
            if action == "fill":
                el.fill(value)
            elif action == "click":
                el.click()
            elif action == "select":
                el.select_option(value)
            filled_count += 1
            page.wait_for_timeout(200)
        except Exception as exc:
            logger.warning("web_form_fill: field %s failed: %s", selector, exc)

    submit_selector = params.get("submit_selector", "")
    if submit_selector:
        page.locator(submit_selector).first.click()
        page.wait_for_timeout(params.get("wait_ms", 2000))

    screenshot_path = f"{screenshots_dir}/form_fill_{ts}.png"
    page.screenshot(path=screenshot_path)

    logger.info("web_form_fill: filled %d/%d fields on %s",
                filled_count, len(fields), url)
    return {
        "success": True,
        "result": f"Filled {filled_count}/{len(fields)} fields on {url}",
        "filled_count": filled_count,
        "screenshot_path": screenshot_path,
    }
```

- [ ] **Step 2: Verify all 5 skills discovered**

```bash
cd /mnt/archie_brain/archie-browser
python -c "
from skill_runner import SkillRunner
from unittest.mock import MagicMock
r = SkillRunner(MagicMock())
for s in r.list_skills(): print(s['name'], '->', s['platforms'])
"
```
Expected: 5 lines.

- [ ] **Step 3: Commit**

```bash
cd /mnt/archie_brain
git add archie-browser/skills/web_form_fill.py
git commit -m "feat(browser): web_form_fill generic skill (#287)"
```

---

### Task 9: Docker setup

**Files:**
- Create: `archie-browser/Dockerfile`
- Create: `archie-browser/docker-compose.yml`
- Modify: `/mnt/archie_brain/docker-compose.yml`

- [ ] **Step 1: Create Dockerfile**

Create `archie-browser/Dockerfile`:
```dockerfile
FROM python:3.12-slim

RUN apt-get update && apt-get install -y \
    libglib2.0-0 libnss3 libnspr4 libdbus-1-3 libatk1.0-0 \
    libatk-bridge2.0-0 libcups2 libdrm2 libxkbcommon0 libxcomposite1 \
    libxdamage1 libxfixes3 libxrandr2 libgbm1 libasound2 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN playwright install chromium --with-deps

COPY . .
RUN mkdir -p /app/screenshots

ENV PYTHONUNBUFFERED=1
EXPOSE 4242
CMD ["python", "app.py"]
```

- [ ] **Step 2: Create standalone docker-compose.yml**

Create `archie-browser/docker-compose.yml`:
```yaml
services:
  archie_browser:
    build: .
    container_name: archie_browser
    restart: unless-stopped
    ports:
      - "4242:4242"
    environment:
      DB_HOST: ${DB_HOST:-archie_database}
      DB_PORT: ${DB_PORT:-5432}
      DB_NAME: ${DB_NAME:-archie}
      DB_USER: ${DB_USER:-archie}
      DB_PASSWORD: ${DB_PASSWORD}
      BROWSER_ENCRYPTION_KEY: ${BROWSER_ENCRYPTION_KEY}
      SCREENSHOTS_DIR: /app/screenshots
    volumes:
      - browser_screenshots:/app/screenshots
    dns:
      - 192.168.1.200
      - 1.1.1.1
    networks:
      - archie_network

volumes:
  browser_screenshots:

networks:
  archie_network:
    external: true
```

- [ ] **Step 3: Add service to root docker-compose.yml**

In `/mnt/archie_brain/docker-compose.yml`, add before the final `networks:` block:
```yaml
  archie_browser:
    build: ./archie-browser
    container_name: archie_browser
    restart: unless-stopped
    ports:
      - "4242:4242"
    environment:
      DB_HOST: archie_database
      DB_PORT: 5432
      DB_NAME: ${DB_NAME:-archie}
      DB_USER: ${DB_USER:-archie}
      DB_PASSWORD: ${DB_PASSWORD}
      BROWSER_ENCRYPTION_KEY: ${BROWSER_ENCRYPTION_KEY}
      SCREENSHOTS_DIR: /app/screenshots
    volumes:
      - browser_screenshots:/app/screenshots
    depends_on:
      - archie_database
    dns:
      - 192.168.1.200
      - 1.1.1.1
    networks:
      - archie_network
```

Add to the `volumes:` section:
```yaml
  browser_screenshots:
```

- [ ] **Step 4: Generate and add BROWSER_ENCRYPTION_KEY**

```bash
python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Add the printed value to both `/mnt/archie_brain/.env` and
`/mnt/archie_brain/platform_v2/.env`:
```
BROWSER_ENCRYPTION_KEY=<paste-generated-key>
```

- [ ] **Step 5: Build and verify**

```bash
cd /mnt/archie_brain
docker compose build archie_browser
docker compose up -d archie_browser
sleep 8
curl http://192.168.1.200:4242/health
```
Expected: `{"skills": [...5 skills...], "status": "ok"}`

- [ ] **Step 6: Commit**

```bash
cd /mnt/archie_brain
git add archie-browser/Dockerfile archie-browser/docker-compose.yml docker-compose.yml
git commit -m "feat(browser): Docker setup -- archie_browser container on :4242 (#287)"
```

---

## Module 2 -- Platform Integration

---

### Task 10: Database migration -- 4 new tables

**Files:**
- Create: `database/migrations/browser_persona_tables.sql`

- [ ] **Step 1: Write the migration**

Create `database/migrations/browser_persona_tables.sql`:
```sql
-- Browser Persona System -- Phase 1
-- Project #287

BEGIN;

-- browser_campaigns created first (referenced by FK in agent_online_persona)
CREATE TABLE IF NOT EXISTS browser_campaigns (
    id                      SERIAL PRIMARY KEY,
    name                    VARCHAR(255) NOT NULL,
    description             TEXT,
    status                  VARCHAR(20) NOT NULL DEFAULT 'draft'
                                CHECK (status IN ('draft','active','paused','completed')),
    campaign_type           VARCHAR(50),
    target_platforms        JSONB NOT NULL DEFAULT '[]',
    schedule                JSONB,
    content_brief           TEXT,
    participating_agent_ids JSONB NOT NULL DEFAULT '[]',
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS agent_browser_sessions (
    id                      SERIAL PRIMARY KEY,
    agent_id                INTEGER NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
    platform                VARCHAR(50) NOT NULL,
    username                VARCHAR(255),
    password_encrypted      TEXT,
    session_data_encrypted  TEXT,
    session_expires_at      TIMESTAMPTZ,
    status                  VARCHAR(20) NOT NULL DEFAULT 'missing'
                                CHECK (status IN ('missing','active','expired','error')),
    last_used_at            TIMESTAMPTZ,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (agent_id, platform)
);

CREATE TABLE IF NOT EXISTS agent_online_persona (
    id                  SERIAL PRIMARY KEY,
    agent_id            INTEGER NOT NULL REFERENCES agents(id)
                            ON DELETE CASCADE UNIQUE,
    posting_frequency   VARCHAR(20) NOT NULL DEFAULT 'manual'
                            CHECK (posting_frequency IN ('daily','weekly','manual')),
    preferred_tone      VARCHAR(20) NOT NULL DEFAULT 'professional'
                            CHECK (preferred_tone IN ('professional','casual','bold')),
    active_platforms    JSONB NOT NULL DEFAULT '[]',
    topic_interests     JSONB NOT NULL DEFAULT '[]',
    engagement_rules    JSONB NOT NULL DEFAULT '{}',
    campaign_id         INTEGER REFERENCES browser_campaigns(id) ON DELETE SET NULL,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS browser_task_log (
    id              SERIAL PRIMARY KEY,
    agent_id        INTEGER NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
    skill           VARCHAR(100) NOT NULL,
    platform        VARCHAR(50),
    params          JSONB,
    status          VARCHAR(20) NOT NULL DEFAULT 'pending'
                        CHECK (status IN ('pending','running','completed','failed')),
    result          JSONB,
    error_message   TEXT,
    screenshot_path TEXT,
    triggered_by    VARCHAR(50)
                        CHECK (triggered_by IN ('schedule','telegram','event','cli','api')),
    duration_ms     INTEGER,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at    TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_browser_task_log_agent
    ON browser_task_log(agent_id);
CREATE INDEX IF NOT EXISTS idx_browser_task_log_status
    ON browser_task_log(status);
CREATE INDEX IF NOT EXISTS idx_browser_sessions_agent
    ON agent_browser_sessions(agent_id);

COMMIT;
```

- [ ] **Step 2: Run migration**

```bash
docker exec archie_database psql -U archie -d archie \
    -f /mnt/archie_brain/database/migrations/browser_persona_tables.sql
```
Expected: `CREATE TABLE` x4, `CREATE INDEX` x3, `COMMIT`

- [ ] **Step 3: Verify tables**

```bash
docker exec archie_database psql -U archie -d archie -c \
    "SELECT tablename FROM pg_tables WHERE tablename LIKE '%browser%' OR tablename LIKE '%agent_online%';"
```
Expected: 4 rows.

- [ ] **Step 4: Commit**

```bash
cd /mnt/archie_brain
git add database/migrations/browser_persona_tables.sql
git commit -m "feat(db): browser persona tables -- sessions, persona, task_log, campaigns (#287)"
```

---

### Task 11: Platform proxy endpoint -- browser_routes.py

**Files:**
- Create: `platform_v2/tools/department_hq/browser_routes.py`

- [ ] **Step 1: Create browser_routes.py**

Create `platform_v2/tools/department_hq/browser_routes.py`:
```python
"""Browser persona API -- proxy to archie_browser container."""
import logging
import os
from datetime import datetime, timezone

import requests
from flask import jsonify, request

from database import get_db_cursor

logger = logging.getLogger(__name__)

_BROWSER_URLS = {
    "hub":        os.getenv("ARCHIE_BROWSER_URL", "http://archie_browser:4242"),
    "outpost-us": os.getenv("ARCHIE_BROWSER_URL_OUTPOST_US",
                            "http://76.13.107.109:4242"),
}


def _browser_url(agent_id: int) -> str:
    with get_db_cursor() as (conn, cur):
        cur.execute(
            "SELECT preferred_node FROM agent_online_persona WHERE agent_id = %s",
            (agent_id,),
        )
        row = cur.fetchone()
    node = row["preferred_node"] if row and row.get("preferred_node") else "hub"
    return _BROWSER_URLS.get(node, _BROWSER_URLS["hub"])


def _log_task(cur, agent_id, skill, platform, params, triggered_by) -> int:
    cur.execute(
        """INSERT INTO browser_task_log
               (agent_id, skill, platform, params, status, triggered_by, created_at)
           VALUES (%s,%s,%s,%s,'pending',%s,NOW()) RETURNING id""",
        (agent_id, skill, platform, params, triggered_by),
    )
    return cur.fetchone()["id"]


def register_browser_routes(bp, admin_required):

    @bp.post("/api/browser/task")
    @admin_required
    def submit_browser_task():
        body = request.get_json() or {}
        agent_id = body.get("agent_id")
        skill = body.get("skill")
        if not agent_id or not skill:
            return jsonify({"error": "agent_id and skill required"}), 400

        with get_db_cursor() as (conn, cur):
            cur.execute(
                "SELECT worker_type FROM agents WHERE id=%s AND status='active'",
                (agent_id,),
            )
            agent = cur.fetchone()
        if not agent:
            return jsonify({"error": f"Agent {agent_id} not found"}), 404
        if agent["worker_type"] != "internal":
            return jsonify({
                "error": "Browser skills are for human agents (worker_type='internal') only"
            }), 403

        params = body.get("params", {})
        triggered_by = body.get("triggered_by", "api")
        platform = params.get("platform", "")

        with get_db_cursor(commit=True) as (conn, cur):
            log_id = _log_task(cur, agent_id, skill, platform, params, triggered_by)

        url = _browser_url(agent_id)
        try:
            resp = requests.post(
                f"{url}/task",
                json={"agent_id": agent_id, "skill": skill, "params": params,
                      "triggered_by": triggered_by},
                timeout=5,
            )
            resp.raise_for_status()
            task_id = resp.json().get("task_id", "")
            with get_db_cursor(commit=True) as (conn, cur):
                cur.execute(
                    "UPDATE browser_task_log SET status='running' WHERE id=%s",
                    (log_id,),
                )
            return jsonify({"task_id": task_id, "log_id": log_id, "status": "running"})
        except Exception as exc:
            with get_db_cursor(commit=True) as (conn, cur):
                cur.execute(
                    "UPDATE browser_task_log SET status='failed', error_message=%s WHERE id=%s",
                    (str(exc), log_id),
                )
            logger.error("browser task submit failed: %s", exc)
            return jsonify({"error": f"Container unreachable: {exc}"}), 502

    @bp.get("/api/browser/task/<task_id>")
    @admin_required
    def get_browser_task(task_id):
        url = _BROWSER_URLS["hub"]
        try:
            resp = requests.get(f"{url}/task/{task_id}", timeout=5)
            if resp.status_code == 404:
                return jsonify({"error": "Task not found"}), 404
            return jsonify(resp.json())
        except Exception as exc:
            return jsonify({"error": str(exc)}), 502

    @bp.get("/api/browser/sessions/<int:agent_id>")
    @admin_required
    def get_agent_sessions(agent_id):
        with get_db_cursor() as (conn, cur):
            cur.execute(
                """SELECT platform, status, username, last_used_at, session_expires_at
                   FROM agent_browser_sessions WHERE agent_id=%s ORDER BY platform""",
                (agent_id,),
            )
            rows = [dict(r) for r in cur.fetchall()]
        for r in rows:
            for k in ("last_used_at", "session_expires_at"):
                if r[k]:
                    r[k] = r[k].isoformat()
        return jsonify({"agent_id": agent_id, "sessions": rows})

    @bp.post("/api/browser/sessions/<int:agent_id>/setup")
    @admin_required
    def setup_agent_session(agent_id):
        body = request.get_json() or {}
        missing = [f for f in ("platform", "username", "password") if not body.get(f)]
        if missing:
            return jsonify({"error": f"Missing: {', '.join(missing)}"}), 400
        url = _browser_url(agent_id)
        try:
            resp = requests.post(
                f"{url}/session/setup",
                json={"agent_id": agent_id, **body},
                timeout=10,
            )
            resp.raise_for_status()
            return jsonify(resp.json())
        except Exception as exc:
            return jsonify({"error": str(exc)}), 502

    @bp.get("/api/browser/skills")
    @admin_required
    def list_browser_skills():
        url = _BROWSER_URLS["hub"]
        try:
            resp = requests.get(f"{url}/health", timeout=5)
            resp.raise_for_status()
            return jsonify({"skills": resp.json().get("skills", [])})
        except Exception as exc:
            return jsonify({"error": str(exc), "skills": []}), 502

    @bp.get("/api/browser/task-log")
    @admin_required
    def get_task_log():
        agent_id = request.args.get("agent_id", type=int)
        limit = min(int(request.args.get("limit", 50)), 200)
        with get_db_cursor() as (conn, cur):
            if agent_id:
                cur.execute(
                    """SELECT btl.*, a.display_name AS agent_name
                       FROM browser_task_log btl
                       JOIN agents a ON a.id = btl.agent_id
                       WHERE btl.agent_id=%s
                       ORDER BY btl.created_at DESC LIMIT %s""",
                    (agent_id, limit),
                )
            else:
                cur.execute(
                    """SELECT btl.*, a.display_name AS agent_name
                       FROM browser_task_log btl
                       JOIN agents a ON a.id = btl.agent_id
                       ORDER BY btl.created_at DESC LIMIT %s""",
                    (limit,),
                )
            rows = [dict(r) for r in cur.fetchall()]
        for r in rows:
            for k in ("created_at", "completed_at"):
                if r[k]:
                    r[k] = r[k].isoformat()
        return jsonify({"tasks": rows, "total": len(rows)})
```

- [ ] **Step 2: Commit**

```bash
cd /mnt/archie_brain
git add platform_v2/tools/department_hq/browser_routes.py
git commit -m "feat(dhq): browser_routes -- proxy + session + task-log API (#287)"
```

---

### Task 12: Register routes + wire dispatch capability

**Files:**
- Modify: `platform_v2/tools/department_hq/__init__.py`
- Modify: `platform_v2/services/department_coordinator.py`

- [ ] **Step 1: Register in DHQ __init__.py**

In `platform_v2/tools/department_hq/__init__.py`, add after the coms_routes import line:

```python
from .browser_routes import register_browser_routes  # noqa: E402
```

Add the call after `register_coms_routes(...)`:

```python
register_browser_routes(department_hq_bp, admin_required)
```

- [ ] **Step 2: Add web_interaction to CAPABILITY_DEPARTMENT_MAP**

In `platform_v2/services/department_coordinator.py` around line 94, add to the
Marketing & Communications block:

```python
    "web_interaction": "Marketing & Communications",  # browser persona tasks
```

- [ ] **Step 3: Restart and verify**

```bash
docker compose restart archie_platform
sleep 6
docker logs archie_platform 2>&1 | grep -i "error" | tail -10
curl -s -o /dev/null -w "%{http_code}" http://192.168.1.200:3000/api/browser/skills
```
Expected log: no errors. curl: `200` or `401` (not 404/500).

- [ ] **Step 4: Commit**

```bash
cd /mnt/archie_brain
git add platform_v2/tools/department_hq/__init__.py \
        platform_v2/services/department_coordinator.py
git commit -m "feat(dhq): register browser_routes + web_interaction capability (#287)"
```

---

### Task 13: DHQ Online Presence tab

**Files:**
- Modify: `platform_v2/tools/department_hq/templates/department_hq.html`
- Create: `platform_v2/tools/department_hq/static/js/browser_presence.js`

- [ ] **Step 1: Add tab nav item in department_hq.html**

Find the COMs tab nav item (search for `coms` in the nav section). Add after it:

```html
<li class="dhq-nav-item" data-tab="online-presence">
    <span class="dhq-nav-icon">&#127760;</span>
    <span class="dhq-nav-label">Online Presence</span>
</li>
```

- [ ] **Step 2: Add tab panel in department_hq.html**

Find the COMs tab panel closing tag. Add the Online Presence panel after it:

```html
<!-- Online Presence Tab -->
<div id="tab-online-presence" class="dhq-tab-panel" style="display:none">
    <div class="dhq-panel-header">
        <h2>Online Presence</h2>
        <p class="dhq-panel-subtitle">
            Browser sessions, personas, and task history for human agents
        </p>
    </div>

    <div class="dhq-section" style="margin-bottom:16px">
        <label class="dhq-label">Human Agent</label>
        <select id="bp-agent-select" class="dhq-select"
                onchange="bpLoadAgent(this.value)">
            <option value="">-- Select agent --</option>
        </select>
    </div>

    <div class="dhq-section" id="bp-sessions-panel" style="display:none">
        <h3 class="dhq-section-title">Browser Sessions</h3>
        <div id="bp-sessions-list"></div>
        <div style="margin-top:12px">
            <button class="dhq-btn dhq-btn-primary"
                    onclick="bpOpenSetupModal()">+ Add Session</button>
        </div>
    </div>

    <div class="dhq-section" id="bp-task-log-panel" style="display:none">
        <h3 class="dhq-section-title">Recent Browser Tasks</h3>
        <div id="bp-task-log"></div>
    </div>

    <div class="dhq-section" id="bp-quick-task-panel" style="display:none">
        <h3 class="dhq-section-title">Run Task</h3>
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;max-width:600px">
            <div>
                <label class="dhq-label">Skill</label>
                <select id="bp-skill-select" class="dhq-select"></select>
            </div>
            <div>
                <label class="dhq-label">Content (for post skills)</label>
                <input id="bp-task-content" class="dhq-input"
                       placeholder="Post content...">
            </div>
        </div>
        <button class="dhq-btn dhq-btn-success" style="margin-top:12px"
                onclick="bpRunTask()">Run Task</button>
        <div id="bp-task-result" style="margin-top:12px"></div>
    </div>
</div>

<!-- Session setup modal -->
<div id="bp-setup-modal" class="bm-overlay" style="display:none"
     onclick="if(event.target===this)this.style.display='none'">
    <div class="bm-shell">
        <div class="bm-frame"></div>
        <div class="bm-content">
            <div class="bm-header">
                <h3>Add Browser Session</h3>
                <button onclick="document.getElementById('bp-setup-modal')
                    .style.display='none'">X</button>
            </div>
            <div class="bm-body" style="padding:20px">
                <div style="margin-bottom:12px">
                    <label class="dhq-label">Platform</label>
                    <select id="bp-setup-platform" class="dhq-select">
                        <option value="linkedin">LinkedIn</option>
                        <option value="twitter">Twitter / X</option>
                        <option value="facebook">Facebook / Meta</option>
                    </select>
                </div>
                <div style="margin-bottom:12px">
                    <label class="dhq-label">Username / Email</label>
                    <input id="bp-setup-username" class="dhq-input" type="text">
                </div>
                <div style="margin-bottom:12px">
                    <label class="dhq-label">Password</label>
                    <input id="bp-setup-password" class="dhq-input"
                           type="password">
                </div>
            </div>
            <div class="bm-footer">
                <button class="dhq-btn dhq-btn-primary"
                        onclick="bpSaveSession()">Save Credentials</button>
            </div>
        </div>
    </div>
</div>
```

- [ ] **Step 3: Create browser_presence.js**

Create `platform_v2/tools/department_hq/static/js/browser_presence.js`:
```javascript
/* Online Presence tab -- browser session + task management */
/* All dynamic content uses textContent or escapeHtml() -- no raw innerHTML */

var _bpAgentId = null;

function escapeHtml(str) {
    return String(str)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

async function bpInit() {
    try {
        var resp = await fetch('/tools/department-hq/api/agents?worker_type=internal');
        var data = await resp.json();
        var sel = document.getElementById('bp-agent-select');
        (data.agents || []).forEach(function(a) {
            var opt = document.createElement('option');
            opt.value = a.id;
            opt.textContent = a.display_name || a.name;
            sel.appendChild(opt);
        });
    } catch(e) { console.error('bpInit agents:', e); }

    try {
        var resp2 = await fetch('/tools/department-hq/api/browser/skills');
        var data2 = await resp2.json();
        var sel2 = document.getElementById('bp-skill-select');
        (data2.skills || []).forEach(function(s) {
            var opt = document.createElement('option');
            opt.value = s.name;
            opt.textContent = s.name +
                (s.platforms.length ? ' (' + s.platforms.join(', ') + ')' : '');
            sel2.appendChild(opt);
        });
    } catch(e) { console.error('bpInit skills:', e); }
}

async function bpLoadAgent(agentId) {
    _bpAgentId = agentId;
    if (!agentId) return;
    document.getElementById('bp-sessions-panel').style.display = 'block';
    document.getElementById('bp-task-log-panel').style.display = 'block';
    document.getElementById('bp-quick-task-panel').style.display = 'block';
    bpRefreshSessions();
    bpRefreshTaskLog();
}

async function bpRefreshSessions() {
    if (!_bpAgentId) return;
    var resp = await fetch(
        '/tools/department-hq/api/browser/sessions/' + _bpAgentId
    );
    var data = await resp.json();
    var el = document.getElementById('bp-sessions-list');
    el.textContent = '';

    var platforms = ['linkedin', 'twitter', 'facebook'];
    var sessionMap = {};
    (data.sessions || []).forEach(function(s) { sessionMap[s.platform] = s; });

    platforms.forEach(function(p) {
        var s = sessionMap[p];
        var status = s ? s.status : 'missing';
        var colors = {active: '#22c55e', error: '#ef4444', missing: '#6b7280',
                      expired: '#f59e0b'};
        var color = colors[status] || '#6b7280';
        var lastUsed = (s && s.last_used)
            ? new Date(s.last_used).toLocaleString() : 'Never';

        var row = document.createElement('div');
        row.style.cssText =
            'display:flex;align-items:center;gap:12px;padding:10px 0;' +
            'border-bottom:1px solid #1e293b';

        var nameEl = document.createElement('span');
        nameEl.style.cssText = 'width:80px;font-weight:600;color:#e2e8f0;' +
            'text-transform:capitalize';
        nameEl.textContent = p;

        var statusEl = document.createElement('span');
        statusEl.style.cssText = 'color:' + color +
            ';font-size:12px;font-weight:600;text-transform:uppercase';
        statusEl.textContent = status;

        var lastEl = document.createElement('span');
        lastEl.style.cssText = 'color:#64748b;font-size:12px';
        lastEl.textContent = 'Last used: ' + lastUsed;

        row.appendChild(nameEl);
        row.appendChild(statusEl);
        row.appendChild(lastEl);
        el.appendChild(row);
    });
}

async function bpRefreshTaskLog() {
    if (!_bpAgentId) return;
    var resp = await fetch(
        '/tools/department-hq/api/browser/task-log?agent_id=' +
        _bpAgentId + '&limit=20'
    );
    var data = await resp.json();
    var el = document.getElementById('bp-task-log');
    el.textContent = '';

    if (!data.tasks || !data.tasks.length) {
        var p = document.createElement('p');
        p.style.cssText = 'color:#64748b;font-size:13px';
        p.textContent = 'No tasks yet.';
        el.appendChild(p);
        return;
    }

    var colors = {completed: '#22c55e', failed: '#ef4444', running: '#f59e0b',
                  pending: '#94a3b8'};

    data.tasks.forEach(function(t) {
        var color = colors[t.status] || '#94a3b8';
        var row = document.createElement('div');
        row.style.cssText =
            'padding:8px 0;border-bottom:1px solid #1e293b;font-size:12px;' +
            'display:grid;grid-template-columns:140px 90px 110px 1fr;gap:8px;' +
            'align-items:center';

        var skillEl = document.createElement('span');
        skillEl.style.color = '#e2e8f0';
        skillEl.textContent = t.skill;

        var stEl = document.createElement('span');
        stEl.style.cssText = 'color:' + color +
            ';text-transform:uppercase;font-weight:600';
        stEl.textContent = t.status;

        var platEl = document.createElement('span');
        platEl.style.color = '#64748b';
        platEl.textContent = t.platform || '--';

        var whenEl = document.createElement('span');
        whenEl.style.color = '#94a3b8';
        whenEl.textContent = new Date(t.created_at).toLocaleString();

        row.appendChild(skillEl);
        row.appendChild(stEl);
        row.appendChild(platEl);
        row.appendChild(whenEl);
        el.appendChild(row);
    });
}

function bpOpenSetupModal() {
    document.getElementById('bp-setup-modal').style.display = 'flex';
}

async function bpSaveSession() {
    if (!_bpAgentId) { alert('Select an agent first'); return; }
    var platform = document.getElementById('bp-setup-platform').value;
    var username = document.getElementById('bp-setup-username').value.trim();
    var password = document.getElementById('bp-setup-password').value;
    if (!username || !password) {
        alert('Username and password required');
        return;
    }
    var resp = await fetch(
        '/tools/department-hq/api/browser/sessions/' + _bpAgentId + '/setup',
        {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({platform: platform, username: username,
                                  password: password}),
        }
    );
    var data = await resp.json();
    document.getElementById('bp-setup-modal').style.display = 'none';
    document.getElementById('bp-setup-username').value = '';
    document.getElementById('bp-setup-password').value = '';
    alert(data.message || (data.success ? 'Credentials saved' : data.error));
    bpRefreshSessions();
}

async function bpRunTask() {
    if (!_bpAgentId) { alert('Select an agent first'); return; }
    var skill = document.getElementById('bp-skill-select').value;
    var content = document.getElementById('bp-task-content').value.trim();
    if (!skill) { alert('Select a skill'); return; }

    var params = content ? {content: content} : {};
    var resultEl = document.getElementById('bp-task-result');
    resultEl.textContent = 'Running...';
    resultEl.style.color = '#f59e0b';

    var resp = await fetch('/tools/department-hq/api/browser/task', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
            agent_id: parseInt(_bpAgentId),
            skill: skill,
            params: params,
            triggered_by: 'cli',
        }),
    });
    var data = await resp.json();
    if (data.error) {
        resultEl.textContent = 'Error: ' + data.error;
        resultEl.style.color = '#ef4444';
    } else {
        resultEl.textContent = 'Task submitted -- ID: ' + data.task_id;
        resultEl.style.color = '#22c55e';
        setTimeout(bpRefreshTaskLog, 5000);
    }
}

document.addEventListener('DOMContentLoaded', function() {
    var nav = document.querySelector('[data-tab="online-presence"]');
    if (nav) {
        nav.addEventListener('click', function() {
            if (!_bpAgentId) bpInit();
        });
    }
});
```

- [ ] **Step 4: Load the JS in department_hq.html**

Find where other DHQ static JS files are loaded and add:
```html
<script src="{{ url_for('department_hq.static', filename='js/browser_presence.js') }}"></script>
```

- [ ] **Step 5: Deploy and verify tab appears**

```bash
docker compose restart archie_platform && sleep 6
```
Open http://192.168.1.200:3000/tools/department-hq -- "Online Presence" tab
should appear in nav. Click it, select an internal agent, verify all three
panels render.

- [ ] **Step 6: Commit**

```bash
cd /mnt/archie_brain
git add platform_v2/tools/department_hq/templates/department_hq.html \
        platform_v2/tools/department_hq/static/js/browser_presence.js
git commit -m "feat(dhq): Online Presence tab -- sessions + task log + quick-run (#287)"
```

---

### Task 14: Agent Academy -- web_interaction skill category

**Files:**
- Modify: `platform_v2/tools/agent_academy/competency_routes.py`

- [ ] **Step 1: Find skill category definitions**

```bash
grep -n "skill_category\|social_content\|categories" \
    /mnt/archie_brain/platform_v2/tools/agent_academy/competency_routes.py | head -20
```

- [ ] **Step 2: Add web_interaction category**

Wherever `social_content` appears as a valid skill category value, add
`"web_interaction"` to the same list. The exact change depends on Step 1 output.

- [ ] **Step 3: Seed Kytran's browser skills in the DB**

```bash
docker exec archie_database psql -U archie -d archie -c "
INSERT INTO agent_skills (agent_id, skill_name, proficiency_level, can_escalate_to)
SELECT a.id, v.skill_name, 1, NULL
FROM agents a
CROSS JOIN (VALUES
    ('linkedin_post'),('linkedin_profile_edit'),
    ('twitter_post'),('meta_portal_setup'),('web_form_fill')
) AS v(skill_name)
WHERE a.display_name ILIKE '%kytran%'
  AND a.worker_type = 'internal'
ON CONFLICT (agent_id, skill_name) DO NOTHING;
"
```
Expected: `INSERT 0 5`

- [ ] **Step 4: Verify in Agent Academy UI**

Open http://192.168.1.200:3000/tools/agent-academy, Skills tab.
Kytran's agent shows 5 browser skills at Lv1.

- [ ] **Step 5: Commit**

```bash
cd /mnt/archie_brain
git add platform_v2/tools/agent_academy/competency_routes.py
git commit -m "feat(academy): web_interaction category + seed Kytran browser skills (#287)"
```

---

### Task 15: KBS publish_via_browser integration

**Files:**
- Modify: `kytran-business-suite/plugins/kbs_social_media/publishing_service.py`

- [ ] **Step 1: Add publish_via_browser to publishing_service.py**

Open `kytran-business-suite/plugins/kbs_social_media/publishing_service.py`.

At the top (after existing imports), add:
```python
import os as _os
_ARCHIE_BASE = _os.getenv("KBS_ARCHIE_BASE_URL", "http://archie_platform:3000")
_BRIDGE_KEY = _os.getenv("KBS_BRIDGE_API_KEY", "")
```

At the bottom of the file, add:
```python
def publish_via_browser(cur, post_id: int, account_id: int) -> dict:
    """Publish via archie_browser. Falls back to API if container unreachable."""
    account = _get_account(cur, account_id)
    if not account:
        raise ValueError(f"Account {account_id} not found or inactive")

    cur.execute(
        "SELECT content, agent_id FROM social_posts WHERE id = %s", (post_id,)
    )
    row = cur.fetchone()
    if not row:
        raise ValueError(f"Post {post_id} not found")

    content = row["content"] if isinstance(row, dict) else row[0]
    agent_id = row["agent_id"] if isinstance(row, dict) else row[1]
    platform = account["platform"]

    if not agent_id:
        logger.info("publish_via_browser: no agent_id on post %s, using API", post_id)
        return {**publish_post(cur, post_id, account_id), "method": "api"}

    _SKILL_MAP = {
        "linkedin": "linkedin_post",
        "twitter": "twitter_post",
        "facebook": "web_form_fill",
    }
    skill = _SKILL_MAP.get(platform)
    if not skill:
        raise ValueError(f"No browser skill for platform: {platform}")

    try:
        resp = requests.post(
            f"{_ARCHIE_BASE}/tools/department-hq/api/browser/task",
            json={"agent_id": agent_id, "skill": skill,
                  "params": {"content": content}, "triggered_by": "kbs"},
            headers={"Authorization": f"Bearer {_BRIDGE_KEY}"},
            timeout=10,
        )
        resp.raise_for_status()
        task_id = resp.json().get("task_id", "")
        now = datetime.now(timezone.utc)
        cur.execute(
            """UPDATE social_posts
               SET status='published', published_at=%s,
                   platform_post_id=%s, updated_at=%s
               WHERE id=%s""",
            (now, f"browser:{task_id}", now, post_id),
        )
        logger.info("publish_via_browser: task %s for post %s on %s",
                    task_id, post_id, platform)
        return {"success": True, "method": "browser",
                "platform_post_id": f"browser:{task_id}"}
    except requests.RequestException as exc:
        logger.warning("publish_via_browser: fallback to API (%s)", exc)
        return {**publish_post(cur, post_id, account_id), "method": "api_fallback"}
```

- [ ] **Step 2: Verify import**

```bash
cd /mnt/archie_brain/kytran-business-suite
python -c "
from plugins.kbs_social_media.publishing_service import publish_via_browser
print('OK')
"
```
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
cd /mnt/archie_brain
git add kytran-business-suite/plugins/kbs_social_media/publishing_service.py
git commit -m "feat(kbs): publish_via_browser -- route posts through browser agent (#287)"
```

---

## Final Verification

- [ ] Container health

```bash
curl http://192.168.1.200:4242/health
```
Expected: `{"skills": [...5 skills...], "status": "ok"}`

- [ ] Platform routes loaded

```bash
docker logs archie_platform 2>&1 | grep -i "error" | tail -10
```
Expected: no browser_routes errors.

- [ ] DB tables exist

```bash
docker exec archie_database psql -U archie -d archie -c \
    "SELECT COUNT(*) FROM agent_browser_sessions; SELECT COUNT(*) FROM browser_task_log;"
```
Expected: `0` rows each.

- [ ] DHQ Online Presence tab: open http://192.168.1.200:3000/tools/department-hq,
  click tab, select Kytran -- all three panels appear.

- [ ] Create PR

```bash
cd /mnt/archie_brain
gh pr create \
  --title "feat(#287): Browser Persona System Phase 1" \
  --body "$(cat <<'EOF'
## Summary
- New archie_browser container :4242 with Playwright + 5 skills
- Skills: linkedin_post, linkedin_profile_edit, twitter_post, meta_portal_setup, web_form_fill
- 4 DB tables: agent_browser_sessions, agent_online_persona, browser_task_log, browser_campaigns
- DHQ Online Presence tab (tab 13) -- sessions, task log, quick-run
- Platform proxy: POST /api/browser/task (human agents only, worker_type=internal)
- KBS publish_via_browser() -- falls back to API if container unreachable

## Test plan
- [ ] curl :4242/health returns 5 skills
- [ ] DHQ Online Presence tab loads + shows Kytran agent
- [ ] Add LinkedIn session credentials via setup modal
- [ ] Run linkedin_post from Quick Run panel
- [ ] Task appears in task log with status=completed

Phase 2 (campaigns) and Phase 3 (geo-distribution) are separate plans.

Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

---

*Spec: `docs/superpowers/specs/2026-04-27-browser-persona-design.md`*
*Phase 2 and Phase 3 plans to follow after Phase 1 ships.*
