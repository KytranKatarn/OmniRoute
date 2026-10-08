"""MP expenses before FY2021 Q2, from the House's per-member archive (Apr 2014 -> Mar 2020).

WHAT THE ARCHIVE IS (measured 2026-10-07). The current House site only serves per-member data from FY2021 Q2
(Jul 2020); earlier years are HTTP 500 there. The older reports live under
    /proactivedisclosure/en/archive-members/expenditurebymember/<code>        member list (name, riding, caucus)
    /proactivedisclosure/en/archive-members/expenditurebymember/<code>/<id>   that member's one-page PDF
with irregular report codes (mer2019q3-a, mer2020q2-1023, mer2017q4b ...) and no index page, so they are listed in
REPORT_CODES below rather than guessed at run time.

THREE THINGS THAT WOULD SILENTLY CORRUPT THE NUMBERS:
 1. The amounts are fiscal YEAR-TO-DATE (Aboultaif FY2019: $85.9K, $184.5K, $283.1K, $399.5K for Q1..Q4). They are
    stored as YTD; parliament.v_mp_expenses_archive_quarterly differences them. A quarter whose predecessor is
    missing is NOT derivable and is left out, never guessed.
 2. The archive has eight categories; the current site (and parliament.mp_expenses) has four. The House defines
    Contracts as "all other expenses ... service contracts, advertising, gifts, constituency office leases, office
    operations, and training", so: salaries = cat 1, travel = cat 3, hospitality = cat 4,
    contracts = cats 2 + 5 + 6 + 7 + 8, total = their sum. Verified: mp_expenses.total_cad == the sum of its four
    categories on all 8,799 rows, so the two sources are comparable.
 3. Every PDF is checked: the category sums must equal the PDF's own Total row (to 5 cents) or the row is rejected
    and counted — a wrong layout fails loudly instead of loading a plausible wrong figure.

Run: python -m ingest.parliament.mp_expenses_archive [FY_FROM FY_TO]     (resumable: stored rows are skipped)
"""
from __future__ import annotations

import io
import logging
import re
import time
import urllib.request
from datetime import date

from sqlalchemy import text

from ingest.parliament._retry import fetch_with_retry
from ingest.parliament.mp_expenses import (_build_mp_index, _match_mp, _quarter_label, build_term_index, family_of_index,
                                           riding_fallback_ok, seat_plausible)

logger = logging.getLogger("wtf-ingest.mp_expenses_archive")

_BASE = "https://www.ourcommons.ca/proactivedisclosure/en/archive-members/"
_HEADERS = {"User-Agent": "Mozilla/5.0 WTFIngest (+https://what-the-fact.com)"}
_SLEEP = 0.35

# (fiscal_year, quarter) -> report code. Probed 2026-10-07. Not found (yet): FY2015 Q2/Q4, FY2017 Q1/Q2.
REPORT_CODES: dict[tuple[int, int], str] = {
    (2015, 1): "mer2015q1", (2015, 3): "mer2015q3",
    (2016, 1): "mer2016q1", (2016, 2): "mer2016q2", (2016, 3): "mer2016q3", (2016, 4): "mer2016q4",
    (2017, 3): "mer2017q3b", (2017, 4): "mer2017q4b",
    (2018, 1): "mer2018q1", (2018, 2): "mer2018q2", (2018, 3): "mer2018q3", (2018, 4): "mer2018q4",
    (2019, 1): "mer2019q1", (2019, 2): "mer2019q2", (2019, 3): "mer2019q3-a", (2019, 4): "mer2019q4",
    (2020, 1): "mer2020q1-1019", (2020, 2): "mer2020q2-1023", (2020, 3): "mer2020q3-1035", (2020, 4): "mer2020q4-1037",
    (2021, 1): "mer2021q1-1041",     # Apr-Jun 2020: the quarter the current site does not serve (it starts at FY2021 Q2)
}

_STATUS = r"Active|DE|NR|NE|NSR|RS|NEB"
_TOKEN = re.compile(r"(\(?-?[\d,]+\.\d{2}\)?|(?<=\s)-)\s*$")
_PERIOD = re.compile(r"April 1, (\d{4}) to ([A-Z][a-z]+) (\d{1,2}), (\d{4})")
_MONTHS = {m: i for i, m in enumerate(
    ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
     "November", "December"], start=1)}


def _money(tok: str) -> float:
    """'12,094.86' -> 12094.86; '(1,234.00)' / '-1,234.00' -> negative; '-' -> 0."""
    tok = tok.strip()
    if tok == "-":
        return 0.0
    neg = tok.startswith("(") or tok.startswith("-")
    val = float(re.sub(r"[^\d.]", "", tok))
    return -val if neg else val


def parse_member_report(text_: str) -> dict | None:
    """One member's one-page report -> YTD amounts in the four current categories, or None if it does not check out."""
    lines = [l.strip() for l in text_.splitlines() if l.strip()]
    flat = "\n".join(lines)
    pm = _PERIOD.search(flat)
    if not pm:
        return None
    period_end = date(int(pm.group(4)), _MONTHS[pm.group(2)], int(pm.group(3)))

    status = riding = None
    for l in lines[:8]:
        m = re.match(rf"^(?P<name>.+?)\s+(?P<status>{_STATUS})\s+(?P<riding>.+?)\s+[\d,]+\s*km", l)
        if m:
            status, riding = m.group("status"), m.group("riding")
            break

    try:
        start = next(i for i, l in enumerate(lines) if l.startswith("Category"))
    except StopIteration:
        return None
    cats = {i: 0.0 for i in range(1, 9)}
    cur = None
    grand = None
    for l in lines[start + 1:]:
        if l.startswith("STATUS:"):
            break
        if l.startswith("Total "):
            tm = _TOKEN.search(l)
            grand = _money(tm.group(1)) if tm else None
            break
        hm = re.match(r"^([1-8])-", l)
        if hm:
            cur = int(hm.group(1))
        tm = _TOKEN.search(l)
        if tm and cur is not None:
            cats[cur] += _money(tm.group(1))
    if grand is None or cur is None:
        return None
    if abs(sum(cats.values()) - grand) > 0.05:
        return None                                   # the layout did not parse — refuse rather than load a wrong number
    return {
        "period_end": period_end, "status": status, "riding": riding,
        "salaries": round(cats[1], 2),
        "travel": round(cats[3], 2),
        "hospitality": round(cats[4], 2),
        "contracts": round(cats[2] + cats[5] + cats[6] + cats[7] + cats[8], 2),
        "total": round(grand, 2),
        "detail": {str(k): round(v, 2) for k, v in cats.items()},
    }


def parse_member_list(html_: str) -> list[dict]:
    """[{path, name, riding, province, caucus}] from an expenditurebymember/<code> page (de-duplicated by path)."""
    out, seen = [], set()
    for row in re.findall(r"<tr[^>]*>(.*?)</tr>", html_, re.S):
        m = re.search(r'ReportSelectionMemberLink"\s+href="([^"]+)"[^>]*>(.*?)</a>', row, re.S)
        if not m or m.group(1) in seen:
            continue
        seen.add(m.group(1))
        cells = [re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", c)).strip() for c in re.findall(r"<td[^>]*>(.*?)</td>", row, re.S)]
        cells = [c for c in cells if c]
        out.append({"path": m.group(1), "name": re.sub(r"\s+", " ", m.group(2)).strip(),
                    "riding": cells[1] if len(cells) > 1 else None,
                    "province": cells[2] if len(cells) > 2 else None,
                    "caucus": cells[3] if len(cells) > 3 else None})
    return out


def quarter_start(fy: int, fq: int) -> date:
    """First day of fiscal quarter fq of fiscal year fy."""
    return {1: date(fy - 1, 4, 1), 2: date(fy - 1, 7, 1), 3: date(fy - 1, 10, 1), 4: date(fy, 1, 1)}[fq]


def quarter_end(fy: int, fq: int) -> date:
    """Last day of fiscal quarter fq of fiscal year fy (FY2019 = Apr 2018 .. Mar 2019)."""
    return {1: date(fy - 1, 6, 30), 2: date(fy - 1, 9, 30), 3: date(fy - 1, 12, 31), 4: date(fy, 3, 31)}[fq]


def _riding_key(name: str | None) -> str:
    """Compare ridings across dash styles/case/spacing: 'Leeds—Grenville—Thousand Islands' == 'leeds-grenville-thousand islands'."""
    return re.sub(r"[^a-z0-9]", "", (name or "").lower().replace("é", "e").replace("è", "e").replace("ô", "o"))


def build_riding_index(engine) -> dict[str, list[tuple]]:
    """{riding_key: [(start, end, mp_id)]} from parliament.mp_terms — who held each riding when."""
    with engine.connect() as c:
        rows = c.execute(text("SELECT riding, start_date, end_date, mp_id FROM parliament.mp_terms "
                              "WHERE riding IS NOT NULL AND mp_id IS NOT NULL")).fetchall()
    idx: dict[str, list[tuple]] = {}
    for riding, start, end, mp in rows:
        idx.setdefault(_riding_key(riding), []).append((start, end, mp))
    return idx


def match_by_riding(idx: dict, riding: str | None, q_start: date, q_end: date):
    """The single MP whose stint for `riding` OVERLAPS the quarter, else None.

    Overlap, not 'held it on the last day': a member who left or died mid-quarter (Gord Brown, May 2018) still has that
    quarter's report. Zero or several holders => None — never guess a person for money figures."""
    holders = {mp for (start, end, mp) in idx.get(_riding_key(riding), [])
               if start <= q_end and (end is None or end >= q_start)}
    return holders.pop() if len(holders) == 1 else None


def _get(url: str, timeout: int = 60) -> bytes:
    def _once():
        with urllib.request.urlopen(urllib.request.Request(url, headers=_HEADERS), timeout=timeout) as r:
            return r.read()
    return fetch_with_retry(_once, label="mp_archive " + url[-40:])


def _pdf_text(data: bytes) -> str:
    import pypdf
    return "\n".join((p.extract_text() or "") for p in pypdf.PdfReader(io.BytesIO(data)).pages)


def run_archive_sync(engine, fy_from: int = 2015, fy_to: int = 2021, sleep: float = _SLEEP,
                     get=_get, pdf_text=_pdf_text) -> dict:
    """Load every archive member report in [fy_from, fy_to]. Resumable: stored (mp, FY, Q) rows are skipped."""
    fam_idx, full_idx = _build_mp_index(engine)
    riding_idx = build_riding_index(engine)
    term_idx = build_term_index(engine)
    fam_of = family_of_index(fam_idx)
    stats = {"implausible": {}, "matched_by_riding": 0, "reports": 0, "stored": 0, "skipped_existing": 0, "unmatched": {}, "rejected": 0, "failed": 0,
             "missing_codes": []}
    for (fy, fq), code in sorted(REPORT_CODES.items()):
        if not (fy_from <= fy <= fy_to):
            continue
        try:
            members = parse_member_list(get(f"{_BASE}expenditurebymember/{code}").decode("utf-8", "ignore"))
        except Exception as exc:
            stats["missing_codes"].append(f"{code}: {exc}")
            continue
        stats["reports"] += 1
        with engine.connect() as c:
            have = {r[0] for r in c.execute(text(
                "SELECT mp_id FROM parliament.mp_expenses_archive WHERE fiscal_year=:y AND fq=:q"), {"y": fy, "q": fq})}
        for mem in members:
            qs, qe = quarter_start(fy, fq), quarter_end(fy, fq)
            mp_id = _match_mp(mem["name"], fam_idx, full_idx)
            if mp_id is not None and not seat_plausible(mp_id, qs, qe, term_idx):
                stats["implausible"][mem["name"]] = stats["implausible"].get(mem["name"], 0) + 1     # a namesake who was not in the seat then
                mp_id = None
            if mp_id is None and not mem["name"].lower().startswith("vacant"):
                # surname changes / nicknames / shared surnames defeat the name match; who held the RIDING that day does not — but only
                # when the surnames agree (or the published surname is unknown), else the published person is a DIFFERENT, unmatched MP
                holder = match_by_riding(riding_idx, mem.get("riding"), qs, qe)
                if riding_fallback_ok(mem["name"], holder, fam_idx, fam_of):
                    mp_id = holder
                    stats["matched_by_riding"] += 1
            if mp_id is None:
                stats["unmatched"][mem["name"]] = stats["unmatched"].get(mem["name"], 0) + 1
                continue
            if mp_id in have:
                stats["skipped_existing"] += 1
                continue
            url = f"{_BASE}expenditurebymember/{mem['path']}".replace("expenditurebymember/", "expenditurereport/", 1)
            try:
                rec = parse_member_report(pdf_text(get(url)))
            except Exception as exc:
                stats["failed"] += 1
                logger.warning("mp_archive %s %s failed: %s", code, mem["name"], exc)
                time.sleep(sleep)
                continue
            if rec is None:
                stats["rejected"] += 1
                logger.warning("mp_archive %s %s: report did not check out (rejected)", code, mem["name"])
                time.sleep(sleep)
                continue
            import json
            with engine.begin() as c:
                c.execute(text("""
                    INSERT INTO parliament.mp_expenses_archive
                        (mp_id, fiscal_year, fq, period, period_end, status, constituency, caucus,
                         ytd_salaries_cad, ytd_travel_cad, ytd_hospitality_cad, ytd_contracts_cad, ytd_total_cad,
                         ytd_detail, source_code, source_url)
                    VALUES (:mp, :fy, :fq, :period, :pend, :status, :riding, :caucus, :sal, :trav, :hosp, :cont,
                            :total, CAST(:detail AS jsonb), :code, :url)
                    ON CONFLICT (mp_id, fiscal_year, fq) DO UPDATE SET
                        ytd_salaries_cad = EXCLUDED.ytd_salaries_cad, ytd_travel_cad = EXCLUDED.ytd_travel_cad,
                        ytd_hospitality_cad = EXCLUDED.ytd_hospitality_cad, ytd_contracts_cad = EXCLUDED.ytd_contracts_cad,
                        ytd_total_cad = EXCLUDED.ytd_total_cad, ytd_detail = EXCLUDED.ytd_detail, synced_at = now()"""),
                    {"mp": mp_id, "fy": fy, "fq": fq, "period": _quarter_label(fy, fq), "pend": rec["period_end"],
                     "status": rec["status"], "riding": rec["riding"] or mem["riding"], "caucus": mem["caucus"],
                     "sal": rec["salaries"], "trav": rec["travel"], "hosp": rec["hospitality"],
                     "cont": rec["contracts"], "total": rec["total"], "detail": json.dumps(rec["detail"]),
                     "code": code, "url": _BASE + "expenditurereport/" + mem["path"]})
            stats["stored"] += 1
            time.sleep(sleep)
        logger.info("mp_archive %s: %d members", code, len(members))

    if stats["stored"] == 0 and stats["skipped_existing"] == 0:
        stats["error"] = "mp_expenses_archive stored 0 rows — the archive layout may have changed"
        logger.error(stats["error"])
    try:
        with engine.begin() as c:
            c.execute(text("INSERT INTO parliament.ingest_log (task, records_fetched, records_upserted, error) "
                           "VALUES ('mp_expenses_archive', :f, :u, :e)"),
                      {"f": stats["stored"] + stats["rejected"] + stats["failed"], "u": stats["stored"],
                       "e": stats.get("error")})
    except Exception as exc:
        logger.warning("mp_expenses_archive: ingest_log write failed: %s", exc)
    stats["unmatched_names"] = len(stats["unmatched"])
    return stats


if __name__ == "__main__":
    import os
    import sys
    from sqlalchemy import create_engine
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    eng = create_engine(os.environ["WTF_DATABASE_URL"], pool_pre_ping=True)
    a = [int(x) for x in sys.argv[1:3]]
    print(run_archive_sync(eng, *a))
