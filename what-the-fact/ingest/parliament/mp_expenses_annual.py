"""MP expenses for FY2009-10 to FY2014-15 from the House's ANNUAL per-member reports.

WHAT THESE ARE (measured 2026-10-07). Before the quarterly archive (FY2015 Q1 onward) the House published ONE report a
year, as a single PDF with one page per member:
    /proactivedisclosure/en/archive-members/expenditurereport/<code>        codes: 2009-2010 2010-2011 2011-2012 MER2013FY ...
    /proactivedisclosure/en/archive-members/expenditurebymember/<code>      the member list (name, riding, caucus)
Each page: "Name  Status  Constituency  size  electors", then labelled category lines, then a printed Total. The amounts are
the WHOLE fiscal year (Apr 1 - Mar 31), so this is stored in its own table (parliament.mp_expenses_annual), never mixed into
the quarterly series: a year cannot be split into quarters honestly.

THE RULES THAT KEEP THE NUMBERS HONEST
 1. Every member page is CHECKED: salaries + travel + hospitality + advertising + printing + offices must equal the page's
    own Total (to 5 cents), or the page is rejected and counted. A layout change fails loudly instead of loading a plausible
    wrong figure.
 2. The four stored categories match the quarterly series: salaries = cat 1, travel = cat 2, hospitality = cat 3,
    contracts = cats 4 + 5 + 6 (advertising, printing, offices — the House's "all other expenses"). The raw lines are kept in
    `detail` so nothing is lost by the fold.
 3. The Total includes BOTH columns, "Member's budget" and "Resources provided by the House" (e.g. householders printed
    centrally), as the House prints it. The later quarterly archive totals are comparable.
 4. A name that does not match is matched by RIDING (who held it that year), else skipped and counted — never guessed.

Run: python -m ingest.parliament.mp_expenses_annual [FY_FROM FY_TO]      (resumable: stored (mp, FY) rows are skipped)
"""
from __future__ import annotations

import io
import json
import logging
import re
import time
from datetime import date

from sqlalchemy import text

from ingest.parliament.mp_expenses import (_build_mp_index, _match_mp, _norm, build_term_index, family_of_index, riding_fallback_ok,
                                           seat_plausible)
from ingest.parliament.mp_expenses_archive import _BASE, _get, build_riding_index, match_by_riding, parse_member_list

logger = logging.getLogger("wtf-ingest.mp_expenses_annual")

# fiscal_year = the year the FY ENDS (FY2010 = Apr 2009 .. Mar 2010), the same convention as the quarterly archive.
ANNUAL_CODES: dict[int, str] = {2010: "2009-2010", 2011: "2010-2011", 2012: "2011-2012", 2013: "MER2013FY",
                                2014: "MER2014FY", 2015: "MER2015FY"}

_STATUS = r"(?:Active|(?:NR|NE|NSR|RS|DE|NEB)(?:\s*,\s*(?:NR|NE|NSR|RS|DE|NEB))*)"
# The header region (everything before the 'Category' row) is joined into ONE string first, because three layouts occur:
#   A  'Albrecht, Harold Active Kitchener-Conestoga 996 km² 84,665'
#   B  riding wrapped over lines, sometimes mid-word: 'Armstrong, Scott ... NEB Cumberland-Colchester-M / usquodoboit Valley / 10,086 km² 68,831'
#   C  part-year members: 'Abbott, Hon. Jim' / 'From April 1st to May 1st, 2011' / 'NSR Kootenay—Columbia 63,831 km² 67,663'
_HEADER = re.compile(
    rf"^(?P<name>.+?,\s.+?)\s+(?:From\s.+?\sto\s.+?\s)?(?P<status>{_STATUS})\s+(?P<riding>.+?)\s+[\d,\.]+\s*km.\s+(?P<electors>[\d,]+)\s*$")
_NUM = re.compile(r"^(?:-|\d{1,3}(?:,\d{3})*\.\d{2}|\d+\.\d{2})$")
_SECTION = re.compile(r"^([1-6])-")
_PAGE_MARK = re.compile(r"Member\s+Status\s+Constituency name", re.I)


def _money(tok: str) -> float:
    return 0.0 if tok == "-" else float(tok.replace(",", ""))


def _split_line(line: str):
    """(label, [numeric tokens]) — trailing tokens that are amounts or '-' are the numbers; the rest is the label."""
    toks = line.split()
    nums: list[str] = []
    while toks and _NUM.match(toks[-1]):
        nums.append(toks.pop())
    return " ".join(toks), nums[::-1]


def parse_member_block(block: str):
    """One member's page text -> record dict, or None when the page does not check out. `block` starts at the header row."""
    lines = [ln.strip() for ln in block.splitlines() if ln.strip()]
    cat = next((i for i, ln in enumerate(lines[:14]) if ln.startswith("Category")), None)
    if cat is None:
        return None
    head = _HEADER.match(" ".join(lines[:cat]))
    if head is None:
        return None
    start = cat + 1
    sections: dict[int, list[tuple[str, float]]] = {n: [] for n in range(1, 7)}
    section, pending, total = None, [], None
    for ln in lines[start:]:
        if ln.startswith("STATUS:") or re.match(r"^Page \d+ (of|de) \d+$", ln):
            break
        label, nums = _split_line(ln)
        sm = _SECTION.match(label) if label else None
        if label == "Total" and nums:
            total = _money(nums[-1])
            break
        if sm and not nums:                      # '2-Travel', '5-Printing', '6-Offices'
            section, pending = int(sm.group(1)), []
            continue
        if sm and nums:                          # '1-Employees' ... 212,325.80 ...', '3-Hospitality ...', '4-Advertising ...'
            section, pending = int(sm.group(1)), []
            sections[section].append((label, _money(nums[-1])))
            continue
        if not nums:                             # a wrapped label ('Informatics and telecommunication equipment' / 'purchases')
            if label and not label.startswith(("Category", "Budgets", "Resources", "by the House", "Reg.", "Travel Points", "Total (", "Member's Budgets")):
                pending.append(label)
            continue
        if section is None:
            continue
        full = " ".join(pending + [label]).strip()
        pending = []
        sections[section].append((full, _money(nums[-1])))
    if total is None:
        return None
    sums = {n: round(sum(v for _l, v in sections[n]), 2) for n in sections}
    salaries, travel, hospitality = sums[1], sums[2], sums[3]
    contracts = round(sums[4] + sums[5] + sums[6], 2)
    if abs(round(salaries + travel + hospitality + contracts, 2) - total) > 0.05:
        return None
    return {"name": head.group("name").strip(), "status": head.group("status").replace(" ", ""),
            "riding": head.group("riding").strip(), "salaries": salaries, "travel": travel, "hospitality": hospitality,
            "contracts": contracts, "total": total,
            "detail": {str(n): [{"line": lab, "cad": v} for lab, v in sections[n]] for n in sections if sections[n]}}


def split_members(full_text: str) -> list[str]:
    """Cut the whole report text into one block per member, at each page's column-header row."""
    parts = _PAGE_MARK.split(full_text)
    return [p.split("\n", 1)[1] if "\n" in p else p for p in parts[1:]]   # drop the header line's tail; block starts at the member row


def _is_vacant(block: str) -> bool:
    first = next((ln.strip() for ln in block.splitlines() if ln.strip()), "")
    return first.lower().startswith("vacant")


def parse_report(full_text: str) -> tuple[list[dict], int, int]:
    """(records, rejected_pages, vacant_pages). A page that does not parse or check out is counted, never loaded. A page for a
    VACANT seat has no member to attribute to (the party whip keeps services running) — it is counted on its own so it can
    never hide a real rejection."""
    recs, rejected, vacant = [], 0, 0
    for block in split_members(full_text):
        if _is_vacant(block):
            vacant += 1
            continue
        r = parse_member_block(block)
        if r is None:
            rejected += 1
        else:
            recs.append(r)
    return recs, rejected, vacant


def fy_dates(fy: int) -> tuple[date, date]:
    return date(fy - 1, 4, 1), date(fy, 3, 31)


def _pdf_text(data: bytes) -> str:
    import pypdf
    return "\n".join((p.extract_text() or "") for p in pypdf.PdfReader(io.BytesIO(data)).pages)


def run_annual_sync(engine, fy_from: int = 2010, fy_to: int = 2015, sleep: float = 0.5, get=_get, pdf_text=_pdf_text) -> dict:
    """Load every annual report in [fy_from, fy_to]. Resumable. Never raises on one bad report."""
    fam_idx, full_idx = _build_mp_index(engine)
    riding_idx = build_riding_index(engine)
    term_idx = build_term_index(engine)
    fam_of = family_of_index(fam_idx)
    stats = {"implausible": {}, "reports": 0, "stored": 0, "skipped_existing": 0, "matched_by_riding": 0, "rejected_pages": 0,
             "vacant_pages": 0, "unmatched": {}, "failed": [], "missing_codes": []}
    for fy, code in sorted(ANNUAL_CODES.items()):
        if not (fy_from <= fy <= fy_to):
            continue
        start, end = fy_dates(fy)
        try:
            members = parse_member_list(get(f"{_BASE}expenditurebymember/{code}").decode("utf-8", "ignore"))
            caucus_by_name = {_norm(m["name"]): m.get("caucus") for m in members}
            recs, rejected, vacant = parse_report(pdf_text(get(f"{_BASE}expenditurereport/{code}")))
        except Exception as exc:                    # one report failing must not stop the others
            stats["failed"].append(f"{code}: {exc}")
            logger.warning("mp_annual %s failed: %s", code, exc)
            continue
        stats["reports"] += 1
        stats["rejected_pages"] += rejected
        stats["vacant_pages"] += vacant
        with engine.connect() as c:
            have = {r[0] for r in c.execute(text("SELECT mp_id FROM parliament.mp_expenses_annual WHERE fiscal_year=:y"),
                                            {"y": fy})}
        for rec in recs:
            if rec["name"].lower().startswith("vacant"):
                continue
            mp_id = _match_mp(rec["name"], fam_idx, full_idx)
            if mp_id is not None and not seat_plausible(mp_id, start, end, term_idx):
                stats["implausible"][rec["name"]] = stats["implausible"].get(rec["name"], 0) + 1       # a namesake who was not in the seat
                mp_id = None
            if mp_id is None:
                holder = match_by_riding(riding_idx, rec["riding"], start, end)
                if riding_fallback_ok(rec["name"], holder, fam_idx, fam_of):
                    mp_id = holder
                    stats["matched_by_riding"] += 1
            if mp_id is None:
                stats["unmatched"][rec["name"]] = stats["unmatched"].get(rec["name"], 0) + 1
                continue
            if mp_id in have:
                stats["skipped_existing"] += 1
                continue
            with engine.begin() as c:
                c.execute(text("""
                    INSERT INTO parliament.mp_expenses_annual
                        (mp_id, fiscal_year, period_start, period_end, name_as_published, status, constituency, caucus,
                         salaries_cad, travel_cad, hospitality_cad, contracts_cad, total_cad, detail, source_code, source_url)
                    VALUES (:mp, :fy, :ps, :pe, :nm, :st, :rd, :cau, :sal, :trav, :hosp, :cont, :tot, CAST(:det AS jsonb), :code, :url)
                    ON CONFLICT (mp_id, fiscal_year) DO UPDATE SET
                        status = EXCLUDED.status, constituency = EXCLUDED.constituency, caucus = EXCLUDED.caucus,
                        salaries_cad = EXCLUDED.salaries_cad, travel_cad = EXCLUDED.travel_cad,
                        hospitality_cad = EXCLUDED.hospitality_cad, contracts_cad = EXCLUDED.contracts_cad,
                        total_cad = EXCLUDED.total_cad, detail = EXCLUDED.detail, synced_at = now()"""),
                    {"mp": mp_id, "fy": fy, "ps": start, "pe": end, "nm": rec["name"], "st": rec["status"],
                     "rd": rec["riding"], "cau": caucus_by_name.get(_norm(rec["name"])), "sal": rec["salaries"],
                     "trav": rec["travel"], "hosp": rec["hospitality"], "cont": rec["contracts"], "tot": rec["total"],
                     "det": json.dumps(rec["detail"]), "code": code,
                     "url": f"{_BASE}expenditurereport/{code}"})
            stats["stored"] += 1
        logger.info("mp_annual %s (FY%d): %d parsed, %d vacant, %d rejected", code, fy, len(recs), vacant, rejected)
        time.sleep(sleep)
    if stats["stored"] == 0 and stats["skipped_existing"] == 0:
        stats["error"] = "mp_expenses_annual stored 0 rows — the report layout may have changed"
        logger.error(stats["error"])
    return stats


if __name__ == "__main__":
    import os
    import sys
    from sqlalchemy import create_engine
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    eng = create_engine(os.environ["WTF_DATABASE_URL"], pool_pre_ping=True)
    a = [int(x) for x in sys.argv[1:3]]
    print(run_annual_sync(eng, *a))
