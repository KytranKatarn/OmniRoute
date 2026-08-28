"""A manifest entry is a (repo, PR) pair.

Before this, _pr_on_open_window matched on PR number alone, so a window listing
archie-platform #48 also authorised archie-code #48. PR numbers collide across
repos; an authority check keyed on the number alone crosses repo boundaries.
"""

import sys
import types

from tests.modstub import install_module_stub
from tools.repair_bay.services import github_service as gs

_WINDOW = [{"id": 7}]


def _patch(monkeypatch, manifest_rows):
    # The package-attribute trap this comment used to describe is now handled centrally by
    # tests/modstub.py, which patches BOTH sys.modules and the `services` package attribute.
    #
    # The old mitigation here was "never do a real import of this submodule anywhere in the
    # suite", so the attribute would stay unset. That is an invariant spanning every test
    # file, enforced only by a comment — and it broke the day test_proposer_service.py did a
    # normal `import services.maintenance_schedule_service`, which silently emptied
    # test_maintenance_window_driver.py's results (#5987: 10 passed alone, 7 failed together).
    install_module_stub(
        monkeypatch,
        "services.maintenance_schedule_service",
        list_windows=lambda status=None, limit=5: _WINDOW,
        get_manifest=lambda window_id: manifest_rows,
    )


def test_a_window_for_one_repo_does_not_authorise_another(monkeypatch):
    _patch(monkeypatch, [{"ref": "48", "repo": "KytranKatarn/archie-platform", "status": "planned"}])
    ok, why = gs._pr_on_open_window(48, repo="KytranKatarn/archie-code")
    assert ok is False
    assert "archie-code" in why or "not on any open window" in why


def test_the_matching_repo_is_authorised(monkeypatch):
    _patch(
        monkeypatch,
        [{"ref": "48", "repo": "KytranKatarn/archie-platform", "status": "planned", "item_type": "repair_bay_pr"}],
    )
    ok, _ = gs._pr_on_open_window(48, repo="KytranKatarn/archie-platform")
    assert ok is True


def test_a_legacy_item_with_no_repo_is_refused_not_assumed(monkeypatch):
    """FAIL CLOSED. An entry that predates repo qualification names no repo, so it
    authorises nothing. Treating a NULL repo as 'the default repo' would silently
    re-open the very hole this closes."""
    _patch(
        monkeypatch,
        [{"ref": "48", "repo": None, "status": "planned", "item_type": "repair_bay_pr"}],
    )
    ok, _ = gs._pr_on_open_window(48, repo="KytranKatarn/archie-platform")
    assert ok is False


def test_an_already_deployed_item_is_still_refused(monkeypatch):
    _patch(
        monkeypatch,
        [{"ref": "48", "repo": "KytranKatarn/archie-platform", "status": "deployed", "item_type": "repair_bay_pr"}],
    )
    ok, why = gs._pr_on_open_window(48, repo="KytranKatarn/archie-platform")
    assert ok is False and "deployed" in why


def test_a_non_pr_item_type_does_not_authorise_even_with_matching_ref_and_repo(monkeypatch):
    """CRITICAL (#380 review round 2): proposer_service writes unified_task /
    proposal / code_issue manifest rows whose `ref` is a SOURCE-ROW id, not a PR
    number. Measured: unified_tasks ids run 535-5985, improvement_proposals ids
    run 328-11758 -- both ranges overlap real PR numbers (latest #2790), and both
    producers write repo='KytranKatarn/archie-platform', so ref+repo alone is not
    proof an item IS a pull request. A 'proposal' item that happens to share a
    ref with a real, unrelated PR must never authorise merging that PR."""
    _patch(
        monkeypatch,
        [{"ref": "2790", "repo": "KytranKatarn/archie-platform", "status": "planned", "item_type": "proposal"}],
    )
    ok, _ = gs._pr_on_open_window(2790, repo="KytranKatarn/archie-platform")
    assert ok is False


def test_a_repair_bay_pr_item_still_authorises(monkeypatch):
    """The positive case for the item_type gate above -- forge_pipeline's own
    item_type ('repair_bay_pr') must keep working."""
    _patch(
        monkeypatch,
        [{"ref": "2790", "repo": "KytranKatarn/archie-platform", "status": "planned", "item_type": "repair_bay_pr"}],
    )
    ok, _ = gs._pr_on_open_window(2790, repo="KytranKatarn/archie-platform")
    assert ok is True


def test_forge_pipeline_queues_repo_qualified_items(monkeypatch):
    """forge_pipeline._record_on_next_window is the ONLY production caller of
    add_item() (grep confirms it — every other hit is a docstring). Under the
    fail-closed matcher above, an item with no repo authorises NOTHING — so
    every self-heal PR this hook queues must carry repo=REPO_FULL, or the
    manifest feature ships with zero working producers: safety-correct, but a
    bug wearing safety's clothes."""
    from tools.repair_bay.services import forge_pipeline as fp

    captured = {}

    def _next_window(**kw):
        return {"id": 7}

    def _add_item(window_id, **kw):
        captured.update(kw)
        return {"ok": True, "id": 1}

    mod = types.ModuleType("services.maintenance_schedule_service")
    mod.next_window = _next_window
    mod.add_item = _add_item
    monkeypatch.setitem(sys.modules, "services.maintenance_schedule_service", mod)

    fp._record_on_next_window(
        {"id": 1, "title": "self-heal fix"},
        {"pr_number": 48, "pr_url": "https://github.com/KytranKatarn/archie-platform/pull/48"},
    )

    assert captured.get("repo") == gs.REPO_FULL, (
        f"forge_pipeline queued a manifest item with repo={captured.get('repo')!r} "
        f"instead of REPO_FULL={gs.REPO_FULL!r} — that item authorises nothing "
        f"under the fail-closed (repo, PR) matcher"
    )
