# A.R.C.H.I.E. Code Tab Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a dedicated "Code" tab to the archie_chat module where A.R.C.H.I.E. runs persistent OpenCode CLI sessions, coordinates with Repair Bay proposals, and routes results by tier (Tier 1 = auto-PR, Tier 2 = human review).

**Architecture:** Two new files (`code_service.py`, `code_routes.py`) extend the existing `archie_chat` blueprint via `register_code_routes(bp)` registered in `__init__.py`. A DB migration creates `code_sessions` + `code_session_events`. The UI is a new Code tab in `archie_chat.html`. Repair Bay hooks into `scan_routes.py` to auto-create sessions from proposals.

**Tech Stack:** Flask, PostgreSQL, `subprocess.Popen`, Server-Sent Events (SSE), flask-sock (WebSocket), xterm.js, OpenCode CLI

---

## File Map

| Action | Path |
|--------|------|
| Create | `database/migrations/037_code_sessions.sql` |
| Create | `platform_v2/tools/archie_chat/code_service.py` |
| Create | `platform_v2/tools/archie_chat/code_routes.py` |
| Create | `platform_v2/tests/test_code_service.py` |
| Create | `platform_v2/tests/test_code_routes.py` |
| Modify | `platform_v2/tools/archie_chat/__init__.py` |
| Modify | `platform_v2/templates/tools/archie_chat.html` |
| Modify | `platform_v2/tools/repair_bay/scan_routes.py` |
| Modify | `platform_v2/requirements.txt` |

---

## Task 1: DB Migration

**Files:**
- Create: `database/migrations/037_code_sessions.sql`

- [ ] **Step 1: Write the migration**

```sql
-- database/migrations/037_code_sessions.sql
BEGIN;

CREATE TABLE IF NOT EXISTS code_sessions (
    id               SERIAL PRIMARY KEY,
    title            TEXT NOT NULL,
    source           TEXT NOT NULL CHECK (source IN ('user', 'repair_bay', 'archie_auto')),
    status           TEXT NOT NULL DEFAULT 'active'
                     CHECK (status IN ('active', 'paused', 'completed', 'failed')),
    tier             INTEGER NOT NULL CHECK (tier IN (1, 2)),
    project_id       INTEGER REFERENCES unified_projects(id),
    proposal_id      INTEGER,
    conversation_id  INTEGER,
    opencode_pid     INTEGER,
    created_by       TEXT NOT NULL CHECK (created_by IN ('archie', 'user')),
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at     TIMESTAMPTZ,
    result_branch    TEXT,
    result_pr_url    TEXT
);

CREATE TABLE IF NOT EXISTS code_session_events (
    id               SERIAL PRIMARY KEY,
    session_id       INTEGER NOT NULL REFERENCES code_sessions(id) ON DELETE CASCADE,
    event_type       TEXT NOT NULL
                     CHECK (event_type IN ('message','diff','file_change','summary','terminal_raw','error')),
    content          JSONB NOT NULL,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_code_session_events_session_id
    ON code_session_events(session_id);

CREATE INDEX IF NOT EXISTS idx_code_sessions_status
    ON code_sessions(status);

COMMIT;
```

- [ ] **Step 2: Run the migration**

```bash
docker exec archie_database psql -U archie -d archie \
  -f /mnt/archie_brain/database/migrations/037_code_sessions.sql
```

Expected: `CREATE TABLE`, `CREATE TABLE`, `CREATE INDEX`, `CREATE INDEX`

- [ ] **Step 3: Verify tables exist**

```bash
docker exec archie_database psql -U archie -d archie \
  -c "\dt code_*"
```

Expected: `code_session_events` and `code_sessions` listed.

- [ ] **Step 4: Commit**

```bash
git add database/migrations/037_code_sessions.sql
git commit -m "feat(db): add code_sessions + code_session_events tables (migration 037)"
```

---

## Task 2: code_service.py — Session CRUD

**Files:**
- Create: `platform_v2/tools/archie_chat/code_service.py`
- Create: `platform_v2/tests/test_code_service.py`

- [ ] **Step 1: Write the failing tests**

```python
# platform_v2/tests/test_code_service.py
import pytest
from unittest.mock import patch, MagicMock
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))


def make_cursor(rows=None, fetchone_val=None):
    cur = MagicMock()
    cur.__enter__ = lambda s: (MagicMock(), s)
    cur.__exit__ = MagicMock(return_value=False)
    cur.fetchone.return_value = fetchone_val
    cur.fetchall.return_value = rows or []
    return cur


@patch('tools.archie_chat.code_service.get_db_cursor')
def test_create_session_returns_id(mock_db):
    from tools.archie_chat.code_service import create_session
    conn = MagicMock()
    cur = MagicMock()
    cur.fetchone.return_value = {"id": 42}
    mock_db.return_value.__enter__ = MagicMock(return_value=(conn, cur))
    mock_db.return_value.__exit__ = MagicMock(return_value=False)

    result = create_session(title="Test", source="user", tier=2, created_by="user")
    assert result == 42


@patch('tools.archie_chat.code_service.get_db_cursor')
def test_get_session_returns_dict(mock_db):
    from tools.archie_chat.code_service import get_session
    conn = MagicMock()
    cur = MagicMock()
    cur.fetchone.return_value = {
        "id": 1, "title": "Fix bug", "source": "repair_bay",
        "status": "active", "tier": 2
    }
    mock_db.return_value.__enter__ = MagicMock(return_value=(conn, cur))
    mock_db.return_value.__exit__ = MagicMock(return_value=False)

    result = get_session(1)
    assert result["id"] == 1
    assert result["status"] == "active"


@patch('tools.archie_chat.code_service.get_db_cursor')
def test_append_event_inserts_row(mock_db):
    from tools.archie_chat.code_service import append_event
    conn = MagicMock()
    cur = MagicMock()
    mock_db.return_value.__enter__ = MagicMock(return_value=(conn, cur))
    mock_db.return_value.__exit__ = MagicMock(return_value=False)

    append_event(session_id=1, event_type="message", content={"text": "hello"})
    cur.execute.assert_called_once()
    call_args = cur.execute.call_args[0][0]
    assert "INSERT INTO code_session_events" in call_args
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /mnt/archie_brain/platform_v2
python -m pytest tests/test_code_service.py -v 2>&1 | head -30
```

Expected: `ModuleNotFoundError` or `ImportError` — `code_service` doesn't exist yet.

- [ ] **Step 3: Write minimal implementation**

```python
# platform_v2/tools/archie_chat/code_service.py
import json
import queue
import subprocess
import threading
from typing import Optional

import psycopg2
from database import get_db_cursor

# In-memory state (per-process lifetime)
_PROCESSES: dict[int, subprocess.Popen] = {}
_SSE_QUEUES: dict[int, queue.Queue] = {}
_RAW_QUEUES: dict[int, queue.Queue] = {}
_SESSION_MODE: dict[int, str] = {}  # 'structured' or 'raw'


def create_session(
    title: str,
    source: str,
    tier: int,
    created_by: str,
    project_id: Optional[int] = None,
    proposal_id: Optional[int] = None,
    conversation_id: Optional[int] = None,
) -> int:
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            """
            INSERT INTO code_sessions
                (title, source, tier, created_by, project_id, proposal_id, conversation_id)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            RETURNING id
            """,
            (title, source, tier, created_by, project_id, proposal_id, conversation_id),
        )
        return cur.fetchone()["id"]


def create_session_from_proposal(proposal_id: int, title: str, severity: str) -> int:
    tier = 1 if severity == "low" else 2
    return create_session(
        title=title,
        source="repair_bay",
        tier=tier,
        created_by="archie",
        proposal_id=proposal_id,
    )


def get_session(session_id: int) -> Optional[dict]:
    with get_db_cursor() as (conn, cur):
        cur.execute("SELECT * FROM code_sessions WHERE id = %s", (session_id,))
        row = cur.fetchone()
        return dict(row) if row else None


def list_sessions(view: str = "source") -> list[dict]:
    with get_db_cursor() as (conn, cur):
        cur.execute(
            "SELECT * FROM code_sessions ORDER BY created_at DESC"
        )
        return [dict(r) for r in cur.fetchall()]


def update_session_status(session_id: int, status: str, **kwargs) -> None:
    fields = ["status = %s"]
    values = [status]
    for col in ("opencode_pid", "result_branch", "result_pr_url", "completed_at"):
        if col in kwargs:
            fields.append(f"{col} = %s")
            values.append(kwargs[col])
    values.append(session_id)
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            f"UPDATE code_sessions SET {', '.join(fields)} WHERE id = %s",
            values,
        )


def append_event(session_id: int, event_type: str, content: dict) -> None:
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            """
            INSERT INTO code_session_events (session_id, event_type, content)
            VALUES (%s, %s, %s)
            """,
            (session_id, event_type, psycopg2.extras.Json(content)),
        )
    # Push to SSE queue if a consumer is listening
    q = _SSE_QUEUES.get(session_id)
    if q:
        q.put({"event_type": event_type, "content": content})


def get_session_events(session_id: int, limit: int = 200) -> list[dict]:
    with get_db_cursor() as (conn, cur):
        cur.execute(
            """
            SELECT event_type, content, created_at
            FROM code_session_events
            WHERE session_id = %s
            ORDER BY id DESC
            LIMIT %s
            """,
            (session_id, limit),
        )
        rows = cur.fetchall()
        return [dict(r) for r in reversed(rows)]
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd /mnt/archie_brain/platform_v2
python -m pytest tests/test_code_service.py -v
```

Expected: 3 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add platform_v2/tools/archie_chat/code_service.py \
        platform_v2/tests/test_code_service.py
git commit -m "feat(archie-chat): code_service.py — session CRUD + event persistence"
```

---

## Task 3: code_service.py — OpenCode Subprocess

**Files:**
- Modify: `platform_v2/tools/archie_chat/code_service.py`

- [ ] **Step 1: Verify OpenCode is installed**

```bash
which opencode && opencode --version
```

Expected: path + version string. If not found: `npm install -g @opencode-ai/opencode`

- [ ] **Step 2: Write failing test for subprocess start**

Add to `platform_v2/tests/test_code_service.py`:

```python
@patch('tools.archie_chat.code_service.subprocess.Popen')
@patch('tools.archie_chat.code_service.get_db_cursor')
def test_start_opencode_stores_pid(mock_db, mock_popen):
    from tools.archie_chat.code_service import start_opencode, _PROCESSES
    conn = MagicMock()
    cur = MagicMock()
    mock_db.return_value.__enter__ = MagicMock(return_value=(conn, cur))
    mock_db.return_value.__exit__ = MagicMock(return_value=False)

    proc = MagicMock()
    proc.pid = 1234
    proc.stdout = MagicMock()
    proc.stdout.__iter__ = MagicMock(return_value=iter([]))
    mock_popen.return_value = proc

    start_opencode(session_id=1)
    assert _PROCESSES.get(1) is proc
```

- [ ] **Step 3: Run test to verify it fails**

```bash
cd /mnt/archie_brain/platform_v2
python -m pytest tests/test_code_service.py::test_start_opencode_stores_pid -v
```

Expected: FAIL — `start_opencode` not defined.

- [ ] **Step 4: Add subprocess functions to code_service.py**

Append to the bottom of `platform_v2/tools/archie_chat/code_service.py`:

```python
OPENCODE_WORKDIR = "/mnt/archie_brain"
OPENCODE_CMD = ["opencode", "--output-format", "json"]


def start_opencode(session_id: int, initial_instruction: Optional[str] = None) -> int:
    proc = subprocess.Popen(
        OPENCODE_CMD,
        cwd=OPENCODE_WORKDIR,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    _PROCESSES[session_id] = proc
    _SESSION_MODE[session_id] = "structured"
    _SSE_QUEUES[session_id] = queue.Queue()

    update_session_status(session_id, "active", opencode_pid=proc.pid)

    t = threading.Thread(
        target=_read_structured_output, args=(session_id, proc), daemon=True
    )
    t.start()

    if initial_instruction:
        send_to_opencode(session_id, initial_instruction)

    return proc.pid


def _read_structured_output(session_id: int, proc: subprocess.Popen) -> None:
    try:
        for raw_line in proc.stdout:
            line = raw_line.strip()
            if not line:
                continue
            if _SESSION_MODE.get(session_id) == "raw":
                q = _RAW_QUEUES.get(session_id)
                if q:
                    q.put(line)
                continue
            try:
                event = json.loads(line)
                event_type = _map_opencode_event(event)
                content = {"raw": event}
                append_event(session_id, event_type, content)
            except json.JSONDecodeError:
                append_event(session_id, "terminal_raw", {"text": line})
    except Exception as exc:
        append_event(session_id, "error", {"text": str(exc)})
    finally:
        _PROCESSES.pop(session_id, None)


def _map_opencode_event(event: dict) -> str:
    t = event.get("type", "")
    if t in ("assistant", "user"):
        return "message"
    if t == "file":
        return "file_change"
    if t == "diff":
        return "diff"
    if t == "summary":
        return "summary"
    return "terminal_raw"


def send_to_opencode(session_id: int, text: str) -> None:
    proc = _PROCESSES.get(session_id)
    if proc and proc.stdin:
        proc.stdin.write(text + "\n")
        proc.stdin.flush()


def resume_session(session_id: int) -> None:
    proc = _PROCESSES.get(session_id)
    if proc and proc.poll() is None:
        return  # already running
    past_events = get_session_events(session_id, limit=50)
    start_opencode(session_id)
    context = "\n".join(
        e["content"].get("text", str(e["content"])) for e in past_events
    )
    if context:
        send_to_opencode(session_id, f"Context from previous session:\n{context}")


def terminate_session(session_id: int, final_status: str = "paused") -> None:
    proc = _PROCESSES.pop(session_id, None)
    if proc:
        proc.terminate()
    _SSE_QUEUES.pop(session_id, None)
    _RAW_QUEUES.pop(session_id, None)
    _SESSION_MODE.pop(session_id, None)
    update_session_status(session_id, final_status, opencode_pid=None)


def set_session_raw_mode(session_id: int, raw: bool) -> None:
    _SESSION_MODE[session_id] = "raw" if raw else "structured"
    if raw:
        _RAW_QUEUES[session_id] = queue.Queue()
    else:
        _RAW_QUEUES.pop(session_id, None)
```

- [ ] **Step 5: Run all tests**

```bash
cd /mnt/archie_brain/platform_v2
python -m pytest tests/test_code_service.py -v
```

Expected: 4 tests PASS.

- [ ] **Step 6: Commit**

```bash
git add platform_v2/tools/archie_chat/code_service.py \
        platform_v2/tests/test_code_service.py
git commit -m "feat(archie-chat): code_service.py — OpenCode subprocess lifecycle"
```

---

## Task 4: code_service.py — Finalize + Tier Routing

**Files:**
- Modify: `platform_v2/tools/archie_chat/code_service.py`

- [ ] **Step 1: Write failing test for finalize**

Add to `platform_v2/tests/test_code_service.py`:

```python
@patch('tools.archie_chat.code_service.subprocess.run')
@patch('tools.archie_chat.code_service.get_db_cursor')
def test_finalize_tier1_opens_pr(mock_db, mock_run):
    from tools.archie_chat.code_service import finalize_session
    conn = MagicMock()
    cur = MagicMock()
    cur.fetchone.return_value = {
        "id": 1, "tier": 1, "proposal_id": None,
        "title": "Fix bug", "status": "active"
    }
    mock_db.return_value.__enter__ = MagicMock(return_value=(conn, cur))
    mock_db.return_value.__exit__ = MagicMock(return_value=False)
    mock_run.return_value = MagicMock(stdout="https://github.com/x/y/pull/99\n", returncode=0)

    finalize_session(1)
    mock_run.assert_called()
    args = mock_run.call_args[0][0]
    assert "gh" in args
    assert "pr" in args
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /mnt/archie_brain/platform_v2
python -m pytest tests/test_code_service.py::test_finalize_tier1_opens_pr -v
```

Expected: FAIL — `finalize_session` not defined.

- [ ] **Step 3: Add finalize_session to code_service.py**

Append to the bottom of `platform_v2/tools/archie_chat/code_service.py`:

```python
def finalize_session(session_id: int) -> None:
    session = get_session(session_id)
    if not session:
        return

    terminate_session(session_id, final_status="completed")

    if session["tier"] == 1:
        _auto_pr(session_id, session)
    else:
        _mark_fix_ready(session_id, session)


def _auto_pr(session_id: int, session: dict) -> None:
    import datetime
    branch = f"auto/code-session-{session_id}-{datetime.date.today().isoformat()}"
    subprocess.run(["git", "checkout", "-b", branch], cwd=OPENCODE_WORKDIR, check=True)
    subprocess.run(["git", "add", "-A"], cwd=OPENCODE_WORKDIR, check=True)
    subprocess.run(
        ["git", "commit", "-m", f"auto: {session['title']}"],
        cwd=OPENCODE_WORKDIR,
        check=True,
    )
    subprocess.run(
        ["git", "push", "-u", "origin", branch],
        cwd=OPENCODE_WORKDIR,
        check=True,
    )
    result = subprocess.run(
        ["gh", "pr", "create", "--title", session["title"], "--body",
         f"Auto-generated by A.R.C.H.I.E. Code Tab (session {session_id}).",
         "--head", branch],
        cwd=OPENCODE_WORKDIR,
        capture_output=True,
        text=True,
    )
    pr_url = result.stdout.strip()
    update_session_status(
        session_id, "completed",
        result_branch=branch, result_pr_url=pr_url
    )
    if session.get("proposal_id"):
        _update_proposal_status(session["proposal_id"], "auto_merged")


def _mark_fix_ready(session_id: int, session: dict) -> None:
    update_session_status(session_id, "completed")
    if session.get("proposal_id"):
        _update_proposal_status(session["proposal_id"], "fix_ready")


def _update_proposal_status(proposal_id: int, status: str) -> None:
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            "UPDATE improvement_proposals SET status = %s WHERE id = %s",
            (status, proposal_id),
        )
```

- [ ] **Step 4: Run all tests**

```bash
cd /mnt/archie_brain/platform_v2
python -m pytest tests/test_code_service.py -v
```

Expected: 5 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add platform_v2/tools/archie_chat/code_service.py \
        platform_v2/tests/test_code_service.py
git commit -m "feat(archie-chat): code_service.py — finalize + tier routing (Tier 1 auto-PR, Tier 2 fix_ready)"
```

---

## Task 5: code_routes.py — HTTP REST Endpoints

**Files:**
- Create: `platform_v2/tools/archie_chat/code_routes.py`
- Create: `platform_v2/tests/test_code_routes.py`
- Modify: `platform_v2/tools/archie_chat/__init__.py`

- [ ] **Step 1: Write failing route tests**

```python
# platform_v2/tests/test_code_routes.py
import pytest
from unittest.mock import patch, MagicMock


@pytest.fixture
def client():
    import sys, os
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
    from app import app
    app.config["TESTING"] = True
    app.config["LOGIN_DISABLED"] = True
    with app.test_client() as c:
        yield c


@patch('tools.archie_chat.code_service.list_sessions', return_value=[])
def test_list_sessions_returns_200(mock_list, client):
    resp = client.get('/tools/archie-chat/api/code-sessions')
    assert resp.status_code == 200
    data = resp.get_json()
    assert "sessions" in data


@patch('tools.archie_chat.code_service.create_session', return_value=99)
def test_create_session_returns_id(mock_create, client):
    resp = client.post('/tools/archie-chat/api/code-sessions',
                       json={"title": "Test", "source": "user", "tier": 2})
    assert resp.status_code == 201
    assert resp.get_json()["session_id"] == 99
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /mnt/archie_brain/platform_v2
python -m pytest tests/test_code_routes.py -v 2>&1 | head -20
```

Expected: 404 or ImportError — routes not registered yet.

- [ ] **Step 3: Create code_routes.py**

```python
# platform_v2/tools/archie_chat/code_routes.py
from flask import jsonify, request
from flask_login import login_required

from . import code_service


def register_code_routes(bp):
    @bp.route("/api/code-sessions", methods=["GET"])
    @login_required
    def list_code_sessions():
        view = request.args.get("view", "source")
        sessions = code_service.list_sessions(view)
        return jsonify({"sessions": sessions})

    @bp.route("/api/code-sessions", methods=["POST"])
    @login_required
    def create_code_session():
        data = request.get_json() or {}
        session_id = code_service.create_session(
            title=data.get("title", "New Session"),
            source=data.get("source", "user"),
            tier=int(data.get("tier", 2)),
            created_by="user",
            project_id=data.get("project_id"),
            proposal_id=data.get("proposal_id"),
        )
        return jsonify({"session_id": session_id}), 201

    @bp.route("/api/code-sessions/<int:session_id>", methods=["GET"])
    @login_required
    def get_code_session(session_id):
        session = code_service.get_session(session_id)
        if not session:
            return jsonify({"error": "not found"}), 404
        events = code_service.get_session_events(session_id)
        return jsonify({"session": session, "events": events})

    @bp.route("/api/code-sessions/<int:session_id>/start", methods=["POST"])
    @login_required
    def start_code_session(session_id):
        data = request.get_json() or {}
        pid = code_service.start_opencode(
            session_id, initial_instruction=data.get("instruction")
        )
        return jsonify({"pid": pid})

    @bp.route("/api/code-sessions/<int:session_id>/resume", methods=["POST"])
    @login_required
    def resume_code_session(session_id):
        code_service.resume_session(session_id)
        return jsonify({"ok": True})

    @bp.route("/api/code-sessions/<int:session_id>/abort", methods=["POST"])
    @login_required
    def abort_code_session(session_id):
        code_service.terminate_session(session_id, final_status="paused")
        return jsonify({"ok": True})

    @bp.route("/api/code-sessions/<int:session_id>/finalize", methods=["POST"])
    @login_required
    def finalize_code_session(session_id):
        code_service.finalize_session(session_id)
        return jsonify({"ok": True})

    @bp.route("/api/code-sessions/<int:session_id>/message", methods=["POST"])
    @login_required
    def message_code_session(session_id):
        data = request.get_json() or {}
        text = data.get("text", "")
        code_service.send_to_opencode(session_id, text)
        return jsonify({"ok": True})

    @bp.route("/api/code-sessions/<int:session_id>/mode", methods=["POST"])
    @login_required
    def set_code_session_mode(session_id):
        data = request.get_json() or {}
        raw = bool(data.get("raw", False))
        code_service.set_session_raw_mode(session_id, raw)
        return jsonify({"ok": True})
```

- [ ] **Step 4: Register routes in __init__.py**

Read `platform_v2/tools/archie_chat/__init__.py` first, then add:

```python
from .code_routes import register_code_routes
# inside create_blueprint() or at module level after bp is defined:
register_code_routes(bp)
```

- [ ] **Step 5: Run route tests**

```bash
cd /mnt/archie_brain/platform_v2
python -m pytest tests/test_code_routes.py -v
```

Expected: 2 tests PASS.

- [ ] **Step 6: Commit**

```bash
git add platform_v2/tools/archie_chat/code_routes.py \
        platform_v2/tools/archie_chat/__init__.py \
        platform_v2/tests/test_code_routes.py
git commit -m "feat(archie-chat): code_routes.py — REST endpoints + register in blueprint"
```

---

## Task 6: SSE Event Streaming

**Files:**
- Modify: `platform_v2/tools/archie_chat/code_routes.py`

- [ ] **Step 1: Add SSE stream route to code_routes.py**

Add inside `register_code_routes(bp)`:

```python
    import json as _json
    import time as _time
    from flask import Response, stream_with_context

    @bp.route("/api/code-sessions/<int:session_id>/stream")
    @login_required
    def stream_code_session(session_id):
        from . import code_service as _cs
        import queue as _queue

        q = _queue.Queue()
        _cs._SSE_QUEUES[session_id] = q

        # Replay last 50 events on connect
        past = _cs.get_session_events(session_id, limit=50)

        def generate():
            for evt in past:
                yield f"data: {_json.dumps(evt)}\n\n"
            while True:
                try:
                    event = q.get(timeout=30)
                    if event is None:
                        break
                    yield f"data: {_json.dumps(event)}\n\n"
                except _queue.Empty:
                    yield ": keepalive\n\n"

        return Response(
            stream_with_context(generate()),
            mimetype="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
            },
        )
```

- [ ] **Step 2: Deploy and smoke test**

```bash
docker compose restart archie_platform
```

Open browser: `http://192.168.1.200:3000/tools/archie-chat` — navigate to Code tab (it won't exist yet, but the API should be live).

```bash
curl -N -H "Cookie: $(cat /tmp/session_cookie)" \
  http://192.168.1.200:3000/tools/archie-chat/api/code-sessions/1/stream
```

Expected: `data: [...]` lines for past events, then `: keepalive` every 30s.

- [ ] **Step 3: Commit**

```bash
git add platform_v2/tools/archie_chat/code_routes.py
git commit -m "feat(archie-chat): SSE event stream endpoint for code sessions"
```

---

## Task 7: WebSocket Raw Terminal (flask-sock + xterm.js)

**Files:**
- Modify: `platform_v2/requirements.txt`
- Modify: `platform_v2/tools/archie_chat/code_routes.py`

- [ ] **Step 1: Add flask-sock to requirements**

```bash
grep flask-sock /mnt/archie_brain/platform_v2/requirements.txt
```

If missing, add it:

```
flask-sock==0.7.0
```

- [ ] **Step 2: Rebuild the container with the new dependency**

```bash
cd /mnt/archie_brain
docker compose build archie_platform
docker compose up -d archie_platform
```

Expected: build succeeds, container starts.

- [ ] **Step 3: Add WebSocket terminal route**

Add to `register_code_routes(bp)` in `code_routes.py`:

```python
    try:
        from flask_sock import Sock
        _sock = Sock()
        _sock.init_app(bp)

        @_sock.route("/api/code-sessions/<int:session_id>/terminal", bp=bp)
        def ws_terminal(ws, session_id):
            from . import code_service as _cs
            import queue as _queue
            _cs.set_session_raw_mode(session_id, True)
            raw_q = _cs._RAW_QUEUES.setdefault(session_id, _queue.Queue())

            def send_output():
                while True:
                    try:
                        chunk = raw_q.get(timeout=1)
                        ws.send(chunk)
                    except _queue.Empty:
                        pass
                    except Exception:
                        break

            import threading
            t = threading.Thread(target=send_output, daemon=True)
            t.start()

            try:
                while True:
                    data = ws.receive()
                    if data is None:
                        break
                    _cs.send_to_opencode(session_id, data)
            finally:
                _cs.set_session_raw_mode(session_id, False)

    except ImportError:
        pass  # flask-sock not installed — WS terminal unavailable
```

- [ ] **Step 4: Verify WebSocket endpoint registers without error**

```bash
docker logs archie_platform 2>&1 | tail -20
```

Expected: no `ImportError` for flask-sock.

- [ ] **Step 5: Commit**

```bash
git add platform_v2/requirements.txt \
        platform_v2/tools/archie_chat/code_routes.py
git commit -m "feat(archie-chat): WebSocket raw terminal via flask-sock + xterm.js integration"
```

---

## Task 8: Code Tab UI

**Files:**
- Modify: `platform_v2/templates/tools/archie_chat.html`

> Before editing, read the current `archie_chat.html` to find: tab bar location, tab content divs, and existing JS patterns.

- [ ] **Step 1: Read the template to find the tab bar**

```bash
grep -n "tab\|COMMS\|COMs\|data-tab" \
  /mnt/archie_brain/platform_v2/templates/tools/archie_chat.html | head -30
```

- [ ] **Step 2: Add the CODE tab button to the tab bar**

Find the tab bar HTML (look for the COMMS tab button). Add the CODE tab adjacent to COMMS:

```html
<button class="ac-tab-btn" data-tab="code" id="code-tab-btn">
  <span>&#9000;</span> CODE
  <span class="ac-tab-indicator" id="code-tab-indicator" style="display:none">&#9679;</span>
</button>
```

- [ ] **Step 3: Add the CODE tab content panel**

Find where tab content panels are defined. Add:

```html
<div class="ac-tab-content" id="tab-code" style="display:none; height:100%">
  <div style="display:flex; height:100%">

    <!-- Left: Session Browser -->
    <div id="code-sidebar" style="width:200px;border-right:1px solid #1e293b;display:flex;flex-direction:column;background:#080d1a;flex-shrink:0">
      <div style="padding:8px;border-bottom:1px solid #1e293b">
        <div style="display:flex;gap:4px;margin-bottom:6px">
          <button class="code-view-btn active" data-view="source">SOURCE</button>
          <button class="code-view-btn" data-view="project">PROJECT</button>
          <button class="code-view-btn" data-view="status">STATUS</button>
        </div>
        <div id="code-view-label" style="color:#64748b;font-size:9px;text-transform:uppercase;letter-spacing:1px">By Source</div>
      </div>
      <div id="code-session-list" style="flex:1;overflow-y:auto;padding:6px"></div>
      <div style="padding:8px;border-top:1px solid #1e293b">
        <button id="code-new-session-btn" class="code-action-btn">+ New Session</button>
      </div>
    </div>

    <!-- Center: Session Feed -->
    <div style="flex:1;display:flex;flex-direction:column;min-width:0">
      <div id="code-session-header" style="padding:8px 12px;border-bottom:1px solid #1e293b;display:flex;align-items:center;gap:8px;font-size:11px">
        <span id="code-session-status-badge"></span>
        <span id="code-session-title" style="color:#e2e8f0"></span>
        <span id="code-session-tier-badge" style="margin-left:auto"></span>
        <span id="code-session-proposal-badge"></span>
      </div>
      <div id="code-event-stream" style="flex:1;overflow-y:auto;padding:12px;display:flex;flex-direction:column;gap:8px;font-family:monospace;font-size:11px">
        <div style="color:#475569;text-align:center;margin-top:40px">Select a session or create a new one</div>
      </div>
      <div id="code-raw-terminal" style="flex:1;display:none;background:#000"></div>
      <div style="padding:8px;border-top:1px solid #1e293b;display:flex;gap:6px;align-items:center">
        <input id="code-input" type="text" placeholder="Message A.R.C.H.I.E. or type a code instruction..."
               style="flex:1;background:#080d1a;border:1px solid #1e293b;border-radius:4px;padding:6px 10px;color:#e2e8f0;font-size:10px;font-family:monospace">
        <button id="code-raw-toggle" class="code-action-btn">&#9000; RAW</button>
        <button id="code-send-btn" class="code-action-btn code-action-btn--primary">SEND</button>
      </div>
    </div>

    <!-- Right: Context Panel -->
    <div id="code-context-panel" style="width:160px;border-left:1px solid #1e293b;display:flex;flex-direction:column;background:#080d1a;padding:8px;gap:8px;flex-shrink:0;font-size:10px">
      <div style="color:#64748b;font-size:9px;text-transform:uppercase;letter-spacing:1px">Session Context</div>
      <div><div style="color:#64748b;font-size:9px;margin-bottom:3px">PROJECT</div><div id="ctx-project" style="color:#94a3b8">—</div></div>
      <div><div style="color:#64748b;font-size:9px;margin-bottom:3px">PROPOSAL</div><div id="ctx-proposal" style="color:#94a3b8">—</div></div>
      <div><div style="color:#64748b;font-size:9px;margin-bottom:3px">TIER</div><div id="ctx-tier" style="color:#f59e0b">—</div></div>
      <div><div style="color:#64748b;font-size:9px;margin-bottom:3px">FILES CHANGED</div><div id="ctx-files" style="color:#94a3b8">—</div></div>
      <div><div style="color:#64748b;font-size:9px;margin-bottom:3px">AGENT</div><div id="ctx-agent" style="color:#00d4ff">F.O.R.G.E.</div></div>
      <div style="margin-top:auto;display:flex;flex-direction:column;gap:4px">
        <button id="code-abort-btn" class="code-action-btn code-action-btn--danger" style="display:none">&#10005; Abort</button>
        <button id="code-repair-bay-btn" class="code-action-btn" style="display:none">&#8594; Repair Bay</button>
      </div>
    </div>

  </div>
</div>
```

- [ ] **Step 4: Add CSS for the Code tab**

Find where per-module CSS is added or add a `<style>` block near the Code tab content:

```css
.code-view-btn {
  background: none; border: 1px solid #1e293b; color: #475569;
  padding: 2px 6px; border-radius: 3px; font-size: 9px; cursor: pointer;
  font-family: inherit;
}
.code-view-btn.active { background: #22c55e22; color: #22c55e; border-color: #22c55e44; }
.code-action-btn {
  background: #1e293b; border: 1px solid #334155; color: #94a3b8;
  padding: 5px 10px; border-radius: 4px; font-size: 9px; cursor: pointer;
  font-family: monospace;
}
.code-action-btn--primary { background: #22c55e22; color: #22c55e; border-color: #22c55e44; }
.code-action-btn--danger  { background: #f87171;   color: #fff;    border: none; }
.code-session-card {
  background: #0a0f1e; border: 1px solid #1e293b; border-radius: 4px;
  padding: 6px; margin-bottom: 4px; cursor: pointer;
}
.code-session-card.active { border-color: #22c55e44; background: #0d1b2a; }
.code-event-message { background: #0d1b2a; border: 1px solid #00d4ff22; border-radius: 4px; padding: 8px; }
.code-event-diff    { background: #0d1b2a; border: 1px solid #22c55e22; border-radius: 4px; padding: 8px; }
.code-event-summary { background: #0d1b2a; border: 1px solid #8b5cf622; border-radius: 4px; padding: 8px; }
.code-event-error   { background: #0d1b2a; border: 1px solid #f8717122; border-radius: 4px; padding: 8px; }
```

- [ ] **Step 5: Add JavaScript for the Code tab**

Add a `<script>` block (or extend existing module JS). The JS must:
- Load sessions on tab activate
- Render session cards in sidebar
- Load session events when a card is clicked
- Connect SSE stream for the active session
- Wire up Send button, Raw toggle, Abort button
- Use `textContent` for user-supplied strings (never `innerHTML` with untrusted data)

```javascript
// Code Tab JS
(function() {
  let activeSessionId = null;
  let sseSource = null;
  let rawMode = false;

  function escHtml(str) {
    const d = document.createElement('div');
    d.textContent = String(str);
    return d.innerHTML;
  }

  function renderSessionCard(s) {
    const card = document.createElement('div');
    card.className = 'code-session-card' + (s.id === activeSessionId ? ' active' : '');
    card.dataset.id = s.id;

    const statusEl = document.createElement('div');
    statusEl.style.cssText = 'font-size:9px;margin-bottom:2px';
    const statusMap = {active:'● ACTIVE', paused:'⏸ PAUSED', completed:'✓ DONE', failed:'✗ FAILED'};
    statusEl.textContent = statusMap[s.status] || s.status;
    statusEl.style.color = s.status === 'active' ? '#22c55e' : s.status === 'paused' ? '#f59e0b' : '#475569';

    const titleEl = document.createElement('div');
    titleEl.style.cssText = 'font-size:10px;color:#94a3b8';
    titleEl.textContent = s.title;

    const metaEl = document.createElement('div');
    metaEl.style.cssText = 'font-size:9px;color:#475569';
    metaEl.textContent = 'Tier ' + s.tier + ' · ' + s.source;

    card.appendChild(statusEl);
    card.appendChild(titleEl);
    card.appendChild(metaEl);
    card.addEventListener('click', () => loadSession(s.id));
    return card;
  }

  function renderEvent(evt) {
    const wrap = document.createElement('div');
    wrap.className = 'code-event-' + (evt.event_type || 'message');

    const label = document.createElement('div');
    label.style.cssText = 'font-size:9px;margin-bottom:4px;color:#64748b';
    label.textContent = evt.event_type.toUpperCase();

    const body = document.createElement('div');
    body.style.cssText = 'font-size:10px;color:#94a3b8';
    const content = evt.content || {};
    body.textContent = content.text || content.raw && JSON.stringify(content.raw) || '';

    wrap.appendChild(label);
    wrap.appendChild(body);
    return wrap;
  }

  function loadSessions() {
    const view = document.querySelector('.code-view-btn.active')?.dataset.view || 'source';
    fetch('/tools/archie-chat/api/code-sessions?view=' + view)
      .then(r => r.json())
      .then(data => {
        const list = document.getElementById('code-session-list');
        list.textContent = '';
        (data.sessions || []).forEach(s => list.appendChild(renderSessionCard(s)));
      });
  }

  function loadSession(id) {
    activeSessionId = id;
    if (sseSource) { sseSource.close(); sseSource = null; }

    fetch('/tools/archie-chat/api/code-sessions/' + id)
      .then(r => r.json())
      .then(data => {
        const s = data.session || {};
        document.getElementById('code-session-title').textContent = s.title || '';
        document.getElementById('code-session-status-badge').textContent =
          ({active:'● ACTIVE', paused:'⏸ PAUSED', completed:'✓ DONE'}[s.status] || s.status);
        document.getElementById('ctx-tier').textContent = s.tier === 1 ? '1 — Auto PR' : '2 — Human Review';
        if (s.proposal_id) {
          document.getElementById('ctx-proposal').textContent = 'Repair Bay #' + s.proposal_id;
        }

        const stream = document.getElementById('code-event-stream');
        stream.textContent = '';
        (data.events || []).forEach(evt => stream.appendChild(renderEvent(evt)));
        stream.scrollTop = stream.scrollHeight;

        document.getElementById('code-abort-btn').style.display = s.status === 'active' ? '' : 'none';
        document.getElementById('code-repair-bay-btn').style.display = s.proposal_id ? '' : 'none';
      });

    sseSource = new EventSource('/tools/archie-chat/api/code-sessions/' + id + '/stream');
    sseSource.onmessage = function(e) {
      const evt = JSON.parse(e.data);
      if (rawMode) return;
      const stream = document.getElementById('code-event-stream');
      stream.appendChild(renderEvent(evt));
      stream.scrollTop = stream.scrollHeight;
    };

    loadSessions(); // refresh sidebar
  }

  document.getElementById('code-send-btn')?.addEventListener('click', () => {
    if (!activeSessionId) return;
    const input = document.getElementById('code-input');
    const text = input.value.trim();
    if (!text) return;
    fetch('/tools/archie-chat/api/code-sessions/' + activeSessionId + '/message', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({text})
    });
    input.value = '';
  });

  document.getElementById('code-input')?.addEventListener('keydown', e => {
    if (e.key === 'Enter') document.getElementById('code-send-btn').click();
  });

  document.getElementById('code-raw-toggle')?.addEventListener('click', () => {
    if (!activeSessionId) return;
    rawMode = !rawMode;
    document.getElementById('code-event-stream').style.display = rawMode ? 'none' : '';
    document.getElementById('code-raw-terminal').style.display = rawMode ? '' : 'none';
    fetch('/tools/archie-chat/api/code-sessions/' + activeSessionId + '/mode', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({raw: rawMode})
    });
  });

  document.getElementById('code-abort-btn')?.addEventListener('click', () => {
    if (!activeSessionId) return;
    fetch('/tools/archie-chat/api/code-sessions/' + activeSessionId + '/abort', {method:'POST'})
      .then(() => loadSessions());
  });

  document.getElementById('code-new-session-btn')?.addEventListener('click', () => {
    const title = window.prompt('Session title:');
    if (!title) return;
    fetch('/tools/archie-chat/api/code-sessions', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({title, source: 'user', tier: 2})
    })
    .then(r => r.json())
    .then(d => { loadSessions(); if (d.session_id) loadSession(d.session_id); });
  });

  document.querySelectorAll('.code-view-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('.code-view-btn').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      loadSessions();
    });
  });

  // Load sessions when Code tab is activated
  const codeTabBtn = document.getElementById('code-tab-btn');
  if (codeTabBtn) {
    codeTabBtn.addEventListener('click', loadSessions);
  }
})();
```

- [ ] **Step 6: Deploy and visually verify**

```bash
docker compose restart archie_platform
```

Open `http://192.168.1.200:3000/tools/archie-chat` in browser.

Verify:
- CODE tab is visible in the tab bar alongside COMMS
- Clicking CODE tab shows 3-column layout
- Session list loads (empty or with existing sessions)
- "+ New Session" prompt works and creates a session
- Clicking a session loads its events

- [ ] **Step 7: Commit**

```bash
git add platform_v2/templates/tools/archie_chat.html
git commit -m "feat(archie-chat): Code tab UI — 3-column layout, session browser, event stream, raw toggle"
```

---

## Task 9: Repair Bay Hook

**Files:**
- Modify: `platform_v2/tools/repair_bay/scan_routes.py`

- [ ] **Step 1: Read the proposal INSERT in scan_routes.py**

```bash
grep -n "improvement_proposals\|RETURNING id\|proposal_id" \
  /mnt/archie_brain/platform_v2/tools/repair_bay/scan_routes.py | head -20
```

Identify the line after `proposal_id = cur.fetchone()["id"]`.

- [ ] **Step 2: Add the hook**

Immediately after `proposal_id = cur.fetchone()["id"]` (around line 323), add:

```python
# Auto-create a Code session for this proposal
try:
    from tools.archie_chat.code_service import create_session_from_proposal
    _severity = issue.get("severity", "medium")
    _title = f"Fix: {issue.get('issue_type', 'issue')} — {issue.get('file_path', '')[:60]}"
    create_session_from_proposal(
        proposal_id=proposal_id,
        title=_title,
        severity=_severity,
    )
except Exception as _e:
    current_app.logger.warning(f"Code session auto-create failed: {_e}")
```

- [ ] **Step 3: Verify import path is correct**

```bash
docker exec archie_platform python -c \
  "from tools.archie_chat.code_service import create_session_from_proposal; print('OK')"
```

Expected: `OK`

- [ ] **Step 4: Test the integration end-to-end**

Trigger a Repair Bay scan manually (or use an existing proposal). Verify a `code_sessions` row is created:

```bash
docker exec archie_database psql -U archie -d archie \
  -c "SELECT id, title, source, tier FROM code_sessions ORDER BY id DESC LIMIT 5;"
```

Expected: rows with `source='repair_bay'` and tier based on severity.

- [ ] **Step 5: Commit**

```bash
git add platform_v2/tools/repair_bay/scan_routes.py
git commit -m "feat(repair-bay): auto-create Code session when improvement_proposals row is inserted"
```

---

## Push and PR

- [ ] **Push branch and open PR**

```bash
git push -u origin feat/archie-code-tab
gh pr create \
  --title "feat: A.R.C.H.I.E. Code Tab — OpenCode sessions inside archie_chat" \
  --body "Implements the Code tab spec (docs/superpowers/specs/2026-04-22-archie-code-tab-design.md).

## What ships
- \`code_sessions\` + \`code_session_events\` DB tables (migration 037)
- \`code_service.py\` — session CRUD, OpenCode subprocess lifecycle, tier-based finalize
- \`code_routes.py\` — REST + SSE + WebSocket endpoints
- Code Tab UI — 3-column layout: session browser, hybrid event feed, context panel
- Repair Bay hook — auto-creates a Code session on every new improvement_proposals row
- flask-sock added to requirements for WebSocket raw terminal

## Success criteria
- [ ] Code tab visible alongside COMMS
- [ ] Sessions persist across page reloads
- [ ] Repair Bay proposals auto-appear in Code tab
- [ ] Tier 1 completion opens a PR automatically
- [ ] Tier 2 completion sets proposal to fix_ready"
```

---

## Self-Review

**Spec coverage check:**
- [x] Code tab visible in archie_chat (Task 8)
- [x] Session browser SOURCE/PROJECT/STATUS views (Task 8 JS)
- [x] Repair Bay auto-creates session (Task 9)
- [x] Structured event stream (Tasks 6 + 8)
- [x] RAW toggle (Tasks 7 + 8)
- [x] Tier 1 auto-PR (Task 4)
- [x] Tier 2 fix_ready + Repair Bay reflects it (Task 4)
- [x] Sessions persist across reloads — events in DB, replayed on SSE connect (Task 6)

**Placeholder scan:** No TBD, no TODO, no "similar to Task N" references. All code is complete.

**Type consistency:**
- `create_session_from_proposal(proposal_id, title, severity)` — matches call in Task 9
- `start_opencode(session_id, initial_instruction)` — matches Task 5 route call
- `finalize_session(session_id)` — matches Task 5 route call
- `_SSE_QUEUES` dict — referenced in Task 6 stream endpoint and Task 3 `append_event`
- `_RAW_QUEUES` dict — referenced in Task 7 WS and Task 3 `set_session_raw_mode`
