# Browser Session Lifecycle — Layer A — Day-1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the Day-1 slice of Layer A — DB-backed browser session storage + cookie-paste re-auth endpoint + silent-failure alert patch — so today's stuck LinkedIn pipeline (#1111 failed company post, 33-skill outage) can be unblocked tonight by Kytran pasting cookies from her browser.

**Architecture:** New Postgres table `browser_sessions` keyed `(agent_id, platform)` with encrypted cookie blob. New `services/browser_session_service.py` is the single source of truth for encrypt/decrypt + DB I/O. New endpoint accepts cookies in Chrome extension format, encrypts, persists, marks active. `archie_browser/session_manager.py` refactored to load session state from the platform HTTP API instead of on-disk JSON. Skill executor patched to fire Telegram on `execution_result.success=false`.

**Tech Stack:** Python, Flask, psycopg2, AES (cryptography lib already in platform), existing Stalwart Telegram pipeline, existing `BROWSER_ENCRYPTION_KEY` env.

**Spec:** `docs/superpowers/specs/2026-05-04-browser-session-lifecycle-design.md`

---

## Out of scope (deferred to separate plans)

- Phase 2 — Probe job (6h cron)
- Phase 3 — Reactive layer wrap in skill_runner
- Phase 4 — `browser_skill_queue` defer + replay worker
- Phase 5 — noVNC sidecar container
- Phase 6 — DHQ "Connected Accounts" tab
- Phase 7 — Telegram inline-button callback handlers (Reconnect / Snooze / Disable Pipeline / Retry)

Each gets its own brainstorm → spec → plan → ship cycle. Phase 1 (this plan) is the foundation that lets Phases 2-7 build on top.

## File map

| Path | Status | Responsibility |
|---|---|---|
| `platform_v2/database/migrations/372_browser_sessions.sql` | new | Schema for `browser_sessions` table |
| `platform_v2/services/browser_session_service.py` | new | Encrypt/decrypt + DB CRUD helpers (single source of truth) |
| `platform_v2/tools/department_hq/session_routes.py` | new | HTTP endpoints: GET state (for archie_browser), POST import-cookies (for Kytran) |
| `platform_v2/tools/department_hq/__init__.py` | modify | Register new session_routes |
| `archie-browser/session_manager.py` | modify lines 48-72 (`load_session`) | Refactor to call platform HTTP API instead of reading disk JSON |
| `platform_v2/services/skill_failure_alerts.py` | new | Telegram-on-skill-failure hook |
| `platform_v2/tools/department_hq/jobs.py` (or wherever the approval executor lives) | modify | Wire skill_failure_alerts into the post-execution path |
| `platform_v2/tests/test_browser_session_service.py` | new | Unit tests for encrypt/decrypt + state-machine |
| `platform_v2/tests/test_browser_session_routes.py` | new | Integration tests for endpoints |

---

## Task 1: Migration 372 — `browser_sessions` table

**Files:**
- Create: `platform_v2/database/migrations/372_browser_sessions.sql`

- [ ] **Step 1: Write the migration SQL**

Create `platform_v2/database/migrations/372_browser_sessions.sql`:

```sql
-- 372_browser_sessions.sql
-- Layer A — Browser Session Lifecycle Management.
-- DB-backed session storage replaces archie-browser's on-disk encrypted JSON.
-- Single source of truth queryable by probe job, reactive layer, DHQ UI.
--
-- Spec: docs/superpowers/specs/2026-05-04-browser-session-lifecycle-design.md
-- Plan: docs/superpowers/plans/2026-05-04-browser-session-lifecycle-day1.md

BEGIN;

CREATE TABLE IF NOT EXISTS browser_sessions (
    id                  SERIAL PRIMARY KEY,
    agent_id            INTEGER NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
    platform            VARCHAR(50) NOT NULL,
    status              VARCHAR(30) NOT NULL DEFAULT 'unverified',
    encrypted_state     BYTEA,
    last_used_at        TIMESTAMP,
    last_probe_at       TIMESTAMP,
    last_probe_ok       BOOLEAN,
    last_failure_reason TEXT,
    reauth_token        VARCHAR(64),
    reauth_expires_at   TIMESTAMP,
    deferred_count      INTEGER NOT NULL DEFAULT 0,
    created_at          TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMP NOT NULL DEFAULT NOW(),
    UNIQUE(agent_id, platform),
    CONSTRAINT browser_sessions_status_check CHECK (
        status IN ('unverified', 'active', 'stale', 'reauth_pending', 'reauth_active', 'disabled')
    )
);

CREATE INDEX IF NOT EXISTS idx_browser_sessions_status ON browser_sessions(status);
CREATE INDEX IF NOT EXISTS idx_browser_sessions_probe ON browser_sessions(last_probe_at);

COMMIT;
```

- [ ] **Step 2: Apply migration**

Run: `docker exec -i archie_database psql -U archie -d archie < platform_v2/database/migrations/372_browser_sessions.sql`
Expected: `BEGIN`, `CREATE TABLE`, `CREATE INDEX` x2, `COMMIT` (or already-exists notices on re-run).

- [ ] **Step 3: Verify**

Run: `docker exec archie_database psql -U archie -d archie -c "\d browser_sessions"`
Expected: 14 columns shown, FK on agent_id with CASCADE, unique on (agent_id, platform), 2 named indexes, status CHECK constraint.

- [ ] **Step 4: Commit**

```bash
git add platform_v2/database/migrations/372_browser_sessions.sql
git commit -m "feat(browser-sessions): migration 372 — browser_sessions table"
```

---

## Task 2: Service module — encrypt/decrypt primitives

**Files:**
- Create: `platform_v2/services/browser_session_service.py`
- Test: `platform_v2/tests/test_browser_session_service.py`

- [ ] **Step 1: Write failing tests for encryption primitives**

Create `platform_v2/tests/test_browser_session_service.py`:

```python
"""Unit tests for services.browser_session_service (Layer A Phase 1)."""

from __future__ import annotations

import json
import os
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture(autouse=True)
def _set_encryption_key(monkeypatch):
    """Service expects BROWSER_ENCRYPTION_KEY env. Use a fixed test key."""
    monkeypatch.setenv("BROWSER_ENCRYPTION_KEY", "0123456789abcdef0123456789abcdef")


@pytest.fixture
def svc():
    from services import browser_session_service
    return browser_session_service


class TestEncryptionPrimitives:
    def test_encrypt_decrypt_round_trip(self, svc):
        original = {"cookies": [{"name": "li_at", "value": "secret-token"}]}
        ciphertext = svc.encrypt_state(original)
        assert isinstance(ciphertext, bytes)
        assert b"secret-token" not in ciphertext  # confirm it IS encrypted
        recovered = svc.decrypt_state(ciphertext)
        assert recovered == original

    def test_decrypt_with_wrong_key_raises(self, svc, monkeypatch):
        ciphertext = svc.encrypt_state({"x": 1})
        monkeypatch.setenv("BROWSER_ENCRYPTION_KEY", "ffffffffffffffffffffffffffffffff")
        # Reload module so it picks up new key
        import importlib
        import services.browser_session_service as m
        importlib.reload(m)
        with pytest.raises(Exception):
            m.decrypt_state(ciphertext)

    def test_encrypt_handles_unicode(self, svc):
        original = {"text": "Bonjour 🇨🇦 — Québécois français"}
        recovered = svc.decrypt_state(svc.encrypt_state(original))
        assert recovered == original
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `docker exec archie_platform python3 -m pytest /app/tests/test_browser_session_service.py::TestEncryptionPrimitives -v`
Expected: FAIL — `ModuleNotFoundError: services.browser_session_service`.

- [ ] **Step 3: Write the encryption primitives**

Create `platform_v2/services/browser_session_service.py`:

```python
"""Browser session lifecycle service (Layer A Phase 1).

Single source of truth for browser_sessions row I/O + state encryption.
Replaces archie-browser/session_manager.py's on-disk JSON storage with
DB-backed encrypted blobs. Used by:
  - archie-browser/session_manager.load_session() via platform HTTP API
  - tools/department_hq/session_routes (cookie-paste endpoint, GET state)
  - (Phase 2) probe job
  - (Phase 3) reactive layer
  - (Phase 4) defer worker
  - (Phase 6) DHQ Connected Accounts tab
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, Optional

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

logger = logging.getLogger(__name__)

# 32-byte AES-256 key. Must be present in env. The hex-encoded value is
# treated as the raw bytes per existing platform convention.
_KEY_HEX = os.getenv("BROWSER_ENCRYPTION_KEY", "")


def _key() -> bytes:
    if not _KEY_HEX:
        raise RuntimeError("BROWSER_ENCRYPTION_KEY env var not set")
    if len(_KEY_HEX) == 64:
        return bytes.fromhex(_KEY_HEX)
    # Permissive fallback — pad/truncate UTF-8 bytes to 32
    raw = _KEY_HEX.encode("utf-8")
    return (raw + b"\x00" * 32)[:32]


def encrypt_state(state: Dict[str, Any]) -> bytes:
    """Encrypt a Playwright storage_state dict to opaque bytes."""
    plaintext = json.dumps(state, ensure_ascii=False).encode("utf-8")
    aes = AESGCM(_key())
    nonce = os.urandom(12)
    ciphertext = aes.encrypt(nonce, plaintext, None)
    return nonce + ciphertext  # caller stores as one BYTEA column


def decrypt_state(blob: bytes) -> Dict[str, Any]:
    """Decrypt a previously-encrypted state blob."""
    nonce, ciphertext = blob[:12], blob[12:]
    aes = AESGCM(_key())
    plaintext = aes.decrypt(nonce, ciphertext, None)
    return json.loads(plaintext.decode("utf-8"))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `docker exec archie_platform python3 -m pytest /app/tests/test_browser_session_service.py::TestEncryptionPrimitives -v`
Expected: 3 PASSED.

- [ ] **Step 5: Commit**

```bash
git add platform_v2/services/browser_session_service.py platform_v2/tests/test_browser_session_service.py
git commit -m "feat(browser-sessions): encrypt/decrypt primitives (AES-GCM)"
```

---

## Task 3: Service — DB I/O helpers (`save_session`, `load_session`, status transitions)

**Files:**
- Modify: `platform_v2/services/browser_session_service.py` (append)
- Modify: `platform_v2/tests/test_browser_session_service.py` (append)

- [ ] **Step 1: Write failing tests**

Append to `test_browser_session_service.py`:

```python
def _mock_cursor(row=None, rows=None):
    """Mock context manager for get_db_cursor."""
    cur = MagicMock()
    cur.fetchone.return_value = row
    cur.fetchall.return_value = rows or []
    conn = MagicMock()

    class _CM:
        def __enter__(self):
            return (conn, cur)
        def __exit__(self, *args):
            return False

    cm = _CM()
    cm.cursor = cur
    return cm


class TestSaveSession:
    def test_upserts_row_with_active_status(self, svc):
        cm = _mock_cursor(row={"id": 1})
        with patch("services.browser_session_service.get_db_cursor", return_value=cm):
            result = svc.save_session(agent_id=7, platform="linkedin",
                                      state={"cookies": []}, status="active")
        assert result["success"] is True
        sql_calls = [str(c.args[0]) for c in cm.cursor.execute.call_args_list]
        assert any("INSERT INTO browser_sessions" in s for s in sql_calls), \
            f"Expected INSERT; got: {sql_calls}"
        assert any("ON CONFLICT" in s for s in sql_calls), "Expected upsert via ON CONFLICT"


class TestLoadSession:
    def test_returns_none_when_no_row(self, svc):
        with patch("services.browser_session_service.get_db_cursor",
                   return_value=_mock_cursor(row=None)):
            result = svc.load_session(agent_id=7, platform="linkedin")
        assert result is None

    def test_returns_decrypted_state_when_active(self, svc):
        original = {"cookies": [{"name": "li_at", "value": "v"}]}
        ciphertext = svc.encrypt_state(original)
        row = {
            "id": 1, "agent_id": 7, "platform": "linkedin",
            "status": "active", "encrypted_state": ciphertext,
        }
        cm = _mock_cursor(row=row)
        with patch("services.browser_session_service.get_db_cursor", return_value=cm):
            result = svc.load_session(agent_id=7, platform="linkedin")
        assert result == original
        # Verify last_used_at was bumped
        sql_calls = [str(c.args[0]) for c in cm.cursor.execute.call_args_list]
        assert any("UPDATE browser_sessions" in s and "last_used_at" in s for s in sql_calls)

    def test_returns_none_when_status_not_active(self, svc):
        original = {"cookies": []}
        row = {
            "id": 1, "agent_id": 7, "platform": "linkedin",
            "status": "stale", "encrypted_state": svc.encrypt_state(original),
        }
        with patch("services.browser_session_service.get_db_cursor",
                   return_value=_mock_cursor(row=row)):
            result = svc.load_session(agent_id=7, platform="linkedin")
        assert result is None  # stale sessions are NOT loaded for skill execution


class TestStatusTransitions:
    def test_mark_stale_updates_status_and_reason(self, svc):
        cm = _mock_cursor(row={"id": 1})
        with patch("services.browser_session_service.get_db_cursor", return_value=cm):
            svc.mark_stale(agent_id=7, platform="linkedin", reason="Page isn't available")
        sql_calls = [str(c.args[0]) for c in cm.cursor.execute.call_args_list]
        assert any("status" in s and "stale" in s for s in sql_calls)

    def test_mark_active_clears_failure_reason(self, svc):
        cm = _mock_cursor(row={"id": 1})
        with patch("services.browser_session_service.get_db_cursor", return_value=cm):
            svc.mark_active(agent_id=7, platform="linkedin")
        sql_calls = [str(c.args[0]) for c in cm.cursor.execute.call_args_list]
        assert any("status" in s and "active" in s for s in sql_calls)
        assert any("last_failure_reason = NULL" in s for s in sql_calls)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `docker exec archie_platform python3 -m pytest /app/tests/test_browser_session_service.py -v`
Expected: 3 prior PASS + 5 new FAIL (`save_session`, `load_session`, `mark_stale`, `mark_active` not defined).

- [ ] **Step 3: Write the DB I/O helpers**

Append to `services/browser_session_service.py`:

```python
from database import get_db_cursor


def save_session(
    agent_id: int,
    platform: str,
    state: Dict[str, Any],
    status: str = "active",
) -> Dict[str, Any]:
    """Upsert a browser session row. Encrypts state, marks status."""
    encrypted = encrypt_state(state)
    with get_db_cursor(commit=True) as (_conn, cur):
        cur.execute(
            """INSERT INTO browser_sessions
                   (agent_id, platform, status, encrypted_state, last_used_at, updated_at)
               VALUES (%s, %s, %s, %s, NOW(), NOW())
               ON CONFLICT (agent_id, platform) DO UPDATE SET
                   status = EXCLUDED.status,
                   encrypted_state = EXCLUDED.encrypted_state,
                   last_used_at = NOW(),
                   last_failure_reason = NULL,
                   updated_at = NOW()
               RETURNING id""",
            (agent_id, platform, status, encrypted),
        )
        row = cur.fetchone()
    return {"success": True, "id": row["id"] if row else None}


def load_session(agent_id: int, platform: str) -> Optional[Dict[str, Any]]:
    """Load decrypted state for active session; return None otherwise.

    Bumps last_used_at on read so probe + DHQ visibility know it's in use.
    """
    with get_db_cursor(commit=True) as (_conn, cur):
        cur.execute(
            """SELECT id, status, encrypted_state
                 FROM browser_sessions
                WHERE agent_id = %s AND platform = %s""",
            (agent_id, platform),
        )
        row = cur.fetchone()
        if not row:
            return None
        if row["status"] != "active":
            return None
        if not row["encrypted_state"]:
            return None
        cur.execute(
            "UPDATE browser_sessions SET last_used_at = NOW() WHERE id = %s",
            (row["id"],),
        )
    return decrypt_state(bytes(row["encrypted_state"]))


def mark_stale(agent_id: int, platform: str, reason: str) -> None:
    with get_db_cursor(commit=True) as (_conn, cur):
        cur.execute(
            """UPDATE browser_sessions
                  SET status = 'stale',
                      last_failure_reason = %s,
                      updated_at = NOW()
                WHERE agent_id = %s AND platform = %s""",
            (reason, agent_id, platform),
        )


def mark_active(agent_id: int, platform: str) -> None:
    with get_db_cursor(commit=True) as (_conn, cur):
        cur.execute(
            """UPDATE browser_sessions
                  SET status = 'active',
                      last_failure_reason = NULL,
                      updated_at = NOW()
                WHERE agent_id = %s AND platform = %s""",
            (agent_id, platform),
        )
```

- [ ] **Step 4: Run tests**

Run: `docker exec archie_platform python3 -m pytest /app/tests/test_browser_session_service.py -v`
Expected: 8 PASSED.

- [ ] **Step 5: Commit**

```bash
git add platform_v2/services/browser_session_service.py platform_v2/tests/test_browser_session_service.py
git commit -m "feat(browser-sessions): save/load/mark_stale/mark_active DB I/O"
```

---

## Task 4: HTTP routes — cookie import + state read

**Files:**
- Create: `platform_v2/tools/department_hq/session_routes.py`
- Modify: `platform_v2/tools/department_hq/__init__.py`
- Test: `platform_v2/tests/test_browser_session_routes.py`

- [ ] **Step 1: Write failing route tests**

Create `platform_v2/tests/test_browser_session_routes.py`:

```python
"""Integration tests for browser session HTTP routes."""

from __future__ import annotations

from unittest.mock import patch

import pytest


@pytest.fixture(autouse=True)
def _key(monkeypatch):
    monkeypatch.setenv("BROWSER_ENCRYPTION_KEY", "0123456789abcdef0123456789abcdef")
    monkeypatch.setenv("INTERNAL_API_KEY", "test-internal-key")


@pytest.fixture
def admin_client():
    from app import app
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False
    with app.test_client() as c:
        with c.session_transaction() as sess:
            sess["user_id"] = 1
            sess["is_admin"] = True
        yield c


@pytest.fixture
def internal_client():
    """Client without admin session — uses X-Internal-Key header instead."""
    from app import app
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False
    with app.test_client() as c:
        yield c


class TestImportCookies:
    def test_admin_can_import_cookies(self, admin_client):
        body = {
            "cookies": [
                {"name": "li_at", "value": "abc", "domain": ".linkedin.com",
                 "path": "/", "expires": -1, "httpOnly": True, "secure": True},
            ],
        }
        with patch("services.browser_session_service.save_session",
                   return_value={"success": True, "id": 42}):
            r = admin_client.post(
                "/tools/department-hq/api/sessions/7/linkedin/import-cookies",
                json=body,
            )
        assert r.status_code == 200
        assert r.get_json()["success"] is True

    def test_rejects_empty_cookies(self, admin_client):
        r = admin_client.post(
            "/tools/department-hq/api/sessions/7/linkedin/import-cookies",
            json={"cookies": []},
        )
        assert r.status_code == 400

    def test_rejects_unauthenticated(self, internal_client):
        r = internal_client.post(
            "/tools/department-hq/api/sessions/7/linkedin/import-cookies",
            json={"cookies": [{"name": "x", "value": "y"}]},
        )
        assert r.status_code in (302, 401)


class TestGetState:
    def test_internal_key_can_read_state(self, internal_client):
        from services import browser_session_service as svc
        ciphertext = svc.encrypt_state({"cookies": [{"name": "li_at", "value": "v"}]})
        with patch("services.browser_session_service.load_session",
                   return_value={"cookies": [{"name": "li_at", "value": "v"}]}):
            r = internal_client.get(
                "/tools/department-hq/api/sessions/7/linkedin/state",
                headers={"X-Internal-Key": "test-internal-key"},
            )
        assert r.status_code == 200
        assert r.get_json()["state"]["cookies"][0]["name"] == "li_at"

    def test_rejects_without_internal_key(self, internal_client):
        r = internal_client.get(
            "/tools/department-hq/api/sessions/7/linkedin/state",
        )
        assert r.status_code == 401

    def test_returns_404_when_no_session(self, internal_client):
        with patch("services.browser_session_service.load_session", return_value=None):
            r = internal_client.get(
                "/tools/department-hq/api/sessions/7/linkedin/state",
                headers={"X-Internal-Key": "test-internal-key"},
            )
        assert r.status_code == 404
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `docker exec archie_platform python3 -m pytest /app/tests/test_browser_session_routes.py -v`
Expected: FAIL — 404s on all routes.

- [ ] **Step 3: Write the routes module**

Create `platform_v2/tools/department_hq/session_routes.py`:

```python
"""Browser session HTTP routes (Layer A Phase 1).

Two endpoints:
- POST /tools/department-hq/api/sessions/<agent>/<platform>/import-cookies
    Admin-only. Accepts Chrome-extension-format cookies, encrypts, persists.
- GET /tools/department-hq/api/sessions/<agent>/<platform>/state
    Internal-key-only. Used by archie_browser to load session state for skill execution.
"""

from __future__ import annotations

import logging
import os

from flask import jsonify, request

logger = logging.getLogger(__name__)

_INTERNAL_KEY = os.getenv("INTERNAL_API_KEY", "")


def _cookies_to_storage_state(cookies: list) -> dict:
    """Convert Chrome-extension cookie format to Playwright storage_state."""
    storage_cookies = []
    for c in cookies:
        if not c.get("name") or "value" not in c:
            continue
        # Playwright cookie schema is close to Chrome's; just normalise field names.
        sc = {
            "name": c["name"],
            "value": c["value"],
            "domain": c.get("domain", ""),
            "path": c.get("path", "/"),
            "httpOnly": bool(c.get("httpOnly", False)),
            "secure": bool(c.get("secure", False)),
            "sameSite": c.get("sameSite", "Lax").capitalize() if c.get("sameSite") else "Lax",
        }
        # `expires` -1 means session cookie; Playwright wants -1 or epoch float
        if "expires" in c and c["expires"] is not None:
            sc["expires"] = float(c["expires"])
        storage_cookies.append(sc)
    return {"cookies": storage_cookies, "origins": []}


def register_session_routes(bp, login_required, admin_required):
    """Register browser-session routes on the Department HQ blueprint."""

    @bp.route(
        "/api/sessions/<int:agent_id>/<platform>/import-cookies",
        methods=["POST"],
    )
    @admin_required
    def import_cookies(agent_id, platform):
        """Admin imports cookies from their browser into the agent's session."""
        from services import browser_session_service

        data = request.get_json(silent=True) or {}
        cookies = data.get("cookies") or []
        if not cookies:
            return jsonify({"success": False, "error": "cookies array is required"}), 400
        if platform not in ("linkedin", "twitter", "facebook"):
            return jsonify({"success": False, "error": f"unsupported platform: {platform}"}), 400

        storage_state = _cookies_to_storage_state(cookies)
        try:
            result = browser_session_service.save_session(
                agent_id=agent_id, platform=platform, state=storage_state, status="active"
            )
        except Exception as exc:
            logger.exception("[browser-sessions] import-cookies failed")
            return jsonify({"success": False, "error": str(exc)}), 500

        return jsonify({"success": True, "session_id": result.get("id"),
                        "cookies_imported": len(storage_state["cookies"])}), 200

    @bp.route("/api/sessions/<int:agent_id>/<platform>/state", methods=["GET"])
    def get_state(agent_id, platform):
        """archie_browser fetches session state for skill execution.

        Auth: X-Internal-Key header (NOT session-based — this is service-to-service).
        """
        if not _INTERNAL_KEY or request.headers.get("X-Internal-Key") != _INTERNAL_KEY:
            return jsonify({"error": "unauthorized"}), 401

        from services import browser_session_service
        state = browser_session_service.load_session(agent_id, platform)
        if state is None:
            return jsonify({"error": "no active session"}), 404
        return jsonify({"state": state}), 200
```

- [ ] **Step 4: Wire registration**

Read `platform_v2/tools/department_hq/__init__.py` to find existing register_*_routes pattern. Append:

```python
from .session_routes import register_session_routes  # noqa: E402
register_session_routes(department_hq_bp, login_required, admin_required)
```

Match exact placement style of existing register_* lines.

- [ ] **Step 5: Run tests**

Run: `docker exec archie_platform python3 -m pytest /app/tests/test_browser_session_routes.py -v`
Expected: 6 PASSED.

- [ ] **Step 6: Commit**

```bash
git add platform_v2/tools/department_hq/session_routes.py \
        platform_v2/tools/department_hq/__init__.py \
        platform_v2/tests/test_browser_session_routes.py
git commit -m "feat(browser-sessions): import-cookies + state HTTP routes"
```

---

## Task 5: Refactor `archie-browser/session_manager.py` — load state via HTTP

**Files:**
- Modify: `archie-browser/session_manager.py` (`load_session` function around lines 48-72)

- [ ] **Step 1: Read existing code**

Run: `sed -n '40,80p' /mnt/archie_brain/archie-browser/session_manager.py`

Note the current `load_session` signature and how it reads the encrypted disk file. The replacement keeps the same signature (`agent_id`, `platform`) but fetches state via HTTP.

- [ ] **Step 2: Modify `load_session`**

Replace the existing `load_session` body with:

```python
def load_session(agent_id: int, platform: str) -> Optional[dict]:
    """Load Playwright storage_state for (agent_id, platform).

    Layer A Phase 1: fetch from platform HTTP API instead of local disk.
    Falls back to None if endpoint unreachable or no active session — caller
    must handle (skill will fail naturally; reactive layer will mark stale).
    """
    import os
    import requests

    platform_url = os.getenv("ARCHIE_PLATFORM_URL", "http://archie_platform:3000")
    internal_key = os.getenv("INTERNAL_API_KEY", "")
    if not internal_key:
        logger.warning("INTERNAL_API_KEY not set; cannot load session via HTTP")
        return None

    url = f"{platform_url}/tools/department-hq/api/sessions/{agent_id}/{platform}/state"
    try:
        resp = requests.get(url, headers={"X-Internal-Key": internal_key}, timeout=5)
    except Exception as exc:
        logger.warning("session HTTP fetch failed: %s", exc)
        return None

    if resp.status_code == 404:
        return None  # no active session — skill will fail at next selector
    if resp.status_code != 200:
        logger.warning("session HTTP fetch %s: %s", resp.status_code, resp.text[:120])
        return None

    return resp.json().get("state")
```

Add `import logging; logger = logging.getLogger(__name__)` if not already present.

- [ ] **Step 3: Update Dockerfile / docker-compose env to pass INTERNAL_API_KEY**

Read `docker-compose.yml` to find the `archie_browser` env block. Append:

```yaml
      - INTERNAL_API_KEY=${INTERNAL_API_KEY}
      - ARCHIE_PLATFORM_URL=http://archie_platform:3000
```

If `INTERNAL_API_KEY` isn't already in the root `.env`, add it (32-byte hex value):
```bash
echo "INTERNAL_API_KEY=$(openssl rand -hex 32)" >> /mnt/archie_brain/.env
```
**SECURITY:** value goes in .env (not committed). Same key must be set on archie_platform too.

- [ ] **Step 4: Recreate archie_browser to pick up new env**

Run: `docker compose up -d --no-deps archie_browser`
Expected: container restarted with new env vars.

Verify: `docker exec archie_browser printenv | grep -E 'INTERNAL_API_KEY|ARCHIE_PLATFORM_URL'`
Should show both values.

- [ ] **Step 5: Smoke test the new path**

Run inside platform container:
```bash
docker exec archie_browser python3 -c "
from session_manager import load_session
result = load_session(7, 'linkedin')
print('result:', None if result is None else 'STATE_LOADED')
"
```
Expected: `result: None` (no session yet — that's correct; populated by Task 6).

- [ ] **Step 6: Commit**

```bash
git add archie-browser/session_manager.py docker-compose.yml
git commit -m "feat(browser-sessions): archie_browser fetches session state via platform HTTP"
```

---

## Task 6: Today's manual repair workflow + E2E live-fire test

**Files:** none (operational verification — no code changes)

This task is the actual today-fix-it step. The user (Kytran) does the cookie export. We do the rest.

- [ ] **Step 1: Find Kytran's user record + the `browser_agent_id` used by skill calls**

Run:
```bash
docker exec archie_database psql -U archie -d archie -c \
  "SELECT id, name FROM agents WHERE id = 342;"
```
Expected: agent #342 (whichever agent the SIGNAL pipeline uses for browser). Confirm it's the right one by checking `action_data->>'browser_agent_id'` on a recent linkedin_post approval row.

- [ ] **Step 2: Provide Kytran the cookie-export instructions**

Tell Kytran:
1. Install Chrome extension "Cookie-Editor" (https://chrome.google.com/webstore/detail/cookie-editor/...)
2. Open https://www.linkedin.com/feed/ in her normal Chrome (verify she's logged in as KE Inc. admin)
3. Click Cookie-Editor icon → "Export" → "Export as JSON"
4. Paste the JSON to Claude
5. Claude POSTs it to the import-cookies endpoint

- [ ] **Step 3: Once Kytran provides cookies, POST to endpoint**

```bash
docker exec archie_platform python3 -c "
import requests
cookies = $COOKIES_JSON  # paste from Kytran
r = requests.post('http://localhost:3000/tools/department-hq/api/sessions/342/linkedin/import-cookies',
                  json={'cookies': cookies},
                  cookies={'session': '$KYTRAN_SESSION_COOKIE'})
print(r.status_code, r.text[:300])
"
```

Or simpler — Kytran calls the endpoint from her browser dev console while she's already logged into the platform:

```js
fetch('/tools/department-hq/api/sessions/342/linkedin/import-cookies', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({cookies: <PASTED_COOKIES>}),
}).then(r => r.json()).then(console.log);
```

Expected: `{"success": true, "session_id": ..., "cookies_imported": N}`.

- [ ] **Step 4: Verify the row landed in DB**

```bash
docker exec archie_database psql -U archie -d archie -c \
  "SELECT id, agent_id, platform, status, length(encrypted_state), last_used_at FROM browser_sessions;"
```
Expected: 1 row, agent_id=342, platform=linkedin, status=active, encrypted_state size > 0.

- [ ] **Step 5: Re-fire the linkedin_company_post test**

```bash
docker exec archie_platform python3 -c "
import json, app
from db import get_db
from psycopg2.extras import RealDictCursor
conn = get_db(); cur = conn.cursor(cursor_factory=RealDictCursor)
cur.execute('SELECT action_data FROM autonomy_approval_queue WHERE id = 1111')
ad = cur.fetchone()['action_data']; cur.close(); conn.close()
from services.browser_service import run_skill_sync
result = run_skill_sync('linkedin_company_post', {
    'content': ad['content'], 'hashtags': ad.get('hashtags', []),
    'company_slug': 'kytran-empowerment-inc',
}, timeout_s=240)
print(json.dumps(result, default=str, indent=2)[:2000])
"
```

Expected (success): `{"success": true, "result": "Posted N characters as kytran-empowerment-inc", "screenshot_path": "..."}`.

- [ ] **Step 6: Confirm post on LinkedIn**

Open https://www.linkedin.com/company/kytran-empowerment-inc/ in browser and visually confirm the post landed.

- [ ] **Step 7: Repeat for personal account if a separate session is needed**

Personal posts use `linkedin_post` skill with a different agent_id. Find the agent_id used by personal-post execution flow (check `signal_linkedin_draft` job code or recent linkedin_post approval rows). Repeat steps 2-6 for that agent_id.

- [ ] **Step 8: No commit (operational verification only)**

If smoke surfaced bugs, fix-and-commit per the standard pattern.

---

## Task 7: Skill failure alert — Telegram on `execution_result.success=false`

**Files:**
- Create: `platform_v2/services/skill_failure_alerts.py`
- Modify: wherever the approval executor lives (Task identifies via grep)
- Test: `platform_v2/tests/test_skill_failure_alerts.py`

- [ ] **Step 1: Find the executor code path**

Run: `grep -nrE "execution_result|status.*=.*'executed'" /mnt/archie_brain/platform_v2/ --include='*.py' | grep -v test_ | grep -v __pycache__ | head -10`

Identify the file/function that writes `execution_result` to `autonomy_approval_queue`. Likely candidates: `services/approval_executor.py`, `tools/department_hq/approvals_routes.py`, or `services/agent_jobs.py`.

- [ ] **Step 2: Write failing tests**

Create `platform_v2/tests/test_skill_failure_alerts.py`:

```python
"""Unit tests for services.skill_failure_alerts."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def svc():
    from services import skill_failure_alerts
    return skill_failure_alerts


class TestAlertOnFailure:
    def test_fires_telegram_when_execution_result_failed(self, svc):
        with patch("services.skill_failure_alerts._send_telegram") as send:
            svc.alert_on_skill_failure(
                approval_id=1111,
                skill_name="linkedin_company_post",
                execution_result={
                    "success": False,
                    "error": "Could not find Start a post button",
                    "_status": "failed",
                },
            )
        send.assert_called_once()
        msg = send.call_args.kwargs.get("message") or send.call_args.args[0]
        assert "linkedin_company_post" in msg
        assert "1111" in msg or "#1111" in msg

    def test_does_not_fire_on_success(self, svc):
        with patch("services.skill_failure_alerts._send_telegram") as send:
            svc.alert_on_skill_failure(
                approval_id=1111,
                skill_name="linkedin_company_post",
                execution_result={"success": True, "result": "Posted 939 characters"},
            )
        send.assert_not_called()

    def test_classifies_timeout_separately(self, svc):
        with patch("services.skill_failure_alerts._send_telegram") as send:
            svc.alert_on_skill_failure(
                approval_id=1112,
                skill_name="linkedin_company_post",
                execution_result={
                    "success": False,
                    "error": "Timeout after 240s",
                    "_status": "timeout",
                },
            )
        send.assert_called_once()
        msg = send.call_args.kwargs.get("message") or send.call_args.args[0]
        assert "timeout" in msg.lower() or "Timeout" in msg
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `docker exec archie_platform python3 -m pytest /app/tests/test_skill_failure_alerts.py -v`
Expected: FAIL — module not found.

- [ ] **Step 4: Write the alert service**

Create `platform_v2/services/skill_failure_alerts.py`:

```python
"""Skill failure alerts (Layer A Phase 1).

Fires a Telegram alert when an approval executor reports
``execution_result.success == False``. Closes the silent-failure gap that
caused today's 9 AM #1111 outage to go unnoticed for hours.
"""

from __future__ import annotations

import logging
from typing import Any, Dict

logger = logging.getLogger(__name__)


def _send_telegram(title: str, message: str) -> None:
    """Thin wrapper around the existing Telegram service. Failures suppressed."""
    try:
        from services.telegram_service import send_system

        send_system(title=title, message=message, source_agent="A.R.C.H.I.E.")
    except Exception:
        logger.exception("[skill_failure_alerts] Telegram send failed")


def alert_on_skill_failure(
    approval_id: int,
    skill_name: str,
    execution_result: Dict[str, Any],
) -> None:
    """Fire alert if execution_result indicates failure. No-op on success."""
    if not execution_result or execution_result.get("success") is True:
        return

    err = execution_result.get("error") or "(no error message)"
    status = execution_result.get("_status") or "failed"
    icon = "⏱" if status == "timeout" else "❌"

    title = f"{icon} Skill failed — {skill_name}"
    message = (
        f"Approval #{approval_id} executed but failed.\n\n"
        f"Skill: {skill_name}\n"
        f"Status: {status}\n"
        f"Error: {err[:300]}\n\n"
        f"This is the silent-failure gap closed by Layer A. "
        f"Check screenshots in archie_browser:/tmp/browser_screenshots/."
    )
    _send_telegram(title=title, message=message)
```

- [ ] **Step 5: Wire into the executor**

Find the executor (Step 1) and add a call AFTER `execution_result` is written to the DB. Example pattern (adapt to actual code):

```python
# After: cur.execute("UPDATE autonomy_approval_queue SET execution_result = %s, ...", ...)
from services.skill_failure_alerts import alert_on_skill_failure
alert_on_skill_failure(
    approval_id=approval_id,
    skill_name=action_type,  # e.g., 'linkedin_post' or read from action_data
    execution_result=execution_result,
)
```

Wrap the call in `try/except Exception` so a Telegram failure never breaks executor flow.

- [ ] **Step 6: Run tests**

Run: `docker exec archie_platform python3 -m pytest /app/tests/test_skill_failure_alerts.py -v`
Expected: 3 PASSED.

- [ ] **Step 7: Smoke test against today's #1111 (already failed)**

Manually invoke the alert with #1111's known result:

```bash
docker exec archie_platform python3 -c "
import app
from services.skill_failure_alerts import alert_on_skill_failure
alert_on_skill_failure(
    approval_id=1111,
    skill_name='linkedin_company_post',
    execution_result={'success': False, 'error': 'Could not find Start a post button on company page', '_status': 'failed'},
)
print('alert fired (check Telegram)')
"
```
Expected: Telegram message arrives in your chat with the failure details.

- [ ] **Step 8: Commit**

```bash
git add platform_v2/services/skill_failure_alerts.py \
        platform_v2/tests/test_skill_failure_alerts.py \
        <executor_file_path>
git commit -m "feat(browser-sessions): Telegram alert on skill execution failure"
```

---

## Task 8: Open PR and merge

- [ ] **Step 1: Push branch**

Run: `git push -u origin feat/browser-sessions-day1`
Expected: branch up.

- [ ] **Step 2: Open PR**

```bash
gh pr create --title "feat(browser-sessions): Layer A Phase 1 — DB schema + cookie-paste + failure alerts" --body "$(cat <<'EOF'
## Summary

Closes Layer A Phase 1 — the foundation for browser session lifecycle management across the 33-skill LinkedIn (and future Twitter/Facebook) Playwright stack. Unblocks today's silent-failure outage.

- **Migration 372**: `browser_sessions` table (encrypted state, status state machine, last_probe + last_used metadata)
- **`services/browser_session_service.py`**: encrypt/decrypt + DB CRUD primitives (single source of truth)
- **HTTP routes**: `POST /api/sessions/<agent>/<platform>/import-cookies` (admin) + `GET /state` (X-Internal-Key for archie_browser)
- **`archie-browser/session_manager.py`**: refactored to load session via platform HTTP instead of disk JSON
- **`services/skill_failure_alerts.py`**: Telegram alert on `execution_result.success=false` — closes today's silent-failure gap

## Today's repair (manual)

1. Kytran exports cookies from her browser via Cookie-Editor extension
2. POSTs to import-cookies endpoint
3. browser_sessions row inserted, status=active
4. linkedin_company_post + linkedin_post live-fire tests verified end-to-end

## Out of scope (Phase 2-7 follow-ons, separate plans)

- Phase 2: 6h probe job
- Phase 3: Reactive layer in skill_runner
- Phase 4: browser_skill_queue + defer/replay worker
- Phase 5: noVNC sidecar container
- Phase 6: DHQ Connected Accounts tab
- Phase 7: Telegram inline-button callback handlers

## Spec / plan

- Spec: `docs/superpowers/specs/2026-05-04-browser-session-lifecycle-design.md`
- Plan: `docs/superpowers/plans/2026-05-04-browser-session-lifecycle-day1.md`

## Test plan

- [x] All unit + integration tests pass (~17 new)
- [x] Migration 372 applied
- [x] Today's KE Inc. session row created + linkedin_company_post test succeeds end-to-end
- [x] Manual fail-trigger of skill_failure_alerts → Telegram received

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

- [ ] **Step 3: Merge after review**

User merges (or self-merge per `feedback_pr-management.md` if changes are non-risky).

- [ ] **Step 4: Update Dev HQ**

```python
mcp__archie__create_project(
    name="Browser Session Lifecycle — Layer A",
    description="Foundation spec at docs/superpowers/specs/2026-05-04-browser-session-lifecycle-design.md. Phase 1 shipped via PR #X. Phases 2-7 follow as separate plans.",
    priority=9, project_type="infrastructure",
)
mcp__archie__create_task(
    project_id=<new>, title="Phase 1 — DB schema + cookie-paste + failure alerts",
    status="completed",  # ship this PR
)
# Pre-create stub tasks for Phase 2-7 so they're tracked
```

---

## Self-review

**Spec coverage:**
- ✅ DB schema (migration 372) → Task 1
- ✅ Encryption primitives → Task 2
- ✅ DB I/O (save/load/mark) → Task 3
- ✅ Cookie-paste endpoint + GET state → Task 4
- ✅ archie_browser refactor to HTTP → Task 5
- ✅ Today's manual E2E repair → Task 6
- ✅ Failure-alert patch → Task 7
- ☐ `browser_skill_queue` table — DEFERRED to Phase 4 plan (out of scope)
- ☐ Probe job — DEFERRED to Phase 2 plan (out of scope)
- ☐ Reactive layer — DEFERRED to Phase 3 plan
- ☐ noVNC sidecar — DEFERRED to Phase 5 plan
- ☐ DHQ tab — DEFERRED to Phase 6 plan
- ☐ Telegram inline-button handlers — DEFERRED to Phase 7 plan

All Phase 1 spec requirements covered. Phase 2-7 explicitly out of scope.

**Type/name consistency:**
- `browser_sessions` table everywhere
- `services.browser_session_service` everywhere
- Status enum values match between migration CHECK constraint and test fixtures
- `(agent_id, platform)` is the canonical key everywhere
- `encrypted_state` (not `state` or `cookies`) — column name matches save/load helpers
- Function names: `encrypt_state`, `decrypt_state`, `save_session`, `load_session`, `mark_stale`, `mark_active`, `alert_on_skill_failure`

**Placeholder scan:** none.
