"""mp_expenses.py — MP quarterly expense report ingest from Our Commons.

Fetches the proactive disclosure listing page, extracts per-MP report links,
downloads each quarterly CSV (travel, hospitality, contracts, salaries),
and upserts into parliament.mp_expenses.

Runs weekly from run_parliament_sync(). Idempotent (UNIQUE on mp_id+period).
Only fetches reports for the current and previous fiscal years to keep it fast.
"""
import csv
import io
import logging
import re
import time
import urllib.request

from sqlalchemy import text

logger = logging.getLogger("wtf-ingest.mp_expenses")

_BASE = "https://www.ourcommons.ca"
_LIST_URL = "https://www.ourcommons.ca/ProactiveDisclosure/en/members"
_HEADERS = {
    "User-Agent": "Mozilla/5.0 WTFIngest (+https://what-the-fact.com)",
    "Accept": "text/html,application/xhtml+xml",
}
_SLEEP = 0.5
_ALLOWED_SCHEMAS = frozenset({"parliament"})


def _get(url: str, timeout: int = 20) -> bytes:
    req = urllib.request.Request(url, headers=_HEADERS)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def _parse_dollar(val: str):
    """Convert '$1,234.56' or '1234.56' to float, or None."""
    if not val:
        return None
    cleaned = re.sub(r"[,$\s]", "", val).strip()
    try:
        return float(cleaned)
    except ValueError:
        return None


def _extract_report_links(html: str) -> list[tuple[str, str]]:
    """Extract (report_id, quarter_label) from the members listing page."""
    # Pattern: /ProactiveDisclosure/en/members/{guid}/{year}/{quarter}
    pattern = r'href="/ProactiveDisclosure/en/members/([0-9a-f-]{36})/(\d{4})/(Q[1-4])"'
    matches = re.findall(pattern, html, re.IGNORECASE)
    seen = set()
    result = []
    for guid, year, quarter in matches:
        key = (guid, year, quarter)
        if key not in seen:
            seen.add(key)
            result.append((guid, f"{year}-{quarter}"))
    return result


def run_expenses_sync(engine, max_reports: int = 100) -> dict:
    """Fetch MP quarterly expense reports from Our Commons proactive disclosure."""
    try:
        html = _get(_LIST_URL).decode("utf-8", errors="ignore")
    except Exception as exc:
        logger.error("mp_expenses: failed to fetch listing: %s", exc)
        return {"error": str(exc)}

    links = _extract_report_links(html)
    if not links:
        logger.warning("mp_expenses: no report links found on listing page")
        return {"reports": 0, "inserted": 0}

    logger.info("mp_expenses: found %d report links", len(links))

    # Load MP slug → id map for name matching
    with engine.connect() as c:
        mp_rows = c.execute(text(
            "SELECT id, name, family_name FROM parliament.mps WHERE is_current = true"
        )).fetchall()
    # family name → mp_id
    family_idx = {(r[2] or "").strip().lower(): r[0] for r in mp_rows if r[2]}
    # full name → mp_id
    name_idx = {(r[1] or "").strip().lower(): r[0] for r in mp_rows if r[1]}

    inserted = 0
    reports_done = 0

    for guid, period in links[:max_reports]:
        csv_url = f"{_BASE}/ProactiveDisclosure/en/members/{guid}/csv"
        try:
            raw = _get(csv_url)
            text_content = raw.decode("utf-8-sig", errors="ignore")
            reader = csv.DictReader(io.StringIO(text_content))
            rows = list(reader)
        except Exception as exc:
            logger.debug("mp_expenses: CSV fetch failed %s: %s", csv_url, exc)
            time.sleep(_SLEEP)
            continue

        for row in rows:
            # Column names vary slightly across quarters — normalize
            name_val = (
                row.get("Name") or row.get("Member") or
                row.get("Nom") or ""
            ).strip()
            if not name_val:
                continue

            # Match by family name (last token before comma or last word)
            if "," in name_val:
                family = name_val.split(",")[0].strip().lower()
            else:
                family = name_val.split()[-1].lower() if name_val else ""

            mp_id = family_idx.get(family) or name_idx.get(name_val.lower())
            if not mp_id:
                continue

            try:
                with engine.begin() as c:
                    c.execute(text("""
                        INSERT INTO parliament.mp_expenses
                            (mp_id, period, travel_cad, hospitality_cad,
                             contracts_cad, salaries_cad, total_cad, source_url)
                        VALUES
                            (:mp, :period, :travel, :hosp, :contracts, :salaries, :total, :url)
                        ON CONFLICT (mp_id, period) DO UPDATE SET
                            travel_cad      = EXCLUDED.travel_cad,
                            hospitality_cad = EXCLUDED.hospitality_cad,
                            contracts_cad   = EXCLUDED.contracts_cad,
                            salaries_cad    = EXCLUDED.salaries_cad,
                            total_cad       = EXCLUDED.total_cad,
                            synced_at       = NOW()
                    """), {
                        "mp": mp_id,
                        "period": period,
                        "travel": _parse_dollar(row.get("Travel") or row.get("Déplacements")),
                        "hosp": _parse_dollar(row.get("Hospitality") or row.get("Accueil")),
                        "contracts": _parse_dollar(row.get("Contracts") or row.get("Contrats")),
                        "salaries": _parse_dollar(row.get("Salaries") or row.get("Salaires")),
                        "total": _parse_dollar(row.get("Total")),
                        "url": csv_url,
                    })
                inserted += 1
            except Exception as exc:
                logger.debug("mp_expenses: insert failed mp=%s period=%s: %s", mp_id, period, exc)

        reports_done += 1
        time.sleep(_SLEEP)

    logger.info("mp_expenses: reports=%d inserted=%d", reports_done, inserted)
    return {"reports": reports_done, "inserted": inserted}
