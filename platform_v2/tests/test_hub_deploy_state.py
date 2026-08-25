"""The hub's own deploy state — the volume-mounted half of provenance (#5867).

`deploy_drift_check.py` covers IMAGE-BAKED products, where the container holds a `COPY .`
snapshot. `archie_platform` / `archie_scheduler` are the opposite shape: they BIND-MOUNT
the tree, so a GitHub merge deploys NOTHING and the platform serves whatever branch the
host checkout sits on. Nothing measured that.

Only `derive_status` is unit-tested — deliberately. The gathering half is git + docker
I/O; this is the part that can be WRONG in a way that matters, which is exactly why it was
split out. An untestable verdict is one nobody can check.
"""

import pytest

import services.hub_deploy_state as hub_deploy_state
from services.hub_deploy_state import derive_status

_CLEAN = {
    "branch": "main",
    "default_branch": "main",
    "on_default_branch": True,
    "behind_main": 0,
    "stale_containers": [],
    "dirty": False,
    "origin_fetched_age_hours": 0.2,
}


def _status(**over):
    return derive_status({**_CLEAN, **over})[0]


def _warnings(**over):
    return derive_status({**_CLEAN, **over})[1]


def test_a_clean_hub_on_main_is_in_sync():
    """The negative control — without it every other assertion could pass on a function
    that always alarms."""
    assert _status() == "in_sync"
    assert _warnings() == []


def test_an_unreadable_repo_is_unknown_never_in_sync():
    """A monitor that cannot see is not a monitor that approves. `deploy_drift_check`
    treats an unreachable product as fail-open for the same reason."""
    assert _status(on_default_branch=None) == "unknown"


def test_a_feature_branch_is_the_loudest_signal():
    """The platform is serving UNMERGED code to every user. This outranks everything —
    and it is the state the live hub was in, undetected, for a whole session."""
    assert _status(on_default_branch=False, branch="feat/x") == "feature_branch"
    # even when other problems are also present
    assert _status(on_default_branch=False, branch="feat/x", behind_main=9, dirty=True) == "feature_branch"


def test_pulled_but_not_restarted_is_needs_restart():
    """The trap deploy-provenance.md prescribes ORDERING for: the code is on disk, the
    long-lived process never loaded it. Grepping the bind-mounted file would show the new
    text and prove nothing."""
    assert _status(stale_containers=["archie_scheduler"]) == "needs_restart"


def test_merged_but_not_pulled_is_needs_pull():
    assert _status(behind_main=3) == "needs_pull"


def test_restart_outranks_pull():
    """Both can be true at once. Restarting is what makes ANY of it live, so it leads."""
    assert _status(behind_main=3, stale_containers=["archie_platform"]) == "needs_restart"


def test_dirty_alone_is_reported():
    assert _status(dirty=True) == "dirty"


def test_every_problem_state_explains_itself():
    """A status with no sentence is a status nobody can act on."""
    for over in (
        {"on_default_branch": False, "branch": "feat/x"},
        {"behind_main": 2},
        {"stale_containers": ["archie_platform"]},
        {"dirty": True},
    ):
        w = _warnings(**over)
        assert w, f"{over} produced no warning"
        assert len(w[0]) > 40, f"{over} warning is too terse to act on: {w[0]!r}"


def test_the_warning_names_the_actual_remedy():
    """Each one has a DIFFERENT fix, and naming the wrong one wastes the operator's time."""
    assert "checkout" in _warnings(on_default_branch=False, branch="feat/x")[0]
    assert "pull" in _warnings(behind_main=1)[0]
    assert "Restart" in _warnings(stale_containers=["archie_platform"])[0]


def test_a_stale_fetch_is_disclosed_because_behind_would_UNDER_report():
    """`behind_main` is measured against the last FETCHED origin/main, and this process
    deliberately does not fetch. Reporting the number without its freshness is the same
    mistake as measuring backup recency without measuring success (#5013)."""
    w = " ".join(_warnings(origin_fetched_age_hours=99.0))
    assert "UNDER-report" in w
    # ...and a fresh fetch says nothing.
    assert "UNDER-report" not in " ".join(_warnings(origin_fetched_age_hours=0.5))


def test_a_missing_fetch_age_does_not_alarm():
    """None is unknown, not stale. Alarming on an unreadable input trains people to
    ignore the alarm."""
    assert "UNDER-report" not in " ".join(_warnings(origin_fetched_age_hours=None))


@pytest.mark.parametrize("stale", [[], None])
def test_no_stale_containers_never_reports_needs_restart(stale):
    assert _status(stale_containers=stale) == "in_sync"


def test_derive_status_is_pure_and_needs_no_repository():
    """If this ever starts touching git or docker it stops being testable, which is the
    whole reason it exists apart from the gatherer.

    Checked on the AST — the CALLS and NAMES actually referenced — not on the source text.
    A substring scan matches this function's own docstring, which says "no git, no docker"
    in prose: the same green-on-a-comment trap as #2817, just failing red instead.
    """
    import ast
    import inspect

    from services import hub_deploy_state

    tree = ast.parse(inspect.getsource(hub_deploy_state.derive_status))
    referenced = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
    attrs = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    for forbidden in ("subprocess", "docker", "_git", "os"):
        assert forbidden not in referenced, f"derive_status must stay pure — it references {forbidden!r}"
    for forbidden in ("run", "getmtime", "from_env"):
        assert forbidden not in attrs, f"derive_status must stay pure — it calls .{forbidden}()"
    # premise check: the scan can see SOMETHING, so an empty result is not a silent pass
    assert "facts" in referenced and "warnings" in referenced


# --- #5867 follow-up: a PARTIAL worktree made `dirty` structurally True -------------------
#
# Measured 2026-08-25, live in archie_platform: `git status --porcelain` returned 2,499
# entries inside the container vs 0 on the host, because `.git` is mounted but most of the
# tree is not — so every unmounted path reads as DELETED. `dirty` therefore fired on every
# call and, since `dirty` outranks `in_sync`, `in_sync` was UNREACHABLE from the only
# environment this module actually runs in. An alarm that always fires is not an alarm.


def test_absent_path_deletions_are_not_dirt(monkeypatch):
    """The false positive: deletions of paths that aren't on disk carry no signal."""
    monkeypatch.setattr(hub_deploy_state.os.path, "exists", lambda p: False)
    dirty, partial = hub_deploy_state._real_dirt(
        " D .claude/hooks/session-init.sh\n D ai_bridge/agent_loop.py\n D scripts/dr/failover.sh"
    )
    assert dirty is False, "unmounted paths must not read as uncommitted work"
    assert partial is True, "but the partial view must be reported, not hidden"


def test_a_real_modification_still_counts(monkeypatch):
    """The signal that must survive: an edit to a file that IS present."""
    monkeypatch.setattr(hub_deploy_state.os.path, "exists", lambda p: True)
    dirty, partial = hub_deploy_state._real_dirt(" M platform_v2/services/hub_deploy_state.py")
    assert dirty is True
    assert partial is False


def test_real_dirt_survives_a_partial_view(monkeypatch):
    """Noise must not mask a genuine edit sitting alongside it."""
    present = {"/mnt/archie_brain/platform_v2/services/hub_deploy_state.py"}
    monkeypatch.setattr(hub_deploy_state.os.path, "exists", lambda p: p in present)
    dirty, partial = hub_deploy_state._real_dirt(
        " D .claude/hooks/session-init.sh\n M platform_v2/services/hub_deploy_state.py"
    )
    assert dirty is True, "a real edit must not be swallowed by the deletion filter"
    assert partial is True


def test_in_sync_is_reachable():
    """The regression this whole section exists for: `in_sync` must be an attainable state."""
    status, warnings = hub_deploy_state.derive_status(
        {
            "branch": "main",
            "on_default_branch": True,
            "behind_main": 0,
            "stale_containers": [],
            "dirty": False,
        }
    )
    assert status == "in_sync"
    assert warnings == []


def test_a_genuine_deletion_of_a_present_tree_still_reads_dirty(monkeypatch):
    """Negative control: the filter must not turn every deletion into a silent skip.

    When the worktree is whole (paths exist), `git status` reporting a staged deletion is
    real work-in-progress and must still count.
    """
    monkeypatch.setattr(hub_deploy_state.os.path, "exists", lambda p: True)
    dirty, partial = hub_deploy_state._real_dirt("D  platform_v2/services/gone.py")
    assert dirty is True
    assert partial is False
