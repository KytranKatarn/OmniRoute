"""A.U.R.O.R.A. forecast verification — pure, DB-free shaping logic.

Deliberately stdlib-only and free of any DB or Flask import, for the same
reason `aurora_map` and `citypage_parse` are: a guard test that cannot import
its subject SKIPS silently, and a silently-skipped test is worse than none
(KB #290497). routes.py does the SQL and hands the rows in here.

WHAT IS BEING MEASURED
----------------------
Every daily-high forecast we publish is stored with the moment it was issued.
When the target day is over we take the highest temperature the station
actually recorded and compare the two.

  bias  = mean(forecast - observed)   signed; negative means the forecast
                                      UNDER-called the high (ran cold)
  mae   = mean(|forecast - observed|) unsigned; how far off, either way

Both are reported because they answer different questions: mae is "how much
should I trust this number", bias is "is it wrong in a fixable direction".
A large mae with near-zero bias is noise; a small mae with a steady bias is a
correctable systematic error. Reporting only one of them hides half the story.

WHAT THIS IS NOT
----------------
These are OUR measurements over OUR observation window, not a claim published
by any forecaster and not a climate baseline. Callers must render the window
alongside the figures — `summarise()` returns it for exactly that reason.
"""

from __future__ import annotations

# Below this many verified pairs a cell is reported but flagged thin, rather
# than silently rendered with the same confidence as a well-sampled one.
MIN_PAIRS_FOR_CONFIDENCE = 30

# A signed bias smaller than this is not meaningfully directional at our
# sample sizes; it renders as "even" rather than cold/warm.
BIAS_NEUTRAL_BAND_C = 0.25


def _round(value, places=2):
    """None-safe round. A missing value stays missing rather than becoming 0."""
    if value is None:
        return None
    return round(float(value), places)


def bias_direction(bias_c):
    """'cold' | 'warm' | 'even' | None — the WORD, so colour is never alone.

    A lean colour without its label is the one thing the design rules forbid,
    and that rule exists because colour is not readable to every reader.
    """
    if bias_c is None:
        return None
    if abs(bias_c) < BIAS_NEUTRAL_BAND_C:
        return "even"
    return "cold" if bias_c < 0 else "warm"


def _aggregate(pairs):
    """(n, bias, mae) over an iterable of (forecast_c, observed_c) tuples.

    Pairs carrying a None on either side are skipped: a missing observation is
    not a zero error. Returns (0, None, None) rather than raising on empty, so
    a city with no verifiable days yet is a gap in the table, not a 500.
    """
    usable = [
        (f, o) for f, o in pairs
        if f is not None and o is not None
    ]
    n = len(usable)
    if n == 0:
        return 0, None, None
    signed = sum(f - o for f, o in usable) / n
    absolute = sum(abs(f - o) for f, o in usable) / n
    return n, signed, absolute


def skill_curve(rows):
    """Accuracy by lead time — the headline chart.

    `rows`: iterable of dicts with lead_days, forecast_c, observed_c.
    Returns a list ordered by lead_days ascending, each entry carrying its own
    sample size so a reader can see which points are thin.
    """
    by_lead: dict[int, list] = {}
    for r in rows:
        lead = r.get("lead_days")
        if lead is None:
            continue
        by_lead.setdefault(int(lead), []).append(
            (r.get("forecast_c"), r.get("observed_c"))
        )

    out = []
    for lead in sorted(by_lead):
        n, bias, mae = _aggregate(by_lead[lead])
        if n == 0:
            continue
        out.append({
            "lead_days": lead,
            "pairs": n,
            "bias_c": _round(bias),
            "mae_c": _round(mae),
            "direction": bias_direction(bias),
            "thin": n < MIN_PAIRS_FOR_CONFIDENCE,
        })
    return out


def city_scoreboard(rows, min_lead=1, max_lead=5):
    """Per-city accuracy over a lead-time band, worst first.

    The band excludes lead 0 by default: a same-day forecast is a much easier
    problem, and including it flatters every city equally while hiding which
    places are genuinely hard to forecast.
    """
    by_city: dict[str, dict] = {}
    for r in rows:
        lead = r.get("lead_days")
        if lead is None or not (min_lead <= int(lead) <= max_lead):
            continue
        key = r.get("site_code")
        if not key:
            continue
        entry = by_city.setdefault(key, {
            "site_code": key,
            "city": r.get("city") or key,
            "province": r.get("province"),
            "pairs_raw": [],
        })
        # A later row may carry a station name where an earlier one did not.
        if r.get("city"):
            entry["city"] = r["city"]
        if r.get("province"):
            entry["province"] = r["province"]
        entry["pairs_raw"].append((r.get("forecast_c"), r.get("observed_c")))

    out = []
    for entry in by_city.values():
        n, bias, mae = _aggregate(entry.pop("pairs_raw"))
        if n == 0:
            continue
        entry.update({
            "pairs": n,
            "bias_c": _round(bias),
            "mae_c": _round(mae),
            "direction": bias_direction(bias),
            "thin": n < MIN_PAIRS_FOR_CONFIDENCE,
        })
        out.append(entry)

    # Worst-forecast city first: that is the interesting end of the table.
    # `or -1` keeps a None mae from crashing the sort; it sorts last.
    out.sort(key=lambda c: (c["mae_c"] if c["mae_c"] is not None else -1), reverse=True)
    return out


def summarise(rows, curve=None):
    """Headline figures plus the observation window they were drawn from.

    The window is returned as part of the payload, not left to the template to
    remember, because a figure published without its window implies a longer
    record than we have.
    """
    curve = curve if curve is not None else skill_curve(rows)
    total_pairs = sum(c["pairs"] for c in curve)

    same_day = next((c for c in curve if c["lead_days"] == 0), None)
    longest = curve[-1] if curve else None

    # Long-range bias: the editorially interesting number. Averaged across the
    # deepest leads we have rather than read off a single point, so one thin
    # day cannot swing the claim.
    long_leads = [c for c in curve if c["lead_days"] >= 5 and c["bias_c"] is not None]
    if long_leads:
        long_bias = sum(c["bias_c"] * c["pairs"] for c in long_leads) / sum(
            c["pairs"] for c in long_leads
        )
    else:
        long_bias = None

    observed_days = [r.get("target_day") for r in rows if r.get("target_day")]

    return {
        "total_pairs": total_pairs,
        "same_day_mae_c": same_day["mae_c"] if same_day else None,
        "same_day_pairs": same_day["pairs"] if same_day else 0,
        "longest_lead_days": longest["lead_days"] if longest else None,
        "longest_mae_c": longest["mae_c"] if longest else None,
        "long_range_bias_c": _round(long_bias),
        "long_range_direction": bias_direction(long_bias),
        "window_start": min(observed_days) if observed_days else None,
        "window_end": max(observed_days) if observed_days else None,
        "window_days": (
            (max(observed_days) - min(observed_days)).days + 1
            if observed_days else 0
        ),
    }


def verification_payload(rows):
    """The whole page payload. Never raises on empty input.

    An empty result is a real state on a fresh deploy — the page must render an
    honest "not enough history yet" rather than a 500 or, worse, zeroes that
    read as a perfect forecast.
    """
    rows = list(rows or [])
    curve = skill_curve(rows)
    summary = summarise(rows, curve=curve)
    return {
        "summary": summary,
        "skill_curve": curve,
        "cities": city_scoreboard(rows),
        "has_data": summary["total_pairs"] > 0,
    }
