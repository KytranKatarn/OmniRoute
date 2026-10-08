"""Senators' QUARTERLY expenditure reports, Sept 2010 - June 2016 (the Senate's pre-2016-Q3 disclosure), one PDF per senator.

Source: https://sencanada.ca/ProactiveDisclosure/Documents/<END>/<END>_<Surname5><GivenInitial>.pdf  — still served for every
period on the Senate's own (now removed) "Past Reports" list (23 periods, 2010-09-01 .. 2016-06-30). The periods are Mar-May /
Jun-Aug / Sep-Nov / Dec-Feb (the last is the 4-month 2016-03-01..2016-06-30), NOT calendar quarters, so they live in their own
table (parliament.senator_expenses_legacy) and are never forced into senator_expenses' 'YYYY-Qn' periods.

Each PDF is one page, one row: five amounts under Staff & Office (1) | Hospitality | Living (NCR) | Travel 2a regular | Travel 2b
other. The PDF prints NO total, and pypdf's plain text does not keep the columns in header order, so the columns are read by
X-POSITION and the order is CHECKED against the header positions that are legible in the same PDF (a layout that disagrees is
rejected, never guessed). KNOWN GAPS in the file list (data/senate_legacy_codes.json, built by scripts/senate_legacy_discover.py): Lucie Pepin
and Luc Letellier de St-Just (left in 2011) and one 'O'Brien' (listed on the Senate's 2015 page as OBrieG, which 404s) could not be located;
senators first appointed after June 2016 correctly have no file in this window. A figure can be negative (a repayment: Duffy's Mar-May 2013 living expenses are -$17,126.12).
"""
import io
import json
import logging
import re
import time
import urllib.error
import urllib.request
from pathlib import Path

logger = logging.getLogger(__name__)

BASE = "https://sencanada.ca/ProactiveDisclosure/Documents/"
_HEADERS = {"User-Agent": "Mozilla/5.0 WTFIngest (+https://what-the-fact.com)"}

# (start, end) of every period on the Senate's Past Reports list (snapshot 2017-02-18 of sencanada.ca/en/ProActive/Archive).
PERIODS = [
    ("2010-09-01", "2010-11-30"), ("2010-12-01", "2011-02-28"), ("2011-03-01", "2011-05-31"), ("2011-06-01", "2011-08-31"),
    ("2011-09-01", "2011-11-30"), ("2011-12-01", "2012-02-29"), ("2012-03-01", "2012-05-31"), ("2012-06-01", "2012-08-31"),
    ("2012-09-01", "2012-11-30"), ("2012-12-01", "2013-02-28"), ("2013-03-01", "2013-05-31"), ("2013-06-01", "2013-08-31"),
    ("2013-09-01", "2013-11-30"), ("2013-12-01", "2014-02-28"), ("2014-03-01", "2014-05-31"), ("2014-06-01", "2014-08-31"),
    ("2014-09-01", "2014-11-30"), ("2014-12-01", "2015-02-28"), ("2015-03-01", "2015-05-31"), ("2015-06-01", "2015-08-31"),
    ("2015-09-01", "2015-11-30"), ("2015-12-01", "2016-02-29"), ("2016-03-01", "2016-06-30"),
]
COLUMNS = ("office", "hospitality", "living", "travel_regular", "travel_other")      # left -> right in every period
_AMT = re.compile(r"^\(?-?[\d,]+\.\d\d\)?$")
# header text legible in every layout -> the column it labels (the 'Regular'/'Other' travel headers are garbled before late 2012)
_HEADER_COL = (("Staff & Office", 0), ("Office(", 0), ("Hospitality", 1), ("Living Expenses", 2), ("Regular", 3), ("Other", 4))
_TITLE = re.compile(r"\bHON\.", re.I)


def url_for(end: str, code: str) -> str:
    return f"{BASE}{end}/{end}_{code}.pdf"


def _money(s: str) -> float:
    neg = s.startswith("(") or s.startswith("-")
    v = float(re.sub(r"[^\d.]", "", s))
    return -v if neg else v


def _fragments(pdf: bytes) -> list:
    """[(y, x, text)] for every text run on page 1 (PDF user-space coordinates)."""
    import pypdf
    out = []

    def visit(text, cm, tm, _fd, _fs):
        t = (text or "").strip()
        if t:
            out.append((round(tm[5] + cm[5], 1), round(tm[4] + cm[4], 1), t))
    pypdf.PdfReader(io.BytesIO(pdf)).pages[0].extract_text(visitor_text=visit)
    return out


def parse_pdf(pdf: bytes) -> dict | None:
    """parse_fragments() over the PDF's text runs; None for anything pypdf cannot read."""
    try:
        return parse_fragments(_fragments(pdf))
    except Exception as exc:
        logger.debug("senate_legacy: unreadable pdf: %s", exc)
        return None


def parse_fragments(fr: list) -> dict | None:
    """{name, office, hospitality, living, travel_regular, travel_other, total, layout_ok} or None when this is not a report row.

    `fr` = [(y, x, text)] text runs. None (never a guess) when the 'Quarter / Trimestre' row does not carry exactly five amounts."""
    q = [f for f in fr if f[2].startswith("Quarter /")]
    if not q:
        return None
    qy = q[0][0]
    # Amounts on the 'Quarter / Trimestre' row. A run may hold ONE amount (usual) or ALL FIVE after the label (2010 'DuffyM'), so
    # every run on the row is tokenised, left to right; the position of a token inside a multi-amount run is its order in the run.
    row = sorted((f for f in fr if abs(f[0] - qy) < 3), key=lambda f: f[1])
    amts = []                                                   # [(x, text)]
    for _y, x, t in row:
        toks = [tok for tok in t.replace("Quarter / Trimestre", " ").split() if _AMT.match(tok)]
        for k, tok in enumerate(toks):
            amts.append((x + k * 1e-3, tok))
    if len(amts) != 5:
        return None
    vals = [_money(a[1]) for a in amts]
    # English name: a run with 'HON.' that is not the French 'L'HON.' twin
    names = [f[2] for f in sorted(fr, key=lambda f: (-f[0], f[1])) if _TITLE.search(f[2]) and not f[2].upper().startswith("L'")]
    name = re.sub(r"\s+", " ", names[0]).strip() if names else None
    # the legible header columns must sit in the same left-to-right order as their amounts
    hx = {}
    for _y, x, t in fr:
        for key, col in _HEADER_COL:
            if t.startswith(key) and col not in hx and not (key == "Office(" and "Staff" in "".join(f[2] for f in fr if f[0] == _y)):
                hx[col] = x
    cols = sorted(hx)
    # >= 2 legible headers, in the same left-to-right order as the amounts they sit over (FY2011-12 garble the staff/office header).
    # Only possible when each amount is its own run (a multi-amount run has no per-amount x); those rows rely on the fixed order.
    ax = [a[0] for a in amts]
    layout_ok = len(cols) >= 2 and all(hx[a] < hx[b] for a, b in zip(cols, cols[1:])) and \
        all(ax[a] < ax[b] for a, b in zip(cols, cols[1:]))
    rec = dict(zip(COLUMNS, vals))
    rec.update({"name": name, "total": round(sum(vals), 2), "layout_ok": layout_ok})
    return rec


def normalise_name(name: str | None) -> tuple[str | None, str | None]:
    """'DOYLE, HON. NORMAN E.' / 'HON. DUFFY, MICHAEL' -> ('Doyle', 'Norman E.'); 'HON. RAYNELL ANDREYCHUK' -> (None, 'Raynell
    Andreychuk') (no comma: the family/given split is left to the matcher, which tries each split)."""
    if not name:
        return None, None
    n = re.sub(r"\bHON\.\s*", "", name, flags=re.I).strip()
    n = re.sub(r"\s+", " ", n)
    if "," in n:
        fam, giv = n.split(",", 1)
        return fam.strip().title(), giv.strip().title()
    return None, n.title()


def _get(url: str, timeout: int = 60):
    """bytes, or None on a 404 (a senator who did not sit that period has no file)."""
    last = None
    for attempt in range(3):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=_HEADERS), timeout=timeout) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            last = e
        except Exception as e:                      # timeouts, resets: retry
            last = e
        time.sleep(1.5 * (attempt + 1))
    raise last


CODES_FILE = Path(__file__).resolve().parent / "data" / "senate_legacy_codes.json"


def load_codes() -> list:
    """[{code, name, ...}] from the discovery file (scripts/senate_legacy_discover.py)."""
    return json.loads(CODES_FILE.read_text(encoding="utf-8"))


def match_published(name: str | None, fam_idx: dict, full_idx: dict):
    """A published name -> parliament.senators id, or None (never a guess). Comma forms go straight to the roster matcher; a
    'GIVEN FAMILY' form is tried with the family as the last 1, 2, then 3 words."""
    from ingest.parliament.senator_expenses import _match_senator
    fam, giv = normalise_name(name)
    if fam:
        return _match_senator(f"{fam}, {giv}", fam_idx, full_idx)
    toks = (giv or "").split()
    for k in (1, 2, 3):
        if len(toks) > k:
            sid = _match_senator(f"{' '.join(toks[-k:])}, {' '.join(toks[:-k])}", fam_idx, full_idx)
            if sid:
                return sid
    return None


def run_legacy_sync(engine, period_from: str = "2010-09-01", period_to: str = "2016-06-30", sleep: float = 0.15,
                    get=_get, codes: list | None = None, parse=parse_pdf) -> dict:
    """Load every (period, senator-code) report in range. Resumable (upsert on period_end + code). Never raises on one bad file.

    A file is stored only if it parses to exactly five amounts AND its legible headers agree with the amounts' order; anything
    else is counted in `unparsed`/`bad_layout` and left out. `per_period` reports how many senators and what total each period
    holds so a thin or oversized period is visible at once."""
    from sqlalchemy import text
    from ingest.parliament.senator_expenses import _load_senator_index
    fam_idx, full_idx = _load_senator_index(engine)
    codes = codes if codes is not None else load_codes()
    stats = {"stored": 0, "not_found": 0, "unparsed": [], "bad_layout": [], "name_mismatch": [], "unmatched_senator": {}, "per_period": {}, "failed": []}
    for start, end in PERIODS:
        if not (period_from <= start and end <= period_to):
            continue
        n, tot = 0, 0.0
        for c in codes:
            code = c["code"]
            try:
                data = get(url_for(end, code))
            except Exception as exc:
                stats["failed"].append(f"{end}/{code}: {exc}")
                continue
            if data is None:
                stats["not_found"] += 1
                continue
            rec = parse(data)
            if rec is None:
                stats["unparsed"].append(f"{end}/{code}")
                continue
            if not rec["layout_ok"]:
                stats["bad_layout"].append(f"{end}/{code}")
                continue
            # the file must carry the person the code was discovered for (a code can be reused by a different senator over time)
            if c.get("family") and c["family"].replace("-", " ").split()[-1] not in (rec["name"] or "").upper().replace("-", " "):
                stats["name_mismatch"].append(f"{end}/{code}: {rec['name']}")
                continue
            sid = match_published(rec["name"], fam_idx, full_idx)
            if sid is None:
                stats["unmatched_senator"][rec["name"]] = stats["unmatched_senator"].get(rec["name"], 0) + 1
            travel = round(rec["travel_regular"] + rec["travel_other"], 2)
            with engine.begin() as conn:
                conn.execute(text("""
                    INSERT INTO parliament.senator_expenses_legacy
                        (senator_id, name_as_published, period_start, period_end, office_cad, hospitality_cad, living_cad,
                         travel_regular_cad, travel_other_cad, travel_cad, total_cad, source_code, source_url)
                    VALUES (:sid, :nm, :ps, :pe, :o, :h, :l, :tr, :to, :t, :tot, :code, :url)
                    ON CONFLICT (period_end, source_code) DO UPDATE SET
                        senator_id = EXCLUDED.senator_id, name_as_published = EXCLUDED.name_as_published,
                        office_cad = EXCLUDED.office_cad, hospitality_cad = EXCLUDED.hospitality_cad, living_cad = EXCLUDED.living_cad,
                        travel_regular_cad = EXCLUDED.travel_regular_cad, travel_other_cad = EXCLUDED.travel_other_cad,
                        travel_cad = EXCLUDED.travel_cad, total_cad = EXCLUDED.total_cad, synced_at = now()"""),
                    {"sid": sid, "nm": rec["name"], "ps": start, "pe": end, "o": rec["office"], "h": rec["hospitality"],
                     "l": rec["living"], "tr": rec["travel_regular"], "to": rec["travel_other"], "t": travel, "tot": rec["total"],
                     "code": code, "url": url_for(end, code)})
            n += 1
            tot += rec["total"]
            stats["stored"] += 1
            time.sleep(sleep)
        stats["per_period"][end] = {"senators": n, "total": round(tot, 2)}
        logger.info("senate_legacy %s..%s: %d senators, $%s", start, end, n, f"{tot:,.0f}")
    if stats["stored"] == 0:
        stats["error"] = "senate_legacy stored 0 rows — the file list or layout may have changed"
        logger.error(stats["error"])
    return stats


if __name__ == "__main__":
    import os
    import sys
    from sqlalchemy import create_engine
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    eng = create_engine(os.environ["WTF_DATABASE_URL"], pool_pre_ping=True)
    a = sys.argv[1:3]
    print(json.dumps(run_legacy_sync(eng, *a), indent=1, default=str))
