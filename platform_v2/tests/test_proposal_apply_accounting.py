"""#5899 — 'deployed' does not mean the code is live; the counts must say so.

`proposal_service.deploy_proposal()` takes a backup, logs "Manual deployment
required - automatic code application disabled for safety", and THEN writes
status='deployed'. The safety behaviour is right; the word is wrong, and it made
Repair Bay's "Completed" tile report 392 when 370 of those (94%) never touched a
file. #5808 already wrote the honest flag (`code_applied: false`) at that site --
nothing read it. Migration 474 backfilled the 344 older rows from the prose.

These tests pin the CONTRACT, not the numbers (which move):
  1. the pre-existing `deployed` expression stays byte-identical -- the split is
     ADDITIVE, so no existing consumer's number can shift;
  2. UNKNOWN is never counted as applied -- `not_applied` matches only an explicit
     'false', and absence gets its own bucket;
  3. migration 474 is idempotent by construction.
"""

import pathlib
import re

import pytest

_SVC = pathlib.Path(__file__).resolve().parents[1] / "services" / "proposal_service.py"
# #5916, AGAIN: platform_v2 is bind-mounted at /app, so parents[2] from
# /app/tests is "/" and the repo's database/ dir is NOT a sibling. Walking upward
# works from a normal checkout; inside the container it must fall back to the known
# mount and then SKIP WITH A REASON. A permanently-red test trains everyone to
# ignore red, which is the whole point of #5922.
_REL = pathlib.Path("database/migrations/474_backfill_code_applied.sql")


def _migration_path():
    for parent in pathlib.Path(__file__).resolve().parents:
        if (parent / _REL).exists():
            return parent / _REL
    for fallback in (pathlib.Path("/mnt/archie_brain"), pathlib.Path("/app").parent):
        if (fallback / _REL).exists():
            return fallback / _REL
    return None


def _svc() -> str:
    return _SVC.read_text(encoding="utf-8")


def test_the_original_deployed_count_is_untouched():
    """The whole point of an additive split: every existing caller keeps its number.
    If this fails someone narrowed `deployed`, and dashboards silently changed."""
    assert "COUNT(*) FILTER (WHERE status = 'deployed' OR status = 'implemented') as deployed," in _svc()
    assert "COUNT(*) FILTER (WHERE status IN ('deployed', 'implemented')) as total_deployed," in _svc()


def test_unknown_is_never_counted_as_applied():
    """An absent flag means WE DO NOT KNOW (22 April rows predate the manual path).
    Counting those as applied would recreate the exact lie this fixes, so
    `not_applied` must key off an EXPLICIT 'false' and unknown must be its own bucket."""
    src = _svc()
    assert "metadata->>'code_applied' = 'false') as not_applied," in src
    assert "metadata->>'code_applied' IS NULL) as apply_unknown," in src
    assert "metadata->>'code_applied' = 'false') as total_not_applied," in src
    # never the inverse form -- `<> 'false'` would sweep unknown into "applied"
    assert "code_applied' <> 'false'" not in src
    assert "code_applied' != 'false'" not in src


def test_migration_474_is_idempotent_and_status_preserving():
    mig = _migration_path()
    if mig is None:
        pytest.skip("database/migrations not reachable from this checkout or mount")
    sql = mig.read_text(encoding="utf-8")
    # re-running must be a no-op: the guard excludes rows that already carry the key
    assert "metadata->>'code_applied' IS NULL" in sql
    # it records the truth WITHOUT relabelling anything -- a status rename is a
    # separate, 21-file change (see #5899); this migration must never attempt it.
    assert not re.search(r"SET\s+status\s*=", sql, re.I)
    assert '"code_applied": false' in sql
