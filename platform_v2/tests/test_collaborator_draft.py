"""Slice 1 (Collaborator Persona Email Assistant) — collaborator persona drafting.

Unit tests for the NEW `human_agent`-mailbox draft path added to
`tools.email_manager.draft_proposal_service`. Pure unit tests: they monkeypatch the
DB cursor + the cluster dispatch helper (following the fake-cursor style of
`test_mail_hq.py`), so no live DB / no live inference is required.

What Slice 1 must guarantee (spec 2026-07-16-collaborator-persona-email-assistant-design):
  * an `action` inbound to a `human_agent` mailbox drafts in THAT collaborator's voice
    (their `system_prompt`) on `llama3.2:3b`, landing in `autonomy_approval_queue`
    as `action_type='email_reply'` ATTRIBUTED to the collaborator (not R.E.S.O.L.V.E.);
  * drafting uses the cold-load-tolerant `queued_dispatch_text` — never `dispatch_json`;
  * no draft when `mailhq:draft:collaborators` is off, and the candidate query only
    selects `action`-priority `human_agent` mail;
  * the existing owner/business draft path is untouched.
"""

import contextlib
import inspect

import tools.email_manager.draft_proposal_service as dps


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def _capturing_cursor(select_rows=None, returning=None, cap=None):
    """A minimal fake cursor. Captures every execute() and serves fetchone/fetchall."""
    select_rows = select_rows or []
    returning = returning if returning is not None else {"id": 99}

    class _Cur:
        def execute(self, q, params=None):
            if cap is not None:
                cap.setdefault("qs", []).append(q)
                cap.setdefault("params", []).append(params)

        def fetchall(self):
            return select_rows

        def fetchone(self):
            last = (cap or {}).get("qs", [""])[-1] if cap else ""
            if "RETURNING" in last:
                return returning
            # platform_settings reads etc. — no row => callers fall back to default
            return None

    @contextlib.contextmanager
    def _cm(commit=False):
        yield (None, _Cur())

    return _cm


_COLLAB_ROW = {
    "id": 501,
    "subject": "Can you review the Q3 brief?",
    "from_address": "client@example.com",
    "body_text": "Please take a look and let me know your thoughts.",
    "body_preview": "Please take a look...",
    "mailbox_id": 42,
    "thread_id": None,
    "rfc_message_id": "<abc@example.com>",
    "mailbox_address": "amina@kytranempowerment.com",
    "mailbox_type": "human_agent",
    "mailbox_name": "Amina",
    "collaborator_agent_id": 341,
    "collaborator_name": "Amina",
    "collaborator_system_prompt": "You are Amina, a warm, precise operations lead. Reply briefly.",
}


# --------------------------------------------------------------------------- #
# gate: default OFF
# --------------------------------------------------------------------------- #
def test_collaborators_gate_default_off(monkeypatch):
    # _setting returns the default ("false") when the key is absent.
    monkeypatch.setattr(dps, "_setting", lambda key, default=None: default)
    assert dps._collaborators_enabled() is False


def test_run_is_noop_when_gate_off(monkeypatch):
    monkeypatch.setattr(dps, "_collaborators_enabled", lambda: False)
    # If the gate is respected, the DB is never touched — make any DB use explode.
    import database

    monkeypatch.setattr(database, "get_db_cursor", lambda *a, **k: (_ for _ in ()).throw(AssertionError("DB touched")))
    out = dps.run_mailhq_collaborator_drafts()
    assert out.get("skipped") is True
    assert dps.COLLAB_FLAG_KEY == "mailhq:draft:collaborators"


# --------------------------------------------------------------------------- #
# core: persona + model + attribution
# --------------------------------------------------------------------------- #
def test_create_proposal_uses_persona_and_model(monkeypatch):
    import database
    import services.cluster_dispatch as cd

    seen = {}

    def _fake_dispatch(capability, prompt, **kw):
        seen["capability"] = capability
        seen["prompt"] = prompt
        seen.update(kw)
        return "  Happy to review it — sending notes shortly.  "

    monkeypatch.setattr(cd, "queued_dispatch_text", _fake_dispatch)

    cap = {}
    monkeypatch.setattr(database, "get_db_cursor", _capturing_cursor(cap=cap))
    # do not fire Telegram in a unit test
    monkeypatch.setattr(dps, "_send_proposal_buttons", lambda *a, **k: None)

    ok = dps._create_collaborator_proposal(dict(_COLLAB_ROW))
    assert ok is True

    # persona + model + local_only forced regardless of routed agent
    assert seen["system_prompt"] == _COLLAB_ROW["collaborator_system_prompt"]
    assert seen["model_override"] == "llama3.2:3b"
    assert seen["local_only"] is True
    assert seen["capability"] == "support"
    assert "Amina" in seen["prompt"]  # drafted "in <name>'s voice"

    # persisted to autonomy_approval_queue as email_reply, ATTRIBUTED to the collaborator
    ins = [q for q in cap["qs"] if "INSERT INTO autonomy_approval_queue" in q]
    assert ins and "'email_reply'" in ins[0]
    # locate the Json(action_data) param on the insert call
    idx = cap["qs"].index(ins[0])
    json_arg = cap["params"][idx][0]
    action_data = getattr(json_arg, "adapted", json_arg)  # psycopg2 Json wraps the dict
    assert action_data["agent"] == "Amina"  # NOT R.E.S.O.L.V.E.
    assert action_data["collaborator_agent_id"] == 341
    assert action_data["mailbox_type"] == "human_agent"
    assert action_data["draft_reply"] == "Happy to review it — sending notes shortly."
    assert action_data["from_address"] == "amina@kytranempowerment.com"  # reply FROM our mailbox
    assert action_data["to_address"] == "client@example.com"


def test_drafting_uses_queued_dispatch_not_dispatch_json():
    # Cold-load-tolerant path (KB #276153): the collaborator draft must go through
    # queued_dispatch_text, never the synchronous dispatch_json.
    src = inspect.getsource(dps._create_collaborator_proposal)
    assert "queued_dispatch_text(" in src  # the cold-load-tolerant call is used
    assert "dispatch_json(" not in src  # the synchronous call is NEVER made


# --------------------------------------------------------------------------- #
# candidate selection: action-priority human_agent only
# --------------------------------------------------------------------------- #
def test_candidate_query_scopes_action_human_agent(monkeypatch):
    monkeypatch.setattr(dps, "_collaborators_enabled", lambda: True)
    # short-circuit the shared processing loop so we only exercise the SELECT
    monkeypatch.setattr(dps, "_process_candidates", lambda cands, fn, key: {"created": 0, "capped": 0, "cooling": 0})

    import database

    cap = {}
    monkeypatch.setattr(database, "get_db_cursor", _capturing_cursor(select_rows=[], cap=cap))

    out = dps.run_mailhq_collaborator_drafts()
    assert out["candidates"] == 0

    sel = [q for q in cap["qs"] if "FROM email_messages" in q][0]
    assert "m.ai_priority = 'action'" in sel
    assert "mb.mailbox_type = %s" in sel
    # human_agent is passed as the mailbox-type param
    idx = cap["qs"].index(sel)
    assert dps._COLLAB_MAILBOX_TYPE == "human_agent"
    assert cap["params"][idx][0] == "human_agent"
    # joins the collaborator agent to source its persona system_prompt
    assert "JOIN agents a ON a.id = mb.owner_agent_id" in sel
    assert "system_prompt" in sel


# --------------------------------------------------------------------------- #
# regression: owner/business path unchanged
# --------------------------------------------------------------------------- #
def test_owner_business_path_unchanged():
    # owner/business drafting still R.E.S.O.L.V.E. via the local fleet_dispatch import,
    # and NEVER includes human_agent — the collaborator path is a separate function.
    assert dps._DRAFT_MAILBOX_TYPES == ("owner", "business")
    owner_src = inspect.getsource(dps._create_proposal)
    assert "R.E.S.O.L.V.E." in owner_src
    assert "from .fleet_dispatch import queued_dispatch_text" in owner_src
    assert "model_override" not in owner_src  # owner/business path never forces a model


# --------------------------------------------------------------------------- #
# Task 2: collaborator_facts_service — CRUD + retrieval + render helpers (#4959)
# --------------------------------------------------------------------------- #
import pytest
from database import get_db_cursor
from services import collaborator_facts_service as cfs

# Marker name for the throwaway agent created by `sample_agent_id` below. Used
# both as the unique `name`/`display_name` and as the teardown lookup key so a
# crashed prior run can never leave stale rows behind (KB: fixture hermeticity).
_TEST_AGENT_MARKER = "__cfacts_test_agent__"


@pytest.fixture(scope="module")
def sample_agent_id():
    """Create a throwaway `agents` row for the collaborator_facts FK tests.

    MUST be hermetic: `archie_test`'s `agents` table is empty in a clean run,
    so `SELECT ... FROM agents LIMIT 1` (the old approach) returns no row and
    every CRUD test ERRORs. Instead, create our own minimal-but-valid agent —
    satisfying every NOT NULL/no-default column and CHECK constraint on
    `agents` (name, model, department [chk_agents_department], floor
    [chk_agents_floor], worker_type [chk_agents_worker_type]) — yield its id
    for the whole module, then delete it (and any prior-run leftover with the
    same marker) in teardown. `collaborator_facts` rows cascade via
    `collaborator_facts_agent_id_fkey ... ON DELETE CASCADE`.
    """
    with get_db_cursor(commit=True) as (conn, cur):
        # Belt-and-suspenders: wipe any leftover from a previous crashed run
        # before creating a fresh one, so rows can never accumulate.
        cur.execute("DELETE FROM agents WHERE display_name=%s", (_TEST_AGENT_MARKER,))
        cur.execute(
            """
            INSERT INTO agents (name, display_name, model, department, floor, worker_type)
            VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING id
            """,
            (
                _TEST_AGENT_MARKER,
                _TEST_AGENT_MARKER,
                "qwen2.5:1.5b",
                "Engineering & Technology",
                "ENGINEERING",
                "internal",
            ),
        )
        agent_id = cur.fetchone()["id"]

    yield agent_id

    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute("DELETE FROM agents WHERE display_name=%s", (_TEST_AGENT_MARKER,))


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
    lo = cfs.add_fact(sample_agent_id, "low priority", importance=1)
    fact_cleanup.append(lo["id"])
    hi = cfs.add_fact(sample_agent_id, "high priority", importance=9)
    fact_cleanup.append(hi["id"])
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


# --------------------------------------------------------------------------- #
# Task 3: validate_draft_no_fabrication learns an allowed_facts_text source (#4959)
# --------------------------------------------------------------------------- #
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


# --------------------------------------------------------------------------- #
# Task 4: facts injected into the collaborator draft prompt + validator call (#4959)
# --------------------------------------------------------------------------- #


def _min_candidate():
    return {
        "id": 1,
        "mailbox_id": 1,
        "mailbox_name": "Jin Park",
        "mailbox_address": "jin@kytranempowerment.com",
        "from_address": "sofia@example.com",
        "subject": "Onboarding timing",
        "body_text": "When can you onboard us?",
        "body_preview": "When can you onboard us?",
        "collaborator_name": "Jin Park",
        "collaborator_system_prompt": "You are Jin Park.",
        "collaborator_agent_id": 999999,
        "rfc_message_id": None,
        "thread_id": None,
    }


def test_facts_injected_into_prompt(monkeypatch):
    captured = {}

    def fake_dispatch(*a, **k):
        captured["prompt"] = k.get("prompt")
        return "We invent 424242 here."  # not in thread or facts => rejected, returns before DB

    monkeypatch.setattr(
        dps, "get_active_facts", lambda aid: [{"fact_text": "Standard onboarding SLA is 3 business days."}]
    )
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
