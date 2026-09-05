"""drift_guard.py — the self-policing guard for the parliamentary cost / funds data.

Runs daily. Two checks, each of which would have caught a multi-week SILENT freeze in week
one instead of by luck weeks later:

  1. RECONCILIATION — cost_reconciliation() must still tie out (the national headline == the
     independent member-by-member sum). A broken window/matcher/ingest that skews the total
     trips this.
  2. SOURCE FRESHNESS — every critical ingest source must have a RECENT SUCCESSFUL run in
     parliament.ingest_log, and its MOST-RECENT run must not be an error. This is the exact
     signal that was there but unwatched when mp_expenses (8 wks) and ec_contributions (3 wks)
     silently stopped.

On a problem it alerts Kytran THROUGH A.R.C.H.I.E. (hub /api/internal/notify → Telegram, her
single outbound voice) and logs to parliament.ingest_log (task='drift_guard') EITHER WAY — so
the guard itself is fail-loud + visible, and can never silently stop the way its subjects did.
Alerts are deduped: one message per problem onset/change, not a daily nag.

Env (all tunable without a deploy):
    WTF_HUB_URL              http://100.64.0.4:3000   mesh hub (never public)
    INTERNAL_API_KEY         —                        bearer for /api/internal/notify
    WTF_DRIFT_MP_DAYS        21   mp_expenses      max age (days) of the last success
    WTF_DRIFT_MIN_DAYS       21   minister_travel
    WTF_DRIFT_EC_DAYS        21   ec_contributions
    WTF_DRIFT_SEN_DAYS       45   senator_expenses (the Senate genuinely lags a quarter)
"""
import json
import logging
import os
import urllib.error
import urllib.request

from sqlalchemy import text

logger = logging.getLogger("wtf-ingest.parliament")

_HUB_URL = os.environ.get("WTF_HUB_URL", "http://100.64.0.4:3000").rstrip("/")
_INTERNAL_KEY = os.environ.get("INTERNAL_API_KEY", "")

# per-source max age (days) for the last SUCCESSFUL ingest before we flag staleness. Sources
# sync weekly, so these catch a freeze within ~2-3 weeks; the last-run-was-an-error check below
# fires the very next day regardless.
# task name -> max age (days). Names MUST match what each sync writes to parliament.ingest_log
# (the senator sync logs under 'senator_expenses_sync', NOT 'senator_expenses').
_MAX_AGE_DAYS = {
    "mp_expenses": int(os.environ.get("WTF_DRIFT_MP_DAYS", "21")),
    "minister_travel": int(os.environ.get("WTF_DRIFT_MIN_DAYS", "21")),
    "ec_contributions": int(os.environ.get("WTF_DRIFT_EC_DAYS", "21")),
    "senator_expenses_sync": int(os.environ.get("WTF_DRIFT_SEN_DAYS", "45")),
    "dept_contracts": int(os.environ.get("WTF_DRIFT_DEPTC_DAYS", "21")),
    "issuer_contracts": int(os.environ.get("WTF_DRIFT_ISSUERC_DAYS", "21")),
    # Elections Canada results. The DATA is static — GE44's official results
    # will never change — so this window is not measuring data freshness, it is
    # measuring that the WEEKLY job in ingest/run.py is still running and the
    # CKAN resource still fetches and parses. 10 = a 7-day cadence plus slack.
    # ⚠️ This number and that cadence are one decision; move them together.
    "elections_results": int(os.environ.get("WTF_DRIFT_ELECTIONS_DAYS", "10")),
    # Added 2026-08-18 (#5725): these five were EXACTLY the feeds that died
    # silently for 2-3 months while this guard watched everything else —
    # senators frozen 87d on a DEAD top-level bs4 import (never called —
    # removed, not dependency-added), senate votes never scheduled,
    # lobbying 57d / ethics 88d with swallowed exceptions and no heartbeat.
    # Their pullers now write parliament.ingest_log rows (openparl.py
    # phase-3 heartbeats, run.py senators block, senate_votes.py hub cron),
    # so a recurrence alarms here instead of rotting quietly.
    "senators_sync": int(os.environ.get("WTF_DRIFT_SENATORS_DAYS", "21")),
    # senators_sync = the CONTAINER run (enrichment-only — its roster scrape
    # needs Playwright and yields 0 in-container, proven 2026-08-18);
    # senators_roster = the HUB cron run that actually refreshes the roster.
    "senators_roster": int(os.environ.get("WTF_DRIFT_SENROSTER_DAYS", "21")),
    "senate_votes": int(os.environ.get("WTF_DRIFT_SENVOTES_DAYS", "21")),
    # lobbying is HUB-owned since 2026-08-18 (Cloudflare turnstile — the
    # weekly hub cron writes this heartbeat; the container no longer tries).
    "lobbying": int(os.environ.get("WTF_DRIFT_LOBBY_DAYS", "21")),
    "ethics_disclosures": int(os.environ.get("WTF_DRIFT_ETHICS_DAYS", "21")),
    "promise_tracker": int(os.environ.get("WTF_DRIFT_PROMISE_DAYS", "21")),
    # House committee rosters (#5728, container phase-3 since 2026-08-18).
    "committees": int(os.environ.get("WTF_DRIFT_COMMITTEES_DAYS", "21")),
    # A.U.R.O.R.A. environmental layers (project #393, CWFIS — ADR-001).
    # Tighter than the parliamentary feeds because these refresh daily, not
    # weekly: a fire layer three weeks stale is worthless during fire season.
    "aurora_firewx": int(os.environ.get("WTF_DRIFT_AURORA_FIREWX_DAYS", "2")),
    "aurora_fire": int(os.environ.get("WTF_DRIFT_AURORA_FIRE_DAYS", "2")),
    # City weather is an HOURLY feed, so 2 days would let it be dead for ~48
    # cycles before anyone heard. 1 day is still generous (24 missed pulls) but
    # this dict is in DAYS; the per-layer 3h/12h staleness that the UI honours
    # lives in wtf.aurora_layer_status.stale_after_hours.
    "aurora_city_obs": int(os.environ.get("WTF_DRIFT_AURORA_CITY_OBS_DAYS", "1")),
    "aurora_city_forecast": int(os.environ.get("WTF_DRIFT_AURORA_CITY_FCST_DAYS", "1")),
    # Weekly subscriber digest (#6233). It crashed EVERY Monday for weeks with no
    # observable signal — same shape as the five feeds above, so it belongs here.
    # 10 days, NOT 21: the send is weekly, so a healthy age never exceeds 7. Ten
    # alarms roughly three days after a single missed Monday while tolerating a
    # late run; 21 would let three consecutive Mondays fail before anyone heard.
    "weekly_digest": int(os.environ.get("WTF_DRIFT_DIGEST_DAYS", "10")),
    # BoC overnight rate decisions (#6272, Batch 9). Same shape as
    # elections_results: BoC decides on a fixed ~8/year schedule, so this
    # window measures the WEEKLY job in ingest/run.py still running and the
    # Valet API still fetching/parsing, not data freshness per se. 10 days
    # for the same reason as elections_results — weekly cadence plus slack.
    "boc_rates": int(os.environ.get("WTF_DRIFT_BOC_DAYS", "10")),
    # CAD/USD daily exchange rate (Batch 12, #6523). Same weekly-job shape as
    # boc_rates — this measures the WEEKLY job in ingest/run.py still firing
    # and the Valet API still reachable, not day-to-day FX freshness (a
    # holiday gap in the underlying series is normal and handled by
    # fx_rates._build_rows, not this guard).
    "fx_rates": int(os.environ.get("WTF_DRIFT_FX_DAYS", "10")),
    # StatCan CPI/unemployment/GDP/housing-starts (Batch 12, #6523). All four
    # release monthly with real-world lag (StatCan itself can take 3-4 weeks
    # after the reference period), so this measures the WEEKLY job still
    # running, with generous slack over the underlying release calendar —
    # same reasoning as elections_results' 10-day window over an infrequent
    # source, just wider because the source itself is naturally slower.
    "statcan_indicators": int(os.environ.get("WTF_DRIFT_STATCAN_DAYS", "40")),
}

# Tasks that MUST have run at least once. The freshness loop below skips a task
# with zero rows ("not yet tracked"), which is right for a legacy sync that
# predates ingest_log — but for a NEW puller it means one that never runs at all
# reports green forever. Anything listed here alarms on absence instead.
_REQUIRED_TASKS = {"aurora_firewx", "aurora_fire",
                   "aurora_city_obs", "aurora_city_forecast",
                   # elections_results is SCHEDULED (weekly, ingest/run.py), so
                   # zero rows does not mean "not tracked yet" — it means the
                   # schedule is not running. Required, or the one signal that
                   # the job vanished is the signal we would skip.
                   "elections_results",
                   # weekly_digest has ZERO rows as of 2026-09-01 (verified), so
                   # without this line the freshness loop would skip it as "not yet
                   # tracked" and it would report green forever — which is exactly
                   # the state that let it crash every Monday unnoticed (#6233).
                   # Safe to require: WTF_WEEKLY_DIGEST_ENABLED=true in prod (verified
                   # on Citadel). If the digest is ever deliberately turned OFF, remove
                   # it from here too, or this alarms honestly but uselessly forever.
                   "weekly_digest",
                   # boc_rates is a brand-new puller (#6272) — the prior manual-only
                   # script never wrote to parliament.ingest_log at all, so this has
                   # zero rows until the first scheduled run lands. Required for the
                   # same reason as weekly_digest: a puller that never fires must
                   # alarm, not report green-by-omission forever.
                   "boc_rates",
                   # fx_rates and statcan_indicators are BOTH brand-new pullers
                   # (Batch 12, #6523) — same reasoning as boc_rates: a puller
                   # that never runs must alarm, not report green-by-omission.
                   "fx_rates",
                   "statcan_indicators"}


def _source_freshness(engine) -> list:
    """One problem string per stale/failing source (empty list = every source healthy).

    The age is computed IN SQL (now() - run_at) so it's timezone-safe regardless of whether the
    ingest_log.run_at column is naive or aware — mixing the two in Python raises."""
    problems = []
    with engine.connect() as conn:
        for task, max_days in _MAX_AGE_DAYS.items():
            row = conn.execute(
                text(
                    "SELECT count(*) AS n, "
                    " EXTRACT(EPOCH FROM (now() - MAX(run_at) FILTER (WHERE COALESCE(error,'') = ''))) / 86400 "
                    "   AS age_days, "
                    " (array_agg(COALESCE(error,'') ORDER BY run_at DESC))[1] AS latest_error "
                    "FROM parliament.ingest_log WHERE task = :t"
                ),
                {"t": task},
            ).fetchone()
            n_entries, age_days, latest_error = (row[0], row[1], row[2]) if row else (0, None, None)
            if not n_entries:
                if task in _REQUIRED_TASKS:
                    problems.append(
                        "%s: has NEVER run — no ingest_log row at all" % task)
                    continue
                # Never logged — there's no baseline to assess freshness against, and the sync
                # may simply predate ingest_log tracking (the data can still be present). Skip
                # quietly rather than false-alarm; it starts being watched once it logs once.
                logger.info("drift_guard: %s not yet tracked in ingest_log — skipping", task)
                continue
            if latest_error:
                problems.append("%s: last run FAILED — %s" % (task, latest_error[:100]))
            elif age_days is None or float(age_days) > max_days:
                shown = ("%.0fd" % float(age_days)) if age_days is not None else "n/a"
                problems.append("%s: last success %s ago (> %dd threshold)" % (task, shown, max_days))
    return problems


def _reconciliation_problems(engine) -> list:
    """Empty unless the national headline no longer equals the member-by-member sum."""
    from ingest.parliament.cost import cost_reconciliation

    rec = cost_reconciliation(engine)
    if rec.get("reconciles"):
        return []
    head = (rec.get("headline") or {}).get("parliamentary")
    return [
        "cost total no longer reconciles member-by-member "
        "(discrepancy %s; headline %s)" % (rec.get("discrepancy"), head)
    ]


def _alert(title: str, message: str, priority: str = "high") -> bool:
    """Speak the alert to Kytran through A.R.C.H.I.E. (hub notify → Telegram). Fail-soft — a
    comms hiccup must never crash the guard (the ingest_log record still stands)."""
    if not _INTERNAL_KEY:
        logger.warning("drift_guard: no INTERNAL_API_KEY — cannot alert: %s", title)
        return False
    payload = json.dumps(
        {"title": title, "message": message, "priority": priority, "source": "wtf-parliament", "telegram": True}
    ).encode("utf-8")
    req = urllib.request.Request(
        _HUB_URL + "/api/internal/notify",
        data=payload,
        headers={"Content-Type": "application/json", "Authorization": "Bearer " + _INTERNAL_KEY},
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.status == 200
    except (urllib.error.URLError, OSError) as exc:
        logger.error("drift_guard: alert POST failed: %s", exc)
        return False


def run_drift_guard(engine) -> dict:
    """Daily guard: reconciliation + source freshness. Alerts on any NEW problem, logs every run.

    Returns {ok, problems:[...], alerted}. Never raises — a guard that can crash is no guard.
    """
    problems = []
    for check in (_reconciliation_problems, _source_freshness):
        try:
            problems.extend(check(engine))
        except Exception as exc:  # a check crashing is itself a problem worth surfacing
            problems.append("%s crashed: %s" % (check.__name__, exc))

    ok = not problems
    joined = ("; ".join(problems))[:500]

    # dedup: only Telegram on onset/change, not the same problem every single day
    try:
        with engine.connect() as conn:
            prev = conn.execute(
                text(
                    "SELECT COALESCE(error, '') FROM parliament.ingest_log "
                    "WHERE task = 'drift_guard' ORDER BY run_at DESC LIMIT 1"
                )
            ).scalar()
    except Exception:
        prev = None
    alerted = False
    if not ok and joined != (prev or ""):
        alerted = _alert(
            "⚠️ Parliament data drift",
            "The Parliament cost / funds data needs attention:\n• " + "\n• ".join(problems),
        )
    elif ok and (prev or ""):   # was in a problem state last run — announce the recovery, then quiet
        alerted = _alert(
            "✅ Parliament data recovered",
            "The earlier Parliament data drift has cleared — the cost total reconciles "
            "member-by-member and every source is fresh again.",
            priority="normal",
        )

    # fail-loud: the guard's own outcome is always visible in ingest_log
    try:
        with engine.begin() as conn:
            if ok:
                conn.execute(
                    text(
                        "INSERT INTO parliament.ingest_log (task, records_fetched, records_upserted) "
                        "VALUES ('drift_guard', 0, 0)"
                    )
                )
            else:
                conn.execute(
                    text("INSERT INTO parliament.ingest_log (task, error) VALUES ('drift_guard', :e)"),
                    {"e": joined},
                )
    except Exception as exc:
        logger.error("drift_guard: could not write ingest_log: %s", exc)

    if ok:
        logger.info("drift_guard: all healthy (reconciles + %d sources fresh)", len(_MAX_AGE_DAYS))
    else:
        logger.warning("drift_guard: %d problem(s)%s: %s", len(problems),
                        " (alerted)" if alerted else " (already alerted)", problems)
    return {"ok": ok, "problems": problems, "alerted": alerted}
