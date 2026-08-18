"""senate_votes.py — Scrape Senate of Canada voting records from sencanada.ca.

Fetches all recorded divisions from sencanada.ca/en/in-the-chamber/votes/
(JS-rendered — uses Playwright). For each vote:
  1. Extracts vote metadata (date, title, bill, result, yeas/nays/abstentions)
  2. Visits detail page to get per-senator ballots (yea/nay/abstention/absent)
  3. Matches senator names to parliament.senators slugs
  4. Upserts to parliament.senate_votes + parliament.senator_votes

Env: WTF_DATABASE_URL
Run: python -m ingest.parliament.senate_votes
"""
import logging
import os
import re
import sys
import time
from datetime import date

from sqlalchemy import create_engine, text

logger = logging.getLogger("wtf-ingest.senate-votes")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

_VOTES_URL = "https://sencanada.ca/en/in-the-chamber/votes/"
_SESSION = "45-1"


def _norm_name(name: str) -> str:
    """Normalize senator name for matching (Last, First → normalized)."""
    name = name.lower()
    for a, b in [("é","e"),("è","e"),("ê","e"),("à","a"),("â","a"),("ç","c"),
                 ("ô","o"),("î","i"),("û","u"),("œ","oe"),("ë","e"),("ï","i")]:
        name = name.replace(a, b)
    return re.sub(r"[^a-z,\s\.]", "", name).strip()


def _build_senator_map(engine) -> dict[str, int]:
    """Return {normalized_name: senator_db_id} for all current senators."""
    with engine.begin() as c:
        rows = c.execute(text(
            "SELECT id, name FROM parliament.senators WHERE is_current = true"
        )).fetchall()
    result = {}
    for sid, name in rows:
        norm = _norm_name(name)
        result[norm] = sid
        # Also index family name alone for fallback
        family = norm.split(",")[0].strip() if "," in norm else norm
        if family not in result:
            result[family] = sid
    return result


def _match_senator(name: str, senator_map: dict) -> int | None:
    """Try to match a senator name string (Last, First) to a DB id."""
    norm = _norm_name(name)
    if norm in senator_map:
        return senator_map[norm]
    # Try family name only
    family = norm.split(",")[0].strip()
    if family in senator_map:
        return senator_map[family]
    return None


def scrape_senate_votes(max_votes: int = 0) -> dict:
    """Scrape senate votes using Playwright. max_votes=0 = no limit."""
    from playwright.sync_api import sync_playwright

    engine = create_engine(os.environ["WTF_DATABASE_URL"])
    senator_map = _build_senator_map(engine)
    logger.info("Loaded %d senator name mappings", len(senator_map))

    stats = {"votes_upserted": 0, "ballots_upserted": 0, "senator_unmatched": set()}

    with sync_playwright() as p:
        # System Chrome, like senators.py — the hub has playwright's PACKAGE
        # but not its managed Chromium download; a bare launch() would raise
        # "Executable doesn't exist" on every cron run (2026-08-18 review).
        browser = p.chromium.launch(
            executable_path="/usr/bin/google-chrome",
            headless=True,
        )
        page = browser.new_page()
        page.set_default_timeout(30000)

        # ── Step 1: extract vote list ─────────────────────────────────────
        page.goto(_VOTES_URL, wait_until="networkidle")
        votes_raw = page.evaluate("""() => {
            const table = document.querySelector('table');
            if (!table) return [];
            return Array.from(table.querySelectorAll('tbody tr')).map(tr => {
                const cells = Array.from(tr.querySelectorAll('td'));
                const titleCell = cells[1]?.innerText || '';
                const yeasM = titleCell.match(/Yeas:\\s*(\\d+)/);
                const naysM = titleCell.match(/Nays:\\s*(\\d+)/);
                const abstM = titleCell.match(/Abstentions?:\\s*(\\d+)/);
                const link = cells[1]?.querySelector('a')?.href;
                const voteId = link?.match(/\\/details\\/(\\d+)\\//)?.[1];
                return {
                    date: cells[0]?.innerText?.trim(),
                    title: titleCell.split('\\n')[0].trim(),
                    bill: (cells[2]?.innerText?.trim() || null) || null,
                    result: cells[3]?.innerText?.trim(),
                    yeas: yeasM ? parseInt(yeasM[1]) : null,
                    nays: naysM ? parseInt(naysM[1]) : null,
                    abstentions: abstM ? parseInt(abstM[1]) : 0,
                    vote_id: voteId || null,
                    detail_url: link || null
                };
            }).filter(v => v.vote_id && v.date);
        }""")

        if max_votes:
            votes_raw = votes_raw[:max_votes]
        logger.info("Found %d votes to process", len(votes_raw))

        # ── Step 2: for each vote, get detail + senator ballots ───────────
        for i, v in enumerate(votes_raw):
            logger.info("[%d/%d] %s — %s", i + 1, len(votes_raw), v["date"], v["title"][:60])

            # Upsert vote record
            try:
                vote_date = date.fromisoformat(v["date"])
            except Exception:
                continue

            with engine.begin() as c:
                row = c.execute(text("""
                    INSERT INTO parliament.senate_votes
                        (vote_id, session, vote_date, title, bill_number, result,
                         yea_total, nay_total, abstention_total, detail_url, synced_at)
                    VALUES (:vid, :session, :date, :title, :bill, :result,
                            :yeas, :nays, :abst, :url, NOW())
                    ON CONFLICT (vote_id) DO UPDATE SET
                        title = EXCLUDED.title, result = EXCLUDED.result,
                        yea_total = EXCLUDED.yea_total, nay_total = EXCLUDED.nay_total,
                        abstention_total = EXCLUDED.abstention_total,
                        synced_at = NOW()
                    RETURNING id
                """), {
                    "vid": v["vote_id"], "session": _SESSION, "date": vote_date,
                    "title": v["title"], "bill": v["bill"] or None,
                    "result": v["result"], "yeas": v["yeas"], "nays": v["nays"],
                    "abst": v["abstentions"], "url": v["detail_url"],
                }).fetchone()
                vote_db_id = row[0]
            stats["votes_upserted"] += 1

            # Fetch detail page for ballots
            if not v["detail_url"]:
                continue
            try:
                page.goto(v["detail_url"], wait_until="networkidle")
                ballots = page.evaluate("""() => {
                    const table = document.querySelector('table');
                    if (!table) return [];
                    return Array.from(table.querySelectorAll('tbody tr')).map(tr => {
                        const cells = Array.from(tr.querySelectorAll('td'));
                        const hasIcon = c => c?.querySelector('i.fa-solid') !== null;
                        let vote = 'absent';
                        if (hasIcon(cells[3])) vote = 'yea';
                        else if (hasIcon(cells[4])) vote = 'nay';
                        else if (hasIcon(cells[5])) vote = 'abstention';
                        return {name: cells[0]?.innerText?.trim(), vote};
                    }).filter(r => r.name);
                }""")
            except Exception as exc:
                logger.warning("Detail page failed for vote %s: %s", v["vote_id"], exc)
                continue

            # Match and upsert ballots
            with engine.begin() as c:
                for b in ballots:
                    sen_id = _match_senator(b["name"], senator_map)
                    if not sen_id:
                        stats["senator_unmatched"].add(b["name"])
                        continue
                    c.execute(text("""
                        INSERT INTO parliament.senator_votes (senator_id, vote_id, ballot)
                        VALUES (:sid, :vid, :ballot)
                        ON CONFLICT (senator_id, vote_id) DO UPDATE SET ballot = EXCLUDED.ballot
                    """), {"sid": sen_id, "vid": vote_db_id, "ballot": b["vote"]})
                    stats["ballots_upserted"] += 1

            time.sleep(0.5)

        browser.close()

    unmatched = list(stats["senator_unmatched"])
    logger.info("Done. votes=%d ballots=%d unmatched_senators=%d",
                stats["votes_upserted"], stats["ballots_upserted"], len(unmatched))
    if unmatched:
        logger.warning("Unmatched senators: %s", unmatched[:10])
    return stats


def run_senate_votes_sync(max_votes: int = 0) -> dict:
    """scrape_senate_votes + a parliament.ingest_log heartbeat either way.

    This scraper needs Playwright + Chrome, which the wtf-ingest container
    deliberately does not carry — it runs on the HUB via weekly cron
    (/etc/cron.d/wtf-senate-votes → scripts/senate_votes_cron.sh). The
    heartbeat is what lets the container-side drift_guard watch it anyway
    ('senate_votes' in _MAX_AGE_DAYS). Before 2026-08-18 this script was
    never scheduled at all: 25 votes frozen at 2026-04-21 while the Senate
    sat and voted through June (site audit)."""
    engine = create_engine(os.environ["WTF_DATABASE_URL"])
    try:
        stats = scrape_senate_votes(max_votes=max_votes)
        with engine.begin() as c:
            c.execute(text(
                "INSERT INTO parliament.ingest_log (task, records_fetched, records_upserted) "
                "VALUES ('senate_votes', :f, :u)"),
                {"f": int(stats.get("votes_upserted") or 0),
                 "u": int(stats.get("ballots_upserted") or 0)})
        return stats
    except Exception as exc:
        try:
            with engine.begin() as c:
                c.execute(text(
                    "INSERT INTO parliament.ingest_log (task, error) VALUES ('senate_votes', :e)"),
                    {"e": str(exc)[:500]})
        except Exception:
            logger.exception("senate_votes heartbeat write failed")
        raise


if __name__ == "__main__":
    max_v = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    run_senate_votes_sync(max_votes=max_v)
