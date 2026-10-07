"""senator_expenses.py — Senate of Canada quarterly senators' expenditure ingest.

Mirrors ingest/parliament/mp_expenses.py (the House analogue) for the Senate.

Source: the Senate "Public Disclosure → Quarterly Expenditure Reports" summary,
served by an Umbraco surface controller as an HTML table fragment:

    GET /umbraco/surface/ProActiveAjax/GetProActiveData
        ?displayFor=Summary&Year=<YYYY>&Quarter=<1-4>&Member=Senators&Lang=en

Each row is one senator with these $ columns:
    Office Expenses | Living Expenses | Hospitality Expenses | Travel Expenses
plus "Contract(s) Awarded" — which is a per-senator "Details" drill-down link,
NOT a summary dollar figure ("N/A" = no contracts).  So contracts_cad is:
    "N/A"    -> 0.00
    "Details"-> NULL   (amount only available behind the drill-down — deferred)
and total_cad = office + living + hospitality + travel + COALESCE(contracts, 0).

Rows are matched to parliament.senators by FAMILY NAME (the summary prints
"Family, Given"; a senator's given name can vary across quarters, e.g.
"Anderson, Margaret Dawn" vs "Anderson, Dawn", so family name is the anchor,
disambiguated by given name only when a surname is shared).

Runs weekly from run.py's Sunday parliament block, AFTER the senator roster
sync (so it matches against the fresh roster).  Idempotent (UNIQUE senator_id+
period).  Fail-soft: a fetch/parse failure logs and returns without wiping.
Only the most recent `max_quarters` are fetched by default to stay fast; pass a
larger value (or run the module directly) to backfill ~5 years.
"""
import logging
import re
import time
import urllib.parse
import urllib.request

from sqlalchemy import text

logger = logging.getLogger("wtf-ingest.senator_expenses")

_BASE = "https://sencanada.ca"
_DATA_URL = _BASE + "/umbraco/surface/ProActiveAjax/GetProActiveData"
_HEADERS = {
    "User-Agent": "Mozilla/5.0 WTFIngest (+https://what-the-fact.com)",
    "Accept": "text/html,application/xhtml+xml,*/*",
    "X-Requested-With": "XMLHttpRequest",
}
_SLEEP = 0.5
_ALLOWED_SCHEMAS = frozenset({"parliament"})

# Column order in the Senate "Senators" summary table.
_COL_OFFICE = 3
_COL_LIVING = 4
_COL_HOSPITALITY = 5
_COL_TRAVEL = 6
_COL_CONTRACTS = 7


def _get(url: str, timeout: int = 25) -> bytes:
    req = urllib.request.Request(url, headers=_HEADERS)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def _fetch_fragment(year=None, quarter=None) -> str:
    params = {"displayFor": "Summary", "Member": "Senators", "Lang": "en"}
    if year is not None and quarter is not None:
        params["Year"] = str(year)
        params["Quarter"] = str(quarter)
    url = _DATA_URL + "?" + urllib.parse.urlencode(params)
    return _get(url).decode("utf-8", errors="ignore")


def _parse_dollar(val: str):
    """Convert '$1,234.56' or '1234.56' to float, or None ('N/A'/'Details'/'')."""
    if not val:
        return None
    cleaned = re.sub(r"[,$\s]", "", val).strip()
    try:
        return float(cleaned)
    except ValueError:
        return None


def _norm_name(name: str) -> str:
    """Lowercase, strip titles, collapse spaces for fuzzy name matching.

    Mirrors ingest/parliament/senators._norm_name so both sides normalise
    identically.
    """
    name = (name or "").lower()
    for title in ("the honourable ", "hon. ", "senator ", "dr. ", "mr. ", "ms. ", "mrs. "):
        name = name.replace(title, "")
    return re.sub(r"\s+", " ", name).strip()


def _strip_tags(cell: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", cell)).strip()


def _available_quarters(fragment: str) -> list[tuple[int, int]]:
    """Parse the quarter dropdown → sorted-desc list of (year, quarter).

    The dropdown anchors are hash routes: #?Year=2026&Quarter=1&Member=Senators.
    """
    pairs = set()
    for y, q in re.findall(r"Year=(\d{4})&Quarter=([1-4])&Member=Senators", fragment):
        pairs.add((int(y), int(q)))
    return sorted(pairs, reverse=True)


def _extract_rows(fragment: str) -> list[list[str]]:
    """Return the data rows (list of cell strings) from the summary table."""
    out = []
    for row in re.findall(r"<tr[^>]*>(.*?)</tr>", fragment, re.S | re.I):
        cells = [_strip_tags(c) for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", row, re.S | re.I)]
        if len(cells) < 8:
            continue
        name = cells[0]
        # Skip the header row and any total/summary rows (data names are "Family, Given").
        if not name or name.lower() == "name" or "," not in name:
            continue
        out.append(cells)
    return out


def _clean_summary_name(name: str) -> str:
    """The Senate marks some rows with a trailing "*" ("Gold, Marc *"): strip it, then normalize spaces."""
    import html
    # The Senate's summary pages HTML-encode accents ("Gagn&#xE9;, Raymonde"). Decode FIRST: left
    # encoded, an existing roster senator never matches and a stub with a garbled name and slug gets
    # created beside the real row (2026-10-06: four duplicates before this was caught).
    name = html.unescape(name or "")
    return re.sub(r"\s+", " ", re.sub(r"\s*\*+\s*$", "", name)).strip()


def _split_family_given(name: str):
    """"Family, Given Middle" -> ("Family", "Given Middle"); (None, None) when there is no comma."""
    if "," not in (name or ""):
        return None, None
    fam, giv = name.split(",", 1)
    fam, giv = fam.strip(), giv.strip()
    return (fam or None), (giv or None)


def _load_senator_index(engine):
    """Build {family_norm: [(given_norm, id)]} and {full_norm: id} from the roster.

    Stub rows (former senators added with only a "Family, Given" `name`, ids 100+) have NULL family_name /
    given_name; they are derived from `name` here so they are matchable. Without this they were invisible to the
    matcher and every expense/travel row of those senators was silently dropped (2026-10-06: 8 stubs + 22 absent
    senators = 30 of the 144 senators on the 2023-2026 summaries)."""
    with engine.connect() as c:
        rows = c.execute(text(
            "SELECT id, name, given_name, family_name FROM parliament.senators"
        )).fetchall()
    fam_idx: dict[str, list[tuple[str, int]]] = {}
    full_idx: dict[str, int] = {}
    for sid, name, given, family in rows:
        if not family and name:
            family, given = _split_family_given(name)[0], given or _split_family_given(name)[1]
        if family:
            fam_idx.setdefault(_norm_name(family), []).append((_norm_name(given or ""), sid))
        if name:
            full_idx[_norm_name(name)] = sid
    return fam_idx, full_idx


def _match_senator(name_val: str, fam_idx, full_idx):
    """Match a summary "Family, Given" name to a senator id."""
    name_val = _clean_summary_name(name_val)
    sid = full_idx.get(_norm_name(name_val))          # exact "Family, Given" == the roster's own `name`
    if sid:
        return sid
    parts = name_val.split(",", 1)
    family = _norm_name(parts[0])
    given = _norm_name(parts[1]) if len(parts) > 1 else ""

    cands = fam_idx.get(family, [])
    if len(cands) == 1:
        return cands[0][1]
    if len(cands) > 1 and given:
        # Shared surname — disambiguate by best given-name token overlap
        # (handles subset/middle-name variants, e.g. summary "Dawn" vs roster
        # "Margaret Dawn").
        gtoks = set(given.split())
        best, best_overlap = None, 0
        for gnorm, sid in cands:
            overlap = len(gtoks & set(gnorm.split()))
            if overlap > best_overlap:
                best, best_overlap = sid, overlap
        if best is not None:
            return best
    # Fallback: full "Given Family" against the roster's full-name index.
    if given:
        sid = full_idx.get(_norm_name(parts[1] + " " + parts[0]))
        if sid:
            return sid
    return None


def _slugify_senator(family: str, given: str) -> str:
    """sencanada-style slug "family-given" ("boniface-gwen", "megie-marie-francoise")."""
    import unicodedata
    raw = unicodedata.normalize("NFKD", f"{family} {given}").encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "-", raw).strip("-")


def ensure_roster_stub(engine, summary_name: str, caucus=None, province=None, fam_idx=None, full_idx=None):
    """Return the roster id for a Senate-summary name, CREATING a stub row when it has none.

    A senator who is on the Senate's own disclosure but not in parliament.senators (it only tracks the current
    roster plus a few hand-added stubs) otherwise has every expense and travel row silently dropped, which quietly
    under-counts any total built on them. The stub carries only what the summary itself says (name, caucus,
    province), is_current=false (a reconcile of the live roster flips it if they still sit), and no entity link.
    Returns None for anything that is not a "Family, Given" name. Updates fam_idx/full_idx in place if given."""
    name = _clean_summary_name(summary_name)
    family, given = _split_family_given(name)
    if not family or not given:
        return None
    slug = _slugify_senator(family, given)
    if not slug:
        return None
    prov = re.sub(r"\s*\(.*\)\s*$", "", (province or "").replace("*", "")).strip() or None
    cau = (caucus or "").replace("*", "").strip() or None
    with engine.begin() as c:
        sid = c.execute(text("""
            INSERT INTO parliament.senators (slug, name, given_name, family_name, caucus, province, is_current)
            VALUES (:slug, :name, :given, :family, :caucus, :prov, false)
            ON CONFLICT (slug) DO UPDATE SET synced_at = parliament.senators.synced_at
            RETURNING id"""), {"slug": slug, "name": name, "given": given, "family": family,
                              "caucus": cau, "prov": prov}).scalar()
    if fam_idx is not None:
        fam_idx.setdefault(_norm_name(family), []).append((_norm_name(given), sid))
    if full_idx is not None:
        full_idx[_norm_name(name)] = sid
    logger.warning("senator_expenses: roster had no match for %r — created stub senator id=%s slug=%s", name, sid, slug)
    return sid


def _contracts_value(raw: str):
    """N/A -> 0.0 (no contracts); a $ figure -> parsed; 'Details' -> None."""
    r = (raw or "").strip()
    if r.upper() in ("N/A", "N.A.", ""):
        return 0.0
    if "$" in r:
        return _parse_dollar(r)
    return None  # "Details" — amount only behind the per-senator drill-down


def run_senator_expenses_sync(engine, max_quarters: int = 8, since_year: int | None = None) -> dict:
    """Public entry point — run the senator-expenditure sync and SELF-LOG the outcome to
    parliament.ingest_log (task='senator_expenses_sync'), exactly like mp_expenses /
    minister_travel / ec_contributions. This is what lets the drift guard watch it: an error or
    empty run is now recorded, never silent. Returns the sync result + elapsed_s.
    """
    t0 = time.time()
    try:
        result = _sync_senator_expenses(engine, max_quarters=max_quarters, since_year=since_year)
    except Exception as exc:  # a crash is itself a fail-loud event
        logger.exception("senator_expenses sync crashed: %s", exc)
        result = {"error": str(exc)}
    # An empty run (no reports AND no rows) is treated as an error so the guard can't read a
    # broken fetch as "fresh". A normal run re-upserts the recent quarters (inserted > 0).
    if not result.get("error") and not result.get("reports") and not result.get("inserted"):
        result = {"error": "no senator reports/rows fetched"}
    try:
        with engine.begin() as c:
            if result.get("error"):
                c.execute(
                    text("INSERT INTO parliament.ingest_log (task, error) VALUES ('senator_expenses_sync', :e)"),
                    {"e": str(result["error"])[:500]},
                )
            else:
                c.execute(
                    text(
                        "INSERT INTO parliament.ingest_log (task, records_fetched, records_upserted) "
                        "VALUES ('senator_expenses_sync', :f, :u)"
                    ),
                    {"f": result.get("reports", 0), "u": result.get("inserted", 0)},
                )
    except Exception as exc:
        logger.error("senator_expenses: could not write ingest_log: %s", exc)
    result["elapsed_s"] = round(time.time() - t0, 1)
    return result


def _sync_senator_expenses(engine, max_quarters: int = 8, since_year: int | None = None) -> dict:
    """Fetch Senate quarterly senator-expenditure reports and upsert them.

    max_quarters: how many of the most-recent available quarters to fetch
        (default 8 ≈ 2 fiscal years, mirroring mp_expenses).  Pass a large value
        (e.g. 20) or set since_year to backfill ~5 years.
    since_year: if set, only fetch quarters with Year >= since_year.
    Returns {"reports": n_quarters, "inserted": n_rows} or {"error": str}.
    """
    try:
        first = _fetch_fragment()  # default = latest quarter; carries the dropdown
    except Exception as exc:
        logger.error("senator_expenses: failed to fetch summary: %s", exc)
        return {"error": str(exc)}

    quarters = _available_quarters(first)
    if not quarters:
        logger.warning("senator_expenses: no quarters found in dropdown")
        return {"reports": 0, "inserted": 0}
    if since_year is not None:
        quarters = [(y, q) for (y, q) in quarters if y >= since_year]
    quarters = quarters[:max_quarters]
    logger.info("senator_expenses: %d quarters to fetch (latest=%s)", len(quarters), quarters[0])

    fam_idx, full_idx = _load_senator_index(engine)
    if not fam_idx:
        logger.warning("senator_expenses: senator roster is empty — nothing to match")
        return {"reports": 0, "inserted": 0}

    inserted = 0
    reports_done = 0
    stubs_created = 0
    unmatched: set[str] = set()

    for (year, quarter) in quarters:
        period = f"{year}-Q{quarter}"
        source_url = (
            f"{_DATA_URL}?displayFor=Summary&Year={year}&Quarter={quarter}"
            f"&Member=Senators&Lang=en"
        )
        try:
            # The latest quarter is already in `first`; avoid a redundant refetch.
            fragment = first if (year, quarter) == quarters[0] else _fetch_fragment(year, quarter)
            rows = _extract_rows(fragment)
        except Exception as exc:
            logger.debug("senator_expenses: fetch/parse failed %s: %s", period, exc)
            time.sleep(_SLEEP)
            continue

        for cells in rows:
            name_val = cells[0].strip()
            sid = _match_senator(name_val, fam_idx, full_idx)
            if not sid:
                sid = ensure_roster_stub(engine, name_val, caucus=cells[1] if len(cells) > 1 else None,
                                         province=cells[2] if len(cells) > 2 else None,
                                         fam_idx=fam_idx, full_idx=full_idx)
                if sid:
                    stubs_created += 1
            if not sid:
                unmatched.add(name_val)
                continue

            office = _parse_dollar(cells[_COL_OFFICE])
            living = _parse_dollar(cells[_COL_LIVING])
            hosp = _parse_dollar(cells[_COL_HOSPITALITY])
            travel = _parse_dollar(cells[_COL_TRAVEL])
            contracts = _contracts_value(cells[_COL_CONTRACTS])
            total = round(
                (office or 0) + (living or 0) + (hosp or 0)
                + (travel or 0) + (contracts or 0), 2
            )

            try:
                with engine.begin() as c:
                    c.execute(text("""
                        INSERT INTO parliament.senator_expenses
                            (senator_id, period, travel_cad, hospitality_cad,
                             contracts_cad, office_cad, living_cad, total_cad, source_url)
                        VALUES
                            (:sid, :period, :travel, :hosp, :contracts,
                             :office, :living, :total, :url)
                        ON CONFLICT (senator_id, period) DO UPDATE SET
                            travel_cad      = EXCLUDED.travel_cad,
                            hospitality_cad = EXCLUDED.hospitality_cad,
                            contracts_cad   = EXCLUDED.contracts_cad,
                            office_cad      = EXCLUDED.office_cad,
                            living_cad      = EXCLUDED.living_cad,
                            total_cad       = EXCLUDED.total_cad,
                            source_url      = EXCLUDED.source_url,
                            synced_at       = NOW()
                    """), {
                        "sid": sid,
                        "period": period,
                        "travel": travel,
                        "hosp": hosp,
                        "contracts": contracts,
                        "office": office,
                        "living": living,
                        "total": total,
                        "url": source_url,
                    })
                inserted += 1
            except Exception as exc:
                logger.debug("senator_expenses: insert failed sid=%s period=%s: %s",
                             sid, period, exc)

        reports_done += 1
        time.sleep(_SLEEP)

    if unmatched:
        logger.info("senator_expenses: %d unmatched summary names (e.g. %s)",
                    len(unmatched), sorted(unmatched)[:5])
    logger.info("senator_expenses: reports=%d inserted=%d stubs_created=%d", reports_done, inserted, stubs_created)
    return {"reports": reports_done, "inserted": inserted, "roster_stubs_created": stubs_created}


def _get_engine():
    import os

    from sqlalchemy import create_engine
    url = os.environ.get("WTF_DATABASE_URL")
    if not url:
        raise RuntimeError("WTF_DATABASE_URL not set")
    return create_engine(url)


if __name__ == "__main__":
    # Standalone backfill: python -m ingest.parliament.senator_expenses
    logging.basicConfig(level=logging.INFO)
    eng = _get_engine()
    # ~5 years of quarters.
    print(run_senator_expenses_sync(eng, max_quarters=20))
