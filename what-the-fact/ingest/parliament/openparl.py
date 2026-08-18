"""openparl.py — OpenParliament.ca API ingest for MPs, votes, and ballots.

Fetches Canadian parliamentary data from api.openparliament.ca:
  1. sync_mps()     — all current MPs (name, party, riding, province, photo)
  2. sync_votes()   — recent vote records (session, date, description, result)
  3. sync_ballots() — per-MP ballot for each vote (Yes / No / Paired)
  4. tag_articles() — name-match MP names against wtf.articles → article_mp_tags

Runs weekly (parliament data changes slowly). Each function is idempotent —
safe to re-run; existing rows are updated on conflict.

Env: WTF_DATABASE_URL (same as rest of WTF ingest)

Rate limit: OpenParliament asks for polite crawling. We sleep 0.5s between
pages and 1s between the three full-table syncs.
"""
import json
import logging
import time
from datetime import date, datetime, timezone
from typing import Optional

import requests
from sqlalchemy import text

logger = logging.getLogger("wtf-ingest.parliament")

_BASE = "https://api.openparliament.ca"
_HEADERS = {
    "User-Agent": "WTFIngest/1.0 (+https://what-the-fact.com; contact@what-the-fact.com)",
    "Accept": "application/json",
}
_PAGE_SLEEP = 0.5   # seconds between paginated requests
_TASK_SLEEP = 1.0   # seconds between sync tasks


# ── helpers ──────────────────────────────────────────────────────────────────

def _get(path: str, params: dict = None) -> Optional[dict]:
    """GET from OpenParliament. Returns parsed JSON or None on error."""
    url = _BASE + path if path.startswith("/") else path
    try:
        resp = requests.get(url, params=params or {}, headers=_HEADERS, timeout=15)
        resp.raise_for_status()
        return resp.json()
    except Exception as exc:
        logger.warning("openparl GET %s failed: %s", path, exc)
        return None


def _paginate(path: str, params: dict = None) -> list[dict]:
    """Fetch all pages from a paginated OpenParliament endpoint."""
    results = []
    p = dict(params or {})
    p.setdefault("limit", 100)
    p.setdefault("offset", 0)
    while True:
        data = _get(path, p)
        if not data:
            break
        objects = data.get("objects") or []
        results.extend(objects)
        if not (data.get("pagination") or {}).get("next_url"):
            break
        p["offset"] += p["limit"]
        time.sleep(_PAGE_SLEEP)
    return results


def _province_from_riding(riding: dict) -> Optional[str]:
    """Extract 2-char province code from a riding object.

    OpenParliament may return 2-char codes ("AB") or full names ("Alberta").
    """
    province = (riding or {}).get("province") or ""
    if not province:
        return None
    # Already a 2-char code
    if len(province) == 2:
        return province.upper()
    _MAP = {
        "Alberta": "AB", "British Columbia": "BC", "Manitoba": "MB",
        "New Brunswick": "NB", "Newfoundland and Labrador": "NL",
        "Nova Scotia": "NS", "Northwest Territories": "NT", "Nunavut": "NU",
        "Ontario": "ON", "Prince Edward Island": "PE", "Quebec": "QC",
        "Saskatchewan": "SK", "Yukon": "YT",
    }
    return _MAP.get(province)


# ── movement capture (change-history audit trail) ─────────────────────────────

def record_movement(conn, subject_type: str, movement_type: str, *,
                    subject_slug: Optional[str] = None, subject_id: Optional[int] = None,
                    name: Optional[str] = None, before: Optional[dict] = None,
                    after: Optional[dict] = None) -> None:
    """Append one row to parliament.mp_movements (migration 038).

    `conn` is an open SQLAlchemy connection inside a transaction (engine.begin()).
    `before`/`after` are plain dicts serialized to JSONB (NULL when omitted).
    Shared by cabinet.py (imports this); senators.py keeps a mirrored copy so it
    stays independently runnable via `python -m ingest.parliament.senators`.
    """
    conn.execute(text("""
        INSERT INTO parliament.mp_movements
            (subject_type, subject_slug, subject_id, name, movement_type,
             before_value, after_value)
        VALUES
            (:st, :slug, :sid, :name, :mt, CAST(:bv AS JSONB), CAST(:av AS JSONB))
    """), {
        "st": subject_type, "slug": subject_slug, "sid": subject_id,
        "name": name, "mt": movement_type,
        "bv": json.dumps(before) if before is not None else None,
        "av": json.dumps(after) if after is not None else None,
    })


# ── sync_mps ─────────────────────────────────────────────────────────────────

def sync_mps(engine) -> dict:
    """Fetch all current MPs, upsert into parliament.mps, and record change
    history (appointments, party/riding changes, departures) to
    parliament.mp_movements — the fix for the old upsert-only behaviour where
    is_current was never flipped false and no history was captured.
    """
    politicians = _paginate("/politicians/", {"current": "true"})
    if not politicians:
        logger.warning("openparl: sync_mps returned 0 politicians")
        return {"fetched": 0, "upserted": 0}

    # ── snapshot prior state for change detection (before any writes) ─────────
    with engine.connect() as c:
        snap_rows = c.execute(text(
            "SELECT slug, name, party, riding_name, cabinet_role, is_current "
            "FROM parliament.mps"
        )).fetchall()
    snapshot = {r[0]: {"name": r[1], "party": r[2], "riding_name": r[3],
                       "cabinet_role": r[4], "is_current": r[5]} for r in snap_rows}
    prior_current = sum(1 for v in snapshot.values() if v["is_current"])

    upserted = 0
    movements = 0
    seen: set[str] = set()
    for pol in politicians:
        url = pol.get("url") or ""
        slug = url.strip("/").split("/")[-1] if url else ""
        if not slug:
            continue
        seen.add(slug)

        # Fetch detail for full fields (given_name, family_name, twitter, email)
        detail = _get(url) or {}
        other = detail.get("other_info") or {}
        twitter = (other.get("twitter") or [None])[0] if isinstance(other.get("twitter"), list) else other.get("twitter")
        parl_mp_id = str(other.get("parl_mp_id") or "")

        party_obj = pol.get("current_party") or {}
        party = (party_obj.get("short_name") or {}).get("en") or party_obj.get("name", {}).get("en") or ""
        riding_obj = pol.get("current_riding") or {}
        riding_name = (riding_obj.get("name") or {}).get("en") or ""
        province_code = _province_from_riding(riding_obj)

        with engine.begin() as c:
            c.execute(text("""
                INSERT INTO parliament.mps
                    (slug, name, given_name, family_name, party, riding_name,
                     province_code, photo_url, twitter, email, parl_mp_id,
                     is_current, openparl_url, updated_at)
                VALUES
                    (:slug, :name, :gn, :fn, :party, :riding, :prov,
                     :photo, :twitter, :email, :mpid, true, :url, NOW())
                ON CONFLICT (slug) DO UPDATE SET
                    name        = EXCLUDED.name,
                    given_name  = EXCLUDED.given_name,
                    family_name = EXCLUDED.family_name,
                    party       = EXCLUDED.party,
                    riding_name = EXCLUDED.riding_name,
                    province_code = EXCLUDED.province_code,
                    photo_url   = COALESCE(EXCLUDED.photo_url, parliament.mps.photo_url),
                    twitter     = COALESCE(EXCLUDED.twitter,   parliament.mps.twitter),
                    email       = COALESCE(EXCLUDED.email,     parliament.mps.email),
                    parl_mp_id  = COALESCE(EXCLUDED.parl_mp_id, parliament.mps.parl_mp_id),
                    is_current  = true,
                    updated_at  = NOW()
            """), {
                "slug": slug,
                "name": pol.get("name") or "",
                "gn": detail.get("given_name") or "",
                "fn": detail.get("family_name") or "",
                "party": party,
                "riding": riding_name,
                "prov": province_code,
                "photo": pol.get("image") or detail.get("image") or None,
                "twitter": twitter,
                "email": detail.get("email") or None,
                "mpid": parl_mp_id or None,
                "url": _BASE + url,
            })
        upserted += 1

        # ── change detection vs snapshot ─────────────────────────────────────
        prev = snapshot.get(slug)
        mp_name = pol.get("name") or ""
        with engine.begin() as c:
            if prev is None:
                record_movement(c, "mp", "appointed", subject_slug=slug, name=mp_name,
                                 after={"party": party, "riding_name": riding_name})
                movements += 1
            else:
                if (prev.get("party") or "") and party and prev["party"] != party:
                    record_movement(c, "mp", "party_change", subject_slug=slug, name=mp_name,
                                     before={"party": prev["party"]},
                                     after={"party": party})
                    movements += 1
                if (prev.get("riding_name") or "") and riding_name and prev["riding_name"] != riding_name:
                    record_movement(c, "mp", "riding_change", subject_slug=slug, name=mp_name,
                                     before={"riding_name": prev["riding_name"]},
                                     after={"riding_name": riding_name})
                    movements += 1
        time.sleep(0.1)  # detail fetch already sleeps via _get; be polite

    # ── departures: prior is_current but NOT seen this run ───────────────────
    # Safety guard: only flip departures when the fetch returned a plausible
    # roster (>=80% of prior current count).  A partial/degraded OpenParliament
    # response must never mass-mark MPs not-current.  A no-op full fetch → 0.
    departed = 0
    if prior_current and len(seen) < max(1, int(0.8 * prior_current)):
        logger.warning(
            "openparl.sync_mps: fetched only %d of %d prior-current MPs — skipping "
            "departure detection (guard) to avoid false mass-departures",
            len(seen), prior_current)
    else:
        for slug, prev in snapshot.items():
            if not prev["is_current"] or slug in seen:
                continue
            with engine.begin() as c:
                c.execute(text(
                    "UPDATE parliament.mps SET is_current = false, updated_at = NOW() "
                    "WHERE slug = :s"
                ), {"s": slug})
                record_movement(c, "mp", "departed", subject_slug=slug,
                                 name=prev.get("name"),
                                 before={"party": prev.get("party"),
                                         "riding_name": prev.get("riding_name"),
                                         "is_current": True},
                                 after={"is_current": False})
            departed += 1
            movements += 1

    logger.info("openparl.sync_mps: fetched=%d upserted=%d movements=%d departed=%d",
                len(politicians), upserted, movements, departed)
    return {"fetched": len(politicians), "upserted": upserted,
            "movements": movements, "departed": departed}


# ── sync_votes ────────────────────────────────────────────────────────────────

def sync_votes(engine, session_filter: str = None) -> dict:
    """Fetch vote records and upsert into parliament.bills.

    session_filter: if set (e.g. "45-1"), only fetch votes for that session.
    Defaults to the two most recent sessions to avoid pulling the entire history
    on first run.
    """
    params = {}
    if session_filter:
        params["session"] = session_filter

    votes = _paginate("/votes/", params)
    if not votes:
        logger.warning("openparl: sync_votes returned 0 votes")
        return {"fetched": 0, "upserted": 0}

    upserted = 0
    for v in votes:
        session = v.get("session") or ""
        number = v.get("number")
        if not session or number is None:
            continue
        bill_url = v.get("bill_url") or ""
        bill_number = bill_url.strip("/").split("/")[-1] if bill_url else None
        desc = v.get("description") or {}
        vote_date_str = v.get("date") or ""
        try:
            vote_date = date.fromisoformat(vote_date_str) if vote_date_str else None
        except ValueError:
            vote_date = None

        with engine.begin() as c:
            c.execute(text("""
                INSERT INTO parliament.bills
                    (session, vote_number, bill_number, description_en, description_fr,
                     vote_date, result, yea_total, nay_total, paired_total, openparl_url)
                VALUES
                    (:sess, :num, :bill, :desc_en, :desc_fr,
                     :vdate, :result, :yea, :nay, :paired, :url)
                ON CONFLICT (session, vote_number) DO UPDATE SET
                    bill_number    = COALESCE(EXCLUDED.bill_number,   parliament.bills.bill_number),
                    description_en = COALESCE(EXCLUDED.description_en, parliament.bills.description_en),
                    description_fr = COALESCE(EXCLUDED.description_fr, parliament.bills.description_fr),
                    vote_date      = COALESCE(EXCLUDED.vote_date,      parliament.bills.vote_date),
                    result         = COALESCE(EXCLUDED.result,         parliament.bills.result),
                    yea_total      = COALESCE(EXCLUDED.yea_total,      parliament.bills.yea_total),
                    nay_total      = COALESCE(EXCLUDED.nay_total,      parliament.bills.nay_total),
                    paired_total   = COALESCE(EXCLUDED.paired_total,   parliament.bills.paired_total)
            """), {
                "sess": session,
                "num": number,
                "bill": bill_number,
                "desc_en": desc.get("en") or None,
                "desc_fr": desc.get("fr") or None,
                "vdate": vote_date,
                "result": v.get("result") or None,
                "yea": v.get("yea_total"),
                "nay": v.get("nay_total"),
                "paired": v.get("paired_total"),
                "url": _BASE + (v.get("url") or ""),
            })
        upserted += 1

    logger.info("openparl.sync_votes: fetched=%d upserted=%d", len(votes), upserted)
    return {"fetched": len(votes), "upserted": upserted}


# ── sync_ballots ──────────────────────────────────────────────────────────────

def sync_ballots(engine, session_filter: str = None) -> dict:
    """For each bill in parliament.bills, fetch per-MP ballots from OpenParliament."""
    with engine.connect() as c:
        if session_filter:
            bills = c.execute(text(
                "SELECT id, session, vote_number FROM parliament.bills WHERE session = :s ORDER BY vote_date DESC"
            ), {"s": session_filter}).fetchall()
        else:
            bills = c.execute(text(
                "SELECT id, session, vote_number FROM parliament.bills ORDER BY vote_date DESC LIMIT 500"
            )).fetchall()

    if not bills:
        return {"bills_processed": 0, "ballots_upserted": 0}

    # Pre-load MP slug → id map
    with engine.connect() as c:
        mp_rows = c.execute(text("SELECT id, slug FROM parliament.mps")).fetchall()
    mp_map = {row[1]: row[0] for row in mp_rows}

    bills_done = 0
    ballots_total = 0
    for bill_id, session, vote_number in bills:
        ballots = _paginate("/votes/ballots/", {
            "vote": f"/votes/{session}/{vote_number}/",
        })
        for b in ballots:
            pol_url = b.get("politician_url") or ""
            slug = pol_url.strip("/").split("/")[-1] if pol_url else ""
            mp_id = mp_map.get(slug)
            ballot_val = b.get("ballot") or ""
            if not mp_id or ballot_val not in ("Yes", "No", "Paired"):
                continue
            try:
                with engine.begin() as c:
                    c.execute(text("""
                        INSERT INTO parliament.mp_votes (mp_id, bill_id, ballot)
                        VALUES (:mp, :bill, :ballot)
                        ON CONFLICT (mp_id, bill_id) DO UPDATE SET ballot = EXCLUDED.ballot
                    """), {"mp": mp_id, "bill": bill_id, "ballot": ballot_val})
                ballots_total += 1
            except Exception as exc:
                logger.debug("ballot insert failed mp=%s bill=%s: %s", mp_id, bill_id, exc)
        bills_done += 1
        time.sleep(_PAGE_SLEEP)

    logger.info("openparl.sync_ballots: bills=%d ballots=%d", bills_done, ballots_total)
    return {"bills_processed": bills_done, "ballots_upserted": ballots_total}


# ── tag_articles ──────────────────────────────────────────────────────────────

def tag_articles(engine, days_back: int = 7) -> dict:
    """Name-match MP names against recent WTF article titles and bodies.

    Inserts into wtf.article_mp_tags. Only processes articles from the last
    `days_back` days to keep the operation fast. Runs after sync_mps so the
    MP list is fresh.
    """
    with engine.connect() as c:
        mps = c.execute(text(
            "SELECT id, name, given_name, family_name FROM parliament.mps WHERE is_current = true"
        )).fetchall()
        articles = c.execute(text("""
            SELECT id, title, LEFT(body, 2000) AS body_excerpt
            FROM wtf.articles
            WHERE published_at > NOW() - INTERVAL ':days days'
        """.replace(":days", str(days_back)))).fetchall()

    tagged = 0
    for mp_id, name, given, family in mps:
        # Match on full name or family name (if family name >= 5 chars to avoid false positives)
        patterns = [name]
        if family and len(family) >= 5:
            patterns.append(family)
        for art_id, title, body in articles:
            text_blob = (title or "") + " " + (body or "")
            if any(p.lower() in text_blob.lower() for p in patterns):
                try:
                    with engine.begin() as c:
                        c.execute(text("""
                            INSERT INTO wtf.article_mp_tags (article_id, mp_id, match_type)
                            VALUES (:aid, :mid, 'name_match')
                            ON CONFLICT (article_id, mp_id) DO NOTHING
                        """), {"aid": art_id, "mid": mp_id})
                    tagged += 1
                except Exception:
                    pass

    logger.info("openparl.tag_articles: articles=%d mps=%d tagged=%d",
                len(articles), len(mps), tagged)
    return {"articles_scanned": len(articles), "tags_inserted": tagged}


# ── main entry point ──────────────────────────────────────────────────────────

# Phase-3 tasks that write their own parliament.ingest_log rows — the
# heartbeat below must not double-log them.
_PHASE3_SELF_LOGGING = {"mp_expenses", "minister_travel"}


def _phase3_heartbeat(engine, task_name, result, exc):
    """Write a parliament.ingest_log heartbeat for Phase-3 tasks that don't
    self-log. Lobbying and ethics failed SILENTLY for 2-3 months (57d/88d
    stale, 2026-08-18 site audit) because their exceptions were swallowed
    non-fatally with no run record — unmonitored while appearing monitored.
    drift_guard alarms on a stale last-SUCCESS, so it needs these rows.
    Never raises (a heartbeat failure must not break the sync)."""
    if task_name in _PHASE3_SELF_LOGGING:
        return
    try:
        # A puller that SWALLOWS its failure and returns {"error": ...}
        # without raising (lobbying does exactly this; in-container ethics
        # can never succeed — playwright is hub-only) must log as an ERROR,
        # or the guard certifies a structurally dead feed green forever.
        swallowed = result.get("error") if isinstance(result, dict) else None
        from sqlalchemy import text as _text
        with engine.begin() as c:
            if exc is None and not swallowed:
                fetched = upserted = 0
                if isinstance(result, dict):
                    fetched = int(result.get("fetched") or result.get("total")
                                  or result.get("articles_scanned") or 0)
                    upserted = int(result.get("upserted") or result.get("updated")
                                   or result.get("inserted")
                                   or result.get("promises_inserted") or 0)
                c.execute(_text(
                    "INSERT INTO parliament.ingest_log (task, records_fetched, records_upserted) "
                    "VALUES (:t, :f, :u)"), {"t": task_name, "f": fetched, "u": upserted})
            else:
                c.execute(_text(
                    "INSERT INTO parliament.ingest_log (task, error) VALUES (:t, :e)"),
                    {"t": task_name, "e": str(exc if exc is not None else swallowed)[:500]})
    except Exception:
        logger.exception("phase3 heartbeat write failed for %s", task_name)


def run_parliament_sync(engine, current_session: str = "45-1") -> dict:
    """Full parliamentary sync. Called weekly from run.py.

    Order: MPs first (ballots need the slug→id map), then votes, then ballots.
    Article tagging runs last on the freshly-updated MP list.
    """
    results = {}
    start = datetime.now(timezone.utc)

    def _log_task(task: str, fn, *args, **kwargs):
        try:
            r = fn(*args, **kwargs)
            results[task] = r
            with engine.begin() as c:
                c.execute(text("""
                    INSERT INTO parliament.ingest_log (task, records_fetched, records_upserted)
                    VALUES (:t, :f, :u)
                """), {"t": task, "f": r.get("fetched", r.get("bills_processed", 0)),
                       "u": r.get("upserted", r.get("ballots_upserted", r.get("tags_inserted", 0)))})
        except Exception as exc:
            logger.exception("parliament sync task %s failed: %s", task, exc)
            results[task] = {"error": str(exc)}
            with engine.begin() as c:
                c.execute(text(
                    "INSERT INTO parliament.ingest_log (task, error) VALUES (:t, :e)"
                ), {"t": task, "e": str(exc)[:500]})
        time.sleep(_TASK_SLEEP)

    _log_task("sync_mps", sync_mps, engine)
    _log_task("sync_votes", sync_votes, engine, session_filter=current_session)
    _log_task("sync_ballots", sync_ballots, engine, session_filter=current_session)
    _log_task("tag_articles", tag_articles, engine)

    # Phase 2: Elections Canada contribution data (~201MB, 4M rows, ~5-10 min)
    try:
        from ingest.parliament.elections_canada import run_ec_sync
        ec_result = run_ec_sync(engine)
        results["ec_contributions"] = ec_result
    except Exception as exc:
        logger.exception("ec_contributions sync failed (non-fatal): %s", exc)
        results["ec_contributions"] = {"error": str(exc)}

    # Phase 3: Accountability data — expenses, lobbying, ethics, promises
    for task_name, module_path, func_name in [
        ("mp_expenses",       "ingest.parliament.mp_expenses",      "run_expenses_sync"),
        ("minister_travel",   "ingest.parliament.minister_travel",  "run_minister_travel_sync"),
        ("lobbying",          "ingest.parliament.lobbying",          "run_lobbying_sync"),
        ("ethics_disclosures","ingest.parliament.ethics_disclosures","run_ethics_sync"),
        ("promise_tracker",   "ingest.parliament.promise_tracker",   "run_promise_tracker"),
    ]:
        try:
            import importlib
            mod = importlib.import_module(module_path)
            fn = getattr(mod, func_name)
            results[task_name] = fn(engine)
            logger.info("parliament sync %s: %s", task_name, results[task_name])
            _phase3_heartbeat(engine, task_name, results[task_name], None)
        except Exception as exc:
            logger.exception("%s sync failed (non-fatal): %s", task_name, exc)
            results[task_name] = {"error": str(exc)}
            _phase3_heartbeat(engine, task_name, None, exc)
        time.sleep(_TASK_SLEEP)

    elapsed = (datetime.now(timezone.utc) - start).total_seconds()
    logger.info("parliament sync complete in %.1fs: %s", elapsed, results)
    return results
