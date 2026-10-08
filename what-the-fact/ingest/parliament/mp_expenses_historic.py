"""House of Commons ANNUAL per-member expenditure reports for FY2002-FY2009 (April 2001 - March 2009) — TOTALS ONLY.

Source: https://www.ourcommons.ca/Content/Boie/pdf/MembersExpenses-<YYYY>-<YYYY>-e.pdf (one text PDF per fiscal year, a table row
per member). These old tables have NO per-member total column and OMIT blank cells, so a member's category split is ambiguous.
What is reliable is the SUM of every dollar amount in the member's row, and that is all this loader stores (the four category
columns stay NULL — never guessed). That sum covers the member's office budget plus the goods and services the House provided,
the same two parts as the printed total in the FY2010+ reports (see mp_expenses_annual.py), but the old tables list fewer
categories, so a year-on-year step at the FY2009/FY2010 boundary is partly definitional and the page says so.

CHECKSUM: the sum over all parsed members must equal the report's own printed Total row to within rounding (RECONCILE_TOLERANCE;
vacant seats are part of that total, so they are parsed and counted but not attributed to a member). The checksum cannot see an
amount moved between two ADJACENT members (the sum is unchanged), so the parser also rejects any member row with an implausible
amount count. A year that does not reconcile is reported and NOT stored.

fiscal_year = the year the FY ENDS (FY2002 = 1 Apr 2001 - 31 Mar 2002), as in mp_expenses_annual.
"""
import io
import json
import logging
import re
import time

from sqlalchemy import text

from ingest.parliament.mp_expenses import _build_mp_index, _match_mp, _norm
from ingest.parliament.mp_expenses_annual import fy_dates
from ingest.parliament.mp_expenses_archive import _get, build_riding_index, match_by_riding

logger = logging.getLogger(__name__)

URL = "https://www.ourcommons.ca/Content/Boie/pdf/MembersExpenses-{code}-e.pdf"
HIST_YEARS = list(range(2002, 2010))
# The report prints each member's cell rounded to the dollar and the Total row rounded separately, so the member sum can differ
# from the printed total by a few dollars across ~3,000 cells (measured FY2002-FY2009: 0-42). A real misparse moves it by thousands.
RECONCILE_TOLERANCE = 100
# A member row has 2-13 dollar amounts (office-budget staff + lease are always there; at most ~13 columns). Outside that the row
# was split or merged wrongly — and the sum checksum cannot see an amount moved between two neighbours, this can.
MIN_AMOUNTS, MAX_AMOUNTS = 2, 14


def hist_code(fy: int) -> str:
    return f"{fy - 1}-{fy}"


_AMT = re.compile(r"\$\s?(\d[\d,]*)")
_NAME = re.compile(r"^[^\W\d_][\w'’.\- ]*,\s+(?:Hon\.\s+)?[^\W\d_][\w'’.\- ]*$", re.UNICODE)
_STATUS = re.compile(r"^(DE|NR|NE|NSR|RS|BY|NEB)$")
_SPLIT_DIGITS = re.compile(r"(\$\d[\d,]*\d) (\d{1,3})(?=\s|\$|$)")      # '$3,386,76 3' -> '$3,386,763' (the PDF breaks a long number)
_SPLIT_COMMA = re.compile(r"(\$\d[\d,]*,) (\d)")                              # '$27,482, 069' -> '$27,482,069'


def _amounts(line: str) -> list[int]:
    line = _SPLIT_DIGITS.sub(r"\1\2", _SPLIT_COMMA.sub(r"\1\2", line))
    return [int(m.replace(",", "")) for m in _AMT.findall(line)]


def _is_pure(line: str) -> bool:
    """Only dollar amounts (and footnote asterisks) — no riding or name text."""
    return "$" in line and not re.sub(r"\$\s?[\d,]+|[*\s]", "", line)


def _is_name(line: str) -> bool:
    s = line.strip()
    if s.lower() == "vacant":                       # a vacant seat: its own row, with real money against it, in the printed total
        return True
    if not (s and "$" not in s and len(s) <= 60 and _NAME.match(s)) or s.startswith(("Members ", "Total")):
        return False
    given = s.split(",", 1)[1].strip()
    return bool(given) and (given[0].isupper())      # a footnote like 'Travel, has been fully used.' is not a member


def _riding_only(line: str) -> bool:
    s = line.strip()
    return bool(s) and "$" not in s and "," not in s and len(s) <= 60 and not _STATUS.match(s)


def _lines(full_text: str) -> list[str]:
    """Data lines only: pages that carry a member table (>= 8 dollar amounts). Prose pages and headers fall away."""
    out = []
    for page in full_text.split("\f"):
        if len(_AMT.findall(page)) < 8:
            continue
        out.extend(ln.strip() for ln in page.splitlines() if ln.strip())
    return out


def printed_total(lines: list[str]) -> int | None:
    """The report's own Total row: the 'Total ...' line plus any wrapped continuation amount lines (within 3 lines)."""
    for i, ln in enumerate(lines):
        if ln.startswith("Total") and len(_amounts(ln)) >= 6:
            tot = sum(_amounts(ln))
            for nxt in lines[i + 1:i + 4]:
                if _is_pure(nxt):
                    tot += sum(_amounts(nxt))
            return tot
    return None


def parse_report(full_text: str) -> dict:
    """{'members': [{name, riding, status, total, n_amounts}], 'vacant': n, 'sum': int, 'printed_total': int|None}.

    Two layouts: 'post' (FY2002: name line, then riding + all amounts on one line) and 'pre' (FY2003-FY2009: an amounts line
    [with the riding glued on, or the riding on the next line], the name line, then a second amounts line)."""
    lines = _lines(full_text)
    names = [i for i, ln in enumerate(lines) if _is_name(ln)]
    # 'post' (FY2002): the line AFTER the first name carries the riding AND the amounts; in 'pre' it is a pure amounts line
    style = "post" if names and names[0] + 1 < len(lines) and "$" in lines[names[0] + 1] and not _is_pure(lines[names[0] + 1]) else "pre"
    members, vacant = [], 0
    for k in names:
        nm = lines[k]
        amts, riding, status = [], None, None
        if style == "post":
            if k + 1 < len(lines) and "$" in lines[k + 1]:
                amts = _amounts(lines[k + 1])
                riding = re.sub(r"\$\s?[\d,]+|\*", "", lines[k + 1]).strip() or None
        else:
            a = k - 1
            rid = []
            while a >= 0 and len(rid) < 3 and _riding_only(lines[a]):   # riding on its own line(s) (FY2009; long ones wrap): amounts are above
                rid.insert(0, lines[a].strip())
                a -= 1
            if rid:
                riding = " ".join(rid)
            if a >= 0 and "$" in lines[a]:
                amts += _amounts(lines[a])
                if riding is None:
                    riding = re.sub(r"\$\s?[\d,]+|\*", "", lines[a]).strip() or None
            j = k + 1
            while j < len(lines) and _is_pure(lines[j]):
                m = j + 1
                while m < len(lines) and m - j <= 3 and _riding_only(lines[m]) and not _is_name(lines[m]):
                    m += 1
                nxt_is_a = m > j + 1 and m < len(lines) and _is_name(lines[m])
                if nxt_is_a:                                   # this pure line is the NEXT member's, with the status blank
                    break
                amts += _amounts(lines[j])
                j += 1
            if j < len(lines) and _STATUS.match(lines[j].strip()):
                status = lines[j].strip()
        if nm.lower().startswith("vacant"):
            vacant += 1
            members.append({"name": nm, "riding": riding, "status": status, "total": sum(amts), "n_amounts": len(amts),
                            "vacant": True})
            continue
        members.append({"name": nm, "riding": riding, "status": status, "total": sum(amts), "n_amounts": len(amts),
                        "vacant": False})
    suspect = [m["name"] for m in members if not m["vacant"] and not (MIN_AMOUNTS <= m["n_amounts"] <= MAX_AMOUNTS)]
    return {"members": members, "vacant": vacant, "sum": sum(m["total"] for m in members),
            "printed_total": printed_total(lines), "style": style, "suspect": suspect}


def _tied_candidates(name: str, fam_idx: dict) -> list:
    """mp_ids sharing the published surname AND tying for the best given-name overlap — the set `_match_mp` refuses to choose
    between (e.g. 'Norman Doyle' and 'Norman E. Doyle': one person stored as two records with disjoint stints)."""
    n = _norm(name)
    if "," not in n:
        return []
    fam, given = n.split(",", 1)[0].strip(), set(n.split(",", 1)[1].split())
    cands = fam_idx.get(fam) or (fam_idx.get(fam.split()[-1]) if fam else None) or []
    if len(cands) < 2:
        return []
    best = max(len(given & c["given"]) for c in cands)
    return [c["id"] for c in cands if best > 0 and len(given & c["given"]) == best]


def build_term_index(engine) -> dict:
    """{mp_id: [(start, end|None)]} from parliament.mp_terms — which MP held a seat when."""
    with engine.connect() as c:
        rows = c.execute(text("SELECT mp_id, start_date, end_date FROM parliament.mp_terms WHERE mp_id IS NOT NULL")).fetchall()
    idx: dict = {}
    for mp, s, e in rows:
        idx.setdefault(mp, []).append((s, e))
    return idx


def resolve_ids(recs: list, fam_idx: dict, full_idx: dict, riding_idx: dict, start, end, term_idx: dict | None = None) -> list:
    """[(rec, mp_id|None, how)] for one fiscal year. Name first, then riding (never a guess).

    A COLLISION — two published members resolving to the SAME mp_id in one year — means one name match is wrong (two people
    called David Anderson sat in this period; the database held only one name match). The record whose RIDING agrees with the id
    keeps it; the others fall back to their own riding holder, or stay unmatched. Without this the second row would silently
    overwrite the first (UNIQUE mp_id, fiscal_year) and charge a Liberal minister's office to a Conservative backbencher."""
    first = []
    for rec in recs:
        by_name = _match_mp(rec["name"], fam_idx, full_idx)
        holder = match_by_riding(riding_idx, rec["riding"], start, end)
        tied_how = None
        if by_name is None and holder is None and term_idx:
            # Ambiguous name AND no riding answer: keep only the candidates with a stint overlapping THIS fiscal year; exactly one
            # left is that person, none or several stays unmatched. (Doyle: his FY2006 riding was renamed, and in FY2009 two members
            # held St. John's East — the riding is silent, the stints are not.)
            live = [i for i in _tied_candidates(rec["name"], fam_idx)
                    if any(s <= end and (e is None or e >= start) for s, e in term_idx.get(i, ()))]
            if len(live) == 1:
                by_name, tied_how = live[0], "name-term"
        first.append([rec, by_name if by_name is not None else holder,
                      tied_how or ("name" if by_name is not None else ("riding" if holder else None)), holder])
    claims: dict = {}
    for row in first:
        if row[1] is not None:
            claims.setdefault(row[1], []).append(row)
    for mp_id, rows in claims.items():
        if len(rows) < 2:
            continue
        agree = [r for r in rows if r[3] == mp_id]
        keep = agree[0] if len(agree) == 1 else None
        for r in rows:
            if r is keep:
                continue
            r[1], r[2] = (r[3], "riding-collision") if (r[3] is not None and r[3] != mp_id and r[3] not in claims) else (None, "ambiguous")
    return [(r[0], r[1], r[2]) for r in first]


def _pdf_text(data: bytes) -> str:
    import pypdf
    return "\f".join((p.extract_text() or "") for p in pypdf.PdfReader(io.BytesIO(data)).pages)


def run_historic_sync(engine, fy_from: int = 2002, fy_to: int = 2009, sleep: float = 0.5, get=_get, pdf_text=_pdf_text) -> dict:
    """Load every report in [fy_from, fy_to] that RECONCILES to its printed total. Resumable; never raises on one bad year."""
    fam_idx, full_idx = _build_mp_index(engine)
    riding_idx = build_riding_index(engine)
    term_idx = build_term_index(engine)
    stats = {"reports": 0, "stored": 0, "skipped_existing": 0, "matched_by_riding": 0, "vacant": 0,
             "unmatched": {}, "unreconciled": [], "failed": []}
    for fy in HIST_YEARS:
        if not (fy_from <= fy <= fy_to):
            continue
        code = hist_code(fy)
        start, end = fy_dates(fy)
        try:
            rep = parse_report(pdf_text(get(URL.format(code=code))))
        except Exception as exc:
            stats["failed"].append(f"{code}: {exc}")
            logger.warning("mp_historic %s failed: %s", code, exc)
            continue
        if rep["suspect"]:
            stats["unreconciled"].append({"fy": fy, "suspect_rows": rep["suspect"][:5]})
            logger.error("mp_historic FY%d has implausible member rows: %s", fy, rep["suspect"][:5])
            continue
        if rep["printed_total"] is None or abs(rep["sum"] - rep["printed_total"]) > RECONCILE_TOLERANCE:
            stats["unreconciled"].append({"fy": fy, "sum": rep["sum"], "printed": rep["printed_total"]})
            logger.error("mp_historic FY%d does not reconcile: members %s vs printed %s", fy, rep["sum"], rep["printed_total"])
            continue
        stats["reports"] += 1
        stats["vacant"] += rep["vacant"]
        with engine.connect() as c:
            have = {r[0] for r in c.execute(text("SELECT mp_id FROM parliament.mp_expenses_annual WHERE fiscal_year=:y"), {"y": fy})}
        live = [r for r in rep["members"] if not r["vacant"]]
        for rec, mp_id, how in resolve_ids(live, fam_idx, full_idx, riding_idx, start, end, term_idx):
            if how in ("riding", "riding-collision"):
                stats["matched_by_riding"] += 1
            if mp_id is None:
                key = rec["name"] + (" [ambiguous]" if how == "ambiguous" else "")
                stats["unmatched"][key] = stats["unmatched"].get(key, 0) + 1
                continue
            if mp_id in have:
                stats["skipped_existing"] += 1
                continue
            with engine.begin() as c:
                c.execute(text("""
                    INSERT INTO parliament.mp_expenses_annual
                        (mp_id, fiscal_year, period_start, period_end, name_as_published, status, constituency,
                         salaries_cad, travel_cad, hospitality_cad, contracts_cad, total_cad, detail, source_code, source_url)
                    VALUES (:mp, :fy, :ps, :pe, :nm, :st, :rd, NULL, NULL, NULL, NULL, :tot, CAST(:det AS jsonb), :code, :url)
                    ON CONFLICT (mp_id, fiscal_year) DO UPDATE SET
                        status = EXCLUDED.status, constituency = EXCLUDED.constituency, total_cad = EXCLUDED.total_cad,
                        detail = EXCLUDED.detail, synced_at = now()"""),
                    {"mp": mp_id, "fy": fy, "ps": start, "pe": end, "nm": rec["name"], "st": rec["status"],
                     "rd": rec["riding"], "tot": rec["total"],
                     "det": json.dumps({"basis": "total_only", "n_amounts": rec["n_amounts"]}), "code": "hist-" + code,
                     "url": URL.format(code=code)})
            stats["stored"] += 1
        logger.info("mp_historic %s (FY%d): %d rows, %d vacant, sum %s", code, fy, len(rep["members"]), rep["vacant"], rep["sum"])
        time.sleep(sleep)
    if stats["stored"] == 0 and stats["skipped_existing"] == 0:
        stats["error"] = "mp_expenses_historic stored 0 rows — the report layout may have changed"
        logger.error(stats["error"])
    return stats


if __name__ == "__main__":
    import os
    import sys
    from sqlalchemy import create_engine
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    eng = create_engine(os.environ["WTF_DATABASE_URL"], pool_pre_ping=True)
    a = [int(x) for x in sys.argv[1:3]]
    print(run_historic_sync(eng, *a))
