"""Reuse must be decided by the ARTIFACT and must fail closed (#5812).

A batch of 12 deploys took 12 FULL ~2,797 MB snapshots (~33 GB) of a tree that never
changed, because deploy_to_production applies no code (#5808). Reusing one snapshot is
correct — but ONLY when the tree is provably identical.

The failure mode these tests exist to prevent is not wasted disk. It is a deploy proceeding
against a restore point that does not match the tree. So every ambiguous input must return
None, and None means "take a fresh backup".
"""

import os

import pytest

from services import predeploy_backup_reuse as R


# ── tree_fingerprint: fails closed on every uncertain input ──────────────────────


def test_fingerprint_is_none_for_a_missing_root(tmp_path):
    """A declared root that does not exist means the caller's assumption about what is
    protected is wrong. Fingerprinting a subset would silently narrow the guarantee."""
    assert R.tree_fingerprint(str(tmp_path / "does-not-exist")) is None


def test_fingerprint_is_none_for_an_empty_tree(tmp_path):
    """An empty walk is far likelier to be a wrong path than a genuinely empty tree.
    A stable digest here would match everything — the worst possible outcome."""
    assert R.tree_fingerprint(str(tmp_path)) is None


def test_fingerprint_is_stable_when_nothing_changes(tmp_path):
    (tmp_path / "a.py").write_text("x = 1\n")
    first = R.tree_fingerprint(str(tmp_path))
    assert first is not None
    assert R.tree_fingerprint(str(tmp_path)) == first


def test_fingerprint_changes_when_a_file_changes(tmp_path):
    f = tmp_path / "a.py"
    f.write_text("x = 1\n")
    before = R.tree_fingerprint(str(tmp_path))
    f.write_text("x = 2  # longer, so size changes too\n")
    os.utime(f, (1_700_000_000, 1_700_000_000))  # force a distinct mtime
    assert R.tree_fingerprint(str(tmp_path)) != before


def test_fingerprint_changes_when_a_file_is_added(tmp_path):
    (tmp_path / "a.py").write_text("x = 1\n")
    before = R.tree_fingerprint(str(tmp_path))
    (tmp_path / "b.py").write_text("y = 2\n")
    assert R.tree_fingerprint(str(tmp_path)) != before


def test_fingerprint_ignores_pycache_churn(tmp_path):
    """__pycache__ is rewritten constantly and protecting it is not the point — if it
    counted, no two deploys would ever match and the optimisation would be dead code."""
    (tmp_path / "a.py").write_text("x = 1\n")
    before = R.tree_fingerprint(str(tmp_path))
    cache = tmp_path / "__pycache__"
    cache.mkdir()
    (cache / "a.cpython-311.pyc").write_bytes(b"\x00\x01\x02")
    assert R.tree_fingerprint(str(tmp_path)) == before


# ── notes round-trip ─────────────────────────────────────────────────────────────


def test_notes_round_trip():
    notes = R.annotate_notes("Pre-deploy snapshot for proposal #8661", "abc123def4567890")
    assert "Pre-deploy snapshot" in notes
    assert R.fingerprint_from_notes(notes) == "abc123def4567890"


def test_notes_without_a_fingerprint_yield_none():
    """Every backup taken BEFORE this change carries no marker. Those must never be
    reused — absence of a fingerprint is not a match."""
    assert R.fingerprint_from_notes("Pre-deploy snapshot for proposal #8661") is None
    assert R.fingerprint_from_notes("") is None
    assert R.fingerprint_from_notes(None) is None


def test_annotate_is_a_noop_without_a_fingerprint():
    assert R.annotate_notes("x", None) == "x"


# ── pick_reusable_backup: the artifact check ─────────────────────────────────────


def _row(name="backup_A", fp="fp_match", age=5.0):
    return {"backup_name": name, "notes": R.annotate_notes("Pre-deploy", fp), "age_minutes": age}


def test_reuses_a_backup_whose_fingerprint_matches():
    assert R.pick_reusable_backup([_row()], "fp_match") == "backup_A"


def test_refuses_when_the_fingerprint_differs():
    """THE test. A recent backup of a DIFFERENT tree must never be reused, however fresh."""
    assert R.pick_reusable_backup([_row(fp="fp_other", age=0.5)], "fp_match") is None


def test_refuses_when_the_current_fingerprint_is_unknown():
    """tree_fingerprint() returned None -> we cannot prove anything -> fresh backup."""
    assert R.pick_reusable_backup([_row()], None) is None


def test_refuses_a_stale_backup_even_on_a_perfect_match():
    """A matching fingerprint proves the CODE is unchanged; it says nothing about DB or
    external state. Age remains a necessary secondary bound."""
    assert R.pick_reusable_backup([_row(age=R.REUSE_MAX_AGE_MINUTES + 1)], "fp_match") is None
    assert R.pick_reusable_backup([_row(age=R.REUSE_MAX_AGE_MINUTES - 1)], "fp_match") == "backup_A"


def test_refuses_rows_that_name_no_artifact():
    assert R.pick_reusable_backup([_row(name="")], "fp_match") is None
    assert R.pick_reusable_backup([{"notes": "treefp=fp_match", "age_minutes": 1}], "fp_match") is None


def test_refuses_rows_with_a_missing_or_negative_age():
    assert R.pick_reusable_backup([{"backup_name": "b", "notes": "treefp=fp_match"}], "fp_match") is None
    assert R.pick_reusable_backup([_row(age=-1)], "fp_match") is None


def test_a_malformed_row_never_selects_a_backup():
    """A row that raises must be skipped, not crash the deploy and not be chosen."""
    bad = {"backup_name": object(), "notes": None, "age_minutes": "not-a-number"}
    assert R.pick_reusable_backup([bad], "fp_match") is None
    # ...and a good row after a bad one is still found.
    assert R.pick_reusable_backup([bad, _row()], "fp_match") == "backup_A"


def test_empty_candidates_is_none():
    assert R.pick_reusable_backup([], "fp_match") is None
    assert R.pick_reusable_backup(None, "fp_match") is None


def test_picks_the_newest_matching_candidate_first():
    rows = [_row(name="newest", age=1.0), _row(name="older", age=30.0)]
    assert R.pick_reusable_backup(rows, "fp_match") == "newest"
