"""Red findings card the owner for permission at PROPOSAL time (owner order,
2026-07-11).

Contract under test:
- red proposals request action_type ``improvement_approve_red`` — NOT in the
  tier-1 auto-approve list, so the requested Tier-2 stands -> Telegram card;
  yellow quality findings stay advise-only (auto-approved improvement_approve).
- agent_loop dedups red cards PER PROPOSAL (distinct reds may pend at once).
- the batch fix dispatcher HOLDS unapproved red fixes; yellows flow.
- the autoheal cycle re-cards reds whose 24h card expired (idempotent safety
  net), before fix dispatch.

agent_loop assertions are source-pins (the 12k-line module is not imported in
unit tests): the source path comes from AGENT_LOOP_PATH (test bundle) or the
live module spec.
"""

import importlib.util
import inspect
import os

import services.audit_pipeline as ap
import services.code_health_autoheal as ah


def _agent_loop_source():
    path = os.environ.get("AGENT_LOOP_PATH")
    if not path:
        spec = importlib.util.find_spec("agent_loop") or importlib.util.find_spec("ai_bridge.agent_loop")
        path = spec.origin
    with open(path, "r", encoding="utf-8") as fh:
        return fh.read()


def test_red_findings_request_the_red_action_type():
    assert ap._approval_action_type("red") == "improvement_approve_red"
    assert ap._approval_action_type("yellow") == "improvement_approve"


def test_batch_dispatcher_holds_unapproved_reds():
    src = inspect.getsource(ap.dispatch_audit_proposals)
    assert "severity_tier" in src, "red gate clause missing from the batch dispatcher SQL"
    assert "'red'" in src
    assert "'approved'" in src


def test_agent_loop_dedups_red_cards_per_proposal():
    src = _agent_loop_source()
    assert "improvement_approve_red" in src, "red action type unknown to agent_loop"
    dedup_region = src.split('== "improvement_approve_red"', 1)
    assert len(dedup_region) == 2, "no per-type dedup branch for improvement_approve_red"
    assert "proposal_id" in dedup_region[1][:900]


def test_agent_loop_executor_handles_red_type():
    src = _agent_loop_source()
    assert (
        '("improvement_approve", "improvement_approve_red")' in src
    ), "executor must treat an approved red card exactly like improvement_approve"


def test_recard_requests_approval_per_unapproved_red(monkeypatch):
    monkeypatch.setattr(ah, "_load_unapproved_reds", lambda: [{"id": 7, "title": "t7"}, {"id": 9, "title": "t9"}])
    sent = []
    monkeypatch.setattr(ah, "_request_red_approval", lambda p: sent.append(p["id"]))
    assert ah._recard_unapproved_reds() == 2
    assert sent == [7, 9]


def test_recard_failure_is_non_fatal(monkeypatch):
    monkeypatch.setattr(ah, "_load_unapproved_reds", lambda: [{"id": 7, "title": "t7"}])

    def boom(p):
        raise RuntimeError("approval queue down")

    monkeypatch.setattr(ah, "_request_red_approval", boom)
    assert ah._recard_unapproved_reds() == 0  # must not raise


def test_cycle_recards_before_fix_dispatch(monkeypatch):
    order = []
    monkeypatch.setattr(
        ah,
        "_deep_scan",
        lambda target: {
            "proposals_created": 1,
            "confirmed": 1,
            "advisory": 0,
            "skipped_duplicates": 0,
            "coverage": {},
            "fingerprints": [],
        },
    )
    monkeypatch.setattr(ah, "_recard_unapproved_reds", lambda: order.append("recard") or 3)
    monkeypatch.setattr(
        ah, "_dispatch_fixes", lambda limit: order.append("dispatch") or {"dispatched": 1, "failed": 0, "skipped": 0}
    )
    monkeypatch.setattr(ah, "_reverify_static", lambda fingerprints: {"fixed": 0, "still_open": 0})
    res = ah.run_autoheal_cycle()
    assert order == ["recard", "dispatch"]
    assert res["reds_recarded"] == 3
