"""The /echo phrase lists, windows and bucket arithmetic — ONE definition shared by
the page (consumer/echo_data.py) and the job that precomputes the counts
(ingest/echo/phrase_counts.py).

Both sides must agree on WHICH phrases are counted and WHICH buckets make up the
window, or the page would read rows the job never wrote. Keeping them here (stdlib
only, no DB, no Flask) is what lets both import it and lets tests pin the contract.
"""

from __future__ import annotations

import datetime

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


def week_starts(today: datetime.date | None = None, weeks: int = SLOGAN_WINDOW_WEEKS) -> list:
    """The `weeks` Monday dates ending with this week's, oldest -> newest.

    Same arithmetic as echo_data.densify_weekly — the reader and the job must
    enumerate identical buckets."""
    today = today or datetime.date.today()
    this_week = today - datetime.timedelta(days=today.weekday())
    return [this_week - datetime.timedelta(weeks=i) for i in range(weeks - 1, -1, -1)]


def day_starts(today: datetime.date | None = None, days: int = WORD_WINDOW_DAYS) -> list:
    """The `days` dates ending with today, oldest -> newest (matches densify_daily)."""
    today = today or datetime.date.today()
    return [today - datetime.timedelta(days=i) for i in range(days - 1, -1, -1)]


def plan_recompute(window: list, present: set, recompute_last: int = 2) -> list:
    """Which buckets of `window` the job must (re)compute.

    * every bucket not yet stored (first run, a gap, a new phrase), and
    * the newest `recompute_last` buckets even when stored, because the newest
      bucket is still filling and the one before it can still receive late articles.

    An old, already-stored bucket is never recomputed: that is what keeps the
    steady-state run to seconds instead of the ~30s a full pass costs.
    """
    wanted = [b for b in window if b not in present]
    newest = window[-recompute_last:] if recompute_last > 0 else []
    return sorted(set(wanted) | set(newest))
