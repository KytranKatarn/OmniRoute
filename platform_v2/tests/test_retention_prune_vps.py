"""The vps retention tier must prune by ARTIFACT presence, never by directory presence.

BACKGROUND (#5616). `retention_prune.py` declared a vps policy for all 10 components in
RETENTION and applied it to none — the string `vps` appeared nowhere else in the file. The
tier grew unbounded (63 run dirs / 49 GB) until outpost-us hit 100% disk on 2026-08-02. The
1.8 GB database dump could then no longer land while the 20 MB gitbundles still fit, which
is exactly why only the `database` component failed nightly.

THE TRAP THESE TESTS EXIST FOR:
`prune_dir()` — the disk-tier pruner this was nearly copied from — selects keepers with
`if not comp_path.exists(): continue`. That is unsafe on a tier fed by rsync, because a
FAILED rsync leaves the component directory behind containing NOTHING. Measured on the live
outpost 2026-08-15: the five newest `database/` dirs were all 4.0K / 0 files, while the last
real 1.7 GB dump sat six days back. An exists()-based ladder keeps five empty folders and
DELETES the only surviving off-site DR copies — turning a stale backup into no backup.

So: an empty component dir must never consume a keep slot, and the pruner must refuse to
empty a component that still holds artifacts.
"""

import sys

import pytest

sys.path.insert(0, "/mnt/archie_brain/scripts/backup")
sys.path.insert(0, "/app")

import retention_prune as rp  # noqa: E402


def _drive(monkeypatch, entries, dry_run=True):
    """Run prune_vps against a scripted remote listing; return (count, doomed RELPATHS).

    NOTE the relpath extraction. An earlier version of this helper returned the full
    'host:/abs/path' token, so assertions like `"<run>/database" not in doomed` could
    never match and passed VACUOUSLY — the test was green for the wrong reason. Compare
    the same shape you assert on.
    """
    monkeypatch.setattr(rp, "_vps_host", lambda: "test-outpost")
    monkeypatch.setattr(rp, "_vps_list", lambda host: entries)
    printed = []
    monkeypatch.setattr("builtins.print", lambda *a, **k: printed.append(" ".join(str(x) for x in a)))
    n = rp.prune_vps(dry_run=dry_run)
    prefix = rp.VPS_REMOTE_ROOT.rstrip("/") + "/"
    doomed = [
        ln.split(" ")[-1].split(":", 1)[-1].replace(prefix, "")
        for ln in printed
        if ln.startswith("[dry-run] would remove")
    ]
    return n, doomed


def test_empty_component_dirs_never_consume_a_keep_slot(monkeypatch):
    """THE REGRESSION — the live 2026-08-15 shape.

    Five newest `database` dirs are EMPTY (failed rsync); the only real dumps are older.
    Policy is database=(7,0,0). All 7 real dumps must survive; the empties are the victims.
    """
    entries = [(f"2026081{d}_060001_daily", "database", False) for d in (5, 4, 3, 2, 1)]
    entries += [(f"202608{d:02d}_060001_daily", "database", True) for d in (2, 1)]
    entries += [(f"202607{d}_060001_daily", "database", True) for d in (31, 30, 29, 28, 27)]

    _n, doomed = _drive(monkeypatch, entries)

    survivors = {t for t in doomed}
    for real in ("20260802_060001_daily/database", "20260727_060001_daily/database"):
        assert real not in survivors, f"DELETED A REAL OFF-SITE DUMP: {real}"
    assert len(doomed) == 5, f"expected only the 5 empty dirs to go, got {doomed}"
    assert all(t.startswith("2026081") for t in doomed)


def test_refuses_to_empty_a_component_that_still_has_artifacts(monkeypatch):
    """Last line of defence: a NON-ZERO policy that retains nothing is a bug, not an order.

    Policy (0,0,1) = 'keep one monthly'. Feed it only NON-monthly artifact-bearing runs and
    the ladder selects zero keepers while real off-site dumps exist. Refuse rather than wipe.
    """
    monkeypatch.setitem(rp.RETENTION, "database", {**rp.RETENTION["database"], "vps": (0, 0, 1)})
    entries = [("20260815_060001_daily", "database", True)]  # day 15 -> not monthly, not Sunday
    n, doomed = _drive(monkeypatch, entries)
    assert n == 0 and doomed == [], "wiped an off-site component that still held artifacts"


def test_zero_policy_deliberately_keeps_nothing(monkeypatch):
    """(0,0,0) is a real instruction — 'code'/'volumes' are set to it so they never live on vps.

    This is the deliberate counterpart to the guard above: the guard must NOT fire here, or
    components that are supposed to be absent from the outpost would accumulate forever.
    """
    monkeypatch.setitem(rp.RETENTION, "volumes", {**rp.RETENTION["volumes"], "vps": (0, 0, 0)})
    entries = [("20260802_060001_daily", "volumes", True)]
    n, _doomed = _drive(monkeypatch, entries)
    assert n == 1, "a (0,0,0) component was not pruned — the tier will grow unbounded"


def test_empty_dirs_are_cleaned_even_under_a_zero_policy(monkeypatch):
    monkeypatch.setitem(rp.RETENTION, "volumes", {**rp.RETENTION["volumes"], "vps": (0, 0, 0)})
    n, _doomed = _drive(monkeypatch, [("20260802_060001_daily", "volumes", False)])
    assert n == 1


def test_unknown_component_and_unparseable_run_are_left_alone(monkeypatch):
    """Never auto-delete something we cannot classify."""
    entries = [
        ("20260802_060001_daily", "some_unknown_component", True),
        ("not-a-timestamp", "database", True),
    ]
    n, doomed = _drive(monkeypatch, entries)
    assert n == 0 and doomed == []


def test_unreachable_outpost_is_skipped_not_guessed(monkeypatch):
    monkeypatch.setattr(rp, "_vps_host", lambda: None)
    assert rp.prune_vps(dry_run=False) == 0


def test_failed_listing_is_skipped_not_guessed(monkeypatch):
    monkeypatch.setattr(rp, "_vps_host", lambda: "test-outpost")
    monkeypatch.setattr(rp, "_vps_list", lambda host: None)
    assert rp.prune_vps(dry_run=False) == 0


def test_vps_policy_is_actually_applied_by_main():
    """The whole bug was a declared-but-never-called policy. Pin the wiring."""
    import inspect

    assert "prune_vps" in inspect.getsource(rp.main), "prune_vps is not wired into main()"


def test_every_tier_in_retention_has_a_pruner():
    """Guards against a THIRD tier repeating the gdrive(#5092)/vps(#5616) bug."""
    import inspect

    src = inspect.getsource(rp)
    tiers = {t for comp in rp.RETENTION.values() for t in comp}
    unpruned = [t for t in tiers if f'"{t}"' not in src.replace(f'"{t}": (', "")]
    # every tier name must appear somewhere outside the RETENTION literal
    for tier in tiers:
        assert src.count(f'"{tier}"') > len(rp.RETENTION), (
            f"tier '{tier}' appears ONLY in the RETENTION dict — declared but never applied, "
            f"which is exactly the #5092/#5616 bug"
        )
