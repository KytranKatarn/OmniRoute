"""
GIC (Governor in Council) appointments ingest — Orders-in-Council database.

Source: https://orders-in-council.canada.ca/
The OIC site requires session-based search. This script uses Playwright to:
1. Load the search page
2. Submit the form with a date range
3. Paginate through results
4. Filter for appointment-related OICs
5. Upsert into gov_watch.gic_appointments

Run: python -m ingest.gov.gic_appointments [--from-date YYYY-MM-DD] [--pages N]

Requires: playwright, sqlalchemy
"""

import argparse
import os
import re
import sys
from datetime import date, timedelta

DB_URL = os.environ.get("WTF_DATABASE_URL", "")
OIC_BASE = "https://orders-in-council.canada.ca"
APPT_KEYWORDS = ("appoin", "appoin")  # catches "appointment" and "reappointment"


def _extract_name(precis: str) -> str | None:
    """Extract appointee name from precis text like 'Appointment of John Smith of Ottawa...'"""
    m = re.match(r"(?:Re-?)?[Aa]ppointment of ([A-Z][^\s].*?) of ", precis)
    return m.group(1).strip() if m else None


def _extract_org(subject: str) -> str | None:
    """Extract organization from subject like 'Appointment of a member of the CRTC'"""
    m = re.search(r"\b(?:of|to) the ([A-Z].{5,60})$", subject)
    return m.group(1).strip() if m else None


def ingest(from_date: str = None, max_pages: int = 100):
    """Scrape OIC appointments using Playwright browser automation."""
    if not DB_URL:
        print("ERROR: WTF_DATABASE_URL not set")
        sys.exit(1)

    if not from_date:
        from_date = (date.today() - timedelta(days=90)).isoformat()

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("ERROR: playwright not installed. Run: pip install playwright && playwright install chromium")
        sys.exit(1)

    print(f"Scraping OIC appointments from {from_date}...")
    rows = []

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(f"{OIC_BASE}/index.php?lang=en")

        # Fill and submit search form
        page.fill("#fromDate", from_date)
        page.fill("#toDate", date.today().isoformat())
        page.click("#btnSearch")
        page.wait_for_load_state("networkidle")

        seen = set()
        for p in range(1, max_pages + 1):
            if p > 1:
                page.goto(f"{OIC_BASE}/results.php?pageNum={p}&lang=en")

            trs = page.query_selector_all("tr")
            page_rows = 0
            for tr in trs:
                cells = tr.query_selector_all("td")
                if len(cells) < 9:
                    continue
                pc = cells[0].inner_text().strip()
                if not pc or pc in seen:
                    continue
                subject = cells[7].inner_text().strip()
                if not any(kw in subject.lower() for kw in APPT_KEYWORDS):
                    continue
                link = cells[0].query_selector("a")
                oic_date = cells[1].inner_text().strip()
                if oic_date < from_date:
                    browser.close()
                    break
                rows.append({
                    "pc_number": pc,
                    "oic_date": oic_date,
                    "department": cells[5].inner_text().strip(),
                    "subject": subject,
                    "precis": cells[8].inner_text().strip(),
                    "oic_url": link.get_attribute("href") if link else None,
                })
                seen.add(pc)
                page_rows += 1

            if page_rows == 0 or oic_date < from_date:
                break

        browser.close()

    print(f"  Scraped {len(rows)} appointment OICs")

    # Enrich with extracted name/org
    for r in rows:
        r["appointee_name"] = _extract_name(r["precis"]) if r["precis"] else None
        r["organization"] = _extract_org(r["subject"])

    # Upsert to DB
    from sqlalchemy import create_engine, text
    engine = create_engine(DB_URL)
    inserted = 0
    with engine.begin() as conn:
        conn.execute(text("CREATE SCHEMA IF NOT EXISTS gov_watch"))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS gov_watch.gic_appointments (
                id              SERIAL PRIMARY KEY,
                pc_number       TEXT UNIQUE NOT NULL,
                oic_date        DATE NOT NULL,
                department      TEXT,
                subject         TEXT NOT NULL,
                precis          TEXT,
                oic_url         TEXT,
                appointee_name  TEXT,
                organization    TEXT,
                scraped_at      TIMESTAMP DEFAULT NOW()
            )
        """))
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS idx_gic_date ON gov_watch.gic_appointments(oic_date DESC)"
        ))
        for row in rows:
            conn.execute(text("""
                INSERT INTO gov_watch.gic_appointments
                    (pc_number, oic_date, department, subject, precis, oic_url, appointee_name, organization)
                VALUES (:pc_number, :oic_date, :department, :subject, :precis, :oic_url, :appointee_name, :organization)
                ON CONFLICT (pc_number) DO UPDATE
                    SET oic_date=EXCLUDED.oic_date, department=EXCLUDED.department,
                        subject=EXCLUDED.subject, precis=EXCLUDED.precis,
                        oic_url=EXCLUDED.oic_url, appointee_name=EXCLUDED.appointee_name,
                        organization=EXCLUDED.organization, scraped_at=NOW()
            """), row)
            inserted += 1

    print(f"  Upserted {inserted} rows")
    print("Done.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--from-date", default=None)
    parser.add_argument("--pages", type=int, default=100)
    args = parser.parse_args()
    ingest(from_date=args.from_date, max_pages=args.pages)
