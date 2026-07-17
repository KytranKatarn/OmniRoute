# Collaborator Persona Curated Facts (Grounding) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the collaborator persona email assistant a curated per-collaborator facts store it may cite, and teach the no-fabrication validator to accept those facts — so a recalled figure passes while pure invention still fails closed.

**Architecture:** New `collaborator_facts` table + isolated service. The existing fleet-dispatched collaborator draft job injects a persona's active facts into the prompt and passes the same facts as an `allowed_facts_text` source to `validate_draft_no_fabrication` (one-line change, backward compatible). Facts are curated by the owner in the DHQ agent-profile modal via 4 admin endpoints.

**Tech Stack:** Python 3 / Flask (psycopg2, RealDictCursor), PostgreSQL, vanilla JS (department-hq.js).

## Global Constraints

- **Spec:** `docs/superpowers/specs/2026-07-17-collaborator-persona-curated-facts-grounding-design.md`.
- **`get_db_cursor` yields RealDictCursor DICT rows** — access columns by name (`row["id"]`), NEVER by index (KB mistake #268832). Use `with get_db_cursor(commit=True) as (conn, cur):`.
- **No new inference / no gate flip.** Grounding is a DB read inside the existing fleet-dispatched `mailhq_collaborator_drafts` job. `mailhq:draft:collaborators` stays OFF. Owner/business draft path unchanged.
- **Validator change is backward compatible** — `allowed_facts_text` defaults to `""`; every existing caller behaves identically.
- **Never use `dispatch_json`** in the draft path (masks cold-load queueing, KB #276153) — untouched here; the draft still uses `queued_dispatch_text`.
- **Tests run on the HOST from `platform_v2/`** (the worktree is not volume-mounted into the container): `cd platform_v2 && python3 -m pytest tests/test_collaborator_draft.py -v`. DB-backed tests reach the live DB at `192.168.1.200:5432` via `database.py`. If the host lacks pytest/psycopg2, `docker cp` the changed files into `archie_platform:/app/...` and run pytest there. Migration 460 (Task 1) must be applied to the live DB before the service/DB tests run.
- **Frontend:** render all API text via `textContent` (XSS-safe). Only `api(path)` (GET) and `apiPost(path, body)` (POST) JS helpers exist — mutation endpoints are therefore POST, not PUT/DELETE (refines the spec's REST verbs for helper compatibility).

---

### Task 1: Migration — `collaborator_facts` table

**Files:**
- Create: `database/migrations/460_collaborator_facts.sql`

**Interfaces:**
- Produces: table `collaborator_facts (id, agent_id, fact_text, category, importance, is_active, created_at, created_by, updated_at)` consumed by Task 2.

- [ ] **Step 1: Write the migration**

```sql
-- 460_collaborator_facts.sql
-- Per-collaborator curated facts — grounding source for persona email drafts (#4959).
-- Read into the collaborator draft prompt AND passed to validate_draft_no_fabrication
-- as the allowed-facts source. Keyed by agent_id (generic); only the collaborator draft
-- path consumes it. Idempotent.
CREATE TABLE IF NOT EXISTS collaborator_facts (
    id          SERIAL PRIMARY KEY,
    agent_id    INTEGER NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
    fact_text   TEXT    NOT NULL,
    category    VARCHAR(60),
    importance  SMALLINT DEFAULT 5,
    is_active   BOOLEAN  DEFAULT TRUE,
    created_at  TIMESTAMPTZ DEFAULT now(),
    created_by  VARCHAR(120),
    updated_at  TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_collab_facts_agent_active
    ON collaborator_facts (agent_id, is_active);
```

- [ ] **Step 2: Apply to the live DB**

Run:
```bash
docker exec -i archie_database psql -U archie -d archie < database/migrations/460_collaborator_facts.sql
```
Expected: `CREATE TABLE` then `CREATE INDEX` (or no error on re-run — idempotent).

- [ ] **Step 3: Verify the schema**

Run: `docker exec archie_database psql -U archie -d archie -c "\d collaborator_facts"`
Expected: table with the 9 columns above, PK on `id`, index `idx_collab_facts_agent_active`.

- [ ] **Step 4: Commit**

```bash
git add database/migrations/460_collaborator_facts.sql
git commit -m "feat(4959): migration 460 — collaborator_facts table"
```

---

### Task 2: `collaborator_facts_service.py` — CRUD + retrieval + render helpers

**Files:**
- Create: `platform_v2/services/collaborator_facts_service.py`
- Test: `platform_v2/tests/test_collaborator_draft.py` (append)

**Interfaces:**
- Consumes: `collaborator_facts` table (Task 1); `database.get_db_cursor`.
- Produces (used by Tasks 4 & 5):
  - `get_active_facts(agent_id: int) -> list[dict]` — active facts, `importance DESC, id`.
  - `list_for_agent(agent_id: int) -> list[dict]` — all (active first).
  - `get_fact(fact_id: int) -> dict | None`
  - `add_fact(agent_id, fact_text, category=None, importance=5, created_by=None) -> dict`
  - `update_fact(fact_id, fact_text=None, category=None, importance=None) -> dict | None`
  - `set_active(fact_id, is_active) -> dict | None`
  - `delete_fact(fact_id) -> bool`
  - `facts_as_prompt_block(facts: list[dict]) -> str` — `""` when empty.
  - `facts_allowed_text(facts: list[dict]) -> str` — newline-joined `fact_text`.
  - Each dict: `{id, agent_id, fact_text, category, importance:int, is_active:bool, created_at:str|None, created_by}`.

- [ ] **Step 1: Write the failing tests**

Append to `platform_v2/tests/test_collaborator_draft.py`:

```python
import pytest
from database import get_db_cursor
from services import collaborator_facts_service as cfs


@pytest.fixture
def sample_agent_id():
    with get_db_cursor() as (conn, cur):
        cur.execute("SELECT id FROM agents ORDER BY id LIMIT 1")
        return cur.fetchone()["id"]


@pytest.fixture
def fact_cleanup():
    created = []
    yield created
    with get_db_cursor(commit=True) as (conn, cur):
        for fid in created:
            cur.execute("DELETE FROM collaborator_facts WHERE id=%s", (fid,))


def test_add_and_get_active(sample_agent_id, fact_cleanup):
    f = cfs.add_fact(sample_agent_id, "Manages the KBS account.", category="account", importance=7)
    fact_cleanup.append(f["id"])
    assert f["fact_text"] == "Manages the KBS account."
    assert f["is_active"] is True and f["importance"] == 7
    active = cfs.get_active_facts(sample_agent_id)
    assert any(a["id"] == f["id"] for a in active)


def test_set_active_filters_out(sample_agent_id, fact_cleanup):
    f = cfs.add_fact(sample_agent_id, "Inactive fact.", importance=1)
    fact_cleanup.append(f["id"])
    cfs.set_active(f["id"], False)
    assert all(a["id"] != f["id"] for a in cfs.get_active_facts(sample_agent_id))
    assert any(a["id"] == f["id"] for a in cfs.list_for_agent(sample_agent_id))


def test_active_ordered_by_importance_desc(sample_agent_id, fact_cleanup):
    lo = cfs.add_fact(sample_agent_id, "low priority", importance=1); fact_cleanup.append(lo["id"])
    hi = cfs.add_fact(sample_agent_id, "high priority", importance=9); fact_cleanup.append(hi["id"])
    ids = [a["id"] for a in cfs.get_active_facts(sample_agent_id)]
    assert ids.index(hi["id"]) < ids.index(lo["id"])


def test_delete_fact(sample_agent_id):
    f = cfs.add_fact(sample_agent_id, "to delete")
    assert cfs.delete_fact(f["id"]) is True
    assert cfs.get_fact(f["id"]) is None


def test_add_requires_text(sample_agent_id):
    with pytest.raises(ValueError):
        cfs.add_fact(sample_agent_id, "   ")


def test_render_helpers():
    facts = [{"fact_text": "SLA is 3 business days."}, {"fact_text": "Owner is Terry."}]
    block = cfs.facts_as_prompt_block(facts)
    assert "ALLOWED FACTS" in block
    assert "SLA is 3 business days." in block and "Owner is Terry." in block
    assert cfs.facts_allowed_text(facts) == "SLA is 3 business days.\nOwner is Terry."
    assert cfs.facts_as_prompt_block([]) == ""
    assert cfs.facts_allowed_text([]) == ""
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd platform_v2 && python3 -m pytest tests/test_collaborator_draft.py -k "fact or render_helpers" -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'services.collaborator_facts_service'`.

- [ ] **Step 3: Write the service**

Create `platform_v2/services/collaborator_facts_service.py`:

```python
"""Curated per-collaborator facts — grounding source for persona email drafts (#4959).

Small, owner-curated fact sets per agent. Read into the collaborator draft prompt AND
passed to validate_draft_no_fabrication as the allowed-facts source, so a recalled figure
passes the guard while pure invention still fails closed. Pure DB; no inference.

get_db_cursor yields RealDictCursor dict rows (KB #268832) — access by column name.
"""
import logging

from database import get_db_cursor

logger = logging.getLogger(__name__)

_COLS = "id, agent_id, fact_text, category, importance, is_active, created_at, created_by"


def _row(r) -> dict:
    return {
        "id": r["id"],
        "agent_id": r["agent_id"],
        "fact_text": r["fact_text"],
        "category": r["category"],
        "importance": int(r["importance"]) if r["importance"] is not None else 5,
        "is_active": bool(r["is_active"]),
        "created_at": r["created_at"].isoformat() if r["created_at"] else None,
        "created_by": r["created_by"],
    }


def get_active_facts(agent_id: int) -> list:
    with get_db_cursor() as (conn, cur):
        cur.execute(
            f"SELECT {_COLS} FROM collaborator_facts "
            "WHERE agent_id=%s AND is_active=TRUE ORDER BY importance DESC, id",
            (agent_id,),
        )
        return [_row(r) for r in cur.fetchall()]


def list_for_agent(agent_id: int) -> list:
    with get_db_cursor() as (conn, cur):
        cur.execute(
            f"SELECT {_COLS} FROM collaborator_facts "
            "WHERE agent_id=%s ORDER BY is_active DESC, importance DESC, id",
            (agent_id,),
        )
        return [_row(r) for r in cur.fetchall()]


def get_fact(fact_id: int):
    with get_db_cursor() as (conn, cur):
        cur.execute(f"SELECT {_COLS} FROM collaborator_facts WHERE id=%s", (fact_id,))
        r = cur.fetchone()
        return _row(r) if r else None


def add_fact(agent_id, fact_text, category=None, importance=5, created_by=None) -> dict:
    fact_text = (fact_text or "").strip()
    if not fact_text:
        raise ValueError("fact_text is required")
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            "INSERT INTO collaborator_facts (agent_id, fact_text, category, importance, created_by) "
            f"VALUES (%s,%s,%s,%s,%s) RETURNING {_COLS}",
            (agent_id, fact_text, category, importance, created_by),
        )
        return _row(cur.fetchone())


def update_fact(fact_id, fact_text=None, category=None, importance=None):
    sets, vals = [], []
    if fact_text is not None:
        sets.append("fact_text=%s"); vals.append(fact_text.strip())
    if category is not None:
        sets.append("category=%s"); vals.append(category)
    if importance is not None:
        sets.append("importance=%s"); vals.append(importance)
    if not sets:
        return get_fact(fact_id)
    sets.append("updated_at=now()")
    vals.append(fact_id)
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            f"UPDATE collaborator_facts SET {', '.join(sets)} WHERE id=%s RETURNING {_COLS}",
            vals,
        )
        r = cur.fetchone()
        return _row(r) if r else None


def set_active(fact_id, is_active):
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            f"UPDATE collaborator_facts SET is_active=%s, updated_at=now() WHERE id=%s RETURNING {_COLS}",
            (bool(is_active), fact_id),
        )
        r = cur.fetchone()
        return _row(r) if r else None


def delete_fact(fact_id) -> bool:
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute("DELETE FROM collaborator_facts WHERE id=%s", (fact_id,))
        return cur.rowcount > 0


def facts_as_prompt_block(facts: list) -> str:
    """Prompt block listing the citable facts. Empty string when there are none."""
    if not facts:
        return ""
    lines = "\n".join(f"- {f['fact_text']}" for f in facts)
    return (
        "ALLOWED FACTS — you MAY reference these; do not invent anything beyond them "
        "or the message below:\n" + lines
    )


def facts_allowed_text(facts: list) -> str:
    """Newline-joined fact text — the allowed-facts source for the validator."""
    return "\n".join(f.get("fact_text", "") for f in (facts or []))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd platform_v2 && python3 -m pytest tests/test_collaborator_draft.py -k "fact or render_helpers" -v`
Expected: PASS (6 tests).

- [ ] **Step 5: Commit**

```bash
git add platform_v2/services/collaborator_facts_service.py platform_v2/tests/test_collaborator_draft.py
git commit -m "feat(4959): collaborator_facts_service — CRUD + retrieval + render helpers"
```

---

### Task 3: Teach the validator an `allowed_facts_text` source

**Files:**
- Modify: `platform_v2/tools/email_manager/draft_proposal_service.py:131-169` (`validate_draft_no_fabrication`)
- Test: `platform_v2/tests/test_collaborator_draft.py` (append)

**Interfaces:**
- Produces: `validate_draft_no_fabrication(draft, inbound_text, allowed_facts_text="") -> (bool, str|None)` — a figure passes iff present in `inbound_text` OR `allowed_facts_text`. Consumed by Task 4.

- [ ] **Step 1: Write the failing tests**

Append to `platform_v2/tests/test_collaborator_draft.py`:

```python
from tools.email_manager.draft_proposal_service import validate_draft_no_fabrication


def test_number_in_allowed_facts_passes():
    ok, reason = validate_draft_no_fabrication(
        "Our standard onboarding SLA is 3 business days.",
        inbound_text="When can you onboard us?",
        allowed_facts_text="Standard onboarding SLA is 3 business days.",
    )
    assert ok, reason


def test_number_absent_from_thread_and_facts_rejected():
    ok, reason = validate_draft_no_fabrication(
        "Churn was 4.1% last quarter.",
        inbound_text="How did we do last quarter?",
        allowed_facts_text="",
    )
    assert not ok
    assert "4.1" in reason


def test_empty_allowed_facts_is_backward_compatible():
    # figure in the thread passes; invented figure still fails — owner-path behavior unchanged
    ok, _ = validate_draft_no_fabrication("You asked about 5 seats.", "We need 5 seats.")
    assert ok
    ok2, _ = validate_draft_no_fabrication("The total is 500.", "No numbers in here.")
    assert not ok2


def test_attachment_claim_rejected_even_with_facts():
    ok, reason = validate_draft_no_fabrication(
        "Please see the attached summary.",
        inbound_text="Can you summarize?",
        allowed_facts_text="A summary exists.",
    )
    assert not ok
    assert "attach" in reason.lower()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd platform_v2 && python3 -m pytest tests/test_collaborator_draft.py -k "allowed_facts or absent_from_thread or backward_compatible or attachment_claim_rejected_even" -v`
Expected: `test_number_in_allowed_facts_passes` FAILS (`allowed_facts_text` is an unexpected keyword argument); others may pass.

- [ ] **Step 3: Modify the validator**

In `validate_draft_no_fabrication`, change the signature and the `invented` computation (draft_proposal_service.py ~L131 and ~L165):

```python
def validate_draft_no_fabrication(draft: str, inbound_text: str, allowed_facts_text: str = ""):
```

and:

```python
    invented = sorted(
        _numbers_in(body) - _numbers_in(inbound_text) - _numbers_in(allowed_facts_text)
    )
    if invented:
        return False, "introduces figures absent from the inbound thread or curated facts: " + ", ".join(invented)
```

Add to the docstring (after the existing "(b) introduces ANY digit-bearing token…" paragraph):

```
    ``allowed_facts_text`` is an optional SECOND allowed-facts source (default "" =>
    prior behavior). The collaborator path passes the persona's active curated facts, so
    a figure the owner curated as citable is not treated as invention. Pure invention —
    a figure in neither the thread nor the facts — still fails closed.
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd platform_v2 && python3 -m pytest tests/test_collaborator_draft.py -k "allowed_facts or absent_from_thread or backward_compatible or attachment_claim_rejected_even" -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add platform_v2/tools/email_manager/draft_proposal_service.py platform_v2/tests/test_collaborator_draft.py
git commit -m "feat(4959): validate_draft_no_fabrication learns an allowed_facts_text source"
```

---

### Task 4: Inject facts into the collaborator draft prompt + validator call

**Files:**
- Modify: `platform_v2/tools/email_manager/draft_proposal_service.py:499-547` (`_create_collaborator_proposal`)
- Test: `platform_v2/tests/test_collaborator_draft.py` (append)

**Interfaces:**
- Consumes: `get_active_facts`, `facts_as_prompt_block`, `facts_allowed_text` (Task 2); `validate_draft_no_fabrication(..., allowed_facts_text=)` (Task 3). Agent id key on the candidate dict is `c["collaborator_agent_id"]`.

- [ ] **Step 1: Write the failing tests**

Append to `platform_v2/tests/test_collaborator_draft.py`. These patch the dispatch seam and force a rejected draft so the function returns before any DB insert (no DB write needed):

```python
import tools.email_manager.draft_proposal_service as dps


def _min_candidate():
    return {
        "id": 1, "mailbox_id": 1,
        "mailbox_name": "Jin Park", "mailbox_address": "jin@kytranempowerment.com",
        "from_address": "sofia@example.com", "subject": "Onboarding timing",
        "body_text": "When can you onboard us?", "body_preview": "When can you onboard us?",
        "collaborator_name": "Jin Park", "collaborator_system_prompt": "You are Jin Park.",
        "collaborator_agent_id": 999999, "rfc_message_id": None, "thread_id": None,
    }


def test_facts_injected_into_prompt(monkeypatch):
    captured = {}

    def fake_dispatch(*a, **k):
        captured["prompt"] = k.get("prompt")
        return "We invent 424242 here."   # not in thread or facts => rejected, returns before DB

    monkeypatch.setattr(dps, "get_active_facts", lambda aid: [{"fact_text": "Standard onboarding SLA is 3 business days."}])
    monkeypatch.setattr(dps, "queued_dispatch_text", fake_dispatch, raising=False)
    # queued_dispatch_text is imported inside the function; patch the source module too:
    import services.cluster_dispatch as cd
    monkeypatch.setattr(cd, "queued_dispatch_text", fake_dispatch, raising=False)

    result = dps._create_collaborator_proposal(_min_candidate())
    assert result == dps._REJECTED
    assert "ALLOWED FACTS" in captured["prompt"]
    assert "Standard onboarding SLA is 3 business days." in captured["prompt"]


def test_no_facts_omits_block(monkeypatch):
    captured = {}

    def fake_dispatch(*a, **k):
        captured["prompt"] = k.get("prompt")
        return "We invent 424242 here."

    monkeypatch.setattr(dps, "get_active_facts", lambda aid: [])
    import services.cluster_dispatch as cd
    monkeypatch.setattr(cd, "queued_dispatch_text", fake_dispatch, raising=False)

    dps._create_collaborator_proposal(_min_candidate())
    assert "ALLOWED FACTS" not in captured["prompt"]


def test_validator_receives_facts_corpus(monkeypatch):
    seen = {}

    def fake_validate(draft, inbound_text, allowed_facts_text=""):
        seen["allowed"] = allowed_facts_text
        return False, "stop before DB"

    monkeypatch.setattr(dps, "get_active_facts", lambda aid: [{"fact_text": "SLA is 3 business days."}])
    import services.cluster_dispatch as cd
    monkeypatch.setattr(cd, "queued_dispatch_text", lambda *a, **k: "Our SLA is 3 business days.", raising=False)
    monkeypatch.setattr(dps, "validate_draft_no_fabrication", fake_validate)

    dps._create_collaborator_proposal(_min_candidate())
    assert "SLA is 3 business days." in seen["allowed"]
```

> Note: `_create_collaborator_proposal` imports `get_active_facts` / `facts_as_prompt_block` / `facts_allowed_text` at module top (Step 3 makes them module-level names on `dps`, so `monkeypatch.setattr(dps, "get_active_facts", …)` works). `queued_dispatch_text` is imported *inside* the function from `services.cluster_dispatch`, so patch it on that source module.

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd platform_v2 && python3 -m pytest tests/test_collaborator_draft.py -k "facts_injected or omits_block or receives_facts_corpus" -v`
Expected: FAIL — `AttributeError: module ... has no attribute 'get_active_facts'` (not imported yet) / no ALLOWED FACTS in prompt.

- [ ] **Step 3: Wire facts into the draft path**

Add a module-level import near the other top-level imports in `draft_proposal_service.py`:

```python
from services.collaborator_facts_service import (
    get_active_facts,
    facts_as_prompt_block,
    facts_allowed_text,
)
```

In `_create_collaborator_proposal`, after `system_prompt = ...` (L517) and before building `prompt`:

```python
    facts = get_active_facts(c.get("collaborator_agent_id"))
    facts_block = facts_as_prompt_block(facts)
```

Change the `prompt` assembly (L519-528) to insert the block after the contract:

```python
    prompt = (
        f"Draft a concise, professional email reply in {name}'s voice to the message below.\n\n"
        f"{_NO_FABRICATION_CONTRACT}\n\n"
        + (f"{facts_block}\n\n" if facts_block else "")
        + f"Mailbox: {c.get('mailbox_name')} <{c.get('mailbox_address')}>\n"
        f"From: {c.get('from_address')}\n"
        f"Subject: {c.get('subject')}\n"
        f"Message:\n{body_snippet}\n\n"
        "Write only the reply body text — no subject line, no greeting header, "
        "no 'Here is a draft' preamble. Start directly with the reply content."
    )
```

Change the validator call (L547) to pass the facts corpus:

```python
    ok, reason = validate_draft_no_fabrication(
        draft, _inbound_text(c), allowed_facts_text=facts_allowed_text(facts)
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd platform_v2 && python3 -m pytest tests/test_collaborator_draft.py -k "facts_injected or omits_block or receives_facts_corpus" -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Run the whole file to confirm no regression**

Run: `cd platform_v2 && python3 -m pytest tests/test_collaborator_draft.py -v`
Expected: PASS (all — the pre-existing collaborator/validator tests + the new ones).

- [ ] **Step 6: Commit**

```bash
git add platform_v2/tools/email_manager/draft_proposal_service.py platform_v2/tests/test_collaborator_draft.py
git commit -m "feat(4959): ground collaborator drafts on curated facts (prompt + validator)"
```

---

### Task 5: Facts CRUD endpoints in the DHQ agent-detail routes

**Files:**
- Modify: `platform_v2/tools/department_hq/agent_detail_routes.py` (add 4 routes after the skills routes, ~L222; update the module docstring endpoint list)

**Interfaces:**
- Consumes: `collaborator_facts_service` (Task 2); existing `get_agent`, `current_user`, `@admin_required`.
- Produces: `GET /api/agent/<id>/facts`, `POST /api/agent/<id>/facts`, `POST /api/agent/facts/<fact_id>/toggle`, `POST /api/agent/facts/<fact_id>/delete` — consumed by Task 6.

- [ ] **Step 1: Add the routes**

Inside `register_agent_detail_routes(bp, admin_required)`, after `api_agent_add_skill` (~L222), add:

```python
    @bp.route("/api/agent/<int:agent_id>/facts")
    @admin_required
    def api_agent_facts(agent_id):
        """List an agent's curated facts (active + inactive) for the editor."""
        from services.collaborator_facts_service import list_for_agent
        try:
            if not get_agent(agent_id):
                return jsonify({"error": "Agent not found"}), 404
            return jsonify({"agent_id": agent_id, "facts": list_for_agent(agent_id)})
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @bp.route("/api/agent/<int:agent_id>/facts", methods=["POST"])
    @admin_required
    def api_agent_add_fact(agent_id):
        """Add a curated fact {fact_text, category?, importance?}."""
        from services.collaborator_facts_service import add_fact
        data = request.get_json(silent=True) or {}
        fact_text = (data.get("fact_text") or "").strip()
        if not fact_text:
            return jsonify({"error": "fact_text is required"}), 400
        try:
            if not get_agent(agent_id):
                return jsonify({"error": "Agent not found"}), 404
            who = getattr(current_user, "username", None)
            importance = data.get("importance", 5)
            try:
                importance = int(importance)
            except (TypeError, ValueError):
                importance = 5
            fact = add_fact(agent_id, fact_text, category=data.get("category"),
                            importance=importance, created_by=who)
            return jsonify({"success": True, "fact": fact})
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @bp.route("/api/agent/facts/<int:fact_id>/toggle", methods=["POST"])
    @admin_required
    def api_agent_toggle_fact(fact_id):
        """Activate/deactivate a fact {is_active: bool}."""
        from services.collaborator_facts_service import set_active
        data = request.get_json(silent=True) or {}
        try:
            fact = set_active(fact_id, bool(data.get("is_active", True)))
            if not fact:
                return jsonify({"error": "Fact not found"}), 404
            return jsonify({"success": True, "fact": fact})
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @bp.route("/api/agent/facts/<int:fact_id>/delete", methods=["POST"])
    @admin_required
    def api_agent_delete_fact(fact_id):
        """Delete a fact."""
        from services.collaborator_facts_service import delete_fact
        try:
            return jsonify({"success": delete_fact(fact_id)})
        except Exception as e:
            return jsonify({"error": str(e)}), 500
```

Also add these four lines to the module docstring endpoint list at the top of the file.

- [ ] **Step 2: Verify import + registration (syntax/wiring)**

Run:
```bash
cd platform_v2 && python3 -c "import ast; ast.parse(open('tools/department_hq/agent_detail_routes.py').read()); print('parse OK')"
```
Expected: `parse OK`.

- [ ] **Step 3: Commit**

```bash
git add platform_v2/tools/department_hq/agent_detail_routes.py
git commit -m "feat(4959): DHQ agent facts endpoints (list/add/toggle/delete, admin)"
```

> Live HTTP verification of these endpoints happens post-deploy in Task 7 (the container runs main until then). They are thin wrappers over the Task-2 service, which is unit-tested.

---

### Task 6: "Curated Facts" section in the DHQ agent-profile modal

**Files:**
- Modify: `platform_v2/tools/department_hq/static/js/department-hq.js`

**Interfaces:**
- Consumes: Task-5 endpoints; existing `api(path)` / `apiPost(path, body)` helpers.
- Pattern to mirror: the social-profiles section (`api('/api/agent/'+id+'/social-profiles')` GET at ~L2183, `apiPost` add at ~L2304) and the profile render entry points at ~L1707 and ~L1761 (`api('/api/agent/'+agentId+'/profile')`).

- [ ] **Step 1: Read the profile modal render**

Read `department-hq.js` around L1690-1790 (the two `/profile` fetch sites) and L2180-2320 (the social-profiles section) to find the container element the profile modal renders into and the exact function name that populates it. Identify the DOM node to append a "Curated Facts" card into (mirror the social-profiles card).

- [ ] **Step 2: Add the facts UI functions**

Add these functions (near the social-profiles functions). They are self-contained and XSS-safe (`textContent`):

```javascript
async function loadAgentFacts(agentId) {
    var host = document.getElementById('agentFactsList');
    if (!host) return;
    host.textContent = 'Loading…';
    var resp = await api('/api/agent/' + agentId + '/facts');
    var facts = (resp && resp.facts) || [];
    host.textContent = '';
    if (!facts.length) {
        var empty = document.createElement('div');
        empty.className = 'dhq-muted';
        empty.textContent = 'No curated facts yet. Add facts this persona may cite in email drafts.';
        host.appendChild(empty);
        return;
    }
    facts.forEach(function (f) {
        var row = document.createElement('div');
        row.className = 'dhq-fact-row' + (f.is_active ? '' : ' dhq-fact-inactive');
        var txt = document.createElement('span');
        txt.className = 'dhq-fact-text';
        txt.textContent = f.fact_text + (f.category ? ' [' + f.category + ']' : '');
        var toggle = document.createElement('button');
        toggle.className = 'dhq-btn-sm';
        toggle.textContent = f.is_active ? 'Deactivate' : 'Activate';
        toggle.onclick = async function () {
            await apiPost('/api/agent/facts/' + f.id + '/toggle', { is_active: !f.is_active });
            loadAgentFacts(agentId);
        };
        var del = document.createElement('button');
        del.className = 'dhq-btn-sm dhq-btn-danger';
        del.textContent = 'Delete';
        del.onclick = async function () {
            await apiPost('/api/agent/facts/' + f.id + '/delete', {});
            loadAgentFacts(agentId);
        };
        row.appendChild(txt);
        row.appendChild(toggle);
        row.appendChild(del);
        host.appendChild(row);
    });
}

async function addAgentFact(agentId) {
    var input = document.getElementById('agentFactInput');
    var cat = document.getElementById('agentFactCategory');
    var text = (input && input.value || '').trim();
    if (!text) return;
    await apiPost('/api/agent/' + agentId + '/facts', {
        fact_text: text,
        category: (cat && cat.value || '').trim() || null,
    });
    if (input) input.value = '';
    if (cat) cat.value = '';
    loadAgentFacts(agentId);
}
```

- [ ] **Step 3: Add the card markup + wire it into profile open**

In the profile modal render (the region from Step 1), add a "Curated Facts" card mirroring the social-profiles card:

```html
<div class="dhq-card">
  <h4>Curated Facts <span class="dhq-muted">(persona may cite these in email drafts)</span></h4>
  <div id="agentFactsList"></div>
  <div class="dhq-fact-add">
    <input id="agentFactInput" type="text" placeholder="e.g. Standard onboarding SLA is 3 business days." />
    <input id="agentFactCategory" type="text" placeholder="category (optional)" />
    <button class="dhq-btn-sm" onclick="addAgentFact(CURRENT_AGENT_ID)">Add</button>
  </div>
</div>
```

Replace `CURRENT_AGENT_ID` with the agent-id variable the modal already holds (found in Step 1; e.g. the `agentId` passed to the profile-render function). Immediately after the profile data renders (both `/profile` sites at ~L1707 and ~L1761, whichever populates this modal), call `loadAgentFacts(agentId)`.

- [ ] **Step 4: Syntax check**

Run:
```bash
cd platform_v2 && node --check tools/department_hq/static/js/department-hq.js && echo "JS OK"
```
Expected: `JS OK` (if `node` unavailable, skip — verified visually in Task 7).

- [ ] **Step 5: Commit**

```bash
git add platform_v2/tools/department_hq/static/js/department-hq.js
git commit -m "feat(4959): Curated Facts section in DHQ agent-profile modal"
```

---

### Task 7: Deploy + live verification

**Files:** none (deploy + manual verification).

- [ ] **Step 1: Deploy** — `platform_v2` is volume-mounted, so a restart picks up the changes once merged to main. During review the merge-pr flow restarts `archie_platform` + `archie_scheduler`. To verify pre-merge from the worktree, `docker cp` the changed files into `archie_platform:/app/...` then `docker compose restart archie_platform`.

- [ ] **Step 2: API smoke** — with the container running the new code, add a fact for a collaborator agent (e.g. Jin Park's agent id) and read it back:
```bash
docker exec archie_platform python3 -c "import sys; sys.path.insert(0,'/app'); from services.collaborator_facts_service import add_fact, get_active_facts; f=add_fact(341,'Standard onboarding SLA is 3 business days.',category='sla'); print(f); print(get_active_facts(341))"
```
Expected: the inserted fact dict + a non-empty active-facts list. (Clean up the test fact after.)

- [ ] **Step 3: UI verify** — open DHQ → Roster → a collaborator persona profile; confirm the "Curated Facts" card lists/add/toggle/delete works (browser or P.R.O.B.E.). Render is XSS-safe (`textContent`).

- [ ] **Step 4: Grounding proof** — confirm a draft citing a fact-number is no longer rejected: `validate_draft_no_fabrication("Our SLA is 3 business days.", "When can you onboard?", allowed_facts_text="Standard onboarding SLA is 3 business days.")` returns `(True, None)`; the same draft with `allowed_facts_text=""` returns rejected.

---

## Self-Review

**Spec coverage:** §3.1 table → Task 1. §3.2 service → Task 2. §3.3 grounding injection → Task 4. §3.4 validator → Task 3. §3.5 endpoints → Task 5, UI → Task 6. §3.6 tests → folded into Tasks 2/3/4. §4 data flow → Tasks 3+4. §6 gate unchanged → Global Constraints. §7 known limits → carried in spec (no code). All covered.

**Placeholder scan:** No TBD/TODO. The one "read and locate" step (Task 6 Step 1) is inherent to editing a large JS file and is paired with complete JS to add; `CURRENT_AGENT_ID` is explicitly flagged for substitution with the variable found in that step.

**Type consistency:** `get_active_facts`/`facts_as_prompt_block`/`facts_allowed_text` names identical across Tasks 2/4. Validator signature `validate_draft_no_fabrication(draft, inbound_text, allowed_facts_text="")` identical in Tasks 3/4. Endpoint paths identical across Tasks 5/6. Fact dict keys (`id, fact_text, category, importance, is_active`) consistent service→routes→JS.
