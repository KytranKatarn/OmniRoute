"""P9 safety blocker (#4958) — no-fabrication guardrail for persona email drafts.

Regression cover for KB mistake #281718: a live test of the Collaborator Persona
Email Assistant produced a draft, in a real person's voice, that INVENTED business
metrics and claimed an attachment that did not exist — one owner tap from being sent
to a real correspondent.

Two controls are tested here:
  1. NO-FABRICATION PROMPT CONTRACT — the drafting prompt forbids inventing any
     specific (numbers, dates, prices, names, attachments, commitments) and allows
     only acknowledge / clarify / defer / restate-what-is-in-the-thread.
  2. HARD OUTPUT CHECK AT THE PERSIST BOUNDARY — `validate_draft_no_fabrication`
     rejects a draft that claims an attachment or introduces a digit-bearing token
     absent from the inbound thread. FAIL CLOSED: a rejected draft writes NO approval
     row and is counted in the job's `rejected` tally.

Pure unit tests — DB cursor + cluster dispatch are monkeypatched (fake-cursor style
of `test_collaborator_draft.py`). No live DB, no live inference, no mail sent.
"""

import contextlib
import inspect

import tools.email_manager.draft_proposal_service as dps

# --------------------------------------------------------------------------- #
# fixtures — the REAL Jin Park incident (KB #281718)
# --------------------------------------------------------------------------- #
# Sofia asked Jin for numbers. The inbound contains NO figures at all.
_JIN_INBOUND_SUBJECT = "Q3 churn + retention numbers"
_JIN_INBOUND_BODY = (
    "Hi Jin — could you send over the updated churn and retention numbers when you "
    "get a chance? Also, which cohort definition are you using for these?"
)

# The ACTUAL fabricated draft llama3.2:3b produced, in Jin Park's voice.
_JIN_HALLUCINATED_DRAFT = (
    "Hi Sofia,\n\n"
    "Thanks for reaching out. I've also attached an updated report covering Q2 "
    "performance. Please find the figures below:\n"
    "- Churn rate: 21.5% (cohort A) / 18.9% (cohort B)\n"
    "- Retention rate: 85.3% (30-day) / 72.1% (60-day)\n\n"
    "Best,\nJin"
)

# What a compliant draft looks like: acknowledge + clarify + defer. No specifics.
_CLEAN_DEFER_DRAFT = (
    "Hi Sofia,\n\n"
    "Thanks for the nudge. I'll pull the latest churn and retention figures together "
    "and follow up shortly. On the cohort definition — could you confirm which one "
    "you'd like me to use so the numbers line up with your analysis?\n\n"
    "Best,\nJin"
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


_JIN_ROW = {
    "id": 777,
    "subject": _JIN_INBOUND_SUBJECT,
    "from_address": "sofia@example.com",
    "body_text": _JIN_INBOUND_BODY,
    "body_preview": _JIN_INBOUND_BODY[:80],
    "mailbox_id": 9,
    "thread_id": None,
    "rfc_message_id": "<sofia-1@example.com>",
    "mailbox_address": "jin@kytranempowerment.com",
    "mailbox_type": "human_agent",
    "mailbox_name": "Jin Park",
    "collaborator_agent_id": 9,
    "collaborator_name": "Jin Park",
    "collaborator_system_prompt": "You are Jin Park, a data lead. Reply briefly.",
}


def _inbound() -> str:
    return f"{_JIN_INBOUND_SUBJECT}\n{_JIN_INBOUND_BODY}"


# --------------------------------------------------------------------------- #
# Control 2 — the validator
# --------------------------------------------------------------------------- #
def test_validator_rejects_attachment_claim():
    """The persona cannot attach anything — any attachment claim is a fabrication."""
    for draft in (
        "Thanks! I've attached the report.",
        "Attaching the summary now.",
        "See the attachment for details.",
    ):
        ok, reason = dps.validate_draft_no_fabrication(draft, _inbound())
        assert ok is False, f"should reject attachment claim: {draft!r}"
        assert "attach" in (reason or "").lower()


def test_validator_rejects_the_real_jin_park_fabrication():
    """The exact draft from KB #281718 must be rejected — every figure was invented."""
    ok, reason = dps.validate_draft_no_fabrication(_JIN_HALLUCINATED_DRAFT, _inbound())
    assert ok is False
    assert reason  # a logged explanation is required


def test_validator_rejects_figures_absent_from_inbound():
    """A figure the inbound never mentioned is fabricated, even with no attachment claim."""
    draft = "Churn is running at 21.5% and retention at 85.3%."
    ok, reason = dps.validate_draft_no_fabrication(draft, _inbound())
    assert ok is False
    assert "21.5" in (reason or "")


def test_validator_accepts_clean_acknowledge_and_defer():
    """The CORRECT draft for the Jin/Sofia thread — acknowledge, clarify, defer."""
    ok, reason = dps.validate_draft_no_fabrication(_CLEAN_DEFER_DRAFT, _inbound())
    assert ok is True, f"clean defer draft must pass, got: {reason}"
    assert reason is None


def test_validator_accepts_figure_present_in_inbound():
    """Restating a figure the correspondent themselves supplied is allowed."""
    inbound = "Subject: churn\nOur churn was 12.4% last quarter — can you confirm?"
    draft = "Confirming the 12.4% churn figure you quoted — I'll follow up with the rest."
    ok, reason = dps.validate_draft_no_fabrication(draft, inbound)
    assert ok is True, f"reused inbound figure must pass, got: {reason}"


def test_validator_normalizes_thousands_separators():
    """$4,200 in the draft matches 4200 in the inbound (and vice versa)."""
    ok, _ = dps.validate_draft_no_fabrication("The $4,200 invoice is in hand.", "invoice for 4200 dollars")
    assert ok is True


def test_validator_accepts_no_digit_draft():
    """A draft with no specifics at all is always safe."""
    ok, reason = dps.validate_draft_no_fabrication("Got it — I'll look into this and follow up.", _inbound())
    assert ok is True and reason is None


def test_validator_handles_empty_draft():
    """An empty/blank draft is not publishable — fail closed."""
    ok, _ = dps.validate_draft_no_fabrication("", _inbound())
    assert ok is False


# --------------------------------------------------------------------------- #
# Control 1 — the prompt contract
# --------------------------------------------------------------------------- #
def test_collaborator_prompt_carries_no_fabrication_contract(monkeypatch):
    import database
    import services.cluster_dispatch as cd

    seen = {}

    def _fake_dispatch(capability, prompt, **kw):
        seen["prompt"] = prompt
        return _CLEAN_DEFER_DRAFT

    monkeypatch.setattr(cd, "queued_dispatch_text", _fake_dispatch)
    monkeypatch.setattr(database, "get_db_cursor", _capturing_cursor(cap={}))
    monkeypatch.setattr(dps, "_send_proposal_buttons", lambda *a, **k: None)

    dps._create_collaborator_proposal(dict(_JIN_ROW))

    p = seen["prompt"].lower()
    # forbids inventing specifics
    for forbidden in ("number", "date", "price", "attach", "invent"):
        assert forbidden in p, f"prompt contract must mention {forbidden!r}"
    # names the allowed moves, including deferring
    assert "follow up" in p
    assert "clarif" in p


# --------------------------------------------------------------------------- #
# FAIL CLOSED — the persist boundary
# --------------------------------------------------------------------------- #
def test_hallucinated_draft_writes_no_approval_row(monkeypatch):
    """A fabricated draft must NEVER reach autonomy_approval_queue."""
    import database
    import services.cluster_dispatch as cd

    monkeypatch.setattr(cd, "queued_dispatch_text", lambda *a, **k: _JIN_HALLUCINATED_DRAFT)

    cap = {}
    monkeypatch.setattr(database, "get_db_cursor", _capturing_cursor(cap=cap))
    # a rejected draft must not ping the owner either
    monkeypatch.setattr(
        dps,
        "_send_proposal_buttons",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("owner pinged for a rejected draft")),
    )

    res = dps._create_collaborator_proposal(dict(_JIN_ROW))

    assert res is not True  # not a success
    inserts = [q for q in cap.get("qs", []) if "INSERT INTO autonomy_approval_queue" in q]
    assert inserts == [], "fail-closed violated: approval row written for a fabricated draft"


def test_clean_draft_still_writes_approval_row(monkeypatch):
    """The guardrail must not break the happy path."""
    import database
    import services.cluster_dispatch as cd

    monkeypatch.setattr(cd, "queued_dispatch_text", lambda *a, **k: _CLEAN_DEFER_DRAFT)

    cap = {}
    monkeypatch.setattr(database, "get_db_cursor", _capturing_cursor(cap=cap))
    monkeypatch.setattr(dps, "_send_proposal_buttons", lambda *a, **k: None)

    ok = dps._create_collaborator_proposal(dict(_JIN_ROW))

    assert ok is True
    assert [q for q in cap["qs"] if "INSERT INTO autonomy_approval_queue" in q]


def test_job_counts_rejected_and_creates_nothing(monkeypatch):
    """End-to-end: hallucinated draft -> no row, `rejected` counter increments."""
    import database
    import services.cluster_dispatch as cd

    monkeypatch.setattr(dps, "_collaborators_enabled", lambda: True)
    monkeypatch.setattr(cd, "queued_dispatch_text", lambda *a, **k: _JIN_HALLUCINATED_DRAFT)
    monkeypatch.setattr(dps, "_send_proposal_buttons", lambda *a, **k: None)

    cap = {}
    monkeypatch.setattr(database, "get_db_cursor", _capturing_cursor(select_rows=[dict(_JIN_ROW)], cap=cap))

    out = dps.run_mailhq_collaborator_drafts()

    assert out["candidates"] == 1
    assert out["created"] == 0
    assert out["rejected"] == 1
    assert [q for q in cap["qs"] if "INSERT INTO autonomy_approval_queue" in q] == []


def test_validator_is_reusable_by_both_paths():
    """The validator is a module-level helper — importable by the owner/business path too."""
    assert callable(dps.validate_draft_no_fabrication)
    sig = inspect.signature(dps.validate_draft_no_fabrication)
    params = list(sig.parameters.values())

    # The two REQUIRED inputs, in order. (Was `len(params) == 2`, which broke when #4959
    # added `allowed_facts_text` for curated-facts grounding — a legitimate addition that a
    # bare count cannot distinguish from collaborator-specific coupling.)
    assert [p.name for p in params[:2]] == ["draft", "inbound_text"]

    # THE ACTUAL INVARIANT: anything beyond those two must be OPTIONAL, so the
    # owner/business path can still call it with two arguments and no knowledge of the
    # collaborator feature. A new REQUIRED parameter would couple the paths — that is what
    # this test exists to catch, and a count only caught it by accident.
    for p in params[2:]:
        assert p.default is not inspect.Parameter.empty, (
            f"{p.name} is required — that couples the owner/business path to a " "collaborator-specific argument"
        )


# --------------------------------------------------------------------------- #
# scope: the owner/business path is NOW wired too (follow-up to this PR)
# --------------------------------------------------------------------------- #
def test_owner_business_path_is_wired():
    """Both draft paths are guarded by the SAME two controls.

    This assertion is the inverse of the original scope marker
    (`test_owner_business_path_not_wired_in_this_pr`), which recorded that PR #2311
    deliberately left the LIVE owner/business path unguarded pending an owner decision.
    That decision was taken; the follow-up wired the same contract + validator into
    `_create_proposal`. Full owner/business cover lives in
    `test_owner_draft_no_fabrication.py`.
    """
    owner_src = inspect.getsource(dps._create_proposal)
    assert "_NO_FABRICATION_CONTRACT" in owner_src
    assert "validate_draft_no_fabrication" in owner_src
