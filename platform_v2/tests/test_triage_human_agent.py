"""Slice 1 (Collaborator Persona Email Assistant) — triage of collaborator mail.

Unit tests for the `human_agent` branch of `tools.email_manager.triage_service`.
Pure unit tests: they monkeypatch the DB cursor + the queue-aware dispatch helper
(following the fake-cursor style of `test_collaborator_draft.py`), so no live DB /
no live inference is required.

The gap these cover (task #4956): triage skipped `mailbox_type='human_agent'`, so
collaborator mail never got an `ai_priority`. The collaborator draft job
(`run_mailhq_collaborator_drafts`) selects `WHERE m.ai_priority = 'action' AND
mb.mailbox_type = 'human_agent'` — it therefore found ZERO candidates and could
never fire, even once enabled.

What this must guarantee:
  * gate OFF (default) → `human_agent` is still skipped, byte-identically, and no
    LLM is burned on the 21 idle collaborator mailboxes;
  * gate ON → `human_agent` mail IS triaged and `ai_priority` gets set;
  * the gate is the SAME `mailhq:draft:collaborators` flag the draft job reads
    (reused, not re-implemented) — one switch turns the whole feature on;
  * owner / business / ai_agent behave identically in BOTH gate states.
"""

import contextlib
import inspect

import pytest

import tools.email_manager.draft_proposal_service as dps
import tools.email_manager.fleet_dispatch as fd
import tools.email_manager.triage_service as ts

_OK_RESPONSE = '{"priority": "action", "suggestion": "Reply today."}'


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def _msg_row(mailbox_type):
    return {
        "id": 501,
        "subject": "Can you review the Q3 brief?",
        "from_address": "client@example.com",
        "body_preview": "Please take a look and let me know your thoughts.",
        "mailbox_type": mailbox_type,
    }


def _capturing_cursor(row=None, cap=None):
    """A minimal fake cursor. Captures every execute() and serves the message row."""

    class _Cur:
        def execute(self, q, params=None):
            if cap is not None:
                cap.setdefault("qs", []).append(q)
                cap.setdefault("params", []).append(params)

        def fetchone(self):
            last = (cap or {}).get("qs", [""])[-1] if cap else ""
            if "FROM email_messages" in last:
                return row
            return None

    @contextlib.contextmanager
    def _cm(commit=False):
        yield (None, _Cur())

    return _cm


def _harness(monkeypatch, mailbox_type, *, gate, response=_OK_RESPONSE):
    """Run triage_message() for one mailbox_type at a given gate state.

    Returns (result, captured_queries, dispatch_kwargs). `dispatch_kwargs` stays
    empty when no LLM call was made.
    """
    import database

    cap = {}
    seen = {}

    monkeypatch.setattr(database, "get_db_cursor", _capturing_cursor(row=_msg_row(mailbox_type), cap=cap))
    monkeypatch.setattr(ts, "_collaborator_triage_enabled", lambda: gate)

    def _fake_dispatch(capability, prompt, **kw):
        seen["capability"] = capability
        seen["prompt"] = prompt
        seen.update(kw)
        return response

    monkeypatch.setattr(fd, "queued_dispatch_text", _fake_dispatch)
    return ts.triage_message(501), cap, seen


def _updates(cap):
    return [q for q in cap.get("qs", []) if "UPDATE email_messages" in q]


# --------------------------------------------------------------------------- #
# gate: reused from the collaborator draft path, default OFF
# --------------------------------------------------------------------------- #
def test_gate_defaults_off_on_the_collaborator_flag(monkeypatch):
    # _setting returns the default ("false") when the key is absent.
    monkeypatch.setattr(dps, "_setting", lambda key, default=None: default)
    assert ts._collaborator_triage_enabled() is False
    assert dps.COLLAB_FLAG_KEY == "mailhq:draft:collaborators"


def test_gate_is_the_collaborator_draft_gate_not_a_reimplementation(monkeypatch):
    # One flag drives both triage and drafting: flipping the draft gate flips triage.
    monkeypatch.setattr(dps, "_collaborators_enabled", lambda: True)
    assert ts._collaborator_triage_enabled() is True
    monkeypatch.setattr(dps, "_collaborators_enabled", lambda: False)
    assert ts._collaborator_triage_enabled() is False


def test_gate_fails_safe_to_off(monkeypatch):
    # A settings-lookup blow-up must keep the pre-existing skip behaviour.
    def _boom():
        raise RuntimeError("platform_settings unavailable")

    monkeypatch.setattr(dps, "_collaborators_enabled", _boom)
    assert ts._collaborator_triage_enabled() is False


def test_collab_mailbox_type_matches_the_draft_job():
    # The two paths must agree on which mailbox marks a collaborator.
    assert ts._COLLAB_MAILBOX_TYPE == dps._COLLAB_MAILBOX_TYPE == "human_agent"


# --------------------------------------------------------------------------- #
# gate OFF → unchanged behaviour
# --------------------------------------------------------------------------- #
def test_human_agent_still_skipped_when_gate_off(monkeypatch):
    out, cap, seen = _harness(monkeypatch, "human_agent", gate=False)
    # byte-identical to the pre-fix behaviour
    assert out == {"skipped": True, "reason": "mailbox_type=human_agent not triaged"}
    assert seen == {}  # no LLM burned on 21 idle collaborator boxes
    assert not _updates(cap)  # ai_priority untouched


# --------------------------------------------------------------------------- #
# gate ON → collaborator mail is triaged
# --------------------------------------------------------------------------- #
def test_human_agent_triaged_when_gate_on(monkeypatch):
    out, cap, seen = _harness(monkeypatch, "human_agent", gate=True)

    assert out["priority"] == "action"
    assert out["suggestion"] == "Reply today."
    # same classify path/priorities as the other triaged mailbox types
    assert seen["capability"] == "classify"
    assert seen["json_mode"] is True

    # ai_priority actually persisted — this is what the collaborator draft
    # candidate query (ai_priority='action') needs in order to ever fire.
    ups = _updates(cap)
    assert ups and "ai_priority" in ups[0]
    idx = cap["qs"].index(ups[0])
    assert cap["params"][idx][0] == "action"


def test_human_agent_priority_falls_back_to_info_on_junk(monkeypatch):
    # Shares the existing validation path — an unknown priority degrades to "info".
    out, cap, _ = _harness(
        monkeypatch, "human_agent", gate=True, response='{"priority": "URGENT!!", "suggestion": "x"}'
    )
    assert out["priority"] == "info"


def test_triage_uses_queued_dispatch_not_dispatch_json():
    # Cold-load-tolerant path (KB #276153): dispatch_json masks cold-load queueing
    # as a hard failure and silently drops the work.
    src = inspect.getsource(ts.triage_message)
    assert "queued_dispatch_text(" in src
    assert "dispatch_json(" not in src


# --------------------------------------------------------------------------- #
# regression: every other mailbox_type unaffected in BOTH gate states
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("gate", [False, True])
def test_owner_path_unaffected(monkeypatch, gate):
    out, cap, seen = _harness(monkeypatch, "owner", gate=gate)
    assert seen["capability"] == "summarize"
    assert "Summarize this email" in seen["prompt"]
    assert out["priority"] == "action"
    assert _updates(cap)


@pytest.mark.parametrize("gate", [False, True])
def test_business_path_unaffected(monkeypatch, gate):
    out, cap, seen = _harness(monkeypatch, "business", gate=gate)
    assert seen["capability"] == "classify"
    assert "business email" in seen["prompt"]
    assert out["priority"] == "action"
    assert _updates(cap)


@pytest.mark.parametrize("gate", [False, True])
def test_ai_agent_always_skipped(monkeypatch, gate):
    # The 38 agent mailboxes handle their own mail — never triaged, gate or no gate.
    out, cap, seen = _harness(monkeypatch, "ai_agent", gate=gate)
    assert out == {"skipped": True, "reason": "mailbox_type=ai_agent not triaged"}
    assert seen == {}
    assert not _updates(cap)
