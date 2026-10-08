"""mp_expenses.py — MP quarterly expense ingest from Our Commons proactive disclosure.

Durable, no-browser rewrite (2026-07). Our Commons restructured its proactive-disclosure
listing in ~May 2026, which silently broke the previous regex-scrape of per-report links:
the regex matched nothing, so every weekly run upserted ZERO rows for ~8 weeks — and nobody
noticed because the task never recorded a result anywhere. This version is built to not let
that happen again:

  * It walks STABLE, PREDICTABLE per-period index URLs instead of scraping a volatile listing:
        index :  {_BASE}/{fiscal_year}/{quarter}   -> HTML carrying exactly one report-CSV guid
        report:  {_BASE}/{guid}/csv                -> ALL members for that quarter, one CSV
                 columns: Name,Constituency,Caucus,Salaries,Travel,Hospitality,Contracts
    (plain HTTP + CSV — no Playwright; the CSV endpoint survived the redesign.)
  * The period label is _quarter_label(fy, q) = the same '{cal_year}-Qn' key already in the DB,
    so it UPDATES existing rows (never duplicates under a new label).
  * MP matching keys on the authoritative parliament.mps.family_name (+ given-name
    disambiguation for shared surnames), so compound surnames match too.
  * It FAILS LOUD: every run writes a parliament.ingest_log row, and a run that upserts zero
    rows returns an `error` + logs at ERROR level — so a future source change surfaces
    immediately instead of freezing the data in silence.

Runs weekly from run_parliament_sync() over the recent fiscal years; idempotent (UNIQUE
mp_id+period). Full backfill: run_expenses_sync(engine, start_fy=2022).
"""
import csv
import datetime
import io
import logging
import re
import time
import urllib.request

from sqlalchemy import text

from ingest.parliament._retry import fetch_with_retry

logger = logging.getLogger("wtf-ingest.mp_expenses")

_BASE = "https://www.ourcommons.ca/ProactiveDisclosure/en/members"
_HEADERS = {
    "User-Agent": "Mozilla/5.0 WTFIngest (+https://what-the-fact.com)",
    "Accept": "text/html,application/xhtml+xml,text/csv",
}
_SLEEP = 0.5
_GUID_RE = re.compile(r"/ProactiveDisclosure/en/members/([0-9a-f-]{36})/csv", re.IGNORECASE)


def _get(url: str, timeout: int = 25) -> bytes:
    def _once() -> bytes:
        req = urllib.request.Request(url, headers=_HEADERS)
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read()

    # A short ourcommons.ca outage (2026-10-04: "upserted 0 rows") must not become a "last run FAILED" row.
    return fetch_with_retry(_once, label="mp_expenses " + url[-40:])


def _parse_dollar(val):
    """'$1,234.56' / '1234.56' -> float, or None."""
    if not val:
        return None
    try:
        return float(re.sub(r"[,$\s]", "", val).strip())
    except ValueError:
        return None


def _quarter_label(fiscal_year: int, quarter: int) -> str:
    """Fiscal (year, quarter) -> the DB period key. FY ends in March:
    Q1=Apr-Jun(fy-1), Q2=Jul-Sep(fy-1), Q3=Oct-Dec(fy-1), Q4=Jan-Mar(fy).
    e.g. fy=2025,q=4 -> '2025-Q4'; fy=2025,q=3 -> '2024-Q3'."""
    cal_year = fiscal_year - 1 if quarter < 4 else fiscal_year
    return f"{cal_year}-Q{quarter}"


# --- name matching (Our Commons CSV "Last, Hon. First" -> parliament.mps) ------------

def _norm(s: str) -> str:
    """Lowercase, strip 'Hon.'/accents/punct-noise, keep comma + spaces."""
    s = re.sub(r"\bHon\.?\s*", "", s or "", flags=re.IGNORECASE).lower()
    for a, b in [("é", "e"), ("è", "e"), ("ê", "e"), ("ë", "e"), ("à", "a"), ("â", "a"),
                 ("ç", "c"), ("ô", "o"), ("î", "i"), ("ï", "i"), ("û", "u"), ("ü", "u"), ("’", "'")]:
        s = s.replace(a, b)
    return re.sub(r"[^a-z,'\s\.\-]", "", s).strip()


# House reports print some MPs under a name that is NOT how parliament.mps spells them, and no amount of normalisation
# bridges these — they are different NAMES for one person. Found 2026-10-07 when the FY2015-FY2021 archive backfill left six
# names unmatched. Keyed by the NORMALISED published name (see _norm), resolved by SLUG because ids are database serials
# while slugs are stable ('rachael-harder' is still Rachael Thomas's slug after her surname change).
# Every entry is a reviewed fact, not a guess. A bare name here wins over surname matching for ANY period, so only add a
# name that is unambiguous for the years the House sync and the archive cover (April 2014 onward).
PUBLISHED_NAME_ALIASES = {
    "harder, rachael": "rachael-harder",           # now Rachael Thomas (surname change)
    "harris, richard": "dick-harris",              # nickname
    "brown, gordon": "gord-brown",                 # nickname
    "harvey, t.j.": "tj-harvey",                   # punctuation
    "o'neill gordon, tilly": "tilly-oneill-gordon",  # hyphen printed as a space
    # Two David Andersons exist (Victoria, left 2006; Cypress Hills-Grasslands, sat to 2015). Only the latter overlaps 2014+.
    "anderson, david": "david-anderson",
}


def _build_mp_index(engine):
    """({family_key: [{id, given:set}]}, {full_name: id}) over ALL MPs (current + former).

    family_key comes from the authoritative parliament.mps.family_name (falls back to the
    last name token). given = the member's normalized given-name tokens, used to break ties
    when several MPs share a surname.
    """
    with engine.begin() as c:
        rows = c.execute(text(
            "SELECT id, name, COALESCE(family_name, ''), slug FROM parliament.mps"
        )).fetchall()
    fam_idx: dict = {}
    full_idx: dict = {}
    slug_to_id = {slug: mp_id for mp_id, _n, _f, slug in rows if slug}
    for mp_id, name, family, _slug in rows:
        nn = _norm(name)
        if nn:
            full_idx.setdefault(nn, mp_id)
        fam = _norm(family) or (nn.split()[-1] if nn else "")
        if not fam:
            continue
        given = set(nn.split()) - set(fam.split())
        fam_idx.setdefault(fam, []).append({"id": mp_id, "given": given})
    # Explicit aliases win; an alias whose slug is not in the table is skipped (never raises, never guesses).
    for published, slug in PUBLISHED_NAME_ALIASES.items():
        if slug in slug_to_id:
            full_idx[published] = slug_to_id[slug]
    return fam_idx, full_idx


def _match_mp(csv_name: str, fam_idx: dict, full_idx: dict):
    """Match a CSV 'Last, First' (or 'First Last') name to one mp_id, or None.

    Everything before the comma is the surname (authoritative on the CSV side). A single
    surname candidate matches; a shared surname is disambiguated by given-name overlap; a
    zero-overlap or tied match is ambiguous -> None (never guess an MP for money figures).
    """
    n = _norm(csv_name)
    if not n:
        return None
    if n in full_idx:
        return full_idx[n]
    if "," in n:
        fam = n.split(",", 1)[0].strip()
        given = set(n.split(",", 1)[1].split())
    else:
        toks = n.split()
        fam = toks[-1] if toks else ""
        given = set(toks[:-1])
    cands = fam_idx.get(fam) or (fam_idx.get(fam.split()[-1]) if fam else None)
    if not cands:
        return None
    if len(cands) == 1:
        return cands[0]["id"]
    scored = sorted(cands, key=lambda c: len(given & c["given"]), reverse=True)
    best = len(given & scored[0]["given"])
    second = len(given & scored[1]["given"]) if len(scored) > 1 else -1
    if best == 0 or best == second:
        return None
    return scored[0]["id"]


# --- identity gates: a name/riding match is only accepted for a person who could have incurred the cost ---------------

# A surname shared with a different MP (Carr, Saini, Lefebvre, Hoeppner...) lets the matcher pick someone who was not in the seat
# at all: 2020-22 costs of the then-MP landed on a namesake first elected in 2023/2025, and Candice Hoeppner's 2009-12 costs on
# Jake Hoeppner (1997-2000). Terms are recorded from the day Parliament OPENED, which is at most ~7 months after the election, so an
# MP-elect can bill a little before their first recorded term (BEFORE); wind-down and late claims run on for a while after the last
# (AFTER). Outside that, the matched person is wrong and the row stays unmatched — never attributed to a namesake.
SEAT_BEFORE_DAYS = 200
SEAT_AFTER_DAYS = 1095


def build_term_index(engine) -> dict:
    """{mp_id: [(start, end|None)]} from parliament.mp_terms — which MP held a seat when."""
    with engine.connect() as c:
        rows = c.execute(text("SELECT mp_id, start_date, end_date FROM parliament.mp_terms WHERE mp_id IS NOT NULL")).fetchall()
    from datetime import date

    def _d(v):
        return date.fromisoformat(str(v)[:10]) if isinstance(v, str) else v      # sqlite hands dates back as text
    idx: dict = {}
    for mp, s, e in rows:
        idx.setdefault(mp, []).append((_d(s), _d(e)))
    return idx


def seat_plausible(mp_id, start, end, term_idx) -> bool:
    """True if `mp_id` held a seat at some point from SEAT_AFTER_DAYS before `start` to SEAT_BEFORE_DAYS after `end`.
    An MP with NO recorded terms is unknowable, not implausible: True (fail-open); so is a missing term index."""
    if not term_idx or not term_idx.get(mp_id):
        return True
    from datetime import timedelta
    return any(s <= end + timedelta(days=SEAT_BEFORE_DAYS) and (e is None or e >= start - timedelta(days=SEAT_AFTER_DAYS))
               for s, e in term_idx[mp_id])


def family_of_index(fam_idx: dict) -> dict:
    """{mp_id: normalised family name} inverted from _build_mp_index's {family: [{id, given}]}."""
    return {c["id"]: fam for fam, cands in fam_idx.items() for c in cands}


def published_family(name: str) -> str:
    """'Cummins,  John' / 'Doyle, Hon. Norman' -> 'cummins' (everything before the comma, normalised)."""
    return _norm((name or "").split(",", 1)[0])


def riding_fallback_ok(name: str, holder_id, fam_idx: dict, fam_of: dict) -> bool:
    """May the RIDING's holder stand in for an unmatched published name? Only when the surnames agree, or the published surname is
    unknown to the roster altogether (a married-name change). A surname that IS on the roster but belongs to someone else means the
    published person is a DIFFERENT MP who simply is not matched: 'Cummins, John' (retired 2011) must not become Kerry-Lynne Findlay,
    who replaced him in Delta-Richmond East."""
    if holder_id is None:
        return False
    fam = published_family(name)
    return fam_of.get(holder_id) == fam or fam not in fam_idx


def quarter_dates(fiscal_year: int, quarter: int):
    """(first day, last day) of fiscal quarter `quarter` of `fiscal_year` (FY ends March: Q1=Apr-Jun of fy-1 ... Q4=Jan-Mar of fy)."""
    from datetime import date
    return {1: (date(fiscal_year - 1, 4, 1), date(fiscal_year - 1, 6, 30)), 2: (date(fiscal_year - 1, 7, 1), date(fiscal_year - 1, 9, 30)),
            3: (date(fiscal_year - 1, 10, 1), date(fiscal_year - 1, 12, 31)), 4: (date(fiscal_year, 1, 1), date(fiscal_year, 3, 31))}[quarter]


# --- fetch one quarter --------------------------------------------------------------

def _report_guid(fiscal_year: int, quarter: int):
    """The one Summary-of-Expenditures report-CSV guid for a (fiscal_year, quarter), or None."""
    try:
        html = _get(f"{_BASE}/{fiscal_year}/{quarter}").decode("utf-8", "ignore")
    except Exception as exc:
        logger.debug("mp_expenses: index fetch failed %s/%s: %s", fiscal_year, quarter, exc)
        return None
    m = _GUID_RE.findall(html)
    return m[0] if m else None


def _fetch_quarter_rows(fiscal_year: int, quarter: int):
    """[{name,salaries,travel,hospitality,contracts}] for the quarter via the report CSV.

    Returns None if the period has no published report yet (or a fetch failure) — distinct
    from [] (report exists but empty), so the caller can tell 'not published' from 'broken'.
    """
    guid = _report_guid(fiscal_year, quarter)
    if not guid:
        return None
    try:
        raw = _get(f"{_BASE}/{guid}/csv")
        reader = csv.DictReader(io.StringIO(raw.decode("utf-8-sig", "ignore")))
        out = []
        for row in reader:
            name = (row.get("Name") or row.get("Nom") or "").strip()
            if not name or name.lower() == "vacant":
                continue
            out.append({
                "name": name,
                "salaries": _parse_dollar(row.get("Salaries") or row.get("Salaires")),
                "travel": _parse_dollar(row.get("Travel") or row.get("Déplacements") or row.get("Voyages")),
                "hospitality": _parse_dollar(row.get("Hospitality") or row.get("Accueil")),
                "contracts": _parse_dollar(row.get("Contracts") or row.get("Contrats")),
            })
        return out
    except Exception as exc:
        logger.warning("mp_expenses: CSV fetch failed %s/%s guid=%s: %s", fiscal_year, quarter, guid, exc)
        return None


def _current_fiscal_year() -> int:
    """FY ending-year (FY ends Mar 31): Apr..Dec -> year+1, Jan..Mar -> year."""
    today = datetime.date.today()
    return today.year + 1 if today.month >= 4 else today.year


# --- the sync entry point -----------------------------------------------------------

def run_expenses_sync(engine, start_fy: int = None, end_fy: int = None) -> dict:
    """Ingest MP quarterly expenses over a range of fiscal years (default: recent 3).

    Weekly call passes no args -> covers the current + previous two fiscal years (picks up
    the latest published quarter + any late amendments). Backfill: start_fy=2022.
    Idempotent. ALWAYS records a parliament.ingest_log row; a zero-upsert run returns an
    `error` and logs ERROR (the silent-freeze guardrail).
    """
    end_fy = end_fy or _current_fiscal_year()
    if start_fy is None:
        start_fy = end_fy - 2
    fam_idx, full_idx = _build_mp_index(engine)
    term_idx = build_term_index(engine)
    implausible: dict = {}

    total_up = total_unmatched = periods_ok = 0
    by_period: dict = {}
    problems: list = []

    for fy in range(start_fy, end_fy + 1):
        for q in range(1, 5):
            period = _quarter_label(fy, q)
            rows = _fetch_quarter_rows(fy, q)
            if rows is None:
                problems.append(f"{period}:no-report")   # unpublished-yet or fetch fail
                time.sleep(_SLEEP)
                continue
            if not rows:
                problems.append(f"{period}:empty")
                time.sleep(_SLEEP)
                continue
            up = un = 0
            qs, qe = quarter_dates(fy, q)
            with engine.begin() as c:
                for r in rows:
                    mp_id = _match_mp(r["name"], fam_idx, full_idx)
                    if mp_id and not seat_plausible(mp_id, qs, qe, term_idx):
                        implausible[r["name"]] = implausible.get(r["name"], 0) + 1      # a namesake who was not in the seat then
                        mp_id = None
                    if not mp_id:
                        un += 1
                        continue
                    total = (r["salaries"] or 0) + (r["travel"] or 0) + (r["hospitality"] or 0) + (r["contracts"] or 0)
                    c.execute(text("""
                        INSERT INTO parliament.mp_expenses
                            (mp_id, period, salaries_cad, travel_cad, hospitality_cad,
                             contracts_cad, total_cad, source_url)
                        VALUES (:mid, :period, :sal, :trav, :hosp, :cont, :total, :url)
                        ON CONFLICT (mp_id, period) DO UPDATE SET
                            salaries_cad    = EXCLUDED.salaries_cad,
                            travel_cad      = EXCLUDED.travel_cad,
                            hospitality_cad = EXCLUDED.hospitality_cad,
                            contracts_cad   = EXCLUDED.contracts_cad,
                            total_cad       = EXCLUDED.total_cad,
                            synced_at       = NOW()
                    """), {
                        "mid": mp_id, "period": period,
                        "sal": r["salaries"], "trav": r["travel"], "hosp": r["hospitality"],
                        "cont": r["contracts"], "total": total,
                        "url": f"{_BASE}/{fy}/{q}",
                    })
                    up += 1
            by_period[period] = {"upserted": up, "unmatched": un, "rows": len(rows)}
            total_up += up
            total_unmatched += un
            periods_ok += 1
            logger.info("mp_expenses %s: %d/%d upserted (%d unmatched)", period, up, len(rows), un)
            time.sleep(_SLEEP)

    result = {
        "periods": periods_ok,
        "upserted": total_up,
        "unmatched": total_unmatched,
        "by_period": by_period,
        "problems": problems[:12],
        "implausible": implausible,          # published names matched to someone who was not in the seat then (left unmatched)
    }
    # Guardrail: a run that touched a real range but upserted nothing means the source moved
    # again (or matching broke). Surface it loudly — the old failure mode was total silence.
    if total_up == 0:
        result["error"] = (
            f"mp_expenses upserted 0 rows over FY{start_fy}-FY{end_fy} "
            f"— Our Commons source or the CSV schema may have changed"
        )
        logger.error("%s | problems=%s", result["error"], problems[:8])

    try:
        with engine.begin() as c:
            c.execute(text(
                "INSERT INTO parliament.ingest_log (task, records_fetched, records_upserted, error) "
                "VALUES ('mp_expenses', :f, :u, :e)"
            ), {"f": total_up + total_unmatched, "u": total_up, "e": result.get("error")})
    except Exception as exc:
        logger.warning("mp_expenses: ingest_log write failed: %s", exc)

    return result


if __name__ == "__main__":
    import os
    import sys
    from sqlalchemy import create_engine
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    eng = create_engine(os.environ["WTF_DATABASE_URL"], pool_pre_ping=True)
    sfy = int(sys.argv[1]) if len(sys.argv) > 1 else None
    print(run_expenses_sync(eng, start_fy=sfy))
