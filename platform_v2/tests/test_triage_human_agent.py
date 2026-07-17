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
import tools.email_manager.mailhq_settings as ms
import tools.email_manager.rules_service as rs
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


# --------------------------------------------------------------------------- #
# #4957 Item 3 — centralized gate helper (mailhq_settings.is_enabled)
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("raw", ["true", "TRUE", " True ", "on", "ON", "1", "yes", " YES "])
def test_is_enabled_true_values(monkeypatch, raw):
    monkeypatch.setattr(ms, "_get", lambda key: raw)
    assert ms.is_enabled("mailhq:draft:collaborators") is True


@pytest.mark.parametrize("raw", ["false", "", None, "0", "nope", "  "])
def test_is_enabled_false_values(monkeypatch, raw):
    monkeypatch.setattr(ms, "_get", lambda key: raw)
    assert ms.is_enabled("mailhq:draft:collaborators") is False


def test_collaborators_enabled_delegates_to_mailhq_settings_is_enabled(monkeypatch):
    # _collaborators_enabled() must be a thin delegate — not a re-implementation —
    # so mailhq_settings.is_enabled is the single source of truth for every gate.
    calls = []
    monkeypatch.setattr(ms, "is_enabled", lambda key: calls.append(key) or True)
    assert dps._collaborators_enabled() is True
    assert calls == [dps.COLLAB_FLAG_KEY]

    calls.clear()
    monkeypatch.setattr(ms, "is_enabled", lambda key: calls.append(key) or False)
    assert dps._collaborators_enabled() is False
    assert calls == [dps.COLLAB_FLAG_KEY]


# --------------------------------------------------------------------------- #
# #4957 Item 2 — triage-health covers collaborators only when the gate is on
# --------------------------------------------------------------------------- #
def test_health_mailbox_types_excludes_human_agent_when_gate_off(monkeypatch):
    monkeypatch.setattr(ts, "_collaborator_triage_enabled", lambda: False)
    assert ts._health_mailbox_types() == ["owner", "business"]


def test_health_mailbox_types_includes_human_agent_when_gate_on(monkeypatch):
    monkeypatch.setattr(ts, "_collaborator_triage_enabled", lambda: True)
    assert ts._health_mailbox_types() == ["owner", "business", "human_agent"]


def _health_cursor(row, cap=None):
    class _Cur:
        def execute(self, q, params=None):
            if cap is not None:
                cap.setdefault("qs", []).append(q)
                cap.setdefault("params", []).append(params)

        def fetchone(self):
            return row

    @contextlib.contextmanager
    def _cm(commit=False):
        yield (None, _Cur())

    return _cm


def test_triage_health_query_parameterized_and_unchanged_when_gate_off(monkeypatch):
    # Gate off: mailbox-type set must be exactly ('owner','business') and passed
    # as a bound parameter (= ANY(%s)) — never string-interpolated into the SQL.
    monkeypatch.setattr(ts, "_collaborator_triage_enabled", lambda: False)
    import database

    cap = {}
    monkeypatch.setattr(database, "get_db_cursor", _health_cursor({"total": 0, "untriaged": 0}, cap=cap))

    out = ts.run_triage_health_check()
    assert out["ok"] is True

    sel = [q for q in cap["qs"] if "FROM email_messages" in q][0]
    assert "mb.mailbox_type = ANY(%s)" in sel
    assert "IN ('owner', 'business')" not in sel  # no longer a literal IN-list
    idx = cap["qs"].index(sel)
    assert cap["params"][idx][0] == ["owner", "business"]


def test_triage_health_query_includes_human_agent_when_gate_on(monkeypatch):
    monkeypatch.setattr(ts, "_collaborator_triage_enabled", lambda: True)
    import database

    cap = {}
    monkeypatch.setattr(database, "get_db_cursor", _health_cursor({"total": 0, "untriaged": 0}, cap=cap))

    ts.run_triage_health_check()

    sel = [q for q in cap["qs"] if "FROM email_messages" in q][0]
    idx = cap["qs"].index(sel)
    assert cap["params"][idx][0] == ["owner", "business", "human_agent"]


# --------------------------------------------------------------------------- #
# #4957 Item 1 — retroactive collaborator-triage backfill
# --------------------------------------------------------------------------- #
def _backfill_row(msg_id=777):
    return {
        "id": msg_id,
        "mailbox_id": 42,
        "from_address": "client@example.com",
        "subject": "Following up",
        "to_address": "amina@kytranempowerment.com",
        "body_preview": "Any update?",
    }


def _backfill_select_cursor(rows, cap=None):
    class _Cur:
        def execute(self, q, params=None):
            if cap is not None:
                cap.setdefault("qs", []).append(q)
                cap.setdefault("params", []).append(params)

        def fetchall(self):
            return rows

        def fetchone(self):
            return None

    @contextlib.contextmanager
    def _cm(commit=False):
        yield (None, _Cur())

    return _cm


def test_backfill_is_noop_when_gate_off(monkeypatch):
    monkeypatch.setattr(ts, "_collaborator_triage_enabled", lambda: False)
    import database

    # gate off => the DB must never be touched.
    monkeypatch.setattr(database, "get_db_cursor", lambda *a, **k: (_ for _ in ()).throw(AssertionError("DB touched")))
    assert ts.backfill_collaborator_triage(limit=25) == 0


def test_backfill_selects_untriaged_human_agent_inbox_and_queues_triage(monkeypatch):
    monkeypatch.setattr(ts, "_collaborator_triage_enabled", lambda: True)

    import database

    cap = {}
    monkeypatch.setattr(database, "get_db_cursor", _backfill_select_cursor([_backfill_row(777)], cap=cap))
    monkeypatch.setattr(rs, "apply_rules", lambda *a, **k: {})

    queued_ids = []
    monkeypatch.setattr(ts, "triage_message_async", lambda mid: queued_ids.append(mid))

    n = ts.backfill_collaborator_triage(limit=25)
    assert n == 1
    assert queued_ids == [777]

    sel = [q for q in cap["qs"] if "FROM email_messages" in q][0]
    assert "mb.mailbox_type = %s" in sel
    assert "m.ai_priority IS NULL" in sel
    assert "m.folder = 'INBOX'" in sel
    assert "m.received_at >= %s" in sel
    idx = cap["qs"].index(sel)
    assert cap["params"][idx][0] == "human_agent"
    assert cap["params"][idx][2] == 25  # LIMIT bound through to the SQL


def test_backfill_bounded_by_limit_param(monkeypatch):
    monkeypatch.setattr(ts, "_collaborator_triage_enabled", lambda: True)

    import database

    cap = {}
    rows = [_backfill_row(i) for i in range(5)]
    monkeypatch.setattr(database, "get_db_cursor", _backfill_select_cursor(rows, cap=cap))
    monkeypatch.setattr(rs, "apply_rules", lambda *a, **k: {})

    queued_ids = []
    monkeypatch.setattr(ts, "triage_message_async", lambda mid: queued_ids.append(mid))

    ts.backfill_collaborator_triage(limit=3)

    sel = [q for q in cap["qs"] if "FROM email_messages" in q][0]
    idx = cap["qs"].index(sel)
    assert cap["params"][idx][-1] == 3  # limit passed straight through as the SQL LIMIT


def test_backfill_respects_skip_triage_rule(monkeypatch):
    # A message that matches an active skip_triage rule must not be triaged,
    # mirroring the live sync path's own check (sync_jobs.py:230).
    monkeypatch.setattr(ts, "_collaborator_triage_enabled", lambda: True)

    import database

    monkeypatch.setattr(database, "get_db_cursor", _backfill_select_cursor([_backfill_row(777)]))
    monkeypatch.setattr(rs, "apply_rules", lambda *a, **k: {"action_type": "skip_triage"})

    queued_ids = []
    monkeypatch.setattr(ts, "triage_message_async", lambda mid: queued_ids.append(mid))

    n = ts.backfill_collaborator_triage(limit=25)
    assert n == 0
    assert queued_ids == []


def test_backfill_never_triages_synchronously():
    # Must only ENQUEUE via triage_message_async — never call triage_message()
    # (synchronous) directly (module-work-pattern: no sync inference on the worker).
    src = inspect.getsource(ts.backfill_collaborator_triage)
    assert "triage_message_async(" in src
    assert "triage_message(" not in src
