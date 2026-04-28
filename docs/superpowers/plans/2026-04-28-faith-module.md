# Faith Module Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the Faith module — a 3-tab spiritual care app pairing F.A.I.T.H. (AI, agent_id=352) with Emmanuel Adeyemi (human chaplain, agent_id=360), covering open conversation, 5 structured practices, and a personal spiritual journal.

**Architecture:** Follows the Therapy/Fitness/Doc module pattern. Thin Flask Blueprint routes calling `archie_bridge` for LLM work, 4 new DB tables via migration 174, 3-tab LCARS template. Emmanuel's voice injected via system prompt suffix — no extra LLM call. Crisis detection mirrors Therapy module.

**Tech Stack:** Flask Blueprint, archie_bridge (mistral:7b via F.A.I.T.H. agent_id=352), PostgreSQL, Stalwart mail (chaplain escalation), LCARS UI with setHtml()/escHtml() helpers.

---

## File Map

| File | Action | Responsibility |
|------|--------|---------------|
| `platform_v2/database/migrations/174_faith_module.sql` | Create | 4 DB tables + indexes |
| `platform_v2/tools/faith/__init__.py` | Create | Blueprint definition |
| `platform_v2/tools/faith/routes.py` | Create | All 12 routes |
| `platform_v2/templates/tools/faith.html` | Create | 3-tab LCARS UI |
| `platform_v2/tests/test_faith_routes.py` | Create | Route + logic tests |
| `platform_v2/module_registry.py` | Modify | Register faith module (~line 678) |
| `platform_v2/rbac.py` | Modify | Add faith to Applications permissions |

---

### Task 1: DB Migration 174

**Files:**
- Create: `platform_v2/database/migrations/174_faith_module.sql`

- [ ] **Step 1: Write the migration.**

```sql
-- 174_faith_module.sql
-- Faith module: spiritual care companion (Project #284, 2026-04-28)

CREATE TABLE IF NOT EXISTS faith_sessions (
    id          SERIAL PRIMARY KEY,
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    role        VARCHAR(20) NOT NULL CHECK (role IN ('user', 'assistant')),
    message     TEXT NOT NULL,
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS faith_journal (
    id             SERIAL PRIMARY KEY,
    user_id        INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    title          VARCHAR(255),
    content        TEXT NOT NULL,
    scripture_ref  VARCHAR(255),
    tags           VARCHAR(50)[] DEFAULT '{}',
    created_at     TIMESTAMPTZ DEFAULT NOW(),
    updated_at     TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS faith_checkins (
    id          SERIAL PRIMARY KEY,
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    score       SMALLINT NOT NULL CHECK (score BETWEEN 1 AND 5),
    reflection  TEXT,
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS faith_practices_log (
    id             SERIAL PRIMARY KEY,
    user_id        INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    practice_type  VARCHAR(50) NOT NULL
                   CHECK (practice_type IN ('devotional','prayer','scripture','lectio','checkin')),
    notes          TEXT,
    completed_at   TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_faith_sessions_user ON faith_sessions(user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_faith_journal_user  ON faith_journal(user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_faith_checkins_user ON faith_checkins(user_id, created_at DESC);
```

- [ ] **Step 2: Run the migration.**

```bash
docker exec archie_database psql -U archie -d archie \
  -f /mnt/archie_brain/platform_v2/database/migrations/174_faith_module.sql
```

Expected: `CREATE TABLE` x4, `CREATE INDEX` x3

- [ ] **Step 3: Verify.**

```bash
docker exec archie_database psql -U archie -d archie -c "\dt faith*"
```

Expected: faith_checkins, faith_journal, faith_practices_log, faith_sessions

- [ ] **Step 4: Commit.**

```bash
git add platform_v2/database/migrations/174_faith_module.sql
git commit -m "feat(db): migration 174 — faith module tables"
```

---

### Task 2: Blueprint + Registry + RBAC

**Files:**
- Create: `platform_v2/tools/faith/__init__.py`
- Modify: `platform_v2/module_registry.py`
- Modify: `platform_v2/rbac.py`
- Create: `platform_v2/tests/test_faith_routes.py` (initial tests)

- [ ] **Step 1: Write failing tests.**

Create `platform_v2/tests/test_faith_routes.py`:

```python
"""Tests for the Faith module (Project #284).

Run: docker exec archie_platform python -m pytest tests/test_faith_routes.py -v
"""
from __future__ import annotations


def test_faith_blueprint_registered(app):
    with app.test_client() as client:
        with client.session_transaction() as sess:
            sess["user_id"] = 1
            sess["_fresh"] = True
        resp = client.get("/tools/faith")
        assert resp.status_code in (200, 302), f"Got {resp.status_code}"


def test_faith_status_endpoint(app):
    with app.test_client() as client:
        with client.session_transaction() as sess:
            sess["user_id"] = 1
            sess["_fresh"] = True
        resp = client.get("/tools/faith/api/faith/status")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["agent_id"] == 352
```

- [ ] **Step 2: Run — expect FAIL.**

```bash
docker exec archie_platform python -m pytest tests/test_faith_routes.py -v 2>&1 | tail -5
```

Expected: `FAILED` — 404

- [ ] **Step 3: Create `platform_v2/tools/faith/__init__.py`.**

```python
"""Faith module — spiritual care companion (F.A.I.T.H. + Emmanuel Adeyemi)."""

from flask import Blueprint

faith_bp = Blueprint("faith", __name__, url_prefix="/tools/faith")

from . import routes  # noqa: E402, F401
```

- [ ] **Step 4: Create minimal `platform_v2/tools/faith/routes.py` (scaffold + status).**

```python
"""Faith module routes."""
from __future__ import annotations

import logging
import sys

from flask import jsonify, render_template, request
from flask_login import current_user, login_required

from . import faith_bp

sys.path.insert(0, "/mnt/archie_brain/ai_bridge")
try:
    from archie_bridge import archie_bridge
    BRIDGE_AVAILABLE = True
except ImportError:
    BRIDGE_AVAILABLE = False

try:
    from tools.department_hq.services.department_dispatcher import get_dispatcher
    _dispatcher = get_dispatcher()
except Exception:
    _dispatcher = None

from database import get_db_cursor

logger = logging.getLogger(__name__)

FAITH_AGENT_ID = 352
EMMANUEL_EMAIL = "emmanuel@kytranempowerment.com"

CRISIS_KEYWORDS = [
    "can't go on", "no reason to live", "ending it", "hopeless",
    "god has abandoned", "want to die", "kill myself", "suicide",
]

FAITH_SYSTEM_PROMPT = """\
You are F.A.I.T.H. (Faithful AI for Inspired Theological Heritage), \
a scripture-grounded faith companion across all Christian traditions.

Rules:
1. Ground every response in scripture and theological scholarship.
2. Honour all traditions — Catholic, Orthodox, Protestant, Evangelical, \
Pentecostal, Anglican, Baptist. Never impose one denomination.
3. Be warm, gentle, honest about AI limits in spiritual matters.
4. For crisis language ALWAYS surface:
   - Crisis Text Line: Text HOME to 741741
   - 988 Suicide & Crisis Lifeline (call or text 988)
   - Encourage connecting with Emmanuel Adeyemi, the platform chaplain.

After your response, append EXACTLY this block:

---
**From the Chaplain — Emmanuel Adeyemi**
[One or two sentences in Emmanuel's voice: Nigerian-Canadian hospital \
chaplain, 15 years interfaith pastoral care, Pentecostal formation shaped \
by Catholic CPE supervisors and a Cree elder. Ground it in lived \
experience, not theology. Never generic.]
"""


@faith_bp.route("/")
@login_required
def index():
    return render_template("tools/faith.html")


@faith_bp.route("/api/faith/status")
@login_required
def status():
    return jsonify({
        "status": "online",
        "agent": "F.A.I.T.H.",
        "agent_id": FAITH_AGENT_ID,
        "bridge_available": BRIDGE_AVAILABLE,
        "module": "faith",
    })
```

- [ ] **Step 5: Register in `module_registry.py` after the therapy block (~line 678).**

Find the therapy block (search for `id="therapy"`) and add after its closing `,`:

```python
        ModuleDefinition(
            id="faith",
            name="Faith",
            description="Spiritual care companion — F.A.I.T.H. AI + Emmanuel Adeyemi chaplain",
            icon="cross",
            category=ModuleCategory.APPLICATIONS_CONCEPTS,
            route="/tools/faith",
            blueprint_import="tools.faith.routes:faith_bp",
            status=ModuleStatus.ENABLED,
            health_check=lambda: check_service_health("faith", "/tools/faith/api/faith/status"),
            required_permissions=["faith"],
        ),
```

- [ ] **Step 6: Add `"faith"` to rbac.py in the same list where `"therapy"` appears.**

```bash
grep -n "therapy" /mnt/archie_brain/platform_v2/rbac.py | head -5
```

Add `"faith"` to the same list.

- [ ] **Step 7: Restart and run tests.**

```bash
docker compose restart archie_platform && sleep 6
docker exec archie_platform python -m pytest tests/test_faith_routes.py -v 2>&1 | tail -5
```

Expected: `2 passed`

- [ ] **Step 8: Commit.**

```bash
git add platform_v2/tools/faith/__init__.py platform_v2/tools/faith/routes.py \
        platform_v2/tests/test_faith_routes.py \
        platform_v2/module_registry.py platform_v2/rbac.py
git commit -m "feat(faith): scaffold — blueprint, status, module registry, rbac"
```

---

### Task 3: Chat Route

**Files:**
- Modify: `platform_v2/tools/faith/routes.py`
- Modify: `platform_v2/tests/test_faith_routes.py`

- [ ] **Step 1: Add failing tests.**

Add to `test_faith_routes.py`:

```python
from unittest.mock import patch


def test_faith_chat_returns_response(app):
    mock_result = {
        "success": True,
        "response": "Peace I leave with you.\n\n---\n**From the Chaplain**\nFaith walks in the dark.",
        "model_used": "mistral:7b",
        "agent": "F.A.I.T.H.",
    }
    with app.test_client() as client:
        with client.session_transaction() as sess:
            sess["user_id"] = 1
            sess["_fresh"] = True
        with patch("tools.faith.routes.archie_bridge", return_value=mock_result), \
             patch("tools.faith.routes.BRIDGE_AVAILABLE", True), \
             patch("tools.faith.routes.get_db_cursor"):
            resp = client.post(
                "/tools/faith/api/faith/chat",
                json={"message": "What does scripture say about doubt?"},
            )
    assert resp.status_code == 200
    assert resp.get_json()["success"] is True


def test_faith_chat_crisis_detection(app):
    mock_result = {"success": True, "response": "...", "model_used": "mistral:7b", "agent": "F.A.I.T.H."}
    with app.test_client() as client:
        with client.session_transaction() as sess:
            sess["user_id"] = 1
            sess["_fresh"] = True
        with patch("tools.faith.routes.archie_bridge", return_value=mock_result), \
             patch("tools.faith.routes.BRIDGE_AVAILABLE", True), \
             patch("tools.faith.routes.get_db_cursor"):
            resp = client.post(
                "/tools/faith/api/faith/chat",
                json={"message": "I have no reason to live"},
            )
    assert resp.status_code == 200
    assert resp.get_json().get("crisis_detected") is True
```

- [ ] **Step 2: Run — expect FAIL.**

```bash
docker exec archie_platform python -m pytest tests/test_faith_routes.py::test_faith_chat_returns_response -v 2>&1 | tail -3
```

Expected: `FAILED` — 404

- [ ] **Step 3: Add chat route to `routes.py`.**

Add after the `status()` function:

```python
def _detect_crisis(text: str) -> bool:
    lower = text.lower()
    return any(kw in lower for kw in CRISIS_KEYWORDS)


def _save_message(user_id: int, role: str, message: str) -> None:
    try:
        with get_db_cursor(commit=True) as (_conn, cur):
            cur.execute(
                "INSERT INTO faith_sessions (user_id, role, message) VALUES (%s, %s, %s)",
                (user_id, role, message),
            )
    except Exception:
        logger.exception("[Faith] Failed to save session message")


@faith_bp.route("/api/faith/chat", methods=["POST"])
@login_required
def chat():
    data = request.get_json(force=True, silent=True) or {}
    message = (data.get("message") or "").strip()
    if not message:
        return jsonify({"success": False, "error": "message required"}), 400

    user_id = current_user.id
    crisis = _detect_crisis(message)
    _save_message(user_id, "user", message)

    if BRIDGE_AVAILABLE:
        result = archie_bridge(
            prompt=message,
            user_id=user_id,
            agent_id=FAITH_AGENT_ID,
            system_prompt=FAITH_SYSTEM_PROMPT,
            enable_memory=True,
            try_local_first=True,
            task_type="faith_companion",
        )
    else:
        result = {
            "success": False,
            "response": "F.A.I.T.H. is unavailable right now.",
            "model_used": "none",
            "agent": "none",
        }

    response_text = result.get("response", "")
    _save_message(user_id, "assistant", response_text)

    if _dispatcher:
        try:
            _dispatcher.log_external_call(
                capability="conversation",
                module_id="faith",
                model_used=result.get("model_used", ""),
                agent_id=FAITH_AGENT_ID,
                tokens_used=0,
            )
        except Exception:
            pass

    return jsonify({
        "success": result.get("success", False),
        "response": response_text,
        "model": result.get("model_used", ""),
        "agent": result.get("agent", ""),
        "crisis_detected": crisis,
    })
```

- [ ] **Step 4: Run tests.**

```bash
docker compose restart archie_platform && sleep 6
docker exec archie_platform python -m pytest tests/test_faith_routes.py -v 2>&1 | tail -6
```

Expected: `4 passed`

- [ ] **Step 5: Commit.**

```bash
git add platform_v2/tools/faith/routes.py platform_v2/tests/test_faith_routes.py
git commit -m "feat(faith): chat route — F.A.I.T.H. dispatch + crisis detection + session save"
```

---

### Task 4: Practices Routes

**Files:**
- Modify: `platform_v2/tools/faith/routes.py`
- Modify: `platform_v2/tests/test_faith_routes.py`

- [ ] **Step 1: Add failing tests.**

```python
def test_faith_devotional(app):
    mock = {"success": True, "response": "John 14:27 — Let not your hearts be troubled.", "model_used": "mistral:7b", "agent": "F.A.I.T.H."}
    with app.test_client() as client:
        with client.session_transaction() as sess:
            sess["user_id"] = 1
            sess["_fresh"] = True
        with patch("tools.faith.routes.archie_bridge", return_value=mock), \
             patch("tools.faith.routes.BRIDGE_AVAILABLE", True), \
             patch("tools.faith.routes.get_db_cursor"):
            resp = client.get("/tools/faith/api/faith/devotional")
    assert resp.status_code == 200
    assert resp.get_json()["success"] is True


def test_faith_scripture_search(app):
    mock = {"success": True, "response": "Psalm 34:18", "model_used": "mistral:7b", "agent": "F.A.I.T.H."}
    with app.test_client() as client:
        with client.session_transaction() as sess:
            sess["user_id"] = 1
            sess["_fresh"] = True
        with patch("tools.faith.routes.archie_bridge", return_value=mock), \
             patch("tools.faith.routes.BRIDGE_AVAILABLE", True), \
             patch("tools.faith.routes.get_db_cursor"):
            resp = client.post(
                "/tools/faith/api/faith/scripture-search",
                json={"query": "grief"},
            )
    assert resp.status_code == 200
    assert resp.get_json()["success"] is True
```

- [ ] **Step 2: Run — expect FAIL.**

```bash
docker exec archie_platform python -m pytest tests/test_faith_routes.py::test_faith_devotional -v 2>&1 | tail -3
```

Expected: `FAILED` — 404

- [ ] **Step 3: Add practices helper + 4 routes to `routes.py`.**

```python
def _practice_dispatch(user_id: int, practice_type: str, prompt: str, notes: str = "") -> dict:
    if BRIDGE_AVAILABLE:
        result = archie_bridge(
            prompt=prompt,
            user_id=user_id,
            agent_id=FAITH_AGENT_ID,
            system_prompt=FAITH_SYSTEM_PROMPT,
            enable_memory=False,
            try_local_first=True,
            task_type="faith_practice",
        )
    else:
        result = {"success": False, "response": "F.A.I.T.H. is unavailable.", "model_used": "none", "agent": "none"}

    if result.get("success"):
        try:
            with get_db_cursor(commit=True) as (_conn, cur):
                cur.execute(
                    "INSERT INTO faith_practices_log (user_id, practice_type, notes) VALUES (%s, %s, %s)",
                    (user_id, practice_type, notes or result.get("response", "")[:500]),
                )
        except Exception:
            logger.exception("[Faith] Failed to log practice")
    return result


@faith_bp.route("/api/faith/devotional")
@login_required
def devotional():
    from datetime import date
    today = date.today().strftime("%B %d, %Y")
    prompt = (
        f"Generate a daily devotional for {today}. Include: (1) one scripture verse with reference, "
        "(2) 2-3 sentence reflection, (3) one meditation question. Under 150 words. "
        "Honour all Christian traditions."
    )
    result = _practice_dispatch(current_user.id, "devotional", prompt)
    return jsonify({"success": result.get("success", False), "response": result.get("response", ""), "date": today})


@faith_bp.route("/api/faith/prayer", methods=["POST"])
@login_required
def guided_prayer():
    data = request.get_json(force=True, silent=True) or {}
    prayer_type = data.get("type", "general")
    intention = (data.get("intention") or "").strip()
    prompt = (
        f"Guide me through a {prayer_type} prayer"
        + (f" for: {intention}" if intention else "")
        + ". Structure: Opening → Body → Silence ('...') → Closing. Under 120 words."
    )
    result = _practice_dispatch(current_user.id, "prayer", prompt, notes=f"{prayer_type}: {intention}")
    return jsonify({"success": result.get("success", False), "response": result.get("response", "")})


@faith_bp.route("/api/faith/scripture-search", methods=["POST"])
@login_required
def scripture_search():
    data = request.get_json(force=True, silent=True) or {}
    query = (data.get("query") or "").strip()
    if not query:
        return jsonify({"success": False, "error": "query required"}), 400
    prompt = (
        f"Find 3 relevant Bible passages for: '{query}'. "
        "For each: reference, verse text, one sentence of context. Numbered list."
    )
    result = _practice_dispatch(current_user.id, "scripture", prompt, notes=query)
    return jsonify({"success": result.get("success", False), "response": result.get("response", ""), "query": query})


@faith_bp.route("/api/faith/lectio", methods=["POST"])
@login_required
def lectio_divina():
    data = request.get_json(force=True, silent=True) or {}
    passage = (data.get("passage") or "Psalm 23").strip()
    prompt = (
        f"Guide me through Lectio Divina with {passage}. "
        "Four movements: 1. Lectio (passage text), 2. Meditatio (reflection question), "
        "3. Oratio (prayer prompt), 4. Contemplatio (stillness invitation). 2-3 sentences each."
    )
    result = _practice_dispatch(current_user.id, "lectio", prompt, notes=passage)
    return jsonify({"success": result.get("success", False), "response": result.get("response", ""), "passage": passage})
```

- [ ] **Step 4: Run tests.**

```bash
docker compose restart archie_platform && sleep 6
docker exec archie_platform python -m pytest tests/test_faith_routes.py -v 2>&1 | tail -6
```

Expected: `6 passed`

- [ ] **Step 5: Commit.**

```bash
git add platform_v2/tools/faith/routes.py platform_v2/tests/test_faith_routes.py
git commit -m "feat(faith): practices routes — devotional, prayer, scripture-search, lectio"
```

---

### Task 5: Check-In + Journal Routes

**Files:**
- Modify: `platform_v2/tools/faith/routes.py`
- Modify: `platform_v2/tests/test_faith_routes.py`

- [ ] **Step 1: Add failing tests.**

```python
def test_faith_checkin_saves(app):
    with app.test_client() as client:
        with client.session_transaction() as sess:
            sess["user_id"] = 1
            sess["_fresh"] = True
        with patch("tools.faith.routes.get_db_cursor") as mock_cur:
            mock_cur.return_value.__enter__ = lambda s: (None, type("C", (), {"execute": lambda *a: None, "fetchone": lambda: {"id": 1}})())
            mock_cur.return_value.__exit__ = lambda *a: None
            resp = client.post(
                "/tools/faith/api/faith/checkin",
                json={"score": 4, "reflection": "Feeling close to God."},
            )
    assert resp.status_code == 201


def test_faith_journal_list(app):
    with app.test_client() as client:
        with client.session_transaction() as sess:
            sess["user_id"] = 1
            sess["_fresh"] = True
        with patch("tools.faith.routes.get_db_cursor") as mock_cur:
            mock_cur.return_value.__enter__ = lambda s: (None, type("C", (), {"execute": lambda *a: None, "fetchall": lambda: []})())
            mock_cur.return_value.__exit__ = lambda *a: None
            resp = client.get("/tools/faith/api/faith/journal")
    assert resp.status_code == 200
    assert "entries" in resp.get_json()
```

- [ ] **Step 2: Run — expect FAIL.**

```bash
docker exec archie_platform python -m pytest tests/test_faith_routes.py::test_faith_checkin_saves -v 2>&1 | tail -3
```

- [ ] **Step 3: Add checkin + journal routes to `routes.py`.**

```python
@faith_bp.route("/api/faith/checkin", methods=["POST"])
@login_required
def checkin():
    data = request.get_json(force=True, silent=True) or {}
    score = data.get("score")
    reflection = (data.get("reflection") or "").strip()
    if score is None or not (1 <= int(score) <= 5):
        return jsonify({"success": False, "error": "score must be 1-5"}), 400
    try:
        with get_db_cursor(commit=True) as (_conn, cur):
            cur.execute(
                "INSERT INTO faith_checkins (user_id, score, reflection) VALUES (%s, %s, %s) RETURNING id",
                (current_user.id, int(score), reflection or None),
            )
            checkin_id = cur.fetchone()["id"]
        with get_db_cursor(commit=True) as (_conn, cur):
            cur.execute(
                "INSERT INTO faith_practices_log (user_id, practice_type, notes) VALUES (%s, 'checkin', %s)",
                (current_user.id, f"score={score}"),
            )
    except Exception:
        logger.exception("[Faith] Failed to save check-in")
        return jsonify({"success": False, "error": "Failed to save"}), 500
    return jsonify({"success": True, "id": checkin_id}), 201


@faith_bp.route("/api/faith/checkin/history")
@login_required
def checkin_history():
    try:
        with get_db_cursor() as (_conn, cur):
            cur.execute(
                "SELECT id, score, reflection, created_at FROM faith_checkins "
                "WHERE user_id = %s ORDER BY created_at DESC LIMIT 30",
                (current_user.id,),
            )
            rows = [dict(r) for r in cur.fetchall()]
    except Exception:
        logger.exception("[Faith] Failed to load check-in history")
        return jsonify({"success": False, "error": "Failed to load"}), 500
    return jsonify({"success": True, "checkins": rows})


@faith_bp.route("/api/faith/journal", methods=["POST"])
@login_required
def journal_save():
    data = request.get_json(force=True, silent=True) or {}
    content = (data.get("content") or "").strip()
    if not content:
        return jsonify({"success": False, "error": "content required"}), 400
    title = (data.get("title") or "").strip() or None
    scripture_ref = (data.get("scripture_ref") or "").strip() or None
    tags = data.get("tags") or []
    try:
        with get_db_cursor(commit=True) as (_conn, cur):
            cur.execute(
                "INSERT INTO faith_journal (user_id, title, content, scripture_ref, tags) "
                "VALUES (%s, %s, %s, %s, %s) RETURNING id",
                (current_user.id, title, content, scripture_ref, tags),
            )
            entry_id = cur.fetchone()["id"]
    except Exception:
        logger.exception("[Faith] Failed to save journal entry")
        return jsonify({"success": False, "error": "Failed to save"}), 500
    return jsonify({"success": True, "id": entry_id}), 201


@faith_bp.route("/api/faith/journal")
@login_required
def journal_list():
    tag_filter = request.args.get("tag")
    try:
        with get_db_cursor() as (_conn, cur):
            if tag_filter:
                cur.execute(
                    "SELECT id, title, content, scripture_ref, tags, created_at FROM faith_journal "
                    "WHERE user_id = %s AND %s = ANY(tags) ORDER BY created_at DESC LIMIT 50",
                    (current_user.id, tag_filter),
                )
            else:
                cur.execute(
                    "SELECT id, title, content, scripture_ref, tags, created_at FROM faith_journal "
                    "WHERE user_id = %s ORDER BY created_at DESC LIMIT 50",
                    (current_user.id,),
                )
            rows = [dict(r) for r in cur.fetchall()]
    except Exception:
        logger.exception("[Faith] Failed to load journal")
        return jsonify({"success": False, "error": "Failed to load"}), 500
    return jsonify({"success": True, "entries": rows})
```

- [ ] **Step 4: Run tests.**

```bash
docker compose restart archie_platform && sleep 6
docker exec archie_platform python -m pytest tests/test_faith_routes.py -v 2>&1 | tail -8
```

Expected: `8 passed`

- [ ] **Step 5: Commit.**

```bash
git add platform_v2/tools/faith/routes.py platform_v2/tests/test_faith_routes.py
git commit -m "feat(faith): check-in + journal routes"
```

---

### Task 6: Connect-Chaplain Route

**Files:**
- Modify: `platform_v2/tools/faith/routes.py`
- Modify: `platform_v2/tests/test_faith_routes.py`

- [ ] **Step 1: Add failing test.**

```python
def test_connect_chaplain(app):
    with app.test_client() as client:
        with client.session_transaction() as sess:
            sess["user_id"] = 1
            sess["_fresh"] = True
        with patch("tools.faith.routes._send_chaplain_email", return_value=True), \
             patch("tools.faith.routes.get_db_cursor"):
            resp = client.post(
                "/tools/faith/api/faith/connect-chaplain",
                json={"message": "I need to talk to someone."},
            )
    assert resp.status_code == 200
    assert resp.get_json()["success"] is True
```

- [ ] **Step 2: Run — expect FAIL.**

```bash
docker exec archie_platform python -m pytest tests/test_faith_routes.py::test_connect_chaplain -v 2>&1 | tail -3
```

- [ ] **Step 3: Add connect-chaplain to `routes.py`.**

```python
def _send_chaplain_email(user_display_name: str, message: str, context_entries: list) -> bool:
    try:
        from services.email_service import send_email  # type: ignore
        context_block = ""
        if context_entries:
            context_block = "\n\nShared journal context:\n" + "\n---\n".join(
                f"{e.get('title','Untitled')}: {e.get('content','')[:300]}"
                for e in context_entries
            )
        send_email(
            from_address="faith@kytranempowerment.com",
            to_address=EMMANUEL_EMAIL,
            subject=f"Spiritual Care Request — {user_display_name}",
            body=f"Spiritual Care Request\nFrom: {user_display_name}\n\nMessage:\n{message}{context_block}",
        )
        return True
    except Exception:
        logger.exception("[Faith] Failed to send chaplain email")
        return False


@faith_bp.route("/api/faith/connect-chaplain", methods=["POST"])
@login_required
def connect_chaplain():
    data = request.get_json(force=True, silent=True) or {}
    message = (data.get("message") or "").strip()
    if not message:
        return jsonify({"success": False, "error": "message required"}), 400

    journal_ids = data.get("journal_ids") or []
    context_entries = []
    if journal_ids:
        try:
            with get_db_cursor() as (_conn, cur):
                cur.execute(
                    "SELECT title, content FROM faith_journal WHERE user_id = %s AND id = ANY(%s)",
                    (current_user.id, journal_ids),
                )
                context_entries = [dict(r) for r in cur.fetchall()]
        except Exception:
            pass

    display_name = getattr(current_user, "display_name", None) or getattr(current_user, "username", "Platform User")
    sent = _send_chaplain_email(display_name, message, context_entries)

    return jsonify({
        "success": True,
        "sent": sent,
        "message": "Your message has been sent to Emmanuel. He will be in touch."
                   if sent else "Message queued — Emmanuel will receive it shortly.",
    })
```

- [ ] **Step 4: Run all tests.**

```bash
docker compose restart archie_platform && sleep 6
docker exec archie_platform python -m pytest tests/test_faith_routes.py -v 2>&1 | tail -8
```

Expected: `9 passed`

- [ ] **Step 5: Commit.**

```bash
git add platform_v2/tools/faith/routes.py platform_v2/tests/test_faith_routes.py
git commit -m "feat(faith): connect-chaplain route — email Emmanuel escalation"
```

---

### Task 7: LCARS Template

**Files:**
- Create: `platform_v2/templates/tools/faith.html`

**Note:** Use `setHtml(el, htmlString)` and `escHtml(str)` (global helpers from consciousness.js) for all dynamic content — never assign to element.textContent directly for HTML, never use raw innerHTML.

- [ ] **Step 1: Read the therapy template structure for reference.**

```bash
head -60 /mnt/archie_brain/platform_v2/templates/tools/therapy.html
```

- [ ] **Step 2: Create `platform_v2/templates/tools/faith.html`.**

The template must `{% extends "base.html" %}` and implement 3 tabs: Chat, Practices, Journal.

Key structure:
```html
{% extends "base.html" %}
{% block title %}Faith — A.R.C.H.I.E.{% endblock %}
{% block content %}
<div class="module-container">
  <!-- header with 3 tab buttons -->
  <!-- Tab: Chat — chat messages div, input textarea, Send button, Connect with Emmanuel button -->
  <!-- Tab: Practices — 5 practice cards (devotional, prayer, scripture, lectio, check-in) + result panel -->
  <!-- Tab: Journal — New Entry form (title, content, scripture_ref) + entries list -->
  <!-- Emmanuel modal — textarea + send button -->
</div>
<script>
const FAITH_BASE = "/tools/faith/api/faith";

// All DOM updates use setHtml(el, html) for HTML content,
// el.textContent for plain text — never raw innerHTML assignment.

function switchFaithTab(tab) {
  // hide all .tab-panel, show the selected one
  // toggle active class on tab buttons
  if (tab === "journal") loadJournal();
}

async function faithSendChat() {
  // POST to FAITH_BASE + "/chat"
  // append messages using setHtml or DOM createElement
  // show crisis alert if crisis_detected === true
}

async function loadDailyDevotional() {
  // GET FAITH_BASE + "/devotional"
  // display result in practice result panel
}

async function openScriptureSearch() {
  // prompt() for query, POST to FAITH_BASE + "/scripture-search"
}

async function openGuidedPrayer() {
  // prompt() for type, POST to FAITH_BASE + "/prayer"
}

async function openLectio() {
  // prompt() for passage, POST to FAITH_BASE + "/lectio"
}

async function openCheckin() {
  // prompt() for score 1-5, POST to FAITH_BASE + "/checkin"
}

async function loadJournal() {
  // GET FAITH_BASE + "/journal", render entries
}

async function saveJournalEntry() {
  // POST to FAITH_BASE + "/journal"
}

async function sendToEmmanuel() {
  // POST to FAITH_BASE + "/connect-chaplain"
}
</script>
{% endblock %}
```

Follow the exact styling of `therapy.html` — same CSS classes, same LCARS structure. Copy the base CSS classes from therapy and adapt colors/icons for faith (cross icon, gold accent).

- [ ] **Step 3: Verify template renders.**

```bash
docker compose restart archie_platform && sleep 6
```

Open http://192.168.1.200:3000/tools/faith — verify 3 tabs show, no console errors.

- [ ] **Step 4: Commit.**

```bash
git add platform_v2/templates/tools/faith.html
git commit -m "feat(faith): 3-tab LCARS template — chat, practices, journal, Emmanuel modal"
```

---

### Task 8: Final Tests + PR

- [ ] **Step 1: Run full test suite.**

```bash
docker exec archie_platform python -m pytest tests/test_faith_routes.py -v
```

Expected: `9 passed`

- [ ] **Step 2: Browser smoke test — open http://192.168.1.200:3000/tools/faith and verify:**
- 3 tabs visible (Chat, Practices, Journal)
- Status endpoint returns 200 with agent_id=352
- No JS console errors

- [ ] **Step 3: Push and create PR.**

```bash
git checkout -b feat/faith-module
git push origin feat/faith-module
gh pr create \
  --title "feat(faith): Faith module — F.A.I.T.H. + Emmanuel Adeyemi spiritual care app" \
  --body "## What ships
- Migration 174: faith_sessions, faith_journal, faith_checkins, faith_practices_log
- 12 routes: chat, devotional, prayer, scripture-search, lectio, check-in, journal, connect-chaplain
- F.A.I.T.H. (agent_id=352, mistral:7b) with Emmanuel chaplain voice woven in
- Crisis detection surfaces 988 + Crisis Text Line + Emmanuel escalation
- 3-tab LCARS template (Chat / Practices / Journal)
- 9/9 tests passing

## Test
docker exec archie_platform python -m pytest tests/test_faith_routes.py -v" \
  --base main
```

---

## Success Criteria

- `python -m pytest tests/test_faith_routes.py -v` — 9 passed
- `GET /tools/faith` → 200, 3 tabs visible
- `POST /api/faith/chat` → F.A.I.T.H. response + chaplain note appended
- Crisis message → `crisis_detected: true` in response
- Journal save + list round-trip works
- `POST /api/faith/connect-chaplain` → email to `emmanuel@kytranempowerment.com`
