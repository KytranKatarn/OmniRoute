"""/echo — real slogan/word-frequency counts, reduced from the design mockup
(#6272 follow-up, Batch 9 cleanup).

design-handoff/wtf-echo.html has three data blocks: slogans (S, incl. a
"pickup" outlet-vs-speaker share), words (W), and posting cadence by channel
(P) — all three are hardcoded JS consts, none are fetches. Scoping (this
session's final workflow pass) found real ingested data for slogans (via
wtf.articles' FTS index, phrase-matched) and words (same mechanism), but
NOTHING for "pickup" (no primary-source distinction in the data) or posting
cadence (no data source at all — the design itself says so).

This file covers three layers: the pure series math in echo_data.py (no DB),
the template rendering real vs. empty data honestly, and that the dropped
sections never appear anywhere on the page.
"""
from __future__ import annotations

import datetime
import pathlib
import sys

import pytest
from jinja2 import ChoiceLoader, DictLoader, Environment, FileSystemLoader, select_autoescape

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from consumer import echo_data  # noqa: E402

TPL = ROOT / "consumer" / "templates"
ROUTES = ROOT / "consumer" / "routes.py"

_STUB = ("{% block title %}{% endblock %}{% block meta %}{% endblock %}"
         "<body>{% block content %}{% endblock %}</body>")


# ---------------------------------------------------------------------------
# Pure series math — no DB, no fixtures
# ---------------------------------------------------------------------------

class TestDensify:
    def test_weekly_series_has_the_requested_length_and_aligns_newest_last(self):
        today = datetime.date(2026, 9, 4)  # Friday
        this_monday = today - datetime.timedelta(days=today.weekday())
        sparse = {this_monday: 5, this_monday - datetime.timedelta(weeks=2): 9}
        dense = echo_data.densify_weekly(sparse, weeks=13, today=today)
        assert len(dense) == 13
        assert dense[-1] == 5          # this week, last in the series
        assert dense[-3] == 9          # 2 weeks ago
        assert dense[-2] == 0          # 1 week ago, no data -> zero-filled, not skipped

    def test_daily_series_has_the_requested_length_and_aligns_newest_last(self):
        today = datetime.date(2026, 9, 4)
        sparse = {today: 12, today - datetime.timedelta(days=5): 7}
        dense = echo_data.densify_daily(sparse, days=30, today=today)
        assert len(dense) == 30
        assert dense[-1] == 12
        assert dense[-6] == 7

    def test_empty_input_is_all_zero_not_an_error(self):
        assert echo_data.densify_weekly({}, weeks=13) == [0] * 13
        assert echo_data.densify_daily({}, days=30) == [0] * 30


class TestTrendClassification:
    def test_rising(self):
        series = [1, 1, 1, 1, 1, 1, 1, 1, 2, 3, 5, 8, 13]
        assert echo_data.classify_trend(series) == "rising"
        assert echo_data.trend_change(series) > 0

    def test_fading(self):
        series = [13, 8, 5, 3, 2, 1, 1, 1, 1, 1, 0, 0, 0]
        assert echo_data.classify_trend(series) == "fading"
        assert echo_data.trend_change(series) < 0

    def test_steady(self):
        series = [5] * 13
        assert echo_data.classify_trend(series) == "steady"
        assert echo_data.trend_change(series) == 0

    def test_quiet_is_distinct_from_steady(self):
        """All-zero must not read as 'steady' (implies real, flat activity)."""
        series = [0] * 13
        assert echo_data.classify_trend(series) == "quiet"
        assert echo_data.trend_change(series) is None

    def test_new_activity_from_nothing_is_rising_not_a_zero_division(self):
        # n=13, quarter q=3 -> "prior" is indices [7:10], "recent" is [10:13].
        # Zero the prior quarter exactly so trend_change has nothing to
        # divide by, and confirm the None-prior branch still reads "rising".
        series = [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 3, 6, 9]
        assert echo_data.classify_trend(series) == "rising"
        assert echo_data.trend_change(series) is None  # prior quarter was 0 -> no ratio

    def test_short_series_defaults_to_steady_not_a_crash(self):
        assert echo_data.classify_trend([1, 2]) == "steady"
        assert echo_data.trend_change([1, 2]) is None


class TestFirstSeenInWindow:
    def test_never_seen_returns_the_window_edge(self):
        assert echo_data.first_seen_in_window([0] * 13, weeks=13) == 13

    def test_seen_this_week_returns_zero(self):
        series = [0] * 12 + [4]
        assert echo_data.first_seen_in_window(series) == 0

    def test_seen_at_window_start_returns_the_full_span(self):
        series = [7] + [0] * 12
        assert echo_data.first_seen_in_window(series) == 12


# ---------------------------------------------------------------------------
# build_slogan_rows / build_word_rows against a fake DB connection
# ---------------------------------------------------------------------------

class _FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def mappings(self):
        return self

    def all(self):
        return self._rows


class _FakeConn:
    """Returns canned weekly/daily buckets keyed by the bound `:phrase`
    param, so build_slogan_rows/build_word_rows can be exercised end-to-end
    with zero real DB access."""

    def __init__(self, weekly_by_phrase=None, daily_by_phrase=None):
        self.weekly_by_phrase = weekly_by_phrase or {}
        self.daily_by_phrase = daily_by_phrase or {}
        self.calls: list[str] = []

    def execute(self, stmt, params=None):
        params = params or {}
        phrase = params.get("phrase")
        self.calls.append(phrase)
        sql = str(stmt)
        if "date_trunc('week'" in sql:
            rows = [{"wk": wk, "n": n} for wk, n in self.weekly_by_phrase.get(phrase, {}).items()]
        else:
            rows = [{"d": d, "n": n} for d, n in self.daily_by_phrase.get(phrase, {}).items()]
        return _FakeResult(rows)


class TestBuildSloganRows:
    def test_every_configured_slogan_gets_a_row_even_at_zero(self):
        conn = _FakeConn()  # no data for anything
        rows = echo_data.build_slogan_rows(conn, "wtf")
        assert len(rows) == len(echo_data.SLOGANS)
        assert all(r["uses"] == 0 for r in rows)
        assert all(r["trend"] == "quiet" for r in rows)

    def test_real_weekly_counts_flow_through_to_uses_and_trend(self):
        first_phrase = echo_data.SLOGANS[0][0]
        today = datetime.date(2026, 9, 4)
        this_monday = today - datetime.timedelta(days=today.weekday())
        weekly = {this_monday - datetime.timedelta(weeks=i): 10 for i in range(4)}
        conn = _FakeConn(weekly_by_phrase={first_phrase: weekly})
        rows = echo_data.build_slogan_rows(conn, "wtf")
        row = next(r for r in rows if r["phrase"] == first_phrase)
        assert row["uses"] == 40
        assert len(row["weekly"]) == echo_data.SLOGAN_WINDOW_WEEKS

    def test_no_uses_never_gets_hidden_from_the_table(self):
        """A slogan gone quiet is itself the honest finding — must stay in
        the row set, not be filtered out for having a zero."""
        conn = _FakeConn()
        rows = echo_data.build_slogan_rows(conn, "wtf")
        phrases = {r["phrase"] for r in rows}
        assert phrases == {p for p, _, _ in echo_data.SLOGANS}


class TestBuildWordRows:
    def test_every_configured_word_gets_a_row(self):
        conn = _FakeConn()
        rows = echo_data.build_word_rows(conn, "wtf")
        assert len(rows) == len(echo_data.WORDS)
        assert all(r["total"] == 0 for r in rows)

    def test_todays_bucket_is_the_last_element(self):
        label, phrase, _ = echo_data.WORDS[0]
        today = datetime.date.today()
        conn = _FakeConn(daily_by_phrase={phrase: {today: 99}})
        rows = echo_data.build_word_rows(conn, "wtf")
        row = next(r for r in rows if r["label"] == label)
        assert row["today"] == 99
        assert row["daily"][-1] == 99


# ---------------------------------------------------------------------------
# Template rendering
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def env():
    return Environment(
        loader=ChoiceLoader([DictLoader({"base.html": _STUB}), FileSystemLoader(str(TPL))]),
        autoescape=select_autoescape(["html"]),
    )


def _slogan_row(phrase="Elbows up", who="Mark Carney / Canada", colour="#d71920",
                 uses=42, trend="steady", trend_pct=0.0, weeks_since_first_seen=5):
    return {
        "phrase": phrase, "who": who, "colour": colour,
        "weekly": [1, 2, 3, 4, 5, 4, 3, 2, 1, 2, 3, 4, uses - 30 if uses > 30 else 1],
        "uses": uses, "trend": trend, "trend_pct": trend_pct,
        "weeks_since_first_seen": weeks_since_first_seen,
    }


def _word_row(label="Trump", colour="#e5484d", total=500, today=20, trend="steady"):
    return {"label": label, "colour": colour, "daily": [10] * 29 + [today], "total": total, "today": today, "trend": trend}


def _render(env, slogans=None, words=None, most_used=None, fading=None, total_uses=0,
            window_weeks=13, word_window_days=30, **overrides):
    kwargs = dict(
        slogans=slogans if slogans is not None else [_slogan_row()],
        words=words if words is not None else [_word_row()],
        most_used=most_used, fading=fading, total_uses=total_uses,
        window_weeks=window_weeks, word_window_days=word_window_days,
        is_subscriber=False,
    )
    kwargs.update(overrides)
    return env.get_template("echo.html").render(**kwargs)


def _body(html):
    return html.split("</style>", 1)[1]


class TestRealDataRenders:
    def test_slogan_and_word_labels_appear(self, env):
        b = _body(_render(env))
        assert "Elbows up" in b
        assert "Trump" in b

    def test_window_sizes_are_stated(self, env):
        b = _body(_render(env, window_weeks=13, word_window_days=30))
        assert "13" in b
        assert "30" in b


class TestEmptyDataIsHonestNotBroken:
    def test_no_slogans_shows_an_empty_state_not_a_crash(self, env):
        b = _body(_render(env, slogans=[]))
        assert "No slogan data available" in b

    def test_no_words_shows_an_empty_state_not_a_crash(self, env):
        b = _body(_render(env, words=[]))
        assert "No word-frequency data available" in b

    def test_no_most_used_or_fading_stat_boxes_render_without_data(self, env):
        b = _body(_render(env, most_used=None, fading=None))
        assert "Most repeated" not in b
        assert "Fading fastest" not in b


class TestDroppedSectionsNeverAppear:
    """These three concepts exist ONLY in the design mockup and must never
    reach the live page — checked against the post-<style> body so a
    template comment explaining WHY they're dropped can't false-positive
    the assertion (the CSS-comment trap that hit /governance and /mps)."""

    @pytest.mark.parametrize("dropped_phrase", [
        "Pickup", "pickup",
        "Who posts most", "posts per week",
        "Fed by the Watch series",
    ])
    def test_dropped_concept_absent_from_rendered_body(self, env, dropped_phrase):
        b = _body(_render(env))
        assert dropped_phrase not in b


# ---------------------------------------------------------------------------
# Route wiring
# ---------------------------------------------------------------------------

class TestRouteWiring:
    def test_echo_removed_from_coming_soon(self):
        src = ROUTES.read_text(encoding="utf-8")
        coming_soon_start = src.index("_COMING_SOON = {")
        # _register_coming_soon is defined well after the dict literal closes
        end = src.index("_register_coming_soon", coming_soon_start)
        block = src[coming_soon_start:end]
        assert '"echo": (' not in block

    def test_echo_route_exists_and_calls_the_pure_data_module(self):
        src = ROUTES.read_text(encoding="utf-8")
        start = src.index('@bp.get("/echo")')
        end = src.index("\n\n\n", start)
        body = src[start:end]
        assert "def echo():" in body
        assert "_echo_data.build_slogan_rows" in body
        assert "_echo_data.build_word_rows" in body
        assert 'render_template(\n        "echo.html"' in body or 'render_template("echo.html"' in body

    def test_fading_selection_ranks_by_real_trend_pct_not_a_dummy_key(self):
        """Regression: the first draft's `fading` pick used a key that could
        never distinguish one fading slogan from another (always -1 for any
        fading row), so it silently returned list-order rather than the
        actually-fastest-fading slogan."""
        src = ROUTES.read_text(encoding="utf-8")
        start = src.index('@bp.get("/echo")')
        end = src.index("\n\n\n", start)
        body = src[start:end]
        assert 'key=lambda r: r["trend_pct"]' in body
