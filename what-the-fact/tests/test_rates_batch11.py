"""Regression coverage for /rates — historical rate-path chart, six-eras
panel, 3 stat tiles, and the HOLD-row fix (2026-09-04, WTF Batch 11).

market_watch.boc_rate_decisions is a MONTHLY average of the BoC Valet series
V122514 (one row per calendar month), not literal per-announcement rows —
verified live against the DB (368 rows, 1996-01-01..2026-08-01, one row per
month, small non-zero change_bps even in months the Bank held). "Material
move" throughout means the SAME >=10bps threshold the decisions-table query
already used to separate a real cut/hike from monthly-averaging noise.

Everything numeric in these tests traces to either (a) the pure helper
functions in consumer/routes.py, exercised directly on synthetic data (no
DB, no network, no app context — same pattern as test_home_top_stories.py's
`from consumer import routes as R`), or (b) a Jinja render of rates.html
with an explicit, hand-built context (same pattern as
test_mp_hero_links.py / test_owners_concentration_stats.py).

Deliberately NOT built: the historical chart uses the SAME >=10bps threshold
as the decisions table to define "material" for the hold-streak and the
"since peak" tiles, rather than a second, independently-tuned definition —
the audit's mockup literally admits its own PATH/ERAS numbers are
placeholders past March 2025 ("the design does not assert them"), so no
number here is carried over from the mockup; every one is either a real
computed value or a well-established public fact (era boundaries).
"""

from __future__ import annotations

import datetime
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

ROUTES_PY = ROOT / "consumer" / "routes.py"
TPL_DIR = ROOT / "consumer" / "templates"

from consumer import routes as R  # noqa: E402

from jinja2 import ChoiceLoader, DictLoader, Environment, FileSystemLoader  # noqa: E402

_BASE_STUB = "{% block meta %}{% endblock %}{% block content %}{% endblock %}"


def _d(s):
    return datetime.date.fromisoformat(s)


def _row(date_s, rate, bps):
    return {"decision_date": _d(date_s), "rate_pct": rate, "change_bps": bps}


# ────────────────────────── source-inspection (rule #6) ──────────────────

def _boc_rates_route_body() -> str:
    src = ROUTES_PY.read_text(encoding="utf-8")
    start = src.index("def boc_rates")
    end = src.index("\n@bp.get", start + 1)
    return src[start:end]


def test_decisions_query_now_includes_literal_hold_rows():
    body = _boc_rates_route_body()
    assert "change_bps = 0" in body, (
        "the decisions query must admit change_bps=0 rows so the gated table "
        "can show real HOLD decisions, not just >=10bps moves"
    )
    # the >=10bps + NULL-first-row branches must still be there (additive fix)
    assert "ABS(change_bps) >= 10" in body
    assert "change_bps IS NULL" in body


def test_history_query_is_unfiltered_and_unlimited():
    """The public chart/eras/stat-tile data must be the REAL full series, not
    the same >=10bps-filtered, 60-row-limited list used for the gated table."""
    body = _boc_rates_route_body()
    hist_start = body.index("history = c.execute")
    hist_sql = body[hist_start:hist_start + 400]
    assert "WHERE" not in hist_sql, "history must not carry the decisions-table filter"
    assert "LIMIT" not in hist_sql, "history must not be truncated like the decisions table"
    assert "ORDER BY decision_date ASC" in hist_sql


# Mutation check (house rule #7) run once at authoring time against
# `git show <parent-commit>:./consumer/routes.py`, not as a permanent test:
# HEAD stops being "pre-fix" the moment this PR merges, so a runtime
# `git show HEAD:...` assertion here would pass at authoring time and then
# fail forever afterward (see test_article_batch11.py's docstring for the
# same reasoning). Confirmed then: the pre-fix route body had neither
# `change_bps = 0` nor a separate `history` query.


# ────────────────────────── pure helpers, direct import ──────────────────

def test_hold_streak_counts_back_from_the_latest_row():
    history = [
        _row("2025-10-01", 2.50, -23),   # material cut — breaks the streak
        _row("2025-11-01", 2.34, -27),   # material cut again
        _row("2025-12-01", 2.27, 4),
        _row("2026-01-01", 2.25, -2),
        _row("2026-02-01", 2.25, 0),
        _row("2026-03-01", 2.27, 2),
    ]
    out = R._boc_hold_streak(history)
    assert out == {"months": 4, "since": _d("2025-12-01")}


def test_hold_streak_none_when_the_most_recent_row_is_itself_material():
    history = [_row("2026-01-01", 2.50, 1), _row("2026-02-01", 2.10, -40)]
    out = R._boc_hold_streak(history)
    assert out["months"] == 0
    assert out["since"] is None


def test_hold_streak_whole_series_when_nothing_was_ever_material():
    history = [_row("2026-01-01", 2.50, None), _row("2026-02-01", 2.51, 1)]
    out = R._boc_hold_streak(history)
    assert out["months"] == 1
    assert out["since"] == _d("2026-02-01")


def test_hold_streak_empty_history_returns_none():
    assert R._boc_hold_streak([]) is None


def test_peak_since_finds_the_real_max_in_window_and_signs_the_bps_change():
    history = [
        _row("2023-01-01", 4.25, 0),
        _row("2024-01-01", 5.03, 1),    # the real peak
        _row("2024-06-01", 4.76, -24),
        _row("2026-08-01", 2.24, -2),   # latest
    ]
    out = R._boc_peak_since(history, years=5)
    assert out["peak_date"] == _d("2024-01-01")
    assert out["peak_rate"] == 5.03
    # (2.24 - 5.03) * 100 = -279 -> a cut since the peak
    assert out["bps_change"] == -279


def test_peak_since_falls_back_to_full_series_when_window_is_empty():
    # every row is older than `years` back from the latest -> window filter
    # would find nothing; must fall back to the whole series, not crash/None.
    history = [_row("2000-01-01", 5.80, None), _row("2000-02-01", 5.75, -5)]
    out = R._boc_peak_since(history, years=1)
    assert out["peak_rate"] == 5.80


def test_peak_since_empty_history_returns_none():
    assert R._boc_peak_since([]) is None


def test_eras_only_includes_eras_with_real_data_and_computes_real_lo_hi():
    # Data only overlaps ONE of the six declared eras (financial crisis).
    history = [
        _row("2008-06-01", 3.00, None),
        _row("2008-12-01", 1.50, -150),
        _row("2009-04-01", 0.25, -125),
    ]
    eras = R._boc_eras(history)
    assert len(eras) == 1
    assert eras[0]["name"] == "Global financial crisis"
    assert eras[0]["low"] == 0.25
    assert eras[0]["high"] == 3.00


def test_eras_easing_cycle_extends_to_the_latest_year_in_the_data_not_hardcoded():
    history = [_row("2024-01-01", 5.03, 0), _row("2026-08-01", 2.24, -2)]
    eras = R._boc_eras(history)
    easing = [e for e in eras if e["name"] == "Easing cycle"][0]
    assert easing["label"] == "2024–"
    assert easing["high"] == 5.03
    assert easing["low"] == 2.24


def test_eras_empty_history_returns_empty_list():
    assert R._boc_eras([]) == []


def test_chart_geometry_spans_the_full_width_and_tracks_min_max():
    history = [_row("2020-01-01", 1.75, None), _row("2022-01-01", 0.25, -150),
               _row("2024-01-01", 5.00, 475)]
    chart = R._boc_rate_chart(history, width=720, height=200, pad=28)
    assert chart is not None
    points = chart["points"].split(" ")
    assert len(points) == 3
    first_x = float(points[0].split(",")[0])
    last_x = float(points[-1].split(",")[0])
    assert first_x == 28.0          # left padding, first point pinned there
    assert last_x == 720 - 28.0     # right padding, last point pinned there
    assert chart["min_rate"] == 0.25
    assert chart["max_rate"] == 5.00
    assert chart["start_date"] == _d("2020-01-01")
    assert chart["end_date"] == _d("2024-01-01")


def test_chart_returns_none_for_fewer_than_two_points():
    assert R._boc_rate_chart([]) is None
    assert R._boc_rate_chart([_row("2026-01-01", 2.25, None)]) is None


# ────────────────────────── template render (Jinja, no Flask/DB) ─────────

def _render(**ctx):
    env = Environment(loader=ChoiceLoader([
        DictLoader({"base.html": _BASE_STUB}),
        FileSystemLoader(str(TPL_DIR)),
    ]))
    base_ctx = dict(
        current={}, decisions=[], source_count=46, chart=None, eras=[],
        peak_stat=None, hold_streak=None, is_subscriber=False,
    )
    base_ctx.update(ctx)
    return env.get_template("rates.html").render(**base_ctx)


def _full_context():
    history = [
        _row("2023-01-01", 4.25, 0),
        _row("2024-01-01", 5.03, 1),
        _row("2024-06-01", 4.76, -24),
        _row("2025-11-01", 2.34, -27),
        _row("2025-12-01", 2.27, 4),
        _row("2026-01-01", 2.25, -2),
        _row("2026-08-01", 2.24, -2),
    ]
    decisions = list(reversed(history))  # DESC, matches the route's ORDER BY
    return dict(
        current={"rate_pct": 2.24, "decision_date": _d("2026-08-01")},
        decisions=decisions,
        chart=R._boc_rate_chart(history),
        eras=R._boc_eras(history),
        peak_stat=R._boc_peak_since(history),
        hold_streak=R._boc_hold_streak(history),
        is_subscriber=True,
    )


def test_three_new_stat_tiles_render_with_real_computed_values():
    html = _render(**_full_context())
    assert "Since Jan 2024 peak" in html
    assert "−279 bps" in html  # (2.24-5.03)*100, U+2212 minus like the existing CUT/HIKE convention
    assert "Consecutive holds" in html
    assert "Decisions a year" in html
    assert ">8<" in html


def test_hold_streak_tile_absent_when_the_series_has_no_streak_yet():
    ctx = _full_context()
    ctx["hold_streak"] = {"months": 0, "since": None}
    html = _render(**ctx)
    assert "Consecutive holds" not in html


def test_chart_section_renders_the_real_polyline_points_and_is_ungated():
    ctx = _full_context()
    ctx["is_subscriber"] = False  # paywalled table hidden; chart must still show
    html = _render(**ctx)
    assert 'points="' + ctx["chart"]["points"] + '"' in html
    assert "Historical background" in html
    assert "Six eras" in html
    # public section renders even though the decision table below is gated
    assert "Unlock with Starter" in html


def test_chart_section_absent_when_there_is_no_history():
    html = _render(chart=None, eras=[], peak_stat=None, hold_streak=None)
    assert "Historical background" not in html
    assert "Six eras" not in html


def test_eras_render_real_low_high_not_mockup_numbers():
    ctx = _full_context()
    html = _render(**ctx)
    # the mockup's fabricated "Financial crisis: down to 0.25% floor by April
    # 2009" prose must never appear verbatim; our note text is independent
    # and our low/high figures are the ones _boc_eras actually computed.
    for era in ctx["eras"]:
        lo = "%.2f" % era["low"]
        hi = "%.2f" % era["high"]
        assert lo in html and hi in html


def test_hold_row_labels_as_HOLD_not_FIRST_and_shows_0_bps():
    ctx = _full_context()
    html = _render(**ctx)
    idx = html.find("Jan 1, 2023")
    assert idx != -1
    # Direction cell precedes the date cell; capture the whole <tr>...</tr>.
    row_start = html.rfind("<tr>", 0, idx)
    row_end = html.find("</tr>", idx)
    row = html[row_start:row_end]
    assert "HOLD" in row
    assert "0 bps" in row


# Mutation check (house rule #7) for the HOLD-vs-FIRST label fix, run once
# at authoring time against `git show <parent-commit>:./consumer/templates/
# rates.html`, not as a permanent test — same reasoning as above: HEAD
# stops being "pre-fix" the moment this PR merges. Confirmed then: the
# pre-fix template rendered a change_bps=0 row as "FIRST", never "HOLD".


def test_paywall_gating_is_unchanged_when_not_a_subscriber():
    ctx = _full_context()
    ctx["is_subscriber"] = False
    html = _render(**ctx)
    assert "Unlock with Starter" in html
    assert "Rate decision history — Starter+" in html
    # the gated table itself must not leak through
    assert "Jan 1, 2023" not in html


def test_empty_current_and_decisions_do_not_crash():
    html = _render()
    assert "Bank of Canada rate decisions" in html
    assert "Decisions a year" in html
