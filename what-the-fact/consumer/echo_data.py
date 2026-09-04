"""Real phrase- and word-frequency data for /echo.

Backed entirely by `wtf.articles`' existing full-text-search index
(`idx_articles_fts`, a GIN index over `to_tsvector('english', title || ' ' || body)`)
— no new ingest pipeline. `phraseto_tsquery` drops English stopwords and matches
adjacent lexemes, which is a reasonable approximation of "this phrase, as written"
without needing a second exact-substring index.

Deliberately dropped vs. the design-handoff mockup (wtf-echo.html):
  - "Pickup" (outlet-vs-speaker share) — no primary-source distinction exists in
    the ingested data to support it.
  - "Who posts most" (social posting cadence by channel) — no data source.
  - "Fed by the Watch series" cross-links — implies live integration that
    doesn't exist yet for this page.
  - Numeric "days ago" claims beyond the query window — we can only honestly
    report the earliest match WITHIN the window we searched, not "first ever".

SLOGANS' `associated_with` is an editorial label (which public figure/campaign
the phrase is commonly attributed to), not something derived from a query —
same convention as party names/colours elsewhere on the site. The counts next
to it are always real, queried numbers.
"""

from __future__ import annotations

import datetime

from sqlalchemy import text

# (phrase, associated_with, colour) — colour reused from the design mockup's
# real party/leader palette (not invented). Candidates without meaningful
# 90-day volume (< 20 mentions) were dropped after checking live counts —
# e.g. "Axe the tax" (1 mention — the carbon tax it targeted was repealed) and
# "Build, baby, build" (3 mentions) are real slogans but too thin to chart.
SLOGANS = [
    ("Elbows up", "Mark Carney / Canada", "#d71920"),
    ("Made in Canada", "multiple", "#929aa5"),
    ("Team Canada", "multiple", "#929aa5"),
    ("Nation building", "Mark Carney", "#d71920"),
    ("Get it done", "Doug Ford", "#1a4782"),
    ("Canada Strong", "Mark Carney", "#d71920"),
    ("Bring it home", "Pierre Poilievre", "#1a4782"),
    ("Alberta first", "Danielle Smith", "#1a4782"),
]

# (label, tsquery phrase, colour)
WORDS = [
    ("Trump", "trump", "#e5484d"),
    ("Tariffs", "tariffs", "#f5a623"),
    ("Affordability", "affordability", "#3d9b35"),
    ("Carbon tax", "carbon tax", "#929aa5"),
    ("Carney", "carney", "#d71920"),
    ("Poilievre", "poilievre", "#1a4782"),
]

SLOGAN_WINDOW_WEEKS = 13
WORD_WINDOW_DAYS = 30


def _fts_match_clause() -> str:
    return (
        "to_tsvector('english', coalesce(title,'') || ' ' || coalesce(body,'')) "
        "@@ phraseto_tsquery('english', :phrase)"
    )


def fetch_weekly_counts(conn, schema: str, phrase: str, weeks: int = SLOGAN_WINDOW_WEEKS) -> dict:
    """Real per-ISO-week match counts for `phrase`, over the last `weeks` weeks."""
    rows = conn.execute(
        text(
            f"""
            SELECT date_trunc('week', published_at)::date AS wk, COUNT(*) AS n
            FROM {schema}.articles
            WHERE published_at >= now() - (:weeks || ' weeks')::interval
              AND suppressed_reason IS NULL
              AND {_fts_match_clause()}
            GROUP BY 1
            ORDER BY 1
            """
        ),
        {"phrase": phrase, "weeks": weeks},
    ).mappings().all()
    return {r["wk"]: r["n"] for r in rows}


def fetch_daily_counts(conn, schema: str, phrase: str, days: int = WORD_WINDOW_DAYS) -> dict:
    """Real per-day match counts for `phrase`, over the last `days` days."""
    rows = conn.execute(
        text(
            f"""
            SELECT date_trunc('day', published_at)::date AS d, COUNT(*) AS n
            FROM {schema}.articles
            WHERE published_at >= now() - (:days || ' days')::interval
              AND suppressed_reason IS NULL
              AND {_fts_match_clause()}
            GROUP BY 1
            ORDER BY 1
            """
        ),
        {"phrase": phrase, "days": days},
    ).mappings().all()
    return {r["d"]: r["n"] for r in rows}


def densify_weekly(counts_by_week: dict, weeks: int = SLOGAN_WINDOW_WEEKS, today: datetime.date | None = None) -> list:
    """Zero-filled weekly series, oldest -> newest, length == `weeks`.

    Pure — takes the sparse DB result and `today` (injectable for tests,
    since datetime.date.today() is otherwise untestable without freezing
    the clock), never touches the DB itself.
    """
    today = today or datetime.date.today()
    this_week_start = today - datetime.timedelta(days=today.weekday())
    series = []
    for i in range(weeks - 1, -1, -1):
        wk = this_week_start - datetime.timedelta(weeks=i)
        series.append(int(counts_by_week.get(wk, 0)))
    return series


def densify_daily(counts_by_day: dict, days: int = WORD_WINDOW_DAYS, today: datetime.date | None = None) -> list:
    """Zero-filled daily series, oldest -> newest, length == `days`."""
    today = today or datetime.date.today()
    series = []
    for i in range(days - 1, -1, -1):
        d = today - datetime.timedelta(days=i)
        series.append(int(counts_by_day.get(d, 0)))
    return series


def trend_change(series: list) -> float | None:
    """(recent_quarter_sum - prior_quarter_sum) / prior_quarter_sum, or None
    when prior is 0 (a ratio against zero is undefined, not "0% change").

    Single source of truth for both classify_trend() and any caller that
    wants to RANK trends against each other (e.g. "which slogan is fading
    fastest"), rather than just bucket them into a label.
    """
    n = len(series)
    if n < 4:
        return None
    q = max(1, n // 4)
    recent = sum(series[-q:])
    prior = sum(series[-2 * q:-q])
    if prior == 0:
        return None
    return (recent - prior) / prior


def classify_trend(series: list) -> str:
    """rising / fading / steady / quiet — from a dense series, oldest->newest.

    Compares the sum of the most-recent quarter of the series against the
    sum of the quarter immediately before it (a full week's noise on either
    side washes out with a single-point compare; this doesn't).
    """
    n = len(series)
    if n < 4:
        return "steady"
    q = max(1, n // 4)
    recent = sum(series[-q:])
    prior = sum(series[-2 * q:-q])
    if recent == 0 and prior == 0:
        return "quiet"
    change = trend_change(series)
    if change is None:
        return "rising"  # prior was 0, recent isn't — can't ratio, but it's new activity
    if change > 0.15:
        return "rising"
    if change < -0.15:
        return "fading"
    return "steady"


def first_seen_in_window(series: list, weeks: int = SLOGAN_WINDOW_WEEKS) -> int:
    """How many weeks ago the first non-zero bucket in this window sits.

    Returns `weeks` (the window edge) if every bucket is zero — i.e. "we
    never saw it in this window", not "it started today". Index 0 of the
    series is the oldest bucket.
    """
    for i, v in enumerate(series):
        if v > 0:
            return len(series) - 1 - i
    return weeks


def build_slogan_rows(conn, schema: str) -> list:
    """One row per SLOGANS entry, all counts real. Zero-use slogans included
    (so the table is honest about a phrase that's gone quiet), never hidden."""
    rows = []
    for phrase, who, colour in SLOGANS:
        weekly = densify_weekly(fetch_weekly_counts(conn, schema, phrase))
        rows.append(
            {
                "phrase": phrase,
                "who": who,
                "colour": colour,
                "weekly": weekly,
                "uses": sum(weekly),
                "trend": classify_trend(weekly),
                "trend_pct": trend_change(weekly),
                "weeks_since_first_seen": first_seen_in_window(weekly),
            }
        )
    return rows


def build_word_rows(conn, schema: str) -> list:
    rows = []
    for label, phrase, colour in WORDS:
        daily = densify_daily(fetch_daily_counts(conn, schema, phrase))
        rows.append(
            {
                "label": label,
                "colour": colour,
                "daily": daily,
                "total": sum(daily),
                "today": daily[-1] if daily else 0,
                "trend": classify_trend(daily),
            }
        )
    return rows
