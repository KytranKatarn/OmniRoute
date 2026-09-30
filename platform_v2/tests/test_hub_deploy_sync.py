"""Hub deploy sync — every merge path closes the gap, or says exactly why it cannot.

`decide` and `attention_item` are PURE and tested directly. `request_hub_deploy` is tested
with the git/docker/DB/host-queue edges stubbed, because the failure worth catching is a
WRONG DECISION (queue a deploy that will be rejected, or skip one that was needed), not
the plumbing.
"""

import pytest

import services.hub_deploy_sync as sync
from services.hub_deploy_sync import attention_item, decide, touches_hub


@pytest.mark.parametrize(
    "status,expected",
    [
        ("in_sync", "noop"),
        ("needs_pull", "deploy"),
        ("needs_restart", "deploy"),
        ("feature_branch", "blocked"),
        ("dirty", "blocked"),
        ("unknown", "blocked"),
        ("something-new", "blocked"),  # an unrecognised state must NOT deploy
    ],
)
def test_decide(status, expected):
    assert decide(status, {"branch": "chore/x"})[0] == expected


def test_feature_branch_reason_names_the_branch_and_the_cure():
    _, reason = decide("feature_branch", {"branch": "chore/opencode-lane-scope"})
    assert "chore/opencode-lane-scope" in reason and "worktree" in reason


@pytest.mark.parametrize(
    "paths,expected",
    [
        (["what-the-fact/consumer/routes.py"], False),
        (["what-the-fact/a.py", "website/x/index.html", ".claude/rules/y.md"], False),
        (["platform_v2/services/x.py"], True),
        (["what-the-fact/a.py", "platform_v2/x.py"], True),  # ONE hub file is enough
        (["scripts/host_monitor.py"], True),
        (None, True),  # unreadable file list => assume it matters
        ([], True),
    ],
)
def test_touches_hub(paths, expected):
    assert touches_hub(paths) is expected


@pytest.fixture
def edges(monkeypatch):
    calls = {"submit": [], "stamp": 0}
    monkeypatch.setattr(sync, "_cooldown_remaining", lambda now=None: calls.get("wait", 0.0))
    monkeypatch.setattr(sync, "_stamp_cooldown", lambda now=None: calls.__setitem__("stamp", calls["stamp"] + 1))

    import tools.system_operations.host_command_client as hc

    monkeypatch.setattr(
        hc,
        "submit_host_command",
        lambda t, p, submitted_by=None, **k: calls["submit"].append((t, submitted_by)) or "cmd-1",
    )
    return calls


def _state(status, **kw):
    return {"status": status, "branch": "main", "behind_main": 3, **kw}


def test_queues_when_behind_and_clean(edges):
    out = sync.request_hub_deploy("merge_pr", state=_state("needs_pull"))
    assert out["queued"] and edges["submit"] == [("hub_deploy", "merge_pr")] and edges["stamp"] == 1


def test_does_not_queue_on_a_working_branch_and_says_why(edges):
    out = sync.request_hub_deploy("merge_pr", state=_state("feature_branch", branch="chore/x"))
    assert not out["queued"] and out["action"] == "blocked" and "chore/x" in out["reason"]
    assert edges["submit"] == []


def test_cooldown_prevents_a_second_request(edges):
    edges["wait"] = 600.0
    out = sync.request_hub_deploy("hub_deploy_provenance", state=_state("needs_pull"))
    assert not out["queued"] and out["action"] == "noop" and edges["submit"] == []


def test_a_wtf_only_pr_does_not_restart_the_hub(edges):
    out = sync.request_hub_deploy(
        "merge_pr", state=_state("needs_pull"), changed_paths=["what-the-fact/x.py"], check_paths=True
    )
    assert out["action"] == "noop" and edges["submit"] == []


def test_never_raises(monkeypatch):
    def boom():
        raise RuntimeError("git exploded")

    import services.hub_deploy_state as st

    monkeypatch.setattr(st, "hub_deploy_state", boom)
    out = sync.request_hub_deploy("merge_pr")
    assert out["queued"] is False and out["action"] == "blocked"


# ---- the Attention Needed wording --------------------------------------------------------


def test_no_item_when_in_sync_or_unknown():
    assert attention_item(None) is None
    assert attention_item({"drift": "in_sync"}) is None
    assert attention_item({}) is None


def test_queued_is_informational_and_never_says_failed():
    it = attention_item({"drift": "pull_required", "behind_main": 7, "deploy": {"queued": True}}, 3.2)
    assert it["level"] == "info" and "7 commits behind main for 3h" in it["text"]
    assert "failed" not in it["text"].lower()


def test_blocked_is_a_warning_that_states_the_reason():
    it = attention_item(
        {
            "drift": "pull_required",
            "behind_main": 1,
            "deploy": {"action": "blocked", "reason": "the live checkout is on 'x'"},
        },
        0.2,
    )
    assert it["level"] == "warning" and "needs a human" in it["text"] and "on 'x'" in it["text"]
    assert "1 commit behind" in it["text"] and "under an hour" in it["text"]


def test_waiting_on_cooldown_is_informational():
    it = attention_item({"drift": "restart_required", "deploy": {"action": "noop"}}, 1)
    assert it["level"] == "info" and "waiting" in it["text"]


# ---- the monitor: drift is a state, not a job failure -----------------------------------


def _run_monitor(monkeypatch, outcome, status="pull_required"):
    import services.fleet_jobs as fj
    import services.hub_deploy_provenance as prov
    import services.telegram_service as tg

    logged, paged = [], []
    monkeypatch.setattr(
        prov,
        "check_hub_deploy",
        lambda *a, **k: {
            "status": status,
            "reason": "checkout is at aaa but origin/main is at bbb",
            "remedy": "git pull",
            "local_head": "a" * 40,
            "remote_head": "b" * 40,
        },
    )
    monkeypatch.setattr(sync, "request_hub_deploy", lambda source, **k: outcome)
    monkeypatch.setattr(fj, "_log_cycle", lambda *a, **k: logged.append((a, k)))
    monkeypatch.setattr(tg, "send_system", lambda **k: paged.append(k))
    fj.hub_deploy_provenance_monitor()
    return logged, paged


def test_drift_that_was_queued_logs_success_and_does_not_page(monkeypatch):
    logged, paged = _run_monitor(
        monkeypatch, {"action": "deploy", "queued": True, "reason": "x", "behind_main": 4, "branch": "main"}
    )
    ((args, kw),) = logged
    assert args[1:4] == (1, 0, 0), "drift must NOT be logged as a failed cycle"
    assert kw["details"]["drift"] == "pull_required" and kw["details"]["deploy"]["queued"] is True
    assert paged == []


def test_drift_that_needs_a_human_pages_with_the_reason(monkeypatch):
    logged, paged = _run_monitor(
        monkeypatch,
        {
            "action": "blocked",
            "queued": False,
            "reason": "the live checkout is on 'chore/x'",
            "behind_main": 9,
            "branch": "chore/x",
        },
    )
    assert logged[0][0][1:4] == (1, 0, 0)
    assert len(paged) == 1 and "chore/x" in paged[0]["message"]


def test_a_real_crash_still_logs_a_failure(monkeypatch):
    import services.fleet_jobs as fj
    import services.hub_deploy_provenance as prov

    logged = []
    monkeypatch.setattr(prov, "check_hub_deploy", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    monkeypatch.setattr(fj, "_log_cycle", lambda *a, **k: logged.append((a, k)))
    fj.hub_deploy_provenance_monitor()
    assert logged[0][0][1:4] == (0, 1, 0) and "boom" in logged[0][1]["error_message"]


def test_merge_pr_requests_a_deploy_from_the_choke_point():
    from pathlib import Path

    src = (Path(__file__).resolve().parent.parent / "tools/repair_bay/services/github_service.py").read_text()
    assert 'request_hub_deploy("merge_pr"' in src and "_repo == REPO_FULL" in src
