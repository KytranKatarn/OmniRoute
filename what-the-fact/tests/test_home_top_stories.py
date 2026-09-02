"""Guard: the homepage TOP STORIES selection (#6149 Design phase 3).

Pure imports — no DB, no network, no app context, so this cannot silently SKIP.
The DB-backed branch is exercised by passing `is_sub=True` (which never queries)
and by forcing the query to raise; the ranking SQL itself is verified live.

🔴 THE LOAD-BEARING TEST IS test_a_signed_in_reader_sees_EXACTLY_what_shipped_before.

This is the highest-traffic page on the site. The change is scoped to signed-out
readers, so the signed-in path must be byte-identical to the previous behaviour
(`articles[:5]`, recency). If that regresses, a paying reader's front page
silently reorders — the failure would look like an editorial decision rather
than a bug.

⚠️ SCOPE, because the spec and the site disagree: Design's Phase 3 says "the
homepage feed's eight free cards are selected for spread". THIS SITE HAS NO SUCH
FEED — the main feed renders client-side into #wtf-feed-articles and
`is_subscriber` gates an upsell box, not a card count. The only server-rendered
story selection a signed-out reader sees is the 5-item sidebar, so that is what
the correction maps onto. Owner-confirmed 2026-09-02.
"""
from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

ROUTES_PY = ROOT / "consumer" / "routes.py"
INDEX_HTML = ROOT / "consumer" / "templates" / "index.html"

from consumer import routes as R  # noqa: E402


def _rows(n=12):
    return [{"id": i, "title": f"story {i}", "published_at": None} for i in range(n)]


# ────────────────── 🔴 the signed-in path must not move at all

def test_a_signed_in_reader_sees_EXACTLY_what_shipped_before():
    rows = _rows()
    assert R._home_top_stories(rows, is_sub=True) == rows[:5]


def test_the_signed_in_path_does_not_touch_the_database():
    """Byte-identical is not enough — it must also cost nothing. If this path
    ever issues a query, the busiest page on the site gains a round trip."""
    called = []
    orig = R._db
    R._db = lambda *a, **k: called.append(1) or (_ for _ in ()).throw(AssertionError("queried"))
    try:
        R._home_top_stories(_rows(), is_sub=True)
    finally:
        R._db = orig
    assert not called


# ─────────────────────────── failure must degrade to the old behaviour

def test_a_query_failure_falls_back_to_recency_and_never_raises():
    """The front page must render even if the spread query breaks. A homepage
    500 to every signed-out visitor is far worse than an unranked sidebar."""
    rows = _rows()
    orig = R._db

    def boom(*a, **k):
        raise RuntimeError("db down")

    R._db = boom
    try:
        out = R._home_top_stories(rows, is_sub=False)
    finally:
        R._db = orig
    assert out == rows[:5]


def test_an_empty_article_list_is_survivable():
    assert R._home_top_stories([], is_sub=True) == []


# ─────────────────────────────────────── sizing + top-up guarantees

def test_the_list_is_never_short_when_recency_can_fill_it():
    """A quiet news day yields few spread stories; the sidebar must still show
    five. Verified through the fallback path (no DB)."""
    rows = _rows(9)
    orig = R._db
    R._db = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("no db"))
    try:
        out = R._home_top_stories(rows, is_sub=False)
    finally:
        R._db = orig
    assert len(out) == R._HOME_TOP_N == 5


def test_constants_match_what_was_measured():
    """48h was chosen because 36 clusters there carry spread vs 13 at 24h.
    Shrinking the window without re-measuring would quietly starve the ranking."""
    assert R._HOME_TOP_N == 5
    assert R._HOME_SPREAD_HOURS == 48


# ────────────────────────────────────── the ranking is real, not decorative

def test_the_query_ranks_by_spread_and_excludes_flat_clusters():
    src = ROUTES_PY.read_text()
    fn = src[src.index("def _home_top_stories("):src.index("_ARCHIVE_WINDOWS =")]
    assert "ORDER BY spread DESC" in fn, "must rank by spread"
    assert "WHERE spread > 0" in fn, "a cluster with no spread is not a spread story"
    assert "suppressed_reason IS NULL" in fn, "suppressed rows must stay excluded"
    assert "_BAND_ORD_SQL" in fn, "must reuse the one shared band scale"


def test_the_future_dated_guard_is_preserved():
    """The homepage already guards against a source emitting a wildly-future
    published_at (the 2026-07-14 front-page freeze). The new query must carry
    the same guard or it reintroduces that bug on the sidebar."""
    src = ROUTES_PY.read_text()
    fn = src[src.index("def _home_top_stories("):src.index("_ARCHIVE_WINDOWS =")]
    assert "INTERVAL '2 hours'" in fn


# ──────────────────────────────────────────── template wiring + honesty

def test_the_template_renders_top_stories_not_a_raw_slice():
    body = INDEX_HTML.read_text()
    assert "{% for a in top_stories %}" in body
    assert "articles[:5]" not in body, "the raw recency slice must be gone"


def test_no_ui_copy_overstates_the_spread():
    """MEASURED 2026-09-02: zero clusters in 48h span 3+ bands, so 'widest
    spread' here is a one- or two-band difference. Copy claiming dramatic
    divergence would not be supported by the data."""
    body = INDEX_HTML.read_text().lower()
    for oversell in ("extreme divergence", "wildly different", "polar opposite"):
        assert oversell not in body
