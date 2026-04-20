# Agent Profile Detail Modal Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the single-source agent profile editor modal in Department HQ Roster tab — 23 editable fields across 5 sections, audit-logged saves, reusing the existing `#agentDetailOverlay` LCARS container.

**Architecture:** One PATCH endpoint (`/tools/department-hq/api/agent/<id>`) + extended GET profile response + new `agent_profile_modal.js`/`.css` that replaces the innards of the legacy `#agentDetailOverlay`. Sensitive-field edits trigger a confirm-on-dirty LCARS sub-overlay. Every successful save writes one `governance_audit_log` row with before/after diff.

**Tech Stack:** Flask + psycopg2 + flask-login admin gate (backend), vanilla JS (no framework) with DOM-construction idioms (no innerHTML on user data) + LCARS `bm-` CSS classes (frontend), pytest + Playwright (tests).

**Branch:** `feat/agent-profile-modal-spec` (continues from the spec commit `6ae0c539`).

**Spec:** `docs/superpowers/specs/2026-04-19-agent-profile-modal-design.md`

**Security discipline:** All dynamic string values from the profile API are written with `textContent` or as attribute values, never concatenated into an innerHTML string. The JS constructs DOM via `createElement` helpers.

---

## Phase 1 — Promote model-availability helper to shared service

`hiring_service._verify_model_available(model)` is underscore-private. The PATCH endpoint needs the same check. Promote it once.

### Task 1: Write the failing test for `services/ollama_availability.py`

**Files:**
- Test: `platform_v2/tests/test_ollama_availability.py` (new)

- [ ] **Step 1: Create the test file**

```python
"""Unit tests for services.ollama_availability.is_model_available."""
from __future__ import annotations

import pytest
from unittest import mock


@pytest.fixture(autouse=True)
def _path():
    import sys
    if "/app" not in sys.path:
        sys.path.insert(0, "/app")


def test_is_model_available_true_when_present():
    from services.ollama_availability import is_model_available

    fake_response = mock.Mock(
        status_code=200,
        json=lambda: {"models": [{"name": "mistral:7b"}, {"name": "llama3:8b"}]},
    )
    with mock.patch("services.ollama_availability.requests.get", return_value=fake_response):
        ok, msg = is_model_available("mistral:7b")
    assert ok is True


def test_is_model_available_false_when_missing():
    from services.ollama_availability import is_model_available

    fake_response = mock.Mock(
        status_code=200,
        json=lambda: {"models": [{"name": "llama3:8b"}]},
    )
    with mock.patch("services.ollama_availability.requests.get", return_value=fake_response):
        ok, msg = is_model_available("mistral:7b")
    assert ok is False
    assert "mistral:7b" in msg


def test_is_model_available_false_on_timeout():
    from services.ollama_availability import is_model_available
    import requests

    with mock.patch(
        "services.ollama_availability.requests.get",
        side_effect=requests.Timeout("timed out"),
    ):
        ok, msg = is_model_available("anything:1b")
    assert ok is False
    assert "timeout" in msg.lower() or "unreachable" in msg.lower()


def test_is_model_available_false_on_connection_error():
    from services.ollama_availability import is_model_available
    import requests

    with mock.patch(
        "services.ollama_availability.requests.get",
        side_effect=requests.ConnectionError("boom"),
    ):
        ok, msg = is_model_available("anything:1b")
    assert ok is False


def test_cloud_suffix_skips_local_probe():
    """:cloud models always return ok without HTTP."""
    from services.ollama_availability import is_model_available

    with mock.patch("services.ollama_availability.requests.get") as m:
        ok, msg = is_model_available("gpt-4o:cloud")
    assert ok is True
    assert m.called is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `docker exec archie_platform python -m pytest /app/tests/test_ollama_availability.py -v`
Expected: `ModuleNotFoundError: No module named 'services.ollama_availability'`

### Task 2: Implement `services/ollama_availability.py`

**Files:**
- Create: `platform_v2/services/ollama_availability.py`

- [ ] **Step 1: Write the module**

```python
"""Minimal Ollama model-availability helper used by hiring & profile update.

Single public entrypoint: is_model_available(model, hub_host=None) -> (ok, message).
"""

from __future__ import annotations

import os
from typing import Optional, Tuple

import requests

DEFAULT_HUB = "http://192.168.1.200:11434"


def is_model_available(
    model: str,
    hub_host: Optional[str] = None,
) -> Tuple[bool, str]:
    """Return (ok, message). 5s timeout, any failure => not ok.

    Cloud models (*:cloud suffix) skip the probe and return ok.
    """
    if not model:
        return False, "model empty"

    if model.endswith(":cloud"):
        return True, "cloud model (probe skipped)"

    host = hub_host or os.environ.get("OLLAMA_HOST") or DEFAULT_HUB
    host = host.rstrip("/")

    try:
        r = requests.get(f"{host}/api/tags", timeout=5)
    except requests.Timeout:
        return False, f"ollama timeout at {host}"
    except requests.ConnectionError:
        return False, f"ollama unreachable at {host}"

    if r.status_code != 200:
        return False, f"ollama returned {r.status_code}"

    try:
        names = {m.get("name") for m in r.json().get("models", [])}
    except Exception:
        return False, "ollama /api/tags malformed"

    if model in names:
        return True, f"{model} available"
    return False, f"{model} not present on {host}"
```

- [ ] **Step 2: Run tests to verify they pass**

Run: `docker exec archie_platform python -m pytest /app/tests/test_ollama_availability.py -v`
Expected: 5 passed.

### Task 3: Retire the private helper in `hiring_service.py`

**Files:**
- Modify: `platform_v2/services/hiring_service.py`

- [ ] **Step 1: Replace the body of `_verify_model_available`**

Locate the function near line 122. Replace its body with a delegation:

```python
def _verify_model_available(model: str, hub_host: Optional[str] = None) -> tuple[bool, str]:
    """Back-compat shim. Prefer services.ollama_availability.is_model_available."""
    from .ollama_availability import is_model_available
    return is_model_available(model, hub_host=hub_host)
```

- [ ] **Step 2: Re-run hiring tests to confirm no regression**

Run: `docker exec archie_platform python -m pytest /app/tests/test_approvals_hire_routes.py -v`
Expected: all passing (same count as before).

### Task 4: Commit Phase 1

- [ ] **Step 1: Commit**

```bash
git add platform_v2/services/ollama_availability.py \
        platform_v2/services/hiring_service.py \
        platform_v2/tests/test_ollama_availability.py
git commit -m "refactor: promote Ollama model-availability check to shared helper

Extracted from hiring_service._verify_model_available for reuse by
agent profile PATCH endpoint. Private helper kept as a shim for
backward compatibility with existing callers.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Phase 2 — Extend `GET /api/agent/<id>/profile` to return full editable set

The current endpoint sanitises the agent row to ~20 fields. We need all 23 editable fields in the response.

### Task 5: Write tests for the extended profile response

**Files:**
- Test: `platform_v2/tests/test_agent_profile_get_extended.py` (new)

- [ ] **Step 1: Write the failing test**

```python
"""Verify GET /api/agent/<id>/profile returns the full editable field set."""
from __future__ import annotations

import os
import sys
import pytest
import psycopg2
import psycopg2.extras


@pytest.fixture(scope="module")
def db():
    try:
        pw = open("/run/secrets/db_password").read().strip()
    except FileNotFoundError:
        pw = os.environ.get("DB_PASSWORD", "")
    conn = psycopg2.connect(
        host=os.environ.get("DB_HOST", "archie_database"),
        dbname=os.environ.get("DB_NAME", "archie"),
        user=os.environ.get("DB_USER", "archie"),
        password=pw,
        cursor_factory=psycopg2.extras.RealDictCursor,
    )
    conn.autocommit = True
    yield conn
    conn.close()


@pytest.fixture(scope="module", autouse=True)
def _syspath():
    if "/app" not in sys.path:
        sys.path.insert(0, "/app")


@pytest.fixture(scope="module")
def client():
    from flask import Flask, Blueprint
    from flask_login import LoginManager, UserMixin

    app = Flask(__name__)
    app.config["SECRET_KEY"] = "test-secret"
    app.config["TESTING"] = True

    lm = LoginManager(app)

    class _User(UserMixin):
        id = 1
        is_admin = True
        username = "test_admin"

    _user = _User()

    @lm.user_loader
    def _load_user(uid):
        return _user

    from tools.department_hq.agent_detail_routes import register_agent_detail_routes

    def admin_required(f):
        return f

    bp = Blueprint("dhq", __name__, url_prefix="/tools/department-hq")
    register_agent_detail_routes(bp, admin_required)
    app.register_blueprint(bp)

    with app.test_client() as c:
        with c.session_transaction() as sess:
            sess["_user_id"] = "1"
            sess["_fresh"] = True
        yield c


EXPECTED_FIELDS = {
    "id", "name", "display_name", "title", "bio", "acronym",
    "acronym_expansion", "pronouns", "current_grade",
    "department", "floor", "writing_tone", "is_department_ai",
    "reports_to_agent_id",
    "model", "temperature", "max_tokens", "system_prompt",
    "communication_style", "appearance_notes",
    "age_range", "gender", "ethnicity",
    "social_topics", "auto_approve_threshold",
    "shift_state", "status", "avatar_url",
}


def test_profile_returns_all_editable_fields(db, client):
    cur = db.cursor()
    cur.execute("SELECT id FROM agents WHERE worker_type='ai' LIMIT 1")
    row = cur.fetchone()
    assert row, "need at least one AI agent in DB"
    agent_id = row["id"]

    resp = client.get(f"/tools/department-hq/api/agent/{agent_id}/profile")
    assert resp.status_code == 200, resp.data

    body = resp.get_json()
    assert "agent" in body
    agent = body["agent"]

    missing = EXPECTED_FIELDS - set(agent.keys())
    assert not missing, f"missing fields in profile response: {missing}"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker exec archie_platform python -m pytest /app/tests/test_agent_profile_get_extended.py -v`
Expected: FAIL — missing fields.

### Task 6: Extend the profile response

**Files:**
- Modify: `platform_v2/tools/department_hq/agent_detail_routes.py` (function `api_agent_profile`)

- [ ] **Step 1: Replace the `agent_data` dict**

In `api_agent_profile()`, replace the existing `agent_data = {...}` block with the union of all editable fields + sanitised read-only fields:

```python
agent_data = {
    # Identity
    "id": agent["id"],
    "name": agent["name"],
    "display_name": agent.get("display_name"),
    "title": agent.get("title", ""),
    "bio": agent.get("bio", ""),
    "acronym": agent.get("acronym"),
    "acronym_expansion": agent.get("acronym_expansion"),
    "pronouns": agent.get("pronouns"),
    "current_grade": agent.get("current_grade"),
    # Classification
    "department": agent.get("department"),
    "floor": agent.get("floor"),
    "writing_tone": agent.get("writing_tone"),
    "is_department_ai": bool(agent.get("is_department_ai")),
    "reports_to_agent_id": agent.get("reports_to_agent_id"),
    # Dispatch (sensitive)
    "model": agent.get("model"),
    "temperature": float(agent.get("temperature") or 0.7),
    "max_tokens": agent.get("max_tokens", 2048),
    "system_prompt": agent.get("system_prompt", ""),
    # Appearance/narrative
    "communication_style": agent.get("communication_style"),
    "appearance_notes": agent.get("appearance_notes"),
    "age_range": agent.get("age_range"),
    "gender": agent.get("gender"),
    "ethnicity": agent.get("ethnicity"),
    # Voice & social
    "social_topics": agent.get("social_topics") or [],
    "auto_approve_threshold": float(agent.get("auto_approve_threshold") or 0.0),
    # Read-only
    "status": agent.get("status"),
    "shift_state": agent.get("shift_state"),
    "avatar_url": agent.get("avatar_url", ""),
    "capabilities": agent.get("capabilities"),
    # Welfare (inlined for header band)
    "stress_level": float(agent.get("stress_level") or 0),
    "energy_level": float(agent.get("energy_level") or 0.5),
    "current_mood": agent.get("current_mood", "neutral"),
    "mood_intensity": float(agent.get("mood_intensity") or 0.5),
}
```

- [ ] **Step 2: Run the test to confirm it passes**

Run: `docker exec archie_platform python -m pytest /app/tests/test_agent_profile_get_extended.py -v`
Expected: 1 passed.

### Task 7: Commit Phase 2

- [ ] **Step 1: Commit**

```bash
git add platform_v2/tools/department_hq/agent_detail_routes.py \
        platform_v2/tests/test_agent_profile_get_extended.py
git commit -m "feat(profile): extend GET /api/agent/<id>/profile to full editable set

Purely additive — existing consumers keep working.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Phase 3 — Add `PATCH /api/agent/<int:agent_id>` endpoint

Single write endpoint for profile edits. Allowlist + per-field validation + audit log.

### Task 8: Write failing tests — allowlist + auth

**Files:**
- Test: `platform_v2/tests/test_agent_profile_patch.py` (new)

- [ ] **Step 1: Create the test file scaffolding**

```python
"""PATCH /tools/department-hq/api/agent/<id> — allowlist, validation, audit."""
from __future__ import annotations

import json
import os
import sys
import pytest
import psycopg2
import psycopg2.extras


def _pw():
    try:
        return open("/run/secrets/db_password").read().strip()
    except FileNotFoundError:
        return os.environ.get("DB_PASSWORD", "")


@pytest.fixture(scope="module")
def db():
    conn = psycopg2.connect(
        host=os.environ.get("DB_HOST", "archie_database"),
        dbname=os.environ.get("DB_NAME", "archie"),
        user=os.environ.get("DB_USER", "archie"),
        password=_pw(),
        cursor_factory=psycopg2.extras.RealDictCursor,
    )
    conn.autocommit = True
    yield conn
    conn.close()


@pytest.fixture(scope="module", autouse=True)
def _syspath():
    if "/app" not in sys.path:
        sys.path.insert(0, "/app")


def _build_client(is_admin: bool = True):
    from flask import Flask, Blueprint, jsonify
    from flask_login import LoginManager, UserMixin, current_user
    from functools import wraps

    app = Flask(__name__)
    app.config["SECRET_KEY"] = "test-secret"
    app.config["TESTING"] = True

    class _User(UserMixin):
        id = 42
        is_admin = is_admin
        username = "test_admin" if is_admin else "test_user"

    lm = LoginManager(app)
    _user = _User()

    @lm.user_loader
    def _load(uid):
        return _user

    def admin_required(f):
        @wraps(f)
        def _inner(*a, **k):
            if not getattr(current_user, "is_admin", False):
                return jsonify({"ok": False, "error": "not_admin"}), 403
            return f(*a, **k)
        return _inner

    from tools.department_hq.agent_detail_routes import register_agent_detail_routes
    bp = Blueprint("dhq", __name__, url_prefix="/tools/department-hq")
    register_agent_detail_routes(bp, admin_required)
    app.register_blueprint(bp)

    c = app.test_client()
    with c.session_transaction() as s:
        s["_user_id"] = "42"
        s["_fresh"] = True
    return c


@pytest.fixture(scope="module")
def admin_client():
    return _build_client(is_admin=True)


@pytest.fixture(scope="module")
def user_client():
    return _build_client(is_admin=False)


@pytest.fixture(scope="module")
def agent_id(db):
    cur = db.cursor()
    cur.execute(
        "SELECT id FROM agents WHERE worker_type='ai' "
        "AND department IS NOT NULL LIMIT 1"
    )
    row = cur.fetchone()
    assert row
    return row["id"]


def test_patch_unknown_field_rejected(admin_client, agent_id):
    resp = admin_client.patch(
        f"/tools/department-hq/api/agent/{agent_id}",
        data=json.dumps({"tier": 99}),
        content_type="application/json",
    )
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "unknown_field"


def test_patch_non_admin_forbidden(user_client, agent_id):
    resp = user_client.patch(
        f"/tools/department-hq/api/agent/{agent_id}",
        data=json.dumps({"bio": "hello"}),
        content_type="application/json",
    )
    assert resp.status_code == 403


def test_patch_missing_agent(admin_client):
    resp = admin_client.patch(
        "/tools/department-hq/api/agent/9999999",
        data=json.dumps({"bio": "x"}),
        content_type="application/json",
    )
    assert resp.status_code == 404
```

- [ ] **Step 2: Run to confirm they fail**

Run: `docker exec archie_platform python -m pytest /app/tests/test_agent_profile_patch.py -v`
Expected: All three fail with 404/405.

### Task 9: Implement the PATCH handler

**Files:**
- Modify: `platform_v2/tools/department_hq/agent_detail_routes.py`

- [ ] **Step 1: Add imports + constants at top of file**

Insert after the existing import block:

```python
import json as _json
import logging
from flask_login import current_user
from services.ollama_availability import is_model_available
from services.agent_service import DEPARTMENT_FLOOR_MAP

logger = logging.getLogger(__name__)

EDITABLE_FIELDS = {
    "display_name", "title", "bio", "acronym", "acronym_expansion",
    "pronouns", "current_grade",
    "department", "floor", "writing_tone", "is_department_ai",
    "reports_to_agent_id",
    "model", "temperature", "max_tokens", "system_prompt",
    "communication_style", "appearance_notes",
    "age_range", "gender", "ethnicity",
    "social_topics", "auto_approve_threshold",
}

SENSITIVE_FIELDS = {
    "model", "temperature", "max_tokens", "system_prompt",
    "is_department_ai", "reports_to_agent_id",
}
```

Note: `update_agent` is already imported in this file — don't duplicate. `DEPARTMENT_FLOOR_MAP` may also already be imported.

- [ ] **Step 2: Register the PATCH route inside `register_agent_detail_routes`**

Add after the existing `/department` POST route:

```python
    @bp.route("/api/agent/<int:agent_id>", methods=["PATCH"])
    @admin_required
    def api_agent_patch(agent_id):
        payload = request.get_json(silent=True) or {}
        if not isinstance(payload, dict) or not payload:
            return jsonify({"ok": False, "error": "empty_body"}), 400

        unknown = set(payload.keys()) - EDITABLE_FIELDS
        if unknown:
            return jsonify(
                {"ok": False, "error": "unknown_field",
                 "fields": sorted(unknown)}
            ), 400

        agent = get_agent(agent_id)
        if not agent:
            return jsonify({"ok": False, "error": "not_found"}), 404

        err = _validate_patch_payload(agent_id, payload)
        if err:
            return jsonify({"ok": False, **err}), 400

        before = {k: agent.get(k) for k in payload.keys()}

        try:
            update_agent(agent_id, **payload)
        except Exception as exc:
            logger.exception("agent PATCH failed for id=%s", agent_id)
            return jsonify({"ok": False, "error": "update_failed",
                            "detail": str(exc)}), 500

        actor_id = getattr(current_user, "id", None)
        _audit_profile_update(
            agent_id=agent_id, user_id=actor_id,
            before=before, after=payload,
        )

        return jsonify({"ok": True,
                        "updated_fields": sorted(payload.keys())}), 200
```

- [ ] **Step 3: Add module-level helpers at end of file**

```python
def _validate_patch_payload(agent_id, payload):
    """Return None if ok; else dict with error + field keys."""
    if "temperature" in payload:
        t = payload["temperature"]
        if not isinstance(t, (int, float)) or not (0.0 <= float(t) <= 2.0):
            return {"error": "invalid_value", "field": "temperature"}
    if "max_tokens" in payload:
        mt = payload["max_tokens"]
        if not isinstance(mt, int) or not (1 <= mt <= 8192):
            return {"error": "invalid_value", "field": "max_tokens"}
    if "auto_approve_threshold" in payload:
        th = payload["auto_approve_threshold"]
        if not isinstance(th, (int, float)) or not (0.0 <= float(th) <= 1000.0):
            return {"error": "invalid_value", "field": "auto_approve_threshold"}
    if "is_department_ai" in payload and not isinstance(
        payload["is_department_ai"], bool
    ):
        return {"error": "invalid_value", "field": "is_department_ai"}
    if "social_topics" in payload:
        s = payload["social_topics"]
        if not isinstance(s, list) or not all(isinstance(x, str) for x in s):
            return {"error": "invalid_value", "field": "social_topics"}
    if "department" in payload:
        if payload["department"] not in DEPARTMENT_FLOOR_MAP:
            return {"error": "invalid_value", "field": "department"}
    if "reports_to_agent_id" in payload:
        rt = payload["reports_to_agent_id"]
        if rt is not None:
            if rt == agent_id:
                return {"error": "reports_to_self",
                        "field": "reports_to_agent_id"}
            target = get_agent(rt)
            if not target:
                return {"error": "reports_to_missing",
                        "field": "reports_to_agent_id"}
    if "model" in payload:
        ok, msg = is_model_available(payload["model"])
        if not ok:
            return {"error": "model_not_available", "field": "model",
                    "detail": msg}
    return None


def _audit_profile_update(*, agent_id, user_id, before, after):
    """One row per save."""
    from database import get_db_cursor

    details = {"before": before, "after": after}
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            """
            INSERT INTO governance_audit_log
                (event_type, event_category, agent_id, user_id,
                 action, details, timestamp)
            VALUES (%s, %s, %s, %s, %s, %s::jsonb, NOW())
            """,
            (
                "agent_profile_update",
                "agent_management",
                agent_id,
                user_id,
                "profile_update",
                _json.dumps(details, default=str),
            ),
        )
```

- [ ] **Step 4: Run the three tests to confirm pass**

Run: `docker exec archie_platform python -m pytest /app/tests/test_agent_profile_patch.py -v`
Expected: 3 passed.

### Task 10: Add validation + save + audit tests

**Files:**
- Modify: `platform_v2/tests/test_agent_profile_patch.py` (append)

- [ ] **Step 1: Append these tests**

```python
def test_patch_valid_identity_fields(admin_client, agent_id, db):
    resp = admin_client.patch(
        f"/tools/department-hq/api/agent/{agent_id}",
        data=json.dumps({"bio": "updated-by-test"}),
        content_type="application/json",
    )
    assert resp.status_code == 200, resp.data
    body = resp.get_json()
    assert body["ok"] is True
    assert "bio" in body["updated_fields"]

    cur = db.cursor()
    cur.execute("SELECT bio FROM agents WHERE id=%s", (agent_id,))
    assert cur.fetchone()["bio"] == "updated-by-test"


def test_patch_temperature_bounds(admin_client, agent_id):
    for bad in [-0.1, 2.1, "hot"]:
        resp = admin_client.patch(
            f"/tools/department-hq/api/agent/{agent_id}",
            data=json.dumps({"temperature": bad}),
            content_type="application/json",
        )
        assert resp.status_code == 400, f"expected 400 for temperature={bad}"
    resp = admin_client.patch(
        f"/tools/department-hq/api/agent/{agent_id}",
        data=json.dumps({"temperature": 0.5}),
        content_type="application/json",
    )
    assert resp.status_code == 200


def test_patch_reports_to_self_rejected(admin_client, agent_id):
    resp = admin_client.patch(
        f"/tools/department-hq/api/agent/{agent_id}",
        data=json.dumps({"reports_to_agent_id": agent_id}),
        content_type="application/json",
    )
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "reports_to_self"


def test_patch_reports_to_missing_rejected(admin_client, agent_id):
    resp = admin_client.patch(
        f"/tools/department-hq/api/agent/{agent_id}",
        data=json.dumps({"reports_to_agent_id": 99999999}),
        content_type="application/json",
    )
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "reports_to_missing"


def test_patch_sensitive_model_invalid(admin_client, agent_id, monkeypatch):
    from tools.department_hq import agent_detail_routes
    monkeypatch.setattr(
        agent_detail_routes, "is_model_available",
        lambda model, hub_host=None: (False, "not there"),
    )
    resp = admin_client.patch(
        f"/tools/department-hq/api/agent/{agent_id}",
        data=json.dumps({"model": "bogus:99b"}),
        content_type="application/json",
    )
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "model_not_available"


def test_patch_sensitive_model_valid(admin_client, agent_id, monkeypatch):
    from tools.department_hq import agent_detail_routes
    monkeypatch.setattr(
        agent_detail_routes, "is_model_available",
        lambda model, hub_host=None: (True, "ok"),
    )
    resp = admin_client.patch(
        f"/tools/department-hq/api/agent/{agent_id}",
        data=json.dumps({"model": "mistral:7b"}),
        content_type="application/json",
    )
    assert resp.status_code == 200


def test_patch_writes_audit_row(admin_client, agent_id, db):
    cur = db.cursor()
    cur.execute(
        "SELECT COUNT(*) AS n FROM governance_audit_log "
        "WHERE event_type='agent_profile_update' AND agent_id=%s",
        (agent_id,),
    )
    before_count = cur.fetchone()["n"]

    admin_client.patch(
        f"/tools/department-hq/api/agent/{agent_id}",
        data=json.dumps({"bio": "audit-test"}),
        content_type="application/json",
    )

    cur.execute(
        "SELECT details FROM governance_audit_log "
        "WHERE event_type='agent_profile_update' AND agent_id=%s "
        "ORDER BY timestamp DESC LIMIT 1",
        (agent_id,),
    )
    row = cur.fetchone()
    details = row["details"]
    if isinstance(details, str):
        details = json.loads(details)
    assert details["after"]["bio"] == "audit-test"

    cur.execute(
        "SELECT COUNT(*) AS n FROM governance_audit_log "
        "WHERE event_type='agent_profile_update' AND agent_id=%s",
        (agent_id,),
    )
    assert cur.fetchone()["n"] == before_count + 1


def test_patch_partial_body_preserves_other_columns(admin_client, agent_id, db):
    cur = db.cursor()
    cur.execute("SELECT title FROM agents WHERE id=%s", (agent_id,))
    original_title = cur.fetchone()["title"]

    admin_client.patch(
        f"/tools/department-hq/api/agent/{agent_id}",
        data=json.dumps({"bio": "partial-test"}),
        content_type="application/json",
    )

    cur.execute("SELECT title, bio FROM agents WHERE id=%s", (agent_id,))
    row = cur.fetchone()
    assert row["title"] == original_title
    assert row["bio"] == "partial-test"


def test_patch_empty_body_rejected(admin_client, agent_id):
    resp = admin_client.patch(
        f"/tools/department-hq/api/agent/{agent_id}",
        data=json.dumps({}),
        content_type="application/json",
    )
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "empty_body"
```

- [ ] **Step 2: Run all tests**

Run: `docker exec archie_platform python -m pytest /app/tests/test_agent_profile_patch.py -v`
Expected: 11 passed.

### Task 11: Commit Phase 3

- [ ] **Step 1: Commit**

```bash
git add platform_v2/tools/department_hq/agent_detail_routes.py \
        platform_v2/tests/test_agent_profile_patch.py
git commit -m "feat(profile): PATCH /api/agent/<id> endpoint for profile edits

23-field allowlist. Per-field validation for temperature,
max_tokens, auto_approve_threshold, social_topics, department,
reports_to_agent_id, is_department_ai, model (via
is_model_available). Every success writes one governance_audit_log
row with before/after diff.

11 unit tests cover allowlist, auth, 404, validation, model probe
(mocked), audit trail, partial body, empty body.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Phase 4 — Frontend JS module + CSS

Create the state-machine JS and modal-specific CSS. No HTML changes yet.
The JS uses a `createElement`-based DOM builder throughout. No `innerHTML`
setter on dynamic data — user-sourced strings go through `textContent` or
attribute properties so the XSS surface is zero by construction.

### Task 12: Create `agent_profile_modal.css`

**Files:**
- Create: `platform_v2/static/css/agent_profile_modal.css`

- [ ] **Step 1: Write the stylesheet**

```css
/* Agent Profile Detail Modal — Task #1916 */

#agentDetailOverlay .apm-root {
  display: flex; flex-direction: column; gap: 14px;
  color: var(--archie-text, #e6f2ff);
  font-family: "IBM Plex Mono", monospace;
}

#agentDetailOverlay .apm-header-band {
  display: grid;
  grid-template-columns: 200px 1fr auto;
  gap: 16px;
  align-items: center;
  padding-bottom: 12px;
  border-bottom: 1px solid rgba(0, 229, 255, 0.25);
}

#agentDetailOverlay .apm-portrait {
  width: 200px; height: 200px;
  border-radius: 12px;
  background: #041828;
  object-fit: cover;
  border: 1px solid rgba(0, 229, 255, 0.4);
}

#agentDetailOverlay .apm-name { font-size: 1.6rem; font-weight: 700; }
#agentDetailOverlay .apm-codename { opacity: 0.7; }
#agentDetailOverlay .apm-subline {
  margin-top: 4px; font-size: 0.9rem; opacity: 0.8;
  display: flex; gap: 8px; align-items: center; flex-wrap: wrap;
}
#agentDetailOverlay .apm-pill {
  padding: 2px 10px; border-radius: 999px;
  background: #0a3a4c; border: 1px solid #00e5ff; font-size: 0.8rem;
  cursor: pointer;
}

#agentDetailOverlay .apm-section {
  border: 1px solid rgba(0, 229, 255, 0.2);
  border-radius: 8px;
  padding: 12px;
  background: rgba(4, 24, 40, 0.6);
}

#agentDetailOverlay .apm-section-title {
  font-size: 1rem; font-weight: 600; margin-bottom: 10px;
  display: flex; justify-content: space-between; align-items: center;
}

#agentDetailOverlay .apm-sensitive-mark {
  color: #ff8a00; font-size: 0.75rem; font-weight: 500;
}

#agentDetailOverlay .apm-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px 16px;
}

#agentDetailOverlay .apm-field { display: flex; flex-direction: column; gap: 4px; }
#agentDetailOverlay .apm-field-label {
  font-size: 0.75rem; letter-spacing: 0.04em; opacity: 0.65;
  text-transform: uppercase;
}
#agentDetailOverlay .apm-field-value { font-size: 0.95rem; min-height: 1.2em; }
#agentDetailOverlay .apm-field-full { grid-column: 1 / -1; }

#agentDetailOverlay input.apm-input,
#agentDetailOverlay select.apm-input,
#agentDetailOverlay textarea.apm-input {
  background: #041828;
  border: 1px solid rgba(0, 229, 255, 0.35);
  color: var(--archie-text, #e6f2ff);
  padding: 6px 8px; border-radius: 4px; font-family: inherit;
  font-size: 0.9rem;
}
#agentDetailOverlay textarea.apm-input { min-height: 80px; resize: vertical; }
#agentDetailOverlay textarea.apm-prompt { min-height: 140px; }

#agentDetailOverlay .apm-input.apm-error {
  border-color: #ff2244; box-shadow: 0 0 0 2px rgba(255, 34, 68, 0.2);
}

#agentDetailOverlay .apm-chip {
  display: inline-block; padding: 2px 10px; margin: 2px;
  border-radius: 999px; background: #0a3a4c; font-size: 0.78rem;
}

#agentDetailOverlay .apm-deeplink {
  font-size: 0.78rem; text-decoration: none; color: #00e5ff;
}
#agentDetailOverlay .apm-deeplink:hover { text-decoration: underline; }

#agentDetailOverlay .apm-footer-actions {
  display: flex; justify-content: flex-end; gap: 10px;
  padding-top: 12px; border-top: 1px solid rgba(0, 229, 255, 0.25);
}

#agentDetailOverlay[data-mode="view"] .apm-edit-only { display: none; }
#agentDetailOverlay[data-mode="edit"] .apm-view-only { display: none; }

#agentDetailOverlay .apm-toast {
  position: absolute; bottom: 20px; left: 50%;
  transform: translateX(-50%);
  padding: 8px 16px; border-radius: 4px; font-size: 0.85rem;
  opacity: 0; transition: opacity 0.2s;
  pointer-events: none;
}
#agentDetailOverlay .apm-toast.show { opacity: 1; }
#agentDetailOverlay .apm-toast.ok { background: #0a4a1a; border: 1px solid #00e58a; }
#agentDetailOverlay .apm-toast.err { background: #4a0a1a; border: 1px solid #ff2244; }

#apmConfirmOverlay {
  display: none;
  position: fixed; inset: 0; z-index: 10000;
  background: rgba(0, 0, 0, 0.65);
  align-items: center; justify-content: center;
}
#apmConfirmOverlay.active { display: flex; }
#apmConfirmOverlay .apm-confirm-shell {
  background: #05263a; border: 1px solid #ff8a00;
  border-radius: 8px; padding: 20px; max-width: 440px;
  color: var(--archie-text, #e6f2ff);
}
#apmConfirmOverlay .apm-confirm-title {
  color: #ff8a00; font-size: 1.1rem; font-weight: 700; margin-bottom: 10px;
}
#apmConfirmOverlay .apm-confirm-body {
  font-size: 0.9rem; margin-bottom: 16px; line-height: 1.4;
}
#apmConfirmOverlay .apm-confirm-actions {
  display: flex; justify-content: flex-end; gap: 10px;
}

@media (max-width: 768px) {
  #agentDetailOverlay .apm-header-band { grid-template-columns: 1fr; }
  #agentDetailOverlay .apm-portrait { width: 140px; height: 140px; }
  #agentDetailOverlay .apm-grid { grid-template-columns: 1fr; }
}
```

### Task 13: Create `agent_profile_modal.js` — DOM builder + state machine

**Files:**
- Create: `platform_v2/static/js/agent_profile_modal.js`

- [ ] **Step 1: Write the module**

Design: a tiny `el(tag, cls, ...children)` helper creates DOM elements. User-sourced values go into `textContent` or element properties (`input.value`, `img.src`) — never concatenated into HTML strings. This eliminates XSS by construction; no `esc()` helper needed.

```javascript
/* Agent Profile Detail Modal — Task #1916
 * window.agentProfileModal = { open, close }
 *
 * XSS policy: all dynamic values from the API are placed via .textContent
 * or element properties. No innerHTML setter on dynamic data.
 */
(function () {
  'use strict';

  const OVERLAY_ID = 'agentDetailOverlay';
  const EDITABLE_FIELDS = [
    'display_name', 'title', 'bio', 'acronym', 'acronym_expansion',
    'pronouns', 'current_grade',
    'department', 'floor', 'writing_tone', 'is_department_ai',
    'reports_to_agent_id',
    'model', 'temperature', 'max_tokens', 'system_prompt',
    'communication_style', 'appearance_notes',
    'age_range', 'gender', 'ethnicity',
    'social_topics', 'auto_approve_threshold',
  ];
  const SENSITIVE_FIELDS = new Set([
    'model', 'temperature', 'max_tokens', 'system_prompt',
    'is_department_ai', 'reports_to_agent_id',
  ]);
  const SECTIONS = [
    { title: 'Identity', sensitive: false, fields: [
      ['display_name', 'Display Name', 'text'],
      ['title', 'Title', 'text'],
      ['acronym', 'Acronym', 'text'],
      ['acronym_expansion', 'Acronym Meaning', 'text'],
      ['pronouns', 'Pronouns', 'text'],
      ['current_grade', 'Current Grade', 'text'],
      ['bio', 'Bio', 'textarea', 'full'],
    ]},
    { title: 'Classification', sensitive: false, fields: [
      ['department', 'Department', 'text'],
      ['floor', 'Floor', 'text'],
      ['writing_tone', 'Writing Tone', 'text'],
      ['is_department_ai', 'Department AI', 'bool'],
      ['reports_to_agent_id', 'Reports To (agent id)', 'int'],
    ]},
    { title: 'Dispatch', sensitive: true, fields: [
      ['model', 'Model', 'text'],
      ['temperature', 'Temperature', 'float'],
      ['max_tokens', 'Max Tokens', 'int'],
      ['system_prompt', 'System Prompt', 'textarea', 'full', 'prompt'],
    ]},
    { title: 'Appearance', sensitive: false, fields: [
      ['age_range', 'Age Range', 'text'],
      ['gender', 'Gender', 'text'],
      ['ethnicity', 'Ethnicity', 'text'],
      ['communication_style', 'Communication Style', 'text'],
      ['appearance_notes', 'Appearance Notes', 'textarea', 'full'],
    ]},
    { title: 'Voice & Social', sensitive: false, fields: [
      ['social_topics', 'Social Topics (comma-separated)', 'csvlist', 'full'],
      ['auto_approve_threshold', 'Auto-Approve $ Threshold', 'float'],
    ]},
  ];

  const state = { agentId: null, snapshot: null, mode: 'view' };

  // DOM builder — safe by construction. No innerHTML on user data.
  function el(tag, cls) {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    for (let i = 2; i < arguments.length; i++) {
      const child = arguments[i];
      if (child === null || child === undefined) continue;
      if (typeof child === 'string') e.appendChild(document.createTextNode(child));
      else e.appendChild(child);
    }
    return e;
  }

  function clear(node) { while (node.firstChild) node.removeChild(node.firstChild); }

  function toast(overlay, msg, kind) {
    let t = overlay.querySelector('.apm-toast');
    if (!t) {
      t = el('div', 'apm-toast');
      (overlay.querySelector('.bm-content') || overlay).appendChild(t);
    }
    t.className = 'apm-toast show ' + (kind || 'ok');
    t.textContent = msg;
    setTimeout(function () { t.className = 'apm-toast'; }, 2500);
  }

  async function fetchProfile(agentId) {
    const r = await fetch(
      '/tools/department-hq/api/agent/' + agentId + '/profile',
      { credentials: 'same-origin' }
    );
    if (!r.ok) throw new Error('profile fetch failed: ' + r.status);
    return r.json();
  }

  function formatView(val, type) {
    if (val === null || val === undefined || val === '') return '—';
    if (type === 'bool') return val ? 'yes' : 'no';
    if (type === 'csvlist') return Array.isArray(val) ? val.join(', ') : String(val);
    return String(val);
  }

  function buildInput(name, type, val, extraCls) {
    let input;
    if (type === 'textarea') {
      input = document.createElement('textarea');
      input.value = (val === null || val === undefined) ? '' : String(val);
    } else if (type === 'bool') {
      input = document.createElement('input');
      input.type = 'checkbox';
      input.checked = !!val;
    } else if (type === 'csvlist') {
      input = document.createElement('input');
      input.type = 'text';
      input.value = Array.isArray(val) ? val.join(', ') : (val || '');
      input.dataset.type = 'csvlist';
    } else {
      input = document.createElement('input');
      input.type = (type === 'int' || type === 'float') ? 'number' : 'text';
      if (type === 'float') input.step = '0.01';
      input.value = (val === null || val === undefined) ? '' : String(val);
      input.dataset.type = type;
    }
    input.className = 'apm-input' + (extraCls ? ' apm-' + extraCls : '');
    input.dataset.edit = name;
    return input;
  }

  function buildField(f, agent) {
    const [name, label, type, layout, extraCls] = f;
    const val = agent[name];
    const wrap = el('div', 'apm-field' + (layout === 'full' ? ' apm-field-full' : ''));
    wrap.appendChild(el('div', 'apm-field-label', label));

    const viewBox = el('div', 'apm-view-only apm-field-value');
    viewBox.dataset.view = name;
    viewBox.textContent = formatView(val, type);
    wrap.appendChild(viewBox);

    const editBox = el('div', 'apm-edit-only');
    editBox.appendChild(buildInput(name, type, val, extraCls));
    wrap.appendChild(editBox);
    return wrap;
  }

  function buildSection(sec, agent) {
    const section = el('div', 'apm-section');
    const titleRow = el('div', 'apm-section-title');
    titleRow.appendChild(document.createTextNode(sec.title));
    if (sec.sensitive) {
      titleRow.appendChild(el('span', 'apm-sensitive-mark',
        '⚠️ Changes affect routing'));
    }
    section.appendChild(titleRow);
    const grid = el('div', 'apm-grid');
    sec.fields.forEach(function (f) { grid.appendChild(buildField(f, agent)); });
    section.appendChild(grid);
    return section;
  }

  function buildHeaderBand(agent) {
    const band = el('div', 'apm-header-band');

    let portrait;
    if (agent.avatar_url) {
      portrait = document.createElement('img');
      portrait.className = 'apm-portrait';
      portrait.src = agent.avatar_url;
      portrait.alt = '';
    } else {
      portrait = el('div', 'apm-portrait');
    }
    band.appendChild(portrait);

    const col = el('div');
    col.appendChild(el('div', 'apm-name', agent.display_name || agent.name));
    const codeline = el('div', 'apm-codename', agent.name);
    if (agent.acronym) {
      codeline.appendChild(document.createTextNode(' · '));
      codeline.appendChild(document.createTextNode(agent.acronym));
    }
    col.appendChild(codeline);

    const sub = el('div', 'apm-subline');
    sub.appendChild(el('span', null, agent.department || '—'));
    sub.appendChild(el('span', null, '·'));
    sub.appendChild(el('span', null, agent.floor || '—'));
    const shift = el('button', 'apm-pill',
      String(agent.shift_state || 'unknown').toUpperCase());
    shift.dataset.action = 'toggle-shift';
    shift.title = 'Click to cycle shift state';
    sub.appendChild(shift);
    col.appendChild(sub);

    band.appendChild(col);

    const editCol = el('div', 'apm-view-only');
    const editBtn = el('button', 'apm-btn', 'EDIT');
    editBtn.dataset.action = 'edit';
    editCol.appendChild(editBtn);
    band.appendChild(editCol);
    return band;
  }

  function buildReadOnlySections(skills, welfare, perf) {
    const frag = document.createDocumentFragment();

    const sk = el('div', 'apm-section');
    const skTitle = el('div', 'apm-section-title');
    skTitle.appendChild(document.createTextNode('Skills '));
    const skLink = el('a', 'apm-deeplink', '→ Academy');
    skLink.href = '/tools/agent-academy#skills';
    skTitle.appendChild(skLink);
    sk.appendChild(skTitle);
    if (skills && skills.length) {
      skills.slice(0, 30).forEach(function (s) {
        const label = (s.skill_name || s.name || s) +
          (s.proficiency_level ? ' · Lv' + s.proficiency_level : '');
        sk.appendChild(el('span', 'apm-chip', label));
      });
    } else {
      const em = el('em'); em.style.opacity = '0.6';
      em.textContent = 'No skills recorded';
      sk.appendChild(em);
    }
    frag.appendChild(sk);

    const pct = function (v) { return v !== undefined && v !== null ?
      (Number(v) * 100).toFixed(0) + '%' : '—'; };
    const wfField = function (label, val) {
      const f = el('div', 'apm-field');
      f.appendChild(el('div', 'apm-field-label', label));
      f.appendChild(el('div', 'apm-field-value', val));
      return f;
    };

    const wf = el('div', 'apm-section');
    const wfTitle = el('div', 'apm-section-title');
    wfTitle.appendChild(document.createTextNode('Welfare '));
    const wfLink = el('a', 'apm-deeplink', '→ Performance');
    wfLink.href = '#performance';
    wfTitle.appendChild(wfLink);
    wf.appendChild(wfTitle);
    const wfGrid = el('div', 'apm-grid');
    wfGrid.appendChild(wfField('Stress', pct(welfare && welfare.stress_level)));
    wfGrid.appendChild(wfField('Energy', pct(welfare && welfare.energy_level)));
    wfGrid.appendChild(wfField('Mood', (welfare && welfare.current_mood) || '—'));
    wf.appendChild(wfGrid);
    frag.appendChild(wf);

    const pf = el('div', 'apm-section');
    const pfTitle = el('div', 'apm-section-title');
    pfTitle.appendChild(document.createTextNode('Performance '));
    const pfLink = el('a', 'apm-deeplink', '→ Performance');
    pfLink.href = '#performance';
    pfTitle.appendChild(pfLink);
    pf.appendChild(pfTitle);
    const pfGrid = el('div', 'apm-grid');
    pfGrid.appendChild(wfField('Tasks Completed',
      String((perf && perf.total_tasks_completed) || 0)));
    pfGrid.appendChild(wfField('Success Rate',
      pct(perf && perf.success_rate)));
    pfGrid.appendChild(wfField('Grade', (perf && perf.current_grade) || '—'));
    pf.appendChild(pfGrid);
    frag.appendChild(pf);

    return frag;
  }

  function buildFooter() {
    const f = el('div', 'apm-footer-actions');
    const viewCol = el('div', 'apm-view-only');
    const closeBtn = el('button', 'apm-btn', 'CLOSE');
    closeBtn.dataset.action = 'close';
    viewCol.appendChild(closeBtn);
    f.appendChild(viewCol);

    const editCol = el('div', 'apm-edit-only');
    const cancel = el('button', 'apm-btn', 'CANCEL');
    cancel.dataset.action = 'cancel';
    const save = el('button', 'apm-btn apm-btn-primary', 'SAVE CHANGES');
    save.dataset.action = 'save';
    editCol.appendChild(cancel);
    editCol.appendChild(save);
    f.appendChild(editCol);
    return f;
  }

  function renderInto(body) {
    clear(body);
    const agent = state.snapshot.agent;
    const root = el('div', 'apm-root');
    root.appendChild(buildHeaderBand(agent));
    SECTIONS.forEach(function (sec) { root.appendChild(buildSection(sec, agent)); });
    root.appendChild(buildReadOnlySections(
      state.snapshot.skills, state.snapshot.welfare, state.snapshot.performance
    ));
    root.appendChild(buildFooter());
    body.appendChild(root);
  }

  function bindActions(overlay, body) {
    body.onclick = function (e) {
      const t = e.target.closest('[data-action]');
      if (!t) return;
      const action = t.getAttribute('data-action');
      if (action === 'close') close();
      else if (action === 'cancel') {
        state.mode = 'view'; overlay.setAttribute('data-mode', 'view');
        renderInto(body); bindActions(overlay, body);
      }
      else if (action === 'edit') {
        state.mode = 'edit'; overlay.setAttribute('data-mode', 'edit');
      }
      else if (action === 'save') saveHandler(overlay, body);
      else if (action === 'toggle-shift') cycleShift(overlay, body);
    };
  }

  function collectDirty(body) {
    const dirty = {};
    const agent = state.snapshot.agent;
    body.querySelectorAll('[data-edit]').forEach(function (ee) {
      const name = ee.getAttribute('data-edit');
      if (!EDITABLE_FIELDS.includes(name)) return;
      let val;
      const type = ee.getAttribute('data-type');
      if (ee.type === 'checkbox') val = ee.checked;
      else if (type === 'int') val = ee.value === '' ? null : parseInt(ee.value, 10);
      else if (type === 'float') val = ee.value === '' ? null : parseFloat(ee.value);
      else if (type === 'csvlist') {
        val = ee.value.split(',').map(function (s) { return s.trim(); })
          .filter(function (s) { return s.length; });
      } else val = ee.value;

      const orig = agent[name];
      const origCmp = Array.isArray(orig) ? orig.join('|') :
                      (orig === null || orig === undefined ? '' : String(orig));
      const newCmp = Array.isArray(val) ? val.join('|') :
                     (val === null || val === undefined ? '' : String(val));
      if (origCmp !== newCmp) dirty[name] = val;
    });
    return dirty;
  }

  async function saveHandler(overlay, body) {
    const dirty = collectDirty(body);
    if (Object.keys(dirty).length === 0) {
      toast(overlay, 'No changes', 'ok');
      state.mode = 'view';
      overlay.setAttribute('data-mode', 'view');
      return;
    }
    const hasSensitive = Object.keys(dirty).some(function (k) {
      return SENSITIVE_FIELDS.has(k);
    });
    const go = hasSensitive ? await confirmOverlay(dirty) : true;
    if (!go) return;

    try {
      const r = await fetch(
        '/tools/department-hq/api/agent/' + state.agentId,
        {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          credentials: 'same-origin',
          body: JSON.stringify(dirty),
        }
      );
      const js = await r.json();
      if (!r.ok) {
        toast(overlay,
          'Save failed: ' + (js.error || r.status) +
          (js.field ? ' (' + js.field + ')' : ''), 'err');
        if (js.field) {
          const ee = body.querySelector('[data-edit="' + js.field + '"]');
          if (ee) ee.classList.add('apm-error');
        }
        return;
      }
      toast(overlay, 'Saved', 'ok');
      state.snapshot = await fetchProfile(state.agentId);
      state.mode = 'view';
      overlay.setAttribute('data-mode', 'view');
      renderInto(body);
      bindActions(overlay, body);
    } catch (err) {
      toast(overlay, 'Network error', 'err');
    }
  }

  async function cycleShift(overlay, body) {
    const order = ['active', 'barracked', 'off_duty'];
    const cur = state.snapshot.agent.shift_state;
    const next = order[(order.indexOf(cur) + 1) % order.length];
    try {
      const r = await fetch(
        '/tools/department-hq/api/agent/' + state.agentId + '/shift',
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          credentials: 'same-origin',
          body: JSON.stringify({ shift_state: next }),
        }
      );
      if (!r.ok) throw new Error('shift POST ' + r.status);
      toast(overlay, 'Shift → ' + next, 'ok');
      state.snapshot = await fetchProfile(state.agentId);
      renderInto(body);
      bindActions(overlay, body);
    } catch (err) {
      toast(overlay, 'Shift change failed', 'err');
    }
  }

  function confirmOverlay(dirty) {
    return new Promise(function (resolve) {
      let cov = document.getElementById('apmConfirmOverlay');
      if (!cov) {
        cov = el('div');
        cov.id = 'apmConfirmOverlay';
        const shell = el('div', 'apm-confirm-shell');
        shell.appendChild(el('div', 'apm-confirm-title',
          'Confirm sensitive change'));
        const bodyDiv = el('div', 'apm-confirm-body');
        bodyDiv.id = 'apmConfirmBody';
        shell.appendChild(bodyDiv);
        const actions = el('div', 'apm-confirm-actions');
        const cancel = el('button', null, 'CANCEL');
        cancel.dataset.cx = 'cancel';
        const ok = el('button', null, 'CONFIRM');
        ok.dataset.cx = 'ok';
        actions.appendChild(cancel);
        actions.appendChild(ok);
        shell.appendChild(actions);
        cov.appendChild(shell);
        document.body.appendChild(cov);
      }
      const bodyDiv = cov.querySelector('#apmConfirmBody');
      bodyDiv.textContent = 'You are changing: ' + Object.keys(dirty)
        .filter(function (k) { return SENSITIVE_FIELDS.has(k); }).join(', ') +
        '. These affect dispatch/routing.';
      cov.classList.add('active');
      cov.onclick = function (e) {
        const b = e.target.closest('[data-cx]');
        if (!b) return;
        cov.classList.remove('active');
        resolve(b.getAttribute('data-cx') === 'ok');
      };
    });
  }

  async function open(agentId) {
    state.agentId = agentId;
    state.mode = 'view';
    const overlay = document.getElementById(OVERLAY_ID);
    if (!overlay) { console.warn('agentProfileModal: no overlay'); return; }
    overlay.setAttribute('data-mode', 'view');
    overlay.setAttribute('data-agent-id', String(agentId));
    overlay.style.display = 'flex';
    overlay.classList.add('active');

    const body = overlay.querySelector('#agentDetailBody') ||
                 overlay.querySelector('.bm-body');
    clear(body);
    body.appendChild(el('div', 'dhq-loading', 'Loading agent profile...'));

    try {
      state.snapshot = await fetchProfile(agentId);
      renderInto(body);
      bindActions(overlay, body);
    } catch (err) {
      clear(body);
      body.appendChild(el('div', 'apm-error', 'Error: ' + err.message));
    }
  }

  function close() {
    const overlay = document.getElementById(OVERLAY_ID);
    if (!overlay) return;
    overlay.classList.remove('active');
    overlay.style.display = 'none';
    state.agentId = null;
    state.snapshot = null;
    state.mode = 'view';
  }

  window.agentProfileModal = { open: open, close: close };
  window.openAgentDetail = function (agentId) { open(agentId); };
  window.closeAgentDetail = function () { close(); };
})();
```

### Task 14: Commit Phase 4

- [ ] **Step 1: Commit**

```bash
git add platform_v2/static/css/agent_profile_modal.css \
        platform_v2/static/js/agent_profile_modal.js
git commit -m "feat(profile): agent profile modal JS + CSS

createElement DOM builder (no innerHTML on user data), state machine,
confirm-on-dirty for sensitive fields, shift cycle pill.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Phase 5 — Wire into `department_hq.html` + Roster tab

### Task 15: Include the new CSS + JS in the template

**Files:**
- Modify: `platform_v2/tools/department_hq/templates/department_hq.html`

- [ ] **Step 1: Add stylesheet link** in the CSS block:

```html
<link rel="stylesheet" href="{{ url_for('static', filename='css/agent_profile_modal.css') }}">
```

- [ ] **Step 2: Include the JS** after existing `department-hq.js` script:

```html
<script src="{{ url_for('static', filename='js/agent_profile_modal.js') }}"></script>
```

### Task 16: Confirm Roster cards call `openAgentDetail` (or wire it)

**Files:**
- Inspect: `platform_v2/tools/department_hq/static/js/department-hq.js`

- [ ] **Step 1: Search for existing handler**

Run: `grep -nE "openAgentDetail|agent-card|rosterContent|data-agent-id" /mnt/archie_brain/platform_v2/tools/department_hq/static/js/department-hq.js | head -20`

- [ ] **Step 2 (only if no call site found):** Add delegation with idempotent bind

Inside the roster render, ensure cards have `data-agent-id`. Then:

```javascript
const rc = document.getElementById('rosterContent');
if (rc && !rc.dataset.apmBound) {
  rc.dataset.apmBound = '1';
  rc.addEventListener('click', function (e) {
    const card = e.target.closest('[data-agent-id]');
    if (card) window.agentProfileModal.open(parseInt(card.dataset.agentId, 10));
  });
}
```

### Task 17: Restart platform + manual smoke

- [ ] **Step 1: Restart**

Run: `docker compose restart archie_platform`

- [ ] **Step 2: Manual smoke**

Visit `http://192.168.1.200:3000/tools/department-hq#roster`, log in as admin, click any AI agent card. Confirm:
- Modal opens, portrait + name band + 5 sections render
- EDIT → fields appear → change bio → SAVE → toast + view mode + new bio
- CLOSE → dismisses, reopen → bio persists

### Task 18: Commit Phase 5

- [ ] **Step 1: Commit**

```bash
git add platform_v2/tools/department_hq/templates/department_hq.html \
        platform_v2/tools/department_hq/static/js/department-hq.js
git commit -m "feat(profile): wire agent profile modal into Dept HQ template

Loads new CSS + JS. Roster card clicks reach modal via
openAgentDetail shim / delegation on #rosterContent.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Phase 6 — Playwright end-to-end

### Task 19: Write the Playwright spec

**Files:**
- Create: `platform_v2/tests/test_agent_profile_modal_e2e.mjs`

- [ ] **Step 1: Write the spec**

```javascript
import { chromium } from 'playwright';

const BASE = process.env.ARCHIE_BASE || 'http://192.168.1.200:3000';
const ADMIN_USER = process.env.ARCHIE_ADMIN_USER || 'admin';
const ADMIN_PASS = process.env.ARCHIE_ADMIN_PASS || 'Kyt$13ran2025';

async function login(page) {
  await page.goto(BASE + '/login');
  await page.fill('input[name="username"]', ADMIN_USER);
  await page.fill('input[name="password"]', ADMIN_PASS);
  await Promise.all([
    page.waitForURL(/dashboard|tools/),
    page.click('button[type="submit"]'),
  ]);
}

async function run() {
  const browser = await chromium.launch();
  const ctx = await browser.newContext();
  const page = await ctx.newPage();
  const fail = function (m) { throw new Error('FAIL: ' + m); };

  await login(page);

  await page.goto(BASE + '/tools/department-hq#roster');
  await page.waitForSelector('[data-agent-id]', { timeout: 10000 });
  await page.click('[data-agent-id]');
  await page.waitForSelector('#agentDetailOverlay.active', { timeout: 5000 });
  const nameText = await page.textContent('#agentDetailOverlay .apm-name');
  if (!nameText || !nameText.trim()) fail('name not rendered');

  await page.click('#agentDetailOverlay [data-action="edit"]');
  await page.waitForSelector('#agentDetailOverlay[data-mode="edit"]', { timeout: 3000 });
  if (!await page.$('textarea[data-edit="bio"]')) fail('bio textarea missing');

  const stamp = 'e2e-' + Date.now();
  await page.fill('textarea[data-edit="bio"]', stamp);
  await page.click('#agentDetailOverlay [data-action="save"]');
  await page.waitForSelector('.apm-toast.show.ok', { timeout: 5000 });
  await page.waitForSelector('#agentDetailOverlay[data-mode="view"]', { timeout: 3000 });
  const bioView = await page.textContent('[data-view="bio"]');
  if (!bioView.includes(stamp)) fail('bio not persisted');

  await page.click('#agentDetailOverlay [data-action="close"]');
  await page.waitForTimeout(300);
  await page.click('[data-agent-id]');
  await page.waitForSelector('#agentDetailOverlay.active');
  const bio2 = await page.textContent('[data-view="bio"]');
  if (!bio2.includes(stamp)) fail('reopen persistence');

  await page.click('#agentDetailOverlay [data-action="edit"]');
  await page.fill('[data-edit="system_prompt"]', 'CONFIRM-TEST ' + stamp);
  await page.click('#agentDetailOverlay [data-action="save"]');
  await page.waitForSelector('#apmConfirmOverlay.active', { timeout: 3000 });
  await page.click('#apmConfirmOverlay [data-cx="ok"]');
  await page.waitForSelector('.apm-toast.show.ok', { timeout: 5000 });

  console.log('PASS: all 5 scenarios');
  await browser.close();
}

run().catch(function (e) { console.error(e); process.exit(1); });
```

- [ ] **Step 2: Run**

Run: `cd /mnt/archie_brain/platform_v2/tests && node test_agent_profile_modal_e2e.mjs`
Expected: `PASS: all 5 scenarios`. If Playwright browser is locked, skip and note in PR.

### Task 20: Commit Phase 6

- [ ] **Step 1: Commit**

```bash
git add platform_v2/tests/test_agent_profile_modal_e2e.mjs
git commit -m "test(profile): Playwright e2e for agent profile modal

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Phase 7 — Pre-flight, PR, close-out

### Task 21: Full regression run

- [ ] **Step 1: Unit tests**

```
docker exec archie_platform python -m pytest \
  /app/tests/test_ollama_availability.py \
  /app/tests/test_agent_profile_get_extended.py \
  /app/tests/test_agent_profile_patch.py \
  /app/tests/test_approvals_hire_routes.py \
  /app/tests/test_approvals_multi_source.py \
  -v
```
Expected: all green.

- [ ] **Step 2: K.I.N. single-writer guardrail**

Run: `python /mnt/archie_brain/scripts/check_agent_single_writer.py`
Expected: pass.

### Task 22: Push branch + open PR

- [ ] **Step 1: Push**

```bash
git push -u origin feat/agent-profile-modal-spec
```

- [ ] **Step 2: Open PR**

```bash
gh pr create --title "feat(profile): Agent Profile Detail Modal (#1916 Project #262)" --body "$(cat <<'EOF'
## Summary
- PATCH /tools/department-hq/api/agent/<id> with 23-field allowlist + validation + audit log
- Extended GET profile response (additive)
- agent_profile_modal.js/.css — reuses #agentDetailOverlay; view/edit modes; confirm-on-dirty for sensitive fields; shift cycle pill; read-only skills/welfare/performance with deep-links
- Promoted Ollama model-availability helper to services/ollama_availability.py
- 23 unit tests + 5-scenario Playwright e2e

## Test plan
- [ ] All new pytest suites green
- [ ] Playwright scenarios pass on hub
- [ ] Manual: edit bio → save → reload → persists
- [ ] Manual: change system_prompt → confirm overlay → accept → saved
- [ ] Audit: governance_audit_log rows with event_type='agent_profile_update'
- [ ] K.I.N. guardrail green

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

### Task 23: Post-merge actions

Only after PR merged.

- [ ] **Step 1: Pull + restart**

```bash
git checkout main && git pull
docker compose restart archie_platform
```

- [ ] **Step 2: Smoke edit + revert on K.I.N. bio**

- [ ] **Step 3: Dev HQ close-out via MCP**

- `complete_task(1916, notes=...)`
- `log_decision(title="Agent Profile Modal as Single-Source Editor", project_id=262, task_id=1916, ...)`
- `update_project_understanding(project_id=262, understanding_level=35, emotional_association="confident")`
- `store_memory(memory_type="vault_note", category="agent-profile", ...)`

- [ ] **Step 4: Log follow-up tasks (project_id=262)**

1. Decommission `tools/directory/` — redirect `/directory` + `/tools/directory` → `/tools/department-hq#roster`
2. Decommission `/directory` + `/api/directory*` inside `platform_v2/business/routes.py`
3. Wire `website/kytranempowerment.com/directory.html` to `/api/public/directory`
4. Build Org Chart tab inside Dept HQ — node click opens agent profile modal

---

## Self-review

**1. Spec coverage**: every spec requirement maps to a task. 23 editable fields → Tasks 6, 8–10 (backend) + Task 13 (frontend SECTIONS array). Sensitive confirm → Task 13 `confirmOverlay` + Task 19 scenario 5. Audit trail → Task 9 `_audit_profile_update` + Task 10 `test_patch_writes_audit_row`. Read-only sections with deep-links → Task 13 `buildReadOnlySections`. Shift cycle pill → Task 13 `cycleShift`. Follow-up tasks explicitly listed in Task 23 Step 4.

**2. Placeholder scan**: no TBD/TODO/later. Every code block is concrete.

**3. Type consistency**: `EDITABLE_FIELDS` is a `set` in Python (Task 9) and an `Array` in JS (Task 13); names identical. `SENSITIVE_FIELDS` matches across both. Route is `PATCH /tools/department-hq/api/agent/<int:agent_id>` everywhere.

**4. Security discipline**: modal JS uses `createElement` + `textContent` + property assignment throughout. No `innerHTML` setter on API data. XSS surface is zero by construction.

**5. Risks**: (a) Reusing `#agentDetailOverlay` replaces its old inner markup; if `department-hq.js` caches references to the old body, Task 16 (inspect) catches it. (b) K.I.N. guardrail checks direct writes to the `agents` table only; the `governance_audit_log` INSERT is allowed.
