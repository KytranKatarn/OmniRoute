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
import unicodedata
from datetime import date
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
_AMOUNT = re.compile(r"\(?-?\d{1,3}(?:,\d{3})*\.\d\d\)?")   # one amount, thousands grouping included; cut out of the glued Quarter row
_CELL_GAP = 30.0        # points: runs this close to the previous run on the Quarter row are pieces of ONE amount (widest seen: 22.7)
# header text legible in every layout -> the column it labels (the 'Regular'/'Other' travel headers are garbled before late 2012)
_HEADER_COL = (("Staff & Office", 0), ("Office(", 0), ("Hospitality", 1), ("Living Expenses", 2), ("Regular", 3), ("Other", 4))
_TITLE = re.compile(r"\bHON\b\.?", re.I)                 # 'HON. X' and, in some periods, 'HON X' (no period)


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
    # The Quarter row is read as ONE character stream, not cell by cell. A cell is a run of text runs within _CELL_GAP points of each other
    # (kerning shifts the pieces of one amount by up to ~23pt: '2,041' then '.58'), but an amount can also START in one cell and END in the
    # next, a whole column away ('0.00 4,' ... '867.92' is one run '0 4,' and four pieces at x=654: 4,867.92 — the old cell-by-cell reading
    # either refused such a row or, in 3 stored rows, kept only '867.92'). So the cells are glued left to right in stream order and the
    # amounts are CUT OUT of the glued text with a strict amount grammar: an amount ends at its first '.dd', which is unambiguous.
    #   * A dropped fragment cannot hide: after the amounts are removed, anything left over on the row (a stray '5,9', a word) makes the
    #     whole row None. Fail closed, never a wrong figure.
    #   * Thousands grouping is part of the grammar, so a mis-glue ('5,9'+'2.50' = '5,92.50') matches no amount, leaves '5,' over, and
    #     the row is refused rather than invented.
    #   * Exactly five amounts, in header order (layout_ok below), or None.
    # A footnote '*' printed beside (or at the same x as) a figure is a marker, not part of it: '-2,599.30','*' must read -2,599.30.
    row = [f for f in fr if abs(f[0] - qy) < 3]
    cells: list = []                                            # [[first_x, last_x, [texts]]], left to right
    for _y, x, t in sorted(row, key=lambda f: f[1]):
        if cells and x - cells[-1][1] <= _CELL_GAP:
            cells[-1][1] = x
            cells[-1][2].append(t)
        else:
            cells.append([x, x, [t]])
    stream, owner = "", []                                      # the glued row, and for each character the cell it came from
    for ci, (_x0, _x1, ts) in enumerate(cells):
        piece = "".join(ts)
        stream += piece
        owner += [ci] * len(piece)
    stream = re.sub(r"Quarter / Trimestre|\*", lambda m: " " * len(m.group()), stream)          # same length: owner[] stays aligned
    found = list(_AMOUNT.finditer(stream))
    if _AMOUNT.sub(" ", stream).strip():
        return None                                             # text on the row that is not part of an amount: refuse the row, never guess
    if len(found) != 5:
        return None
    amts, per_cell = [], {}                                     # [(x, text)]
    for m in found:
        ci = owner[m.start()]
        amts.append((round(cells[ci][0]) + per_cell.get(ci, 0) * 1e-3, m.group()))
        per_cell[ci] = per_cell.get(ci, 0) + 1
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
    n = re.sub(r"\bHON\b\.?\s*", "", name, flags=re.I).strip()
    n = re.sub(r"\s+", " ", n)
    if "," in n:
        fam, giv = n.split(",", 1)
        fam = re.sub(r"\s+(?:JR|SR)\.?$", "", fam.strip(), flags=re.I)      # 'ENVERGA JR., HON. TOBIAS C.' -> family 'Enverga'
        return fam.strip().title(), giv.strip().title()
    return None, n.title()


_KEY_DROP = frozenset({"hon", "jr", "sr", "the", "l"})


def name_key(name: str | None) -> str | None:
    """A deterministic identity key for a PUBLISHED name, independent of the form it was printed in: accents folded, lower-case
    words only, the honorific / Jr / Sr and single-letter initials dropped, the rest sorted. 'CHAPUT, HON. MARIA' and
    'HON. MARIA CHAPUT' share one key; 'ENVERGA JR., HON. TOBIAS C.' and 'HON. TOBIAS C. ENVERGA' share another. It exists so a
    senator who is not on the roster (so senator_id stays NULL, deliberately) still groups across periods. It never GUESSES:
    two forms that differ by a real word ('Pierre Claude Nolin' vs 'Pierre Nolin') get different keys — a missing link is
    visible and fixable, a wrong merge is not."""
    if not name:
        return None
    folded = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii").lower()
    words = sorted(w for w in re.findall(r"[a-z]+", folded) if len(w) > 1 and w not in _KEY_DROP)
    return " ".join(words) or None


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


def _fold_given(token: str) -> str:
    """'JOSÉE' / 'S.M.' / 'Marie-P.' -> 'josee' / 'sm' / 'marie-p' (accent-folded, lower-case, only letters and hyphens kept)."""
    t = unicodedata.normalize("NFKD", token or "").encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z-]", "", t)


def given_agrees(published_name: str | None, roster_given: str | None) -> bool:
    """Does the PUBLISHED name share a given name with the roster senator? Accent- and case-insensitive. Agreement is ANY full given
    name (3+ letters) in common, because people go by a middle name ('HECTOR DANIEL LANG' is roster 'Daniel') or the roster carries
    an initial first ('A. Raynell' = 'RAYNELL ANDREYCHUK'). Failing that, a leading initial ('S.M.') agrees with a name starting with
    that letter. 'DOUGLAS JOHN' vs 'Robert', 'DENNIS' vs 'Rebecca', 'VERNON DARRYL' vs 'Judy' and 'DAVID P.' vs 'Larry W.' share nothing.
    Fails closed: a missing side, or a nickname ('MICHAEL' vs 'Mike'), is NOT an agreement."""
    _fam, giv = normalise_name(published_name)                    # comma form -> the given names; 'GIVEN FAMILY' form -> the whole name
    pub = [t for t in (_fold_given(x) for x in (giv or "").split()) if t]
    roster = [t for t in (_fold_given(x) for x in (roster_given or "").split()) if t]
    if not pub or not roster:
        return False
    if {t for t in pub if len(t) >= 3} & {t for t in roster if len(t) >= 3}:
        return True
    if len(pub[0]) <= 2 or len(roster[0]) <= 2:                   # a leading initial: 'S.M.' -> 'sm' agrees with 'sandra'
        return pub[0][0] == roster[0][0]
    return False


def _as_date(v):
    """date / datetime / 'YYYY-MM-DD...' string (sqlite returns text, Postgres a date) -> date, None stays None."""
    if v is None:
        return None
    if isinstance(v, str):
        return date.fromisoformat(v[:10])
    return v.date() if hasattr(v, "date") else v


def plausible_link(published_name: str | None, roster, period_end) -> bool:
    """May this published name be linked to this roster senator, FOR THIS PERIOD? `roster` is (given_name, appointed_at) or None.
    The family-name matcher accepts a unique family hit without looking at the given name, which attached retired senators to
    unrelated sitting ones (Douglas John Black -> Robert Black, Dennis Patterson -> Rebecca Patterson, Vernon Darryl White -> Judy
    White, David P. Smith merged into Larry W. Smith: the namesake class of ADR-047). So the link needs (1) the given name to agree and
    (2) the period not to end before the senator was appointed. Anything else is "no link": the row stays attributed by its own
    published name (name_key), never to someone else."""
    if not roster:
        return False
    given, appointed = roster
    if not given_agrees(published_name, given):
        return False
    a, e = _as_date(appointed), _as_date(period_end)
    if a is not None and e is not None and e < a:
        return False
    return True


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
    from ingest.parliament.senator_expenses import _split_family_given

    with engine.connect() as _c:
        roster = {rid: ((given or (_split_family_given(name)[1] if name else None)), appointed)
                  for rid, name, given, appointed in _c.execute(text("SELECT id, name, given_name, appointed_at FROM parliament.senators")).fetchall()}
    codes = codes if codes is not None else load_codes()
    stats = {"stored": 0, "not_found": 0, "unparsed": [], "bad_layout": [], "name_mismatch": [], "unmatched_senator": {}, "implausible_link": [], "per_period": {}, "failed": []}
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
            if sid is not None and not plausible_link(rec["name"], roster.get(sid), date.fromisoformat(end)):
                stats["implausible_link"].append(f"{end}/{code}: {rec['name']} !~ senator id {sid}")
                sid = None                                           # fail closed: keep it under its own published name
            if sid is None:
                stats["unmatched_senator"][rec["name"]] = stats["unmatched_senator"].get(rec["name"], 0) + 1
            travel = round(rec["travel_regular"] + rec["travel_other"], 2)
            with engine.begin() as conn:
                conn.execute(text("""
                    INSERT INTO parliament.senator_expenses_legacy
                        (senator_id, name_as_published, name_key, period_start, period_end, office_cad, hospitality_cad, living_cad,
                         travel_regular_cad, travel_other_cad, travel_cad, total_cad, source_code, source_url)
                    VALUES (:sid, :nm, :nk, :ps, :pe, :o, :h, :l, :tr, :to, :t, :tot, :code, :url)
                    ON CONFLICT (period_end, source_code) DO UPDATE SET
                        senator_id = EXCLUDED.senator_id, name_as_published = EXCLUDED.name_as_published,
                        name_key = EXCLUDED.name_key,
                        office_cad = EXCLUDED.office_cad, hospitality_cad = EXCLUDED.hospitality_cad, living_cad = EXCLUDED.living_cad,
                        travel_regular_cad = EXCLUDED.travel_regular_cad, travel_other_cad = EXCLUDED.travel_other_cad,
                        travel_cad = EXCLUDED.travel_cad, total_cad = EXCLUDED.total_cad, synced_at = now()"""),
                    {"sid": sid, "nm": rec["name"], "nk": name_key(rec["name"]), "ps": start, "pe": end, "o": rec["office"], "h": rec["hospitality"],
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
