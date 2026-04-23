"""
ARCHIE Chat — Code Session Service

Session CRUD and event persistence for the Code Tab feature.
Uses `opencode serve` HTTP API for all LLM interaction — no TUI subprocess.

One shared opencode server per platform process (lazy-started). Sessions are
tracked in-memory; the opencode server holds its own SQLite state.
"""

import json
import os
import queue
import subprocess
import threading
import time
import urllib.error
import urllib.request
from typing import Optional

import psycopg2.extras

from database import get_db_cursor

# ---------------------------------------------------------------------------
# In-memory state
# ---------------------------------------------------------------------------

_SSE_QUEUES: dict = {}  # session_id -> {conn_id: queue.Queue}
_RAW_QUEUES: dict = {}  # session_id -> queue.Queue
_SESSION_MODE: dict = {}  # session_id -> 'structured' | 'raw'
_OPENCODE_SESSIONS: dict = {}  # session_id -> opencode internal session ID (str)

# ---------------------------------------------------------------------------
# OpenCode server config
# ---------------------------------------------------------------------------

OPENCODE_WORKDIR = "/mnt/archie_brain"
OPENCODE_BINARY = os.environ.get("OPENCODE_BINARY", "/mnt/archie_brain/scripts/opencode")
OPENCODE_SERVER_PORT = int(os.environ.get("OPENCODE_SERVER_PORT", "19998"))
_OPENCODE_URL = f"http://127.0.0.1:{OPENCODE_SERVER_PORT}"

_server_proc: Optional[subprocess.Popen] = None
_server_lock = threading.Lock()


# ---------------------------------------------------------------------------
# Session CRUD
# ---------------------------------------------------------------------------


def create_session(
    title: str,
    source: str,
    tier: int,
    created_by: str,
    project_id: int = None,
    proposal_id: int = None,
    conversation_id: int = None,
) -> int:
    """INSERT a new code session and return its id."""
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            """
            INSERT INTO code_sessions
                (title, source, tier, created_by, project_id, proposal_id,
                 conversation_id, status, created_at)
            VALUES
                (%s, %s, %s, %s, %s, %s, %s, 'active', NOW())
            RETURNING id
            """,
            (title, source, tier, created_by, project_id, proposal_id, conversation_id),
        )
        row = cur.fetchone()
    return row["id"]


def create_session_from_proposal(proposal_id: int, title: str, severity: str) -> int:
    """Create a code session seeded from a Repair Bay proposal."""
    tier = 1 if severity == "low" else 2
    return create_session(
        title=title,
        source="repair_bay",
        tier=tier,
        created_by="archie",
        proposal_id=proposal_id,
    )


def get_session(session_id: int) -> Optional[dict]:
    """Fetch a single code session by id."""
    with get_db_cursor(commit=False) as (conn, cur):
        cur.execute("SELECT * FROM code_sessions WHERE id = %s", (session_id,))
        row = cur.fetchone()
    return dict(row) if row else None


def list_sessions(view: str = "source") -> list:
    """List all code sessions ordered by most recent first."""
    with get_db_cursor(commit=False) as (conn, cur):
        cur.execute("SELECT * FROM code_sessions ORDER BY created_at DESC")
        rows = cur.fetchall()
    return [dict(r) for r in rows]


def update_session_status(session_id: int, status: str, **kwargs) -> None:
    """Update the status of a code session, plus any optional fields."""
    _col_map = {
        "opencode_pid": "opencode_pid = %s",
        "result_branch": "result_branch = %s",
        "result_pr_url": "result_pr_url = %s",
        "completed_at": "completed_at = %s",
    }
    set_clauses = ["status = %s"]
    values = [status]
    for key, fragment in _col_map.items():
        if key in kwargs:
            set_clauses.append(fragment)
            values.append(kwargs[key])
    values.append(session_id)
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            f"UPDATE code_sessions SET {', '.join(set_clauses)} WHERE id = %s",
            values,
        )


# ---------------------------------------------------------------------------
# Event log
# ---------------------------------------------------------------------------


def append_event(session_id: int, event_type: str, content: dict) -> None:
    """Persist a session event and push it to all live SSE queues."""
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            """
            INSERT INTO code_session_events
                (session_id, event_type, content, created_at)
            VALUES (%s, %s, %s, NOW())
            """,
            (session_id, event_type, psycopg2.extras.Json(content)),
        )
    payload = {"event_type": event_type, "content": content}
    for q in list(_SSE_QUEUES.get(session_id, {}).values()):
        try:
            q.put_nowait(payload)
        except Exception:
            pass


def get_session_events(session_id: int, limit: int = 200) -> list:
    """Fetch the most recent events for a session, oldest-first."""
    with get_db_cursor(commit=False) as (conn, cur):
        cur.execute(
            """
            SELECT id, event_type, content, created_at
            FROM code_session_events
            WHERE session_id = %s
            ORDER BY id DESC
            LIMIT %s
            """,
            (session_id, limit),
        )
        rows = cur.fetchall()
    return [dict(r) for r in reversed(rows)]


# ---------------------------------------------------------------------------
# opencode server lifecycle
# ---------------------------------------------------------------------------


_OPENCODE_FREE_MODEL = "opencode/big-pickle"  # opencode hosted free model name (not Python pickle)


def _ensure_opencode_config() -> None:
    """Write /tmp/.config/opencode/config.json to pin the free provider model."""
    config_dir = "/tmp/.config/opencode"
    config_path = f"{config_dir}/config.json"
    os.makedirs(config_dir, exist_ok=True)
    if not os.path.exists(config_path):
        with open(config_path, "w") as f:
            json.dump({"model": _OPENCODE_FREE_MODEL}, f)


def _ensure_server_running() -> None:
    """Start the shared opencode serve process if it is not already up."""
    global _server_proc
    with _server_lock:
        if _server_proc and _server_proc.poll() is None:
            return
        _ensure_opencode_config()
        env = os.environ.copy()
        env["HOME"] = "/tmp"
        # Strip GITHUB_TOKEN so opencode does not auto-detect GitHub Copilot
        # and override the configured free provider.
        env.pop("GITHUB_TOKEN", None)
        env.pop("COPILOT_AGENT_HOST", None)
        _server_proc = subprocess.Popen(
            [OPENCODE_BINARY, "serve", "--port", str(OPENCODE_SERVER_PORT)],
            env=env,
            cwd=OPENCODE_WORKDIR,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        # Poll until the HTTP endpoint responds (max ~9 s)
        for _ in range(30):
            time.sleep(0.3)
            try:
                urllib.request.urlopen(f"{_OPENCODE_URL}/session", timeout=1)
                return
            except Exception:
                pass


def _http_post(url: str, payload: dict) -> dict:
    """POST JSON to opencode server; return parsed response dict."""
    data = json.dumps(payload).encode()
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"}, method="POST")
    r = urllib.request.urlopen(req, timeout=300)
    return json.loads(r.read().decode())


# ---------------------------------------------------------------------------
# OpenCode session lifecycle
# ---------------------------------------------------------------------------


def start_opencode(session_id: int, initial_instruction: Optional[str] = None) -> int:
    """Ensure server is running, create an opencode session, return server PID.

    Args:
        session_id: Our DB session id
        initial_instruction: Optional first message sent after session creation

    Returns:
        int: PID of the shared opencode server process (0 if unavailable)
    """
    _ensure_server_running()
    resp = _http_post(f"{_OPENCODE_URL}/session", {})
    opencode_session_id = resp["id"]
    _OPENCODE_SESSIONS[session_id] = opencode_session_id
    _SESSION_MODE[session_id] = "structured"
    _SSE_QUEUES.setdefault(session_id, {})
    update_session_status(
        session_id,
        "active",
        opencode_pid=_server_proc.pid if _server_proc else None,
    )
    if initial_instruction:
        _send_message_async(session_id, opencode_session_id, initial_instruction)
    return _server_proc.pid if _server_proc else 0


def send_to_opencode(session_id: int, text: str) -> None:
    """Send a message to the session's opencode instance (async)."""
    opencode_session_id = _OPENCODE_SESSIONS.get(session_id)
    if not opencode_session_id:
        return
    _send_message_async(session_id, opencode_session_id, text)


def _send_message_async(session_id: int, opencode_session_id: str, text: str) -> None:
    t = threading.Thread(
        target=_send_message_and_emit,
        args=(session_id, opencode_session_id, text),
        daemon=True,
    )
    t.start()


def _send_message_and_emit(session_id: int, opencode_session_id: str, text: str) -> None:
    """POST message to opencode, parse parts, emit events."""
    append_event(session_id, "message", {"role": "user", "text": text})
    try:
        resp = _http_post(
            f"{_OPENCODE_URL}/session/{opencode_session_id}/message",
            {"parts": [{"type": "text", "text": text}]},
        )
        _emit_response_parts(session_id, resp.get("parts", []))
    except Exception as exc:
        append_event(session_id, "error", {"text": str(exc)})


def _emit_response_parts(session_id: int, parts: list) -> None:
    mode = _SESSION_MODE.get(session_id, "structured")
    for part in parts:
        part_type = part.get("type", "")
        if part_type == "text":
            text = part.get("text", "")
            if mode == "raw":
                raw_q = _RAW_QUEUES.get(session_id)
                if raw_q is not None:
                    try:
                        raw_q.put_nowait(text)
                    except queue.Full:
                        pass
            else:
                append_event(session_id, "message", {"role": "assistant", "text": text})
        elif part_type == "reasoning":
            if mode != "raw":
                append_event(
                    session_id,
                    "terminal_raw",
                    {"text": f"[thinking] {part.get('text', '')}"},
                )
        elif part_type in ("tool-input", "tool-result"):
            if mode != "raw":
                append_event(session_id, "tool", part)
        # step-start / step-finish — metadata only, skip


def resume_session(session_id: int) -> None:
    """Reconnect to an existing opencode session or create a fresh one with context."""
    if _OPENCODE_SESSIONS.get(session_id):
        return  # already wired up in this server process
    _ensure_server_running()
    resp = _http_post(f"{_OPENCODE_URL}/session", {})
    opencode_session_id = resp["id"]
    _OPENCODE_SESSIONS[session_id] = opencode_session_id
    _SESSION_MODE[session_id] = "structured"
    _SSE_QUEUES.setdefault(session_id, {})
    past = get_session_events(session_id, limit=50)
    if past:
        context = "\n".join(e["content"].get("text", str(e["content"])) for e in past)
        _send_message_async(
            session_id,
            opencode_session_id,
            f"Context from previous session:\n{context}",
        )


def terminate_session(session_id: int, final_status: str = "paused") -> None:
    """Clean up in-memory state and update DB status."""
    _OPENCODE_SESSIONS.pop(session_id, None)
    _SSE_QUEUES.pop(session_id, None)
    _RAW_QUEUES.pop(session_id, None)
    _SESSION_MODE.pop(session_id, None)
    update_session_status(session_id, final_status, opencode_pid=None)


def set_session_raw_mode(session_id: int, raw: bool) -> None:
    """Switch between structured (SSE events) and raw (queue passthrough) mode."""
    _SESSION_MODE[session_id] = "raw" if raw else "structured"
    if raw:
        _RAW_QUEUES.setdefault(session_id, queue.Queue(maxsize=500))
    else:
        _RAW_QUEUES.pop(session_id, None)


# ---------------------------------------------------------------------------
# Session finalization — tier routing
# ---------------------------------------------------------------------------


def finalize_session(session_id: int) -> None:
    """Complete a session: clean up, route result by tier."""
    session = get_session(session_id)
    if not session:
        return
    terminate_session(session_id, final_status="completed")
    if session["tier"] == 1:
        _auto_pr(session_id, session)
    else:
        _mark_fix_ready(session_id, session)


def _auto_pr(session_id: int, session: dict) -> None:
    """Tier 1: create git branch, commit, push, open PR via gh."""
    import datetime

    branch = f"auto/code-session-{session_id}-{datetime.date.today().isoformat()}"
    try:
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
    except subprocess.CalledProcessError as exc:
        update_session_status(session_id, "failed", result_branch=branch)
        append_event(session_id, "error", {"text": f"git step failed: {exc}"})
        return
    result = subprocess.run(
        [
            "gh",
            "pr",
            "create",
            "--title",
            session["title"],
            "--body",
            f"Auto-generated by A.R.C.H.I.E. Code Tab (session {session_id}).",
            "--head",
            branch,
        ],
        cwd=OPENCODE_WORKDIR,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        update_session_status(
            session_id,
            "failed",
            result_branch=branch,
            result_pr_url=f"ERROR: {result.stderr.strip()[:200]}",
        )
        append_event(session_id, "error", {"text": f"gh pr create failed: {result.stderr.strip()}"})
        return
    pr_url = result.stdout.strip()
    update_session_status(session_id, "completed", result_branch=branch, result_pr_url=pr_url)
    if session.get("proposal_id"):
        _update_proposal_status(session["proposal_id"], "pr_opened")


def _mark_fix_ready(session_id: int, session: dict) -> None:
    """Tier 2: mark proposal as fix_ready for human review."""
    update_session_status(session_id, "completed")
    if session.get("proposal_id"):
        _update_proposal_status(session["proposal_id"], "fix_ready")


def _update_proposal_status(proposal_id: int, status: str) -> None:
    """Update improvement_proposals.status."""
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            "UPDATE improvement_proposals SET status = %s WHERE id = %s",
            (status, proposal_id),
        )
