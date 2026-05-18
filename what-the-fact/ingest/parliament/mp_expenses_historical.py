"""mp_expenses_historical.py — Backfill all historical MP expense quarters.

URL pattern: ourcommons.ca/ProactiveDisclosure/en/members/{fiscal_year}/{quarter}
  - fiscal_year: 2021, 2022, ... 2026 (ending year of the fiscal year Apr–Mar)
  - quarter: 1–4

Scrapes each quarter page (JS-rendered), matches MP names to parliament.mps,
upserts to parliament.mp_expenses. Idempotent — safe to re-run.

Env: WTF_DATABASE_URL
Run: python -m ingest.parliament.mp_expenses_historical
"""
import logging
import os
import re
import sys
import time

from sqlalchemy import create_engine, text

logger = logging.getLogger("wtf-ingest.mp-expenses-historical")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

_BASE = "https://www.ourcommons.ca/ProactiveDisclosure/en/members"

# Quarter → date ranges for period label
_QUARTER_DATES = {
    1: ("Apr 1", "Jun 30"),
    2: ("Jul 1", "Sep 30"),
    3: ("Oct 1", "Dec 31"),
    4: ("Jan 1", "Mar 31"),
}


def _quarter_label(fiscal_year: int, quarter: int) -> str:
    """e.g. fiscal_year=2026, quarter=3 → '2025-Q3' (Oct–Dec 2025)"""
    # Fiscal year ends in March: Q1=Apr-Jun(fy-1), Q2=Jul-Sep(fy-1), Q3=Oct-Dec(fy-1), Q4=Jan-Mar(fy)
    cal_year = fiscal_year - 1 if quarter < 4 else fiscal_year
    return f"{cal_year}-Q{quarter}"


def _norm(s: str) -> str:
    s = re.sub(r'\bHon\.\s*', '', s, flags=re.IGNORECASE)
    s = s.lower()
    for a, b in [('é','e'),('è','e'),('ê','e'),('à','a'),('â','a'),('ç','c'),('ô','o'),('î','i'),('û','u')]:
        s = s.replace(a, b)
    return re.sub(r'[^a-z,\s\.\-]', '', s).strip()


def _build_mp_map(engine) -> dict:
    """Return {normalized_name_variant: mp_id} for all MPs (current + former)."""
    with engine.begin() as c:
        rows = c.execute(text("SELECT id, name FROM parliament.mps")).fetchall()
    mp_map = {}
    for mp_id, mp_name in rows:
        n = _norm(mp_name)
        parts = n.split()
        if len(parts) >= 2:
            last_first = f"{parts[-1]}, {' '.join(parts[:-1])}"
            mp_map[last_first] = mp_id
            mp_map[parts[-1]] = mp_id
    return mp_map


def _match_mp(name: str, mp_map: dict) -> int | None:
    n = _norm(name)
    if n in mp_map:
        return mp_map[n]
    family = n.split(',')[0].strip()
    return mp_map.get(family)


def scrape_quarter(page, fiscal_year: int, quarter: int, engine, mp_map: dict) -> dict:
    """Scrape one quarter page and upsert to DB. Returns stats dict."""
    url = f"{_BASE}/{fiscal_year}/{quarter}"
    period = _quarter_label(fiscal_year, quarter)

    try:
        page.goto(url, wait_until="networkidle", timeout=30000)
    except Exception as exc:
        logger.warning("Failed to load %s: %s", url, exc)
        return {"period": period, "matched": 0, "unmatched": 0, "error": str(exc)}

    rows = page.evaluate("""() => {
        const table = document.querySelector('table');
        if (!table) return [];
        return Array.from(table.querySelectorAll('tbody tr')).map(tr => {
            const cells = Array.from(tr.querySelectorAll('td'));
            const p = s => parseFloat((s||'').replace(/[$,\\s]/g,'')) || 0;
            return {
                name: cells[0]?.innerText?.trim(),
                salaries: p(cells[3]?.innerText),
                travel: p(cells[4]?.innerText),
                hospitality: p(cells[5]?.innerText),
                contracts: p(cells[6]?.innerText)
            };
        }).filter(r => r.name && r.name.length > 2);
    }""")

    if not rows:
        logger.warning("No rows for %s (404 or empty)", period)
        return {"period": period, "matched": 0, "unmatched": 0}

    matched = unmatched = 0
    with engine.begin() as c:
        for row in rows:
            mp_id = _match_mp(row["name"], mp_map)
            if not mp_id:
                unmatched += 1
                continue
            total = row["salaries"] + row["travel"] + row["hospitality"] + row["contracts"]
            c.execute(text("""
                INSERT INTO parliament.mp_expenses
                    (mp_id, period, salaries_cad, travel_cad, hospitality_cad, contracts_cad, total_cad)
                VALUES (:mid, :period, :sal, :trav, :hosp, :cont, :total)
                ON CONFLICT (mp_id, period) DO UPDATE SET
                    salaries_cad=EXCLUDED.salaries_cad, travel_cad=EXCLUDED.travel_cad,
                    hospitality_cad=EXCLUDED.hospitality_cad, contracts_cad=EXCLUDED.contracts_cad,
                    total_cad=EXCLUDED.total_cad
            """), {
                "mid": mp_id, "period": period,
                "sal": row["salaries"], "trav": row["travel"],
                "hosp": row["hospitality"], "cont": row["contracts"],
                "total": total,
            })
            matched += 1

    logger.info("  %s: %d rows, %d matched, %d unmatched", period, len(rows), matched, unmatched)
    return {"period": period, "matched": matched, "unmatched": unmatched}


def backfill_all(start_fy: int = 2022, end_fy: int = 2026) -> list[dict]:
    """Scrape all quarters from start_fy to end_fy inclusive."""
    from playwright.sync_api import sync_playwright

    engine = create_engine(os.environ["WTF_DATABASE_URL"])
    mp_map = _build_mp_map(engine)
    logger.info("MP map: %d entries. Scraping FY%d–FY%d", len(mp_map), start_fy, end_fy)

    results = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.set_default_timeout(30000)

        for fy in range(start_fy, end_fy + 1):
            for q in range(1, 5):
                # Skip future quarters
                import datetime
                today = datetime.date.today()
                cal_year = fy - 1 if q < 4 else fy
                if cal_year > today.year:
                    continue
                if cal_year == today.year and q > (today.month - 1) // 3 + 1:
                    continue

                stats = scrape_quarter(page, fy, q, engine, mp_map)
                results.append(stats)
                time.sleep(0.8)

        browser.close()

    total_matched = sum(r["matched"] for r in results)
    total_quarters = len(results)
    logger.info("Done. %d quarters, %d total rows matched", total_quarters, total_matched)
    return results


if __name__ == "__main__":
    start_fy = int(sys.argv[1]) if len(sys.argv) > 1 else 2022
    end_fy = int(sys.argv[2]) if len(sys.argv) > 2 else 2026
    backfill_all(start_fy=start_fy, end_fy=end_fy)
