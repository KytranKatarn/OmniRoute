"""Dashboard quick-review must not resurface OLDER generations after the newest image is approved."""

import pathlib

SRC = (
    pathlib.Path(__file__).resolve().parents[1] / "tools" / "media_studio" / "services" / "generation_service.py"
).read_text()


def _pending_query():
    start = SRC.index("WITH candidates AS (")
    return SRC[start : SRC.index("LIMIT 5", start)]


def test_candidates_must_be_newer_than_the_approved_canonical():
    q = _pending_query()
    assert q.count("cm.created_at >= ml.created_at") == 1
    assert "ap2.approved = true" in q


def test_existing_exact_match_exclusion_is_kept():
    q = _pending_query()
    assert "approved.approved = true" in q and "approval_dismissed" in q
