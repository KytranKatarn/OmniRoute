"""ethics_disclosures.py — Ethics Commissioner disclosure link ingest.

Scrapes the CIEC public disclosures listing page to collect per-MP
disclosure document links. Stores link-only (no PDF parsing in v1).
Upserts into parliament.mp_disclosures.

URL: https://ciec-ccie.parl.gc.ca/en/disclosures/
Runs weekly. Idempotent (UNIQUE on mp_id+disclosure_year+disclosure_type).
"""
import logging
import re
import time
import urllib.request

from sqlalchemy import text

logger = logging.getLogger("wtf-ingest.ethics")

_BASE = "https://ciec-ccie.parl.gc.ca"
_LIST_URL = "https://ciec-ccie.parl.gc.ca/en/disclosures/"
_HEADERS = {
    "User-Agent": "Mozilla/5.0 WTFIngest (+https://what-the-fact.com)",
    "Accept": "text/html",
}
_SLEEP = 0.3


def _get(url: str) -> str:
    req = urllib.request.Request(url, headers=_HEADERS)
    with urllib.request.urlopen(req, timeout=20) as r:
        return r.read().decode("utf-8", errors="ignore")


def _extract_year(text_content: str) -> int | None:
    m = re.search(r"20(2[0-9]|1[0-9])", text_content)
    return int(m.group(0)) if m else None


def run_ethics_sync(engine) -> dict:
    """Scrape Ethics Commissioner disclosure list and store links per MP."""
    try:
        html = _get(_LIST_URL)
    except Exception as exc:
        logger.error("ethics: failed to fetch listing: %s", exc)
        return {"error": str(exc)}

    # Load MP name → id map
    with engine.connect() as c:
        mp_rows = c.execute(text(
            "SELECT id, name, family_name FROM parliament.mps WHERE is_current = true"
        )).fetchall()
    family_idx = {(r[2] or "").strip().lower(): r[0] for r in mp_rows if r[2]}
    name_idx = {(r[1] or "").strip().lower(): r[0] for r in mp_rows if r[1]}

    # Extract disclosure links — patterns vary but links usually contain
    # /en/disclosures/ followed by MP-slug-like path or year
    # Example: /en/disclosures/public-declarations/trudeau-justin-2024
    link_pattern = re.compile(
        r'href="(/en/disclosures/[^"]+)"[^>]*>([^<]{5,80})<',
        re.IGNORECASE
    )
    matches = link_pattern.findall(html)

    inserted = 0
    skipped = 0

    for path, label in matches:
        label = label.strip()
        # Try to extract year from path or label
        year = _extract_year(path) or _extract_year(label)

        # Try to extract MP name from path (slug-style: last-name-first-name-year)
        slug_parts = path.strip("/").split("/")
        if not slug_parts:
            skipped += 1
            continue

        last_part = slug_parts[-1] if slug_parts[-1].isdigit() else slug_parts[-1]
        # If last part is a year, use second-to-last
        if last_part.isdigit() and len(slug_parts) >= 2:
            name_slug = slug_parts[-2]
        else:
            name_slug = last_part

        # Try matching family name from slug (first token before hyphen)
        family_from_slug = name_slug.split("-")[0].lower()
        mp_id = family_idx.get(family_from_slug)

        # Also try full label as name
        if not mp_id:
            mp_id = name_idx.get(label.lower())

        if not mp_id:
            skipped += 1
            continue

        disc_url = _BASE + path if path.startswith("/") else path
        disc_type = "public"
        if "initial" in path.lower():
            disc_type = "initial"
        elif "annual" in path.lower():
            disc_type = "annual"

        try:
            with engine.begin() as c:
                c.execute(text("""
                    INSERT INTO parliament.mp_disclosures
                        (mp_id, disclosure_year, disclosure_type, disclosure_url)
                    VALUES (:mp, :yr, :dtype, :url)
                    ON CONFLICT (mp_id, disclosure_year, disclosure_type) DO UPDATE SET
                        disclosure_url = EXCLUDED.disclosure_url,
                        synced_at = NOW()
                """), {
                    "mp": mp_id,
                    "yr": year or 0,
                    "dtype": disc_type,
                    "url": disc_url,
                })
            inserted += 1
        except Exception as exc:
            logger.debug("ethics: insert failed mp=%s: %s", mp_id, exc)
            skipped += 1

    logger.info("ethics: inserted=%d skipped=%d", inserted, skipped)
    return {"inserted": inserted, "skipped": skipped}
