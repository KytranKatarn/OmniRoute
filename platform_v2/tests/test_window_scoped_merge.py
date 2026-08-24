"""Window-scoped COO auto-merge (#5247b).

The owner chose: during an ANNOUNCED maintenance window, A.R.C.H.I.E. as COO may
auto-merge approved Tier<=2 PRs from that window's manifest. Tier 3 never.

This is added as a SEPARATE authority ('coo_window'), strictly NARROWER than
'coo' — same Tier-2 ceiling plus a third condition. Nothing that could merge
before gains any new power; the existing 20 merge-governance tests still pass
untouched.

WHY THE THIRD CONDITION IS THREE CHECKS, not one:
  * the window must be OPEN, not merely announced — an announced window is a
    proposal, an open one is the period the owner agreed to;
  * the PR must be ON that window's manifest — the owner was shown a SPECIFIC
    list, and add_item() already refuses to extend a manifest after opening, so
    honouring the list here is what makes that refusal mean anything;
  * the item must still be 'planned' — never merge the same item twice.

FAILS CLOSED throughout. #5194 exists because a parallel path merged a PR on a
`needs_changes` verdict; the lesson was that this gate must deny on every
uncertainty, not just on explicit refusal.
"""

import pytest

pytest.importorskip("psycopg2")

from tests.dbguard import import_or_skip  # noqa: E402
from tests.modstub import install_module_stub  # noqa: E402

try:
    from tools.repair_bay.services import github_service as gs
except Exception as exc:  # pragma: no cover
    import_or_skip(exc, "github_service")


def _install(monkeypatch, windows=None, manifests=None, boom=False):
    def list_windows(status=None, limit=20):
        if boom:
            raise RuntimeError("db down")
        return [w for w in (windows or []) if w["status"] == status]

    def get_manifest(window_id):
        if boom:
            raise RuntimeError("db down")
        return (manifests or {}).get(window_id, [])

    install_module_stub(
        monkeypatch,
        "services.maintenance_schedule_service",
        list_windows=list_windows,
        get_manifest=get_manifest,
    )


_OPEN = [{"id": 3, "status": "open"}]
_ANNOUNCED = [{"id": 3, "status": "announced"}]


# ------------------------------------------------------------- happy path ---
def test_pr_on_open_window_manifest_is_allowed(monkeypatch):
    _install(
        monkeypatch,
        _OPEN,
        {3: [{"ref": "2499", "repo": gs.REPO_FULL, "status": "planned", "item_type": "repair_bay_pr"}]},
    )
    ok, why = gs._pr_on_open_window(2499)
    assert ok is True
    assert "open window 3" in why


def test_ref_is_compared_as_a_string(monkeypatch):
    """manifest refs are TEXT; a PR number is an int. A type mismatch here would
    silently deny every merge."""
    _install(
        monkeypatch,
        _OPEN,
        {3: [{"ref": 2499, "repo": gs.REPO_FULL, "status": "planned", "item_type": "repair_bay_pr"}]},
    )
    ok, _ = gs._pr_on_open_window(2499)
    assert ok is True


# ------------------------------------------------------------ denials ------
def test_no_open_window_denies(monkeypatch):
    _install(monkeypatch, [], {})
    ok, why = gs._pr_on_open_window(2499)
    assert ok is False
    assert "no maintenance window is open" in why


def test_announced_but_not_open_denies(monkeypatch):
    """An announced window is a PROPOSAL. Merging during it would pre-empt the
    period the owner actually agreed to."""
    _install(monkeypatch, _ANNOUNCED, {3: [{"ref": "2499", "status": "planned"}]})
    ok, _ = gs._pr_on_open_window(2499)
    assert ok is False


def test_pr_not_on_the_manifest_denies(monkeypatch):
    """THE POINT OF THE APPROVED LIST. A PR the owner was never shown must not
    ride along just because a window happens to be open."""
    _install(monkeypatch, _OPEN, {3: [{"ref": "1111", "status": "planned"}]})
    ok, why = gs._pr_on_open_window(2499)
    assert ok is False
    assert "not on any open window" in why


def test_already_deployed_item_denies(monkeypatch):
    _install(
        monkeypatch,
        _OPEN,
        {3: [{"ref": "2499", "repo": gs.REPO_FULL, "status": "deployed", "item_type": "repair_bay_pr"}]},
    )
    ok, why = gs._pr_on_open_window(2499)
    assert ok is False
    assert "already" in why


# --------------------------------------------------------- item_type gate ---
def test_a_non_pr_item_type_is_never_authorised(monkeypatch):
    """#380 review round 2, Critical 1: proposer_service writes unified_task /
    proposal / code_issue manifest rows whose `ref` is a SOURCE-ROW id, not a PR
    number -- and those id ranges overlap real PR numbers. Matching on ref+repo
    alone let a window listing 'proposal ref 2790' authorise unrelated PR #2790."""
    _install(
        monkeypatch,
        _OPEN,
        {3: [{"ref": "2499", "repo": gs.REPO_FULL, "status": "planned", "item_type": "proposal"}]},
    )
    ok, _ = gs._pr_on_open_window(2499)
    assert ok is False


def test_a_repair_bay_pr_item_type_is_still_authorised(monkeypatch):
    _install(
        monkeypatch,
        _OPEN,
        {3: [{"ref": "2499", "repo": gs.REPO_FULL, "status": "planned", "item_type": "repair_bay_pr"}]},
    )
    ok, _ = gs._pr_on_open_window(2499)
    assert ok is True


def test_lookup_error_fails_closed(monkeypatch):
    """An unattended merge must never happen because a check could not run."""
    _install(monkeypatch, boom=True)
    ok, why = gs._pr_on_open_window(2499)
    assert ok is False
    assert "refusing" in why


def test_missing_service_fails_closed(monkeypatch):
    import sys

    monkeypatch.setitem(sys.modules, "services.maintenance_schedule_service", None)
    ok, _ = gs._pr_on_open_window(2499)
    assert ok is False


# ------------------------------------------------------ authority scoping ---
def test_coo_window_is_registered_with_the_coo_ceiling():
    env_key, ceiling = gs._AUTHORITY_CEILING["coo_window"]
    assert ceiling == 2, "window-scoped merges use the COO Tier-2 ceiling"
    assert env_key == "ARCHIE_COO_AUTO_MERGE_MAX_TIER"


def test_coo_window_is_never_wider_than_coo():
    """It may be narrower, never wider. If these ever diverge upward, the new
    authority has become a privilege escalation."""
    assert gs._AUTHORITY_CEILING["coo_window"][1] <= gs._AUTHORITY_CEILING["coo"][1]


def test_default_authority_is_still_the_most_restrictive():
    assert gs._DEFAULT_AUTHORITY == "forge"
    assert gs._AUTHORITY_CEILING["forge"][1] == 1, "an unknown caller must never inherit COO powers"


def test_window_condition_applies_only_to_coo_window(monkeypatch):
    """Existing authorities must be completely unaffected — the third condition
    is additive to the new one only."""
    import inspect

    src = inspect.getsource(gs._automerge_governance_ok)
    assert '"coo_window"' in src, "condition 3 is not scoped to coo_window"
    idx = src.index('"coo_window"')
    assert "_pr_on_open_window" in src[idx : idx + 400], "window check is not inside the coo_window branch"
