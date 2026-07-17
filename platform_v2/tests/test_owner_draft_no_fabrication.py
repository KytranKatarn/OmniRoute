"""P9 safety blocker (#4958) — no-fabrication guardrail on the OWNER/BUSINESS draft path.

Sibling of `test_draft_no_fabrication.py` (which covers the collaborator path and the
validator itself). This file covers the SECOND, higher-stakes path: R.E.S.O.L.V.E.
drafting replies for the `owner` + `business` mailboxes.

Why this matters more than the collaborator path: `mailhq:draft:enabled` is TRUE — the
owner/business path is LIVE. It used the same "draft a reply" prompt shape with no
fabrication contract and no output check, and queues drafts for one-tap [Send] under the
OWNER's or the BUSINESS's name. KB mistake #281718 proved the failure mode on the sibling
path (invented churn/retention figures + a non-existent attachment, in a real person's
voice); the same exposure existed here.

The two controls (identical to the collaborator path, reusing the SAME helpers):
  1. NO-FABRICATION PROMPT CONTRACT injected into the drafting prompt.
  2. HARD OUTPUT CHECK at the persist boundary — FAIL CLOSED: no approval row, no owner
     ping, counted as `rejected` in the job summary.

Pure unit tests — DB cursor + fleet dispatch are monkeypatched (fake-cursor style of
`test_collaborator_draft.py`). No live DB, no live inference, no mail sent.
"""

import contextlib
import inspect

import tools.email_manager.draft_proposal_service as dps

# --------------------------------------------------------------------------- #
# fixtures — the REAL fabrication from KB #281718, aimed at an OWNER mailbox
# --------------------------------------------------------------------------- #
_INBOUND_SUBJECT = "Q3 churn + retention numbers"
_INBOUND_BODY = (
    "Hi — could you send over the updated churn and retention numbers when you get a "
    "chance? Also, which cohort definition are you using for these?"
)

# The ACTUAL fabricated draft llama3.2:3b produced (KB #281718): a claimed attachment
# plus four invented figures. Nothing in the inbound contains any of it.
_HALLUCINATED_DRAFT = (
    "Hi Sofia,\n\n"
    "Thanks for reaching out. I've also attached an updated report covering Q2 "
    "performance. Please find the figures below:\n"
    "- Churn rate: 21.5% (cohort A) / 18.9% (cohort B)\n"
    "- Retention rate: 85.3% (30-day) / 72.1% (60-day)\n\n"
    "Best,\nKytran"
)

# A compliant draft: acknowledge + clarify + defer. No specifics invented.
_CLEAN_DEFER_DRAFT = (
    "Hi Sofia,\n\n"
    "Thanks for the nudge. I'll pull the latest churn and retention figures together "
    "and follow up shortly. On the cohort definition — could you confirm which one "
    "you'd like me to use?\n\n"
    "Best,\nKytran"
)


def _capturing_cursor(select_rows=None, returning=None, cap=None):
    """Minimal fake cursor. Captures every execute() and serves fetchone/fetchall."""
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
            return None  # platform_settings reads -> callers fall back to defaults

    @contextlib.contextmanager
    def _cm(commit=False):
        yield (None, _Cur())

    return _cm


# An owner-mailbox candidate row, exactly the shape the owner/business SELECT yields
# (no collaborator/persona columns — this path drafts as R.E.S.O.L.V.E.).
_OWNER_ROW = {
    "id": 777,
    "subject": _INBOUND_SUBJECT,
    "from_address": "sofia@example.com",
    "body_text": _INBOUND_BODY,
    "body_preview": _INBOUND_BODY[:80],
    "mailbox_id": 1,
    "thread_id": None,
    "rfc_message_id": "<sofia-1@example.com>",
    "mailbox_address": "kytran@kytranempowerment.com",
    "mailbox_type": "owner",
    "mailbox_name": "Kytran",
}


def _patch_dispatch(monkeypatch, reply):
    """Patch the owner path's dispatch helper (imported from .fleet_dispatch at call time)."""
    import tools.email_manager.fleet_dispatch as fd

    seen = {}

    def _fake(capability, prompt, **kw):
        seen["capability"] = capability
        seen["prompt"] = prompt
        seen.update(kw)
        return reply

    monkeypatch.setattr(fd, "queued_dispatch_text", _fake)
    return seen


# --------------------------------------------------------------------------- #
# Control 1 — the prompt contract reaches the OWNER/BUSINESS drafting prompt
# --------------------------------------------------------------------------- #
def test_owner_prompt_carries_no_fabrication_contract(monkeypatch):
    import database

    seen = _patch_dispatch(monkeypatch, _CLEAN_DEFER_DRAFT)
    monkeypatch.setattr(database, "get_db_cursor", _capturing_cursor(cap={}))
    monkeypatch.setattr(dps, "_send_proposal_buttons", lambda *a, **k: None)

    dps._create_proposal(dict(_OWNER_ROW))

    # the SAME contract constant the collaborator path uses — not a forked copy
    assert dps._NO_FABRICATION_CONTRACT in seen["prompt"]
    p = seen["prompt"].lower()
    for forbidden in ("number", "date", "price", "attach", "invent"):
        assert forbidden in p, f"prompt contract must mention {forbidden!r}"
    assert "follow up" in p  # deferring is named as the correct move
    assert "clarif" in p


# --------------------------------------------------------------------------- #
# Control 2 — FAIL CLOSED at the persist boundary
# --------------------------------------------------------------------------- #
def test_hallucinated_owner_draft_writes_no_approval_row(monkeypatch):
    """The real #281718 fabrication must NEVER reach autonomy_approval_queue."""
    import database

    _patch_dispatch(monkeypatch, _HALLUCINATED_DRAFT)

    cap = {}
    monkeypatch.setattr(database, "get_db_cursor", _capturing_cursor(cap=cap))
    # a rejected draft must not ping the owner either
    monkeypatch.setattr(
        dps,
        "_send_proposal_buttons",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("owner pinged for a rejected draft")),
    )

    res = dps._create_proposal(dict(_OWNER_ROW))

    assert res is not True  # not a success
    assert res == dps._REJECTED  # distinctly a guardrail rejection, not a dispatch failure
    inserts = [q for q in cap.get("qs", []) if "INSERT INTO autonomy_approval_queue" in q]
    assert inserts == [], "fail-closed violated: approval row written for a fabricated draft"


def test_owner_validation_uses_full_inbound_not_prompt_snippet(monkeypatch):
    """A figure quoted BEYOND the 1000-char prompt snippet is still the sender's own.

    The prompt is truncated to 1000 chars; validation must run against the FULL thread
    text (subject + body), or a late-quoted figure would be falsely flagged as invented.
    """
    import database

    filler = "Some earlier context about the quarter. " * 40  # > 1000 chars
    row = dict(_OWNER_ROW)
    row["body_text"] = filler + "Anyway, our churn was 12.4% last quarter — can you confirm?"
    row["body_preview"] = row["body_text"][:80]

    _patch_dispatch(monkeypatch, "Confirming the 12.4% churn figure you quoted — I'll follow up.")

    cap = {}
    monkeypatch.setattr(database, "get_db_cursor", _capturing_cursor(cap=cap))
    monkeypatch.setattr(dps, "_send_proposal_buttons", lambda *a, **k: None)

    ok = dps._create_proposal(row)

    assert ok is True, "a figure present late in the inbound must not be treated as fabricated"
    assert [q for q in cap["qs"] if "INSERT INTO autonomy_approval_queue" in q]


def test_owner_draft_reusing_inbound_figure_is_accepted(monkeypatch):
    """Restating a figure the correspondent themselves supplied is allowed."""
    import database

    row = dict(_OWNER_ROW)
    row["subject"] = "invoice 4200"
    row["body_text"] = "Can you confirm the 4200 invoice is in hand?"
    row["body_preview"] = row["body_text"]

    _patch_dispatch(monkeypatch, "Confirming the $4,200 invoice is in hand — I'll follow up shortly.")

    cap = {}
    monkeypatch.setattr(database, "get_db_cursor", _capturing_cursor(cap=cap))
    monkeypatch.setattr(dps, "_send_proposal_buttons", lambda *a, **k: None)

    ok = dps._create_proposal(row)

    assert ok is True
    assert [q for q in cap["qs"] if "INSERT INTO autonomy_approval_queue" in q]


# --------------------------------------------------------------------------- #
# REGRESSION — the live feature still works exactly as before
# --------------------------------------------------------------------------- #
def test_clean_owner_draft_still_queues_unchanged(monkeypatch):
    """THE regression that proves the live path is not broken.

    A legitimate, non-fabricated draft must still produce an identical approval row:
    same action_type, same R.E.S.O.L.V.E. attribution, same addressing, same owner ping.
    """
    import database

    _patch_dispatch(monkeypatch, "  " + _CLEAN_DEFER_DRAFT + "  ")  # padded: still stripped

    cap = {}
    pinged = {}
    monkeypatch.setattr(database, "get_db_cursor", _capturing_cursor(cap=cap))
    monkeypatch.setattr(
        dps,
        "_send_proposal_buttons",
        lambda queue_id, c, draft, agent: pinged.update(queue_id=queue_id, agent=agent),
    )

    ok = dps._create_proposal(dict(_OWNER_ROW))
    assert ok is True

    ins = [q for q in cap["qs"] if "INSERT INTO autonomy_approval_queue" in q]
    assert ins and "'email_reply'" in ins[0]

    idx = cap["qs"].index(ins[0])
    json_arg = cap["params"][idx][0]
    action_data = getattr(json_arg, "adapted", json_arg)  # psycopg2 Json wraps the dict

    assert action_data["agent"] == "R.E.S.O.L.V.E."  # unchanged attribution
    assert action_data["draft_reply"] == _CLEAN_DEFER_DRAFT  # stripped, verbatim
    assert action_data["from_address"] == "kytran@kytranempowerment.com"  # reply FROM our mailbox
    assert action_data["to_address"] == "sofia@example.com"  # TO the original sender
    assert action_data["subject"] == f"Re: {_INBOUND_SUBJECT}"
    assert action_data["message_id"] == 777
    assert action_data["mailbox_id"] == 1
    assert action_data["in_reply_to"] == "<sofia-1@example.com>"
    # the owner is still pinged with Approve/Cancel buttons
    assert pinged == {"queue_id": 99, "agent": "R.E.S.O.L.V.E."}


def test_dispatch_failure_still_distinct_from_rejection(monkeypatch):
    """An empty/failed dispatch returns False (not _REJECTED) — retry accounting differs."""
    import database

    _patch_dispatch(monkeypatch, None)
    monkeypatch.setattr(database, "get_db_cursor", _capturing_cursor(cap={}))

    assert dps._create_proposal(dict(_OWNER_ROW)) is False


# --------------------------------------------------------------------------- #
# job-level: the `rejected` counter, mirroring the collaborator job's shape
# --------------------------------------------------------------------------- #
def test_owner_job_counts_rejected_and_creates_nothing(monkeypatch):
    """End-to-end: hallucinated draft -> no row, `rejected` counter increments."""
    import database

    monkeypatch.setattr(dps, "_draft_enabled", lambda: True)
    _patch_dispatch(monkeypatch, _HALLUCINATED_DRAFT)
    monkeypatch.setattr(dps, "_send_proposal_buttons", lambda *a, **k: None)

    cap = {}
    monkeypatch.setattr(database, "get_db_cursor", _capturing_cursor(select_rows=[dict(_OWNER_ROW)], cap=cap))

    out = dps.run_mailhq_draft_proposals()

    assert out["candidates"] == 1
    assert out["created"] == 0
    assert out["rejected"] == 1
    assert [q for q in cap["qs"] if "INSERT INTO autonomy_approval_queue" in q] == []


def test_owner_job_creates_for_clean_draft(monkeypatch):
    """The live job still creates proposals for legitimate drafts."""
    import database

    monkeypatch.setattr(dps, "_draft_enabled", lambda: True)
    _patch_dispatch(monkeypatch, _CLEAN_DEFER_DRAFT)
    monkeypatch.setattr(dps, "_send_proposal_buttons", lambda *a, **k: None)

    cap = {}
    monkeypatch.setattr(database, "get_db_cursor", _capturing_cursor(select_rows=[dict(_OWNER_ROW)], cap=cap))

    out = dps.run_mailhq_draft_proposals()

    assert out["candidates"] == 1
    assert out["created"] == 1
    assert out["rejected"] == 0
    assert [q for q in cap["qs"] if "INSERT INTO autonomy_approval_queue" in q]


def test_owner_job_summary_shape_mirrors_collaborator(monkeypatch):
    """Counter shape must match the collaborator job's summary."""
    import database

    monkeypatch.setattr(dps, "_draft_enabled", lambda: True)
    monkeypatch.setattr(database, "get_db_cursor", _capturing_cursor(select_rows=[], cap={}))

    out = dps.run_mailhq_draft_proposals()
    assert set(out) == {"candidates", "created", "capped", "cooling", "rejected"}


def test_owner_gate_untouched_and_still_respected(monkeypatch):
    """The live gate key is unchanged, and an OFF gate is still a hard no-op."""
    assert dps.DRAFT_FLAG_KEY == "mailhq:draft:enabled"

    monkeypatch.setattr(dps, "_draft_enabled", lambda: False)
    import database

    monkeypatch.setattr(database, "get_db_cursor", lambda *a, **k: (_ for _ in ()).throw(AssertionError("DB touched")))
    out = dps.run_mailhq_draft_proposals()
    assert out.get("skipped") is True


# --------------------------------------------------------------------------- #
# scope / reuse
# --------------------------------------------------------------------------- #
def test_owner_path_reuses_shared_helpers_not_a_fork():
    """Both controls must be the SHARED helpers — a forked copy would drift out of sync."""
    src = inspect.getsource(dps._create_proposal)
    assert "_NO_FABRICATION_CONTRACT" in src
    assert "validate_draft_no_fabrication(" in src
    assert "_inbound_text(c)" in src  # validated against the FULL thread, not the snippet
    assert "_REJECTED" in src


def test_owner_path_still_resolve_via_fleet_dispatch():
    """Guarding must not change WHO drafts or HOW it is dispatched (KB #276153)."""
    src = inspect.getsource(dps._create_proposal)
    assert "R.E.S.O.L.V.E." in src
    assert "from .fleet_dispatch import queued_dispatch_text" in src
    assert "queued_dispatch_text(" in src
    assert "dispatch_json(" not in src  # never the synchronous call
    assert "model_override" not in src  # owner/business path never forces a model


def test_collaborator_path_untouched():
    """This change must not alter the (already-guarded, still-gated-off) collab path."""
    assert dps.COLLAB_FLAG_KEY == "mailhq:draft:collaborators"
    assert dps._COLLAB_MODEL == "llama3.2:3b"
    collab_src = inspect.getsource(dps._create_collaborator_proposal)
    assert "validate_draft_no_fabrication(" in collab_src
    assert "model_override=_COLLAB_MODEL" in collab_src
