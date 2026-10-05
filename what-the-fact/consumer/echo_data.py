"""Real phrase- and word-frequency data for /echo.

Counts are PRECOMPUTED. ingest/echo/phrase_counts.py runs the full-text phrase queries
(`phraseto_tsquery` over `wtf.articles`' `idx_articles_fts` expression — it drops English
stopwords and matches adjacent lexemes, a reasonable approximation of "this phrase, as
written") once a day and stores the result in `wtf.echo_phrase_counts` (migration 089).
This module only READS that table. It used to run the 14 queries per request, which
measured ~42 s on Citadel (2026-10-05) and held a gunicorn worker the whole time.

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

# The phrase lists and windows live in shared/echo_phrases.py so the page and the job
# that precomputes the counts cannot disagree about them. Re-exported here because the
# page, its tests and the template wiring refer to echo_data.SLOGANS / WORDS / windows.
from shared.echo_phrases import (  # noqa: E402,F401
    SLOGANS,
    SLOGAN_WINDOW_WEEKS,
    WORDS,
    WORD_WINDOW_DAYS,
    day_starts,
    week_starts,
)


def fetch_weekly_counts(conn, schema: str, phrase: str, weeks: int = SLOGAN_WINDOW_WEEKS,
                        end: datetime.date | None = None) -> dict:
    """Stored per-ISO-week counts for `phrase`, over the `weeks` weeks ending at `end`."""
    since = week_starts(end, weeks)[0]
    rows = conn.execute(
        text(
            f"""
            SELECT bucket_start AS wk, n
            FROM {schema}.echo_phrase_counts
            WHERE kind = 'slogan' AND phrase = :phrase AND bucket_start >= :since
            ORDER BY 1
            """
        ),
        {"phrase": phrase, "since": since},
    ).mappings().all()
    return {r["wk"]: r["n"] for r in rows}


def fetch_daily_counts(conn, schema: str, phrase: str, days: int = WORD_WINDOW_DAYS,
                       end: datetime.date | None = None) -> dict:
    """Stored per-day counts for `phrase`, over the `days` days ending at `end`."""
    since = day_starts(end, days)[0]
    rows = conn.execute(
        text(
            f"""
            SELECT bucket_start AS d, n
            FROM {schema}.echo_phrase_counts
            WHERE kind = 'word' AND phrase = :phrase AND bucket_start >= :since
            ORDER BY 1
            """
        ),
        {"phrase": phrase, "since": since},
    ).mappings().all()
    return {r["d"]: r["n"] for r in rows}


def counts_status(conn, schema: str, today: datetime.date | None = None) -> dict:
    """Is the precomputed table complete enough to render? Never raises.

    -> {"ready": bool, "as_of": datetime|None, "slogan_end": date|None, "word_end": date|None}

    Each window is anchored on the NEWEST bucket the job has computed for every phrase —
    not on today — so the page keeps showing the last complete data, labelled with its
    date, instead of flipping to "not ready" for the stretch between a UTC midnight and
    the daily run. It is `ready` only when EVERY phrase has EVERY bucket of its window.
    Anything less (table absent because migration 089 is not applied, first run still
    backfilling, a gap) is NOT ready: an unfilled table must never render as zeros.
    """
    today = today or datetime.date.today()
    floor = today - datetime.timedelta(days=SLOGAN_WINDOW_WEEKS * 7 + 28)
    try:
        rows = conn.execute(
            text(
                f"""
                SELECT kind, phrase, bucket_start, computed_at
                FROM {schema}.echo_phrase_counts
                WHERE bucket_start >= :floor
                """
            ),
            {"floor": floor},
        ).mappings().all()
    except Exception:  # noqa: BLE001 — a missing table is a "not ready" state, not a 500
        return {"ready": False, "as_of": None, "slogan_end": None, "word_end": None}

    have: dict = {}
    stamped: dict = {}
    for r in rows:
        key = (r["kind"], r["phrase"])
        have.setdefault(key, set()).add(r["bucket_start"])
        if r.get("computed_at") is not None:
            stamped[key] = max(stamped.get(key, r["computed_at"]), r["computed_at"])

    def _anchor(kind, phrases):
        sets = [have.get((kind, p), set()) for p in phrases]
        common = set.intersection(*sets) if sets else set()
        return max(common) if common else None

    s_phr = [p for p, _w, _c in SLOGANS]
    w_phr = [p for _l, p, _c in WORDS]
    slogan_end, word_end = _anchor("slogan", s_phr), _anchor("word", w_phr)
    if slogan_end is None or word_end is None:
        return {"ready": False, "as_of": None, "slogan_end": slogan_end, "word_end": word_end}
    s_ok = all(set(week_starts(slogan_end)) <= have.get(("slogan", p), set()) for p in s_phr)
    w_ok = all(set(day_starts(word_end)) <= have.get(("word", p), set()) for p in w_phr)
    stamps = [stamped[("slogan", p)] for p in s_phr if ("slogan", p) in stamped] + \
             [stamped[("word", p)] for p in w_phr if ("word", p) in stamped]
    return {"ready": bool(s_ok and w_ok), "as_of": min(stamps) if stamps else None,
            "slogan_end": slogan_end, "word_end": word_end}


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


def build_slogan_rows(conn, schema: str, end: datetime.date | None = None) -> list:
    """One row per SLOGANS entry, all counts real. Zero-use slogans included
    (so the table is honest about a phrase that's gone quiet), never hidden."""
    rows = []
    for phrase, who, colour in SLOGANS:
        weekly = densify_weekly(fetch_weekly_counts(conn, schema, phrase, end=end), today=end)
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


def build_word_rows(conn, schema: str, end: datetime.date | None = None) -> list:
    rows = []
    for label, phrase, colour in WORDS:
        daily = densify_daily(fetch_daily_counts(conn, schema, phrase, end=end), today=end)
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
