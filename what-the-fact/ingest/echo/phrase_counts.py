"""Precompute /echo's slogan and word counts into wtf.echo_phrase_counts.

/echo used to run 14 full-text phrase queries per request (~42 s measured on Citadel
2026-10-05). This job does that work once a day and the page reads the result.

How the work stays small after the first run
  * ONE SQL pass per grain computes every phrase for a range of buckets: each article's
    tsvector is built once and tested against all phrases (not once per phrase).
  * Only buckets that are MISSING, plus the newest two, are (re)computed
    (shared.echo_phrases.plan_recompute). A full 13-week/30-day backfill costs about
    30 s; the steady-state daily run recomputes two weeks + two days.

House pattern: never raises; writes a parliament.ingest_log heartbeat on BOTH the
success and the failure path (task `echo_phrase_counts`), so ingest/parliament/drift_guard
alarms when it stops running instead of the table quietly going stale.
"""
from __future__ import annotations

import datetime as dt
import logging

from sqlalchemy import text

from shared.echo_phrases import SLOGANS, WORDS, day_starts, plan_recompute, week_starts

logger = logging.getLogger(__name__)

TASK = "echo_phrase_counts"
_STATEMENT_TIMEOUT = "600s"  # the first backfill pass is ~30 s; this is a ceiling, not a budget


def _kinds() -> list:
    """(kind, grain, phrases, step). WORDS carries (label, tsquery-phrase, colour);
    the TABLE key is the tsquery phrase, which is what the page's reader passes."""
    return [
        ("slogan", "week", [p for p, _who, _c in SLOGANS], dt.timedelta(weeks=1)),
        ("word", "day", [p for _label, p, _c in WORDS], dt.timedelta(days=1)),
    ]


def build_pass_sql(grain: str, n_phrases: int) -> str:
    """One pass: every phrase counted per bucket over [:start, :end). `grain` is
    interpolated, so it is checked against a closed set — never user input."""
    if grain not in ("week", "day"):
        raise ValueError(f"unsupported grain {grain!r}")
    cols = ",\n               ".join(
        f"COUNT(*) FILTER (WHERE tsv @@ phraseto_tsquery('english', :p{i})) AS c{i}"
        for i in range(n_phrases)
    )
    return f"""
        WITH recent AS MATERIALIZED (
            SELECT date_trunc('{grain}', published_at)::date AS b,
                   to_tsvector('english', coalesce(title, '') || ' ' || coalesce(body, '')) AS tsv
            FROM wtf.articles
            WHERE published_at >= :start AND published_at < :end
              AND suppressed_reason IS NULL
        )
        SELECT b,
               {cols}
        FROM recent
        GROUP BY b"""


def contiguous(buckets: list, step: dt.timedelta) -> list:
    """Every bucket from min to max inclusive. The pass scans that whole range anyway,
    so every bucket in it is written fresh — including empty ones, as explicit zeros."""
    lo, hi = min(buckets), max(buckets)
    out, b = [], lo
    while b <= hi:
        out.append(b)
        b += step
    return out


def _stored_complete_buckets(conn, kind: str, phrases: list, since: dt.date) -> set:
    """Buckets that hold a row for EVERY current phrase. A bucket missing even one
    (a phrase added later, a partial earlier run) is not complete and gets recomputed."""
    rows = conn.execute(
        text(
            "SELECT bucket_start FROM wtf.echo_phrase_counts "
            "WHERE kind = :k AND phrase = ANY(:phrases) AND bucket_start >= :since "
            "GROUP BY bucket_start HAVING COUNT(DISTINCT phrase) = :n"
        ),
        {"k": kind, "phrases": list(phrases), "since": since, "n": len(phrases)},
    ).all()
    return {r[0] for r in rows}


def _heartbeat(engine, result: dict, exc: Exception | None) -> None:
    """parliament.ingest_log row on BOTH paths, including a swallowed {"error": ...}
    return — a swallowed error that never reaches the log is how an ingest rots unseen."""
    swallowed = result.get("error") if isinstance(result, dict) else None
    try:
        with engine.begin() as c:
            if exc is None and not swallowed:
                c.execute(
                    text("INSERT INTO parliament.ingest_log (task, records_fetched, records_upserted) "
                         "VALUES (:t, :f, :u)"),
                    {"t": TASK, "f": int(result.get("candidates") or 0),
                     "u": int(result.get("upserted") or 0)},
                )
            else:
                c.execute(
                    text("INSERT INTO parliament.ingest_log (task, error) VALUES (:t, :e)"),
                    {"t": TASK, "e": str(exc or swallowed)[:500]},
                )
    except Exception:  # noqa: BLE001 — a failed heartbeat must not take the loop down
        logger.exception("%s heartbeat write failed", TASK)


def run_echo_phrase_counts(engine, today: dt.date | None = None, dry_run: bool = False) -> dict:
    out: dict = {"candidates": 0, "upserted": 0}
    exc: Exception | None = None
    try:
        today = today or dt.date.today()
        for kind, grain, phrases, step in _kinds():
            window = week_starts(today) if grain == "week" else day_starts(today)
            with engine.connect() as c:
                present = _stored_complete_buckets(c, kind, phrases, window[0])
            todo = plan_recompute(window, present)
            out[f"{kind}_buckets"] = len(todo)
            if not todo:
                continue
            buckets = contiguous(todo, step)
            params = {"start": buckets[0], "end": buckets[-1] + step}
            params.update({f"p{i}": p for i, p in enumerate(phrases)})
            with engine.begin() as c:
                c.execute(text(f"SET LOCAL statement_timeout = '{_STATEMENT_TIMEOUT}'"))
                got = {r[0]: list(r[1:]) for r in c.execute(text(build_pass_sql(grain, len(phrases)))
                                                            , params).all()}
                rows = [
                    {"k": kind, "ph": phrase, "b": b, "n": int((got.get(b) or [0] * len(phrases))[i])}
                    for b in buckets for i, phrase in enumerate(phrases)
                ]
                out["candidates"] += len(rows)
                if not dry_run and rows:
                    c.execute(
                        text("INSERT INTO wtf.echo_phrase_counts (kind, phrase, bucket_start, n) "
                             "VALUES (:k, :ph, :b, :n) "
                             "ON CONFLICT (kind, phrase, bucket_start) "
                             "DO UPDATE SET n = EXCLUDED.n, computed_at = now()"),
                        rows,
                    )
                    out["upserted"] += len(rows)
    except Exception as e:  # noqa: BLE001 — a dead ingest must alarm, not crash the loop
        exc = e
        out["error"] = str(e)[:300]
        logger.exception("%s failed", TASK)
    _heartbeat(engine, out, exc)
    return out
