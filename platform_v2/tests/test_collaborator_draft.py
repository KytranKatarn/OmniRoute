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
