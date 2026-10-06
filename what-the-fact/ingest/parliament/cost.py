"""cost.py -- "What Parliament Costs Canadians" cost model (project #348, Phase 1: MPs).

Pure, read-only functions that compute the approximate annual + 5-year cost to taxpayers of
an MP (and, in Phase 2, a senator). This module is the SINGLE SOURCE OF TRUTH for the number;
the consumer API (consumer/cost_routes.py) and any surface just call these.

    taxpayer_cost(mp, year) = base_indemnity(year) + role_top_up(role, year) + office_expenses(year)

  * base_indemnity / role_top_up -- published yearly constants from parliament.indemnity_rates
    (seeded + SOURCED by migration 039; Library of Parliament "Indemnities, Salaries and
    Allowances"). Rounded to the nearest $100 at source.
  * office_expenses -- travel + hospitality + contracts + office-staff salaries, summed from
    parliament.mp_expenses (House of Commons proactive Members' Expenditures disclosures).

HONESTY RAILS (public financial display):
  * every figure is labelled "approximate" (see _NOTE) and the components are exposed, never a
    single opaque number;
  * indemnity is charged ONLY for a year the member actually served -- proxied by having >=1
    mp_expenses row that year (an MP with no disclosure that year cost taxpayers no salary in
    this model), so the national total matches the raw disclosure;
  * pensions and some central costs are OUT of scope;
  * top-ups key to the member's CURRENT cabinet_role (parliament.mps has no historical role
    dimension), so pre-2025 minister/PM top-ups are approximate -- documented in migration 039.

Read-only: opens a short connection off the passed SQLAlchemy `engine`; never writes.
"""

from __future__ import annotations

import re
import unicodedata

from sqlalchemy import text

from shared.fiscal_quarters import CHRONO_DESC_SQL, CHRONO_KEY_SQL

# Default/fallback window. The LIVE window is computed dynamically from the data by
# _complete_years() so the model auto-advances as new quarters are disclosed — a year rolls
# into the headline once its 4th quarter lands, an incomplete year never inflates it, and the
# current partial year is detected automatically. This is what keeps the public totals honest +
# up to date over time without a manual code bump (the trap that once froze ingestion for weeks).
YEARS = (2021, 2022, 2023, 2024, 2025)

_NOTE = (
    "approximate -- office expenses + indemnity; excludes pensions and central costs"
)


# --------------------------------------------------------------------------- helpers

def _year_quarters(conn) -> dict:
    """{fiscal_year: {quarters}} present in parliament.mp_expenses — the completeness signal
    (MP expenditures are the primary, most-current source; senator/ministerial data is added
    where available for a year the MP data has established)."""
    out: dict = {}
    for yr, q in conn.execute(
        text("SELECT LEFT(period, 4)::int, RIGHT(period, 2) FROM parliament.mp_expenses GROUP BY 1, 2")
    ).fetchall():
        out.setdefault(int(yr), set()).add(q)
    return out


WINDOW_SIZE = 5   # the headline is a TRAILING window of at most this many complete years


def window_years(quarters_by_year: dict):
    """-> (window, current_year, retired).

    window       the last WINDOW_SIZE years with all 4 quarters on file (falls back to YEARS if none).
    current_year the latest disclosed year NEWER than the window that is still partial, else None.
    retired      complete years that have rolled OFF the front of the window.

    Capping the window is what keeps every "5-year" key and label (grand_total_5yr, five_year_total, "5-year
    cost" copy, the public /api/cost/summary contract that civic-watch also reads) TRUE. Uncapped, the year
    2026 completing (~Feb 2027, once its Q2+Q3 are disclosed) would silently turn the headline into SIX
    years under a 5-year name. Capped, 2027 rolls the window to 2022-2026 and 2021 drops out.
    """
    complete = sorted(y for y, qs in quarters_by_year.items() if len(qs) >= 4)
    window = tuple(complete[-WINDOW_SIZE:]) or YEARS
    newer = [y for y in quarters_by_year if y > window[-1]]
    retired = tuple(y for y in complete if y < window[0])
    return window, (max(newer) if newer else None), retired


def _complete_years(conn) -> tuple:
    """The headline window (see window_years): the trailing <=5 years with all 4 quarters on file. DYNAMIC —
    auto-advances as quarters are disclosed; an incomplete year is never counted in the headline (it drops
    to an addendum). Falls back to the static YEARS only if the table is unexpectedly empty."""
    return window_years(_year_quarters(conn))[0]


def _current_partial_year(conn):
    """The latest disclosed year NEWER than the window that is still partial (< 4 quarters) — i.e. 'the
    current year, to date'. Returns the int year or None. This is the year we surface as a live addendum +
    chart bar and project a full-year estimate for."""
    return window_years(_year_quarters(conn))[1]


def _prorate(annual, quarters):
    """A year's base salary / top-up (an ANNUAL amount) scaled to the quarters actually disclosed.

    A partial year carries only its disclosed quarters of office expenses, so its salary must be the same
    fraction of a year — otherwise the year-to-date total mixes 2 quarters of expenses with 4 quarters of
    salary and _project() (which annualizes by 4/quarters) would then count the salary twice over. Complete
    years (4 quarters) are unchanged."""
    q = max(0, min(int(quarters or 0), 4))
    return round(float(annual or 0) * q / 4)


PROJECTION_MIN_QUARTERS = 2
SEASONAL_MIN_PRIOR_YEARS = 2          # prior COMPLETE years needed to use seasonal shares (else plain annualizing)
# Order quarters are DISCLOSED in within a year label: Q4 = Jan-Mar, Q1 = Apr-Jun, Q2 = Jul-Sep, Q3 = Oct-Dec
# (the "<year>-Q<fiscal quarter>" scheme), so the first two disclosed are Q4 + Q1 and the third is Q2.
QUARTER_ORDER = ("Q4", "Q1", "Q2", "Q3")


def _project(ytd, quarters):
    """Plain annualizing (ytd / quarters x 4) — the FALLBACK when there are too few prior complete years to know
    how a year is distributed. None below PROJECTION_MIN_QUARTERS or once the year is complete."""
    q = int(quarters or 0)
    if q < PROJECTION_MIN_QUARTERS or q >= 4 or not ytd:
        return None
    return round(float(ytd) / q * 4)


def _median(xs):
    xs = sorted(xs)
    n = len(xs)
    return xs[n // 2] if n % 2 else (xs[n // 2 - 1] + xs[n // 2]) / 2


def seasonal_projection(series: dict, year: int, disclosed=None):
    """Full-year projection of ONE expense series from the quarters disclosed so far, or None.

    series     {year: {"Q1": amount, ...}}
    disclosed  the quarter labels on file for `year` (default: all that the series has for it)

    Method: expenses are strongly seasonal, so ytd / 4 x ... is the wrong question. Instead take the SAME quarters'
    share of the full year in each of the last (up to 5) prior COMPLETE years and divide: projected = ytd / share.
    The MEDIAN share is used, so one disrupted year (2025: an April election, MPs 222 -> 339) cannot drag the
    estimate; the lowest and highest share give the range. Measured over 2021-2024 the Jan-Jun quarters were
    50.5-52.4% of the year's MP office expenses and the first three quarters 75-76%, so this is tight in a normal
    year. With fewer than SEASONAL_MIN_PRIOR_YEARS prior years it falls back to plain annualizing (no range).
    """
    year_q = series.get(year, {})
    disclosed = set(disclosed if disclosed is not None else year_q) & set(year_q)
    n = len(disclosed)
    ytd = sum(year_q[q] for q in disclosed)
    if n < PROJECTION_MIN_QUARTERS or n >= 4 or not ytd:
        return None
    prior = [y for y in sorted(series) if y < year and len(series[y]) >= 4][-5:]
    shares = []
    for y in prior:
        total = sum(series[y].values())
        part = sum(series[y].get(q, 0) for q in disclosed)
        if total > 0 and part > 0:
            shares.append(part / total)
    if len(shares) >= SEASONAL_MIN_PRIOR_YEARS:
        share = _median(shares)
        return {"projected": round(ytd / share), "low": round(ytd / max(shares)), "high": round(ytd / min(shares)),
                "share": share, "share_low": min(shares), "share_high": max(shares), "n_prior": len(shares),
                "method": "seasonal", "ytd": round(ytd)}
    flat = round(ytd / n * 4)
    return {"projected": flat, "low": flat, "high": flat, "share": n / 4, "share_low": n / 4, "share_high": n / 4,
            "n_prior": len(shares), "method": "annualized", "ytd": round(ytd)}


def projection_backtest(series_by_kind: dict, stages=(2, 3)) -> list:
    """What the seasonal method WOULD have projected for each past complete year after `stages` quarters, against
    what that year turned out to be. MP office expenses only: they are ~95% of the projected expense line and have
    five complete years of history (senators have too few to back-test), and salary is a known rate, not projected.
    Uses only years BEFORE the one being projected for its shares, so it is an honest out-of-sample test.
    [{year, stage_quarters, projected, actual, error_pct}]"""
    out = []
    kinds = [k for k in ("mp",) if series_by_kind.get(k)]
    if not kinds:
        return out
    years = sorted(y for y in series_by_kind[kinds[0]] if len(series_by_kind[kinds[0]][y]) >= 4)
    for y in years:
        for stage in stages:
            disclosed = QUARTER_ORDER[:stage]
            projected = actual = 0
            ok = True
            for k in kinds:
                ser = series_by_kind[k]
                if y not in ser or len(ser[y]) < 4:
                    continue
                r = seasonal_projection({yy: v for yy, v in ser.items() if yy <= y}, y, disclosed)
                if not r or r["method"] != "seasonal":
                    ok = False
                    break
                projected += r["projected"]
                actual += sum(ser[y].values())
            if ok and actual:
                out.append({"year": y, "stage_quarters": stage, "projected": projected, "actual": round(actual),
                            "error_pct": round((projected - actual) / actual * 100, 1)})
    return out


def _quarter_series(conn) -> dict:
    """{kind: {year: {quarter: amount}}} for the three expense series that get projected."""
    queries = {
        "mp": "/* quarter_series:mp */ SELECT LEFT(period, 4)::int, RIGHT(period, 2), "
              "COALESCE(SUM(travel_cad + hospitality_cad + contracts_cad + salaries_cad), 0) "
              "FROM parliament.mp_expenses GROUP BY 1, 2",
        "senator": "/* quarter_series:senator */ SELECT LEFT(period, 4)::int, RIGHT(period, 2), "
                   "COALESCE(SUM(COALESCE(travel_cad, 0) + COALESCE(hospitality_cad, 0) + COALESCE(contracts_cad, 0) "
                   "+ COALESCE(office_cad, 0) + COALESCE(living_cad, 0)), 0) "
                   "FROM parliament.senator_expenses GROUP BY 1, 2",
        "ministerial": "/* quarter_series:ministerial */ SELECT LEFT(period, 4)::int, RIGHT(period, 2), "
                       "COALESCE(SUM(total_cad), 0) FROM parliament.minister_travel GROUP BY 1, 2",
    }
    out: dict = {}
    for kind, sql in queries.items():
        ser: dict = {}
        for yr, q, amt in conn.execute(text(sql)).fetchall():
            ser.setdefault(int(yr), {})[str(q)] = float(amt or 0)
        out[kind] = ser
    return out


# A minister's CURRENT department = the owner_org of their most recent quarter. "Most recent" must be chronological:
# the period label is "<calendar year>-Q<fiscal quarter>" with Q4 = Jan-Mar, so ORDER BY period DESC puts 2026-Q4
# (Jan-Mar 2026) ABOVE 2026-Q1 (Apr-Jun 2026) and would pick the older department after a mid-year move.
_LATEST_ORG_SQL = (
    "SELECT owner_org FROM parliament.minister_travel "
    "WHERE mp_id = :mid AND COALESCE(owner_org, '') <> '' "
    "ORDER BY " + CHRONO_DESC_SQL + " LIMIT 1"
)

# Series whose labels use the House fiscal-quarter scheme above (mp_expenses, and minister_travel which mirrors it).
# senator_expenses uses the Senate's own calendar quarters, where plain text order IS chronological.
_FISCAL_LABEL_TABLES = frozenset({"parliament.mp_expenses", "parliament.minister_travel"})


def series_coverage(conn, table: str) -> dict:
    """{rows, first, last} for a table's `period` labels, FIRST and LAST in date order. MIN/MAX on the label text
    reported 2026-Q4 (Jan-Mar 2026) as the latest MP quarter when it is 2026-Q1 (Apr-Jun 2026)."""
    rows = int(conn.execute(text("SELECT COUNT(*) FROM {0}".format(table))).scalar() or 0)
    if table in _FISCAL_LABEL_TABLES:
        first = conn.execute(text("SELECT period FROM {0} ORDER BY {1} ASC, period ASC LIMIT 1".format(table, CHRONO_KEY_SQL))).scalar()
        last = conn.execute(text("SELECT period FROM {0} ORDER BY {1} LIMIT 1".format(table, CHRONO_DESC_SQL))).scalar()
    else:
        r = conn.execute(text("SELECT MIN(period), MAX(period) FROM {0}".format(table))).fetchone()
        first, last = r[0], r[1]
    return {"rows": rows, "first": first, "last": last}


def _all_rates(conn) -> dict:
    """{fiscal_year: {role: amount_float}} from the sourced reference table (one query)."""
    rows = conn.execute(
        text("SELECT fiscal_year, role, amount_cad FROM parliament.indemnity_rates")
    ).fetchall()
    out: dict = {}
    for fy, role, amount in rows:
        out.setdefault(int(fy), {})[role] = float(amount)
    return out


def _topup_role(cabinet_role):
    """Map a parliament.mps.cabinet_role string to an indemnity_rates top-up role, or None.

    Per the design: minister_topup whenever a cabinet_role is set, pm_topup for the PM.
    Speaker handled defensively (paid at minister level) though no MP currently carries it.
    """
    if not cabinet_role:
        return None
    c = cabinet_role.lower()
    if "prime minister" in c:
        return "pm_topup"
    if "speaker" in c:
        return "speaker_topup"
    return "minister_topup"


# --- name matching (civic official -> parliamentary roster) ------------------
# Mirrors the matchers in ingest.parliament.cabinet / .senators: normalize, then
# key on the family name (last token) and disambiguate shared surnames by
# given-name token overlap. Read-only; NEVER guesses a number on a miss.

_TITLE_PREFIXES = (
    "the right honourable ", "the honourable ", "honourable ", "hon. ", "hon ",
)


def _strip_title(name: str) -> str:
    low = (name or "").lower()
    for pref in _TITLE_PREFIXES:
        if low.startswith(pref):
            return name[len(pref):]
    return name


def _norm(name: str) -> str:
    """Lowercase, strip accents, drop punctuation, collapse spaces."""
    name = unicodedata.normalize("NFKD", name or "").encode("ascii", "ignore").decode()
    name = re.sub(r"[.'’\-]", " ", name.lower())
    return re.sub(r"\s+", " ", name).strip()


def _name_tokens(name: str) -> list:
    """Normalized tokens of a full name, title stripped (e.g. 'Given Surname')."""
    return _norm(_strip_title(name)).split()


def _index_by_family(rows) -> dict:
    """Build {family_key: [{id, name, given:set}]} from roster rows (id, name, given, family).

    family_key = last token of the normalized family name (fallback: last token of the
    full name). given = the normalized given-name tokens (fallback: all-but-last of the
    full name) used to disambiguate a shared surname.
    """
    idx: dict = {}
    for r in rows:
        rid, full, given_name, family_name = r[0], r[1], r[2], r[3]
        fam = _norm(family_name).split() or _name_tokens(full)
        if not fam:
            continue
        given = set(_norm(given_name).split())
        if not given:
            given = set(_name_tokens(full)[:-1])
        idx.setdefault(fam[-1], []).append({"id": rid, "name": full, "given": given})
    return idx


def _match_official(idx: dict, name: str):
    """Match an official's 'Given Surname' to one roster entry, or None.

    Single candidate for the surname -> match. Multiple -> pick the one with the most
    given-name token overlap; a zero-overlap or tied best is AMBIGUOUS -> None (public
    financial data: never attribute a cost on a guess).
    """
    toks = _name_tokens(name)
    if not toks:
        return None
    cands = idx.get(toks[-1], [])
    if not cands:
        return None
    if len(cands) == 1:
        return cands[0]
    off_given = set(toks[:-1])
    scored = sorted(cands, key=lambda c: len(off_given & c["given"]), reverse=True)
    best = len(off_given & scored[0]["given"])
    second = len(off_given & scored[1]["given"]) if len(scored) > 1 else -1
    if best == 0 or best == second:
        return None
    return scored[0]


def _mp_cost(conn, mp_id: int, year: int, rates_by_year: dict) -> dict:
    """Core per-(mp, year) cost using an open connection + preloaded rates. Read-only."""
    row = conn.execute(
        text(
            """
            SELECT COALESCE(SUM(e.travel_cad), 0)      AS travel,
                   COALESCE(SUM(e.hospitality_cad), 0) AS hospitality,
                   COALESCE(SUM(e.contracts_cad), 0)   AS contracts,
                   COALESCE(SUM(e.salaries_cad), 0)    AS salaries,
                   COUNT(*)                            AS n_rows,
                   MAX(m.cabinet_role)                 AS cabinet_role
              FROM parliament.mp_expenses e
              JOIN parliament.mps m ON m.id = e.mp_id
             WHERE e.mp_id = :mid
               AND LEFT(e.period, 4) = :yr
            """
        ),
        {"mid": mp_id, "yr": str(year)},
    ).fetchone()

    travel, hospitality, contracts, salaries = (
        float(row[0]), float(row[1]), float(row[2]), float(row[3])
    )
    served = int(row[4]) > 0
    cabinet_role = row[5]

    rates = rates_by_year.get(int(year), {}) if served else {}
    office_total = round(travel + hospitality + contracts + salaries)
    indemnity = round(rates.get("mp", 0.0)) if served else 0
    tu_role = _topup_role(cabinet_role) if served else None
    top_up = round(rates.get(tu_role, 0.0)) if tu_role else 0

    return {
        "year": int(year),
        "served": served,
        "indemnity": indemnity,
        "top_up": top_up,
        "top_up_role": tu_role,
        "office": {
            "travel": round(travel),
            "hospitality": round(hospitality),
            "contracts": round(contracts),
            "salaries": round(salaries),
        },
        "office_total": office_total,
        "total": office_total + indemnity + top_up,
        "_note": _NOTE,
    }


def _senator_cost(conn, senator_id: int, year: int, rates_by_year: dict) -> dict:
    """Core per-(senator, year) cost. Read-only. Mirrors _mp_cost using
    parliament.senator_expenses (travel + hospitality + contracts + office + living) +
    the senator base indemnity. Senators carry no cabinet top-up."""
    row = conn.execute(
        text(
            """
            SELECT COALESCE(SUM(e.travel_cad), 0)      AS travel,
                   COALESCE(SUM(e.hospitality_cad), 0) AS hospitality,
                   COALESCE(SUM(e.contracts_cad), 0)   AS contracts,
                   COALESCE(SUM(e.office_cad), 0)      AS office,
                   COALESCE(SUM(e.living_cad), 0)      AS living,
                   COUNT(*)                            AS n_rows
              FROM parliament.senator_expenses e
             WHERE e.senator_id = :sid
               AND LEFT(e.period, 4) = :yr
            """
        ),
        {"sid": senator_id, "yr": str(year)},
    ).fetchone()

    travel, hospitality, contracts, office, living = (
        float(row[0]), float(row[1]), float(row[2]), float(row[3]), float(row[4])
    )
    served = int(row[5]) > 0
    office_total = round(travel + hospitality + contracts + office + living)
    indemnity = round(rates_by_year.get(int(year), {}).get("senator", 0.0)) if served else 0

    return {
        "year": int(year),
        "served": served,
        "indemnity": indemnity,
        "top_up": 0,
        "top_up_role": None,
        "office": {
            "travel": round(travel),
            "hospitality": round(hospitality),
            "contracts": round(contracts),
            "office": round(office),
            "living": round(living),
        },
        "office_total": office_total,
        "total": office_total + indemnity,
        "_note": _NOTE,
    }


def _current_year_block(conn, core, table: str, id_col: str, sid: int, rates_by_year: dict):
    """One member's CURRENT partial-year cost (year-to-date) + a projected full year, or None
    if they have no current-year disclosure. `core` = _mp_cost/_senator_cost; `table`/`id_col`
    (hardcoded constants — never user input) locate the member's rows to count disclosed
    quarters. The projection uses the national seasonal share of the quarters on file (see seasonal_projection), refining as quarters land."""
    cur = _current_partial_year(conn)
    if cur is None:
        return None
    c = core(conn, int(sid), cur, rates_by_year)
    if not c["served"]:
        return None
    quarters = {
        str(r[0]) for r in conn.execute(
            text("SELECT DISTINCT RIGHT(period, 2) FROM " + table + " WHERE " + id_col + " = :sid AND LEFT(period, 4) = :yr"),
            {"sid": int(sid), "yr": str(cur)},
        ).fetchall()
    }
    nq = len(quarters)
    indemnity_annual, top_up_annual = c["indemnity"], c.get("top_up", 0)
    indemnity = _prorate(indemnity_annual, nq)            # the core returns ANNUAL salary/top-up; this is a partial year
    top_up = _prorate(top_up_annual, nq)
    total = c["office_total"] + indemnity + top_up
    projected = None
    if nq >= PROJECTION_MIN_QUARTERS and nq < 4:
        # Office expenses: this member's year-to-date over the NATIONAL median share those same quarters make of a
        # year (a single member's own history is far too erratic); salary is the known annual rate, counted once.
        kind = "mp" if table.endswith("mp_expenses") else "senator"
        r = seasonal_projection(_quarter_series(conn).get(kind, {}), cur, quarters)
        if r and r["method"] == "seasonal":
            projected = round(c["office_total"] / r["share"]) + indemnity_annual + top_up_annual
        else:
            projected = _project(total, nq)
    return {
        "year": cur,
        "quarters": nq,
        "total": total,
        "office_total": c["office_total"],
        "indemnity": indemnity,
        "top_up": top_up,
        "projected_full_year": projected,
        "_note": (
            "year-to-date — {0} quarter(s) disclosed so far; projected = estimate from the usual seasonal pattern, "
            "actuals will differ".format(nq)
        ),
    }


# --------------------------------------------------------------------------- contract link

def _canonical_dept(owner_org: str) -> str:
    """The English canonical department name used as the parliament.dept_contracts key.

    parliament.minister_travel.owner_org is bilingual ('English | French'); the dept-contract
    rollup (mirrored from Gov Watch) is keyed by that English half, so a minister joins to their
    portfolio's contract volume with no extra normalization."""
    if not owner_org:
        return ""
    return owner_org.split(" | ", 1)[0].strip()


def _dept_contracts_map(conn, depts) -> dict:
    """{canonical dept -> {total, n, by_fy, central_purchaser, window, source}} from
    parliament.dept_contracts, for the given canonical department names.

    Fail-soft: if the table does not exist yet (pre-migration) or the query errors, returns {}
    so the contract link simply stays dark — the cost figures themselves are never affected."""
    depts = [d for d in (depts or []) if d]
    if not depts:
        return {}
    try:
        rows = conn.execute(
            text(
                "SELECT canonical_dept, total, n, by_fy, central_purchaser, "
                "       window_start, window_end, source "
                "FROM parliament.dept_contracts WHERE canonical_dept = ANY(:d)"
            ),
            {"d": list(depts)},
        ).fetchall()
    except Exception:
        return {}
    out = {}
    for cd, total, n, by_fy, central, ws, we, source in rows:
        if isinstance(by_fy, str):
            import json as _json
            try:
                by_fy = _json.loads(by_fy)
            except ValueError:
                by_fy = {}
        out[cd] = {
            "total": int(total) if total is not None else 0,
            "n": int(n) if n is not None else 0,
            "by_fy": by_fy if isinstance(by_fy, dict) else {},
            "central_purchaser": bool(central),
            "window": {"start": str(ws) if ws else None, "end": str(we) if we else None},
            "source": source,
        }
    return out


# --------------------------------------------------------------------------- public API

def mp_cost(engine, mp_id: int, year: int) -> dict:
    """Approximate taxpayer cost of one MP for one year.

    Returns {year, served, indemnity, top_up, top_up_role,
             office:{travel,hospitality,contracts,salaries}, office_total, total, _note}.
    """
    with engine.connect() as conn:
        return _mp_cost(conn, int(mp_id), int(year), _all_rates(conn))


def mp_cost_5yr(engine, mp_id: int) -> dict:
    """5-year cost for one MP -- one row per year the member served + the running total.

    Returns {mp_id, name, years:[mp_cost, ...], five_year_total, _note}.
    """
    with engine.connect() as conn:
        rates = _all_rates(conn)
        name = conn.execute(
            text("SELECT name FROM parliament.mps WHERE id = :mid"), {"mid": int(mp_id)}
        ).scalar()
        years = []
        for y in _complete_years(conn):
            c = _mp_cost(conn, int(mp_id), y, rates)
            if c["served"]:
                years.append(c)
        current = _current_year_block(conn, _mp_cost, "parliament.mp_expenses", "mp_id", int(mp_id), rates)

    five_year_total = sum(y["total"] for y in years)
    return {
        "mp_id": int(mp_id),
        "name": name,
        "years": years,
        "five_year_total": five_year_total,
        # current partial year (year-to-date) + projected full year — NEVER in five_year_total.
        "current": current,
        # Ministerial (departmental) travel + hospitality — borne CENTRALLY, a separate line
        # ON TOP of the MP office budget above (never folded into five_year_total). Zero for a
        # non-minister. This is the cost the MP budget can't show (why the PM shows ~$0 travel).
        "ministerial": minister_travel_5yr(engine, int(mp_id)),
        "_note": _NOTE,
    }


def minister_travel_5yr(engine, mp_id: int) -> dict:
    """Ministerial (departmental) travel + hospitality for an MP over the cost window.

    From parliament.minister_travel (open.canada.ca proactive disclosure) — the cost of a
    cabinet role that is borne CENTRALLY (government travel, official hospitality) and is NOT
    in the MP office budget. Aggregated per calendar year (matching mp_cost_5yr's window).
    Returns {years:[{year, travel, hospitality, total}], five_year_total, title, _note};
    five_year_total is 0 for a non-minister.
    """
    with engine.connect() as conn:
        cy = _complete_years(conn)
        rows = conn.execute(
            text(
                """
                SELECT LEFT(period, 4)::int          AS yr,
                       COALESCE(SUM(travel_cad), 0)      AS travel,
                       COALESCE(SUM(hospitality_cad), 0) AS hosp,
                       MAX(title)                        AS title
                  FROM parliament.minister_travel
                 WHERE mp_id = :mid AND LEFT(period, 4)::int BETWEEN :y0 AND :y1
                 GROUP BY 1 ORDER BY 1
                """
            ),
            {"mid": int(mp_id), "y0": cy[0], "y1": cy[-1]},
        ).fetchall()

        # Contract chain link (#373): this minister's CURRENT department (the most recent
        # minister_travel.owner_org) -> the federal contract volume their portfolio oversees
        # (parliament.dept_contracts, mirrored from Gov Watch). Fail-soft (None if no data).
        latest_org = conn.execute(text(_LATEST_ORG_SQL), {"mid": int(mp_id)}).scalar()
        _canon = _canonical_dept(latest_org or "")
        _cmap = _dept_contracts_map(conn, [_canon]) if _canon else {}
    contracts = {**_cmap[_canon], "department": _canon} if _canon and _canon in _cmap else None

    years = []
    title = None
    for yr, travel, hosp, t in rows:
        years.append({
            "year": int(yr),
            "travel": round(float(travel)),
            "hospitality": round(float(hosp)),
            "total": round(float(travel) + float(hosp)),
        })
        if t:
            title = t
    return {
        "years": years,
        "five_year_total": sum(y["total"] for y in years),
        "title": title,
        "contracts": contracts,   # portfolio contract volume (#373 Contract link); None if none
        "_note": (
            "ministerial (departmental) travel + hospitality — borne centrally (government "
            "travel/official hospitality), NOT charged to the MP office budget"
        ),
    }


def senator_cost(engine, senator_id: int, year: int) -> dict:
    """Approximate taxpayer cost of one senator for one year."""
    with engine.connect() as conn:
        return _senator_cost(conn, int(senator_id), int(year), _all_rates(conn))


def senator_cost_5yr(engine, senator_id: int) -> dict:
    """5-year cost for one senator -- one row per year served + the running total."""
    with engine.connect() as conn:
        rates = _all_rates(conn)
        name = conn.execute(
            text("SELECT name FROM parliament.senators WHERE id = :sid"),
            {"sid": int(senator_id)},
        ).scalar()
        years = []
        for y in _complete_years(conn):
            c = _senator_cost(conn, int(senator_id), y, rates)
            if c["served"]:
                years.append(c)
        current = _current_year_block(
            conn, _senator_cost, "parliament.senator_expenses", "senator_id", int(senator_id), rates
        )
    five_year_total = sum(y["total"] for y in years)
    return {
        "senator_id": int(senator_id),
        "name": name,
        "years": years,
        "five_year_total": five_year_total,
        # current partial year (year-to-date) + projected full year — NEVER in five_year_total.
        "current": current,
        "_note": _NOTE,
    }


def _year_projection(series, yr, mp_salary_annual, sen_base_annual, mp_total, senator_total, total,
                     ministerial_total, mp_q):
    """The `projected` block for the current partial year. Office expenses come from seasonal_projection per
    series; base salary is the annual rate x members (known, so never extrapolated). Falls back to plain
    annualizing of the year-to-date figures when there is no expense history to take shares from."""
    mp_p = seasonal_projection(series.get("mp", {}), yr)
    sen_p = seasonal_projection(series.get("senator", {}), yr)
    min_p = seasonal_projection(series.get("ministerial", {}), yr)
    if not mp_p:
        return {"mp": _project(mp_total, mp_q), "senator": _project(senator_total, mp_q),
                "parliamentary": _project(total, mp_q), "ministerial": _project(ministerial_total, mp_q),
                "combined": _project(total + ministerial_total, mp_q), "from_quarters": mp_q,
                "method": "annualized", "low": None, "high": None, "combined_low": None, "combined_high": None}

    def part(r, ytd_fallback):
        return (r["projected"], r["low"], r["high"]) if r else (ytd_fallback, ytd_fallback, ytd_fallback)

    mp_o, mp_lo, mp_hi = part(mp_p, 0)
    sn_o, sn_lo, sn_hi = part(sen_p, 0)
    mn, mn_lo, mn_hi = part(min_p, ministerial_total)
    mp_full = mp_o + mp_salary_annual
    sen_full = sn_o + sen_base_annual
    parl = mp_full + sen_full
    parl_lo = mp_lo + mp_salary_annual + sn_lo + sen_base_annual
    parl_hi = mp_hi + mp_salary_annual + sn_hi + sen_base_annual
    return {
        "mp": mp_full, "senator": sen_full, "parliamentary": parl, "ministerial": mn, "combined": parl + mn,
        "low": parl_lo, "high": parl_hi, "combined_low": parl_lo + mn_lo, "combined_high": parl_hi + mn_hi,
        "from_quarters": mp_q, "method": mp_p["method"], "share": mp_p["share"], "n_prior": mp_p["n_prior"],
    }


def parliament_cost_summary(engine) -> dict:
    """National "cost of Parliament" per year + the 5-year grand total (MPs; senators = Phase 2).

    Returns {by_year:[{year, mp_count, mp_office_total, mp_indemnity_total, senator_total,
                        total, avg_per_mp}, ...], grand_total_5yr, _note}.
    mp_indemnity_total = base indemnity (per served MP) + PM/minister top-ups.
    senator_total is the Phase-2 hook -- always 0 until parliament.senator_expenses lands.
    """
    with engine.connect() as conn:
        rates = _all_rates(conn)

        # office spend + how many distinct MPs disclosed (i.e. served), per year
        office_rows = conn.execute(
            text(
                """
                SELECT LEFT(e.period, 4)::int                                     AS yr,
                       COUNT(DISTINCT e.mp_id)                                     AS mp_count,
                       COALESCE(SUM(e.travel_cad + e.hospitality_cad
                                    + e.contracts_cad + e.salaries_cad), 0)        AS office_total
                  FROM parliament.mp_expenses e
                 GROUP BY 1
                 ORDER BY 1
                """
            )
        ).fetchall()

        # distinct served cabinet MPs per (year, cabinet_role) -> maps to a top-up role
        topup_rows = conn.execute(
            text(
                """
                SELECT LEFT(e.period, 4)::int  AS yr,
                       m.cabinet_role          AS cabinet_role,
                       COUNT(DISTINCT e.mp_id) AS n
                  FROM parliament.mp_expenses e
                  JOIN parliament.mps m ON m.id = e.mp_id
                 WHERE m.cabinet_role IS NOT NULL
                 GROUP BY 1, 2
                """
            )
        ).fetchall()

        # senator office spend + distinct-senator count per year (0 rows until
        # parliament.senator_expenses is populated)
        senator_rows = conn.execute(
            text(
                """
                SELECT LEFT(e.period, 4)::int AS yr,
                       COUNT(DISTINCT e.senator_id) AS sen_count,
                       COALESCE(SUM(COALESCE(e.travel_cad, 0) + COALESCE(e.hospitality_cad, 0)
                                    + COALESCE(e.contracts_cad, 0) + COALESCE(e.office_cad, 0)
                                    + COALESCE(e.living_cad, 0)), 0) AS office_total
                  FROM parliament.senator_expenses e
                 GROUP BY 1
                """
            )
        ).fetchall()

        # ministerial (departmental) travel + hospitality per year — borne CENTRALLY, kept as a
        # SEPARATE line from the parliamentary total (never folded into `total`).
        min_rows = conn.execute(
            text(
                "SELECT LEFT(period, 4)::int AS yr, COALESCE(SUM(total_cad), 0) AS t "
                "FROM parliament.minister_travel GROUP BY 1"
            )
        ).fetchall()

        # quarter coverage per disclosed MP-expense year — lets us flag PARTIAL years
        # (fewer than 4 quarters on file) so a 2-quarter 2020 or a 1-quarter 2026-to-date is
        # never silently summed into the headline as if it were a full year.
        cov_rows = conn.execute(
            text(
                "SELECT LEFT(period, 4)::int AS yr, "
                "array_agg(DISTINCT RIGHT(period, 2) ORDER BY RIGHT(period, 2)) AS qs "
                "FROM parliament.mp_expenses GROUP BY 1"
            )
        ).fetchall()
        series = _quarter_series(conn)      # per-quarter expense history: drives the seasonal projection + backtest

    quarters_by_year: dict = {int(yr): list(qs) for yr, qs in cov_rows}
    senator_by_year: dict = {
        int(yr): (int(sc), float(ot or 0)) for yr, sc, ot in senator_rows
    }
    ministerial_by_year: dict = {int(yr): round(float(t or 0)) for yr, t in min_rows}

    topup_by_year: dict = {}
    for yr, cabinet_role, n in topup_rows:
        role = _topup_role(cabinet_role)
        amount = rates.get(int(yr), {}).get(role, 0.0) if role else 0.0
        topup_by_year[int(yr)] = topup_by_year.get(int(yr), 0.0) + amount * int(n)

    # DYNAMIC window: the COMPLETE fiscal years (>= 4 quarters on file) drive the headline; it
    # auto-advances as new quarters are disclosed. current_year = the latest partial year beyond
    # the window (the "current year, to date"). Falls back to the static YEARS if the table is empty.
    complete_years, current_year, retired_years = window_years(quarters_by_year)

    by_year = []          # the COMPLETE fiscal years — drive the headline + chart
    addenda = []          # disclosed years OUTSIDE the window (partial quarters) — addenda only
    grand_total_5yr = 0
    ministerial_grand_5yr = 0
    for yr, mp_count, office_total in office_rows:
        yr = int(yr)
        mp_count = int(mp_count)
        office_total = round(float(office_total or 0))
        base_indemnity = round(rates.get(yr, {}).get("mp", 0.0)) * mp_count
        top_ups = round(topup_by_year.get(yr, 0.0))
        mp_indemnity_total = base_indemnity + top_ups
        sen_count, sen_office = senator_by_year.get(yr, (0, 0.0))
        senator_total = round(sen_office) + round(rates.get(yr, {}).get("senator", 0.0)) * sen_count
        total = office_total + mp_indemnity_total + senator_total
        ministerial_total = ministerial_by_year.get(yr, 0)   # separate line, not in `total`
        row = {
            "year": yr,
            "mp_count": mp_count,
            "mp_office_total": office_total,
            "mp_indemnity_total": mp_indemnity_total,
            "senator_count": sen_count,
            "senator_total": senator_total,
            "total": total,
            "ministerial_total": ministerial_total,
            "avg_per_mp": round(total / mp_count) if mp_count else 0,
        }
        if yr in complete_years:
            by_year.append(row)
            grand_total_5yr += total
            ministerial_grand_5yr += ministerial_total
        elif yr in retired_years:
            continue   # a COMPLETE year that rolled off the trailing window: not partial, so no addendum
        else:
            # A disclosed year OUTSIDE the complete window — always PARTIAL (< 4 quarters).
            # Reported as an addendum beneath the headline, NEVER folded into the totals above:
            # split by chamber (MP / Senate / ministerial) + quarters, and for the CURRENT year a
            # projected full-year (annualized from >= PROJECTION_MIN_QUARTERS quarters, else null — honest + auto-refining).
            mp_q = len(quarters_by_year.get(yr, []))
            # Salary is an ANNUAL rate: scale it to the quarters disclosed (see _prorate) so the year-to-date
            # figure does not mix a full year of salary with part a year of expenses. The PROJECTION below uses the
            # annual figures (salary is a known rate, not something to extrapolate).
            mp_indemnity_annual = mp_indemnity_total
            sen_base_annual = round(rates.get(yr, {}).get("senator", 0.0)) * sen_count
            mp_indemnity_total = _prorate(mp_indemnity_annual, mp_q)
            senator_total = round(sen_office) + _prorate(sen_base_annual, mp_q)
            total = office_total + mp_indemnity_total + senator_total
            mp_total = office_total + mp_indemnity_total
            projected = None
            if yr == current_year and mp_q >= PROJECTION_MIN_QUARTERS:
                projected = _year_projection(series, yr, mp_indemnity_annual, sen_base_annual,
                                             mp_total, senator_total, total, ministerial_total, mp_q)
            addenda.append({
                "year": yr,
                "quarters": quarters_by_year.get(yr, []),
                "kind": "latest_ytd" if yr > complete_years[-1] else "partial_pre_window",
                "mp": mp_total,
                "mp_office": office_total,
                "mp_indemnity": mp_indemnity_total,
                "mp_count": mp_count,
                "senator": senator_total,
                "senator_count": sen_count,
                "parliamentary": total,
                "ministerial": ministerial_total,
                "combined": total + ministerial_total,
                "projected": projected,
            })

    addenda.sort(key=lambda a: a["year"])
    return {
        "window": {
            "start": complete_years[0],
            "end": complete_years[-1],
            "years": list(complete_years),
            "current_year": current_year,
            "label": "{0} complete fiscal years ({1}–{2})".format(
                len(complete_years), complete_years[0], complete_years[-1]
            ),
        },
        "by_year": by_year,
        "grand_total_5yr": grand_total_5yr,
        # ministerial (departmental) travel + hospitality — borne CENTRALLY, reported as a
        # SEPARATE figure (never folded into grand_total_5yr) + a combined headline.
        "ministerial_grand_5yr": ministerial_grand_5yr,
        "combined_grand_5yr": grand_total_5yr + ministerial_grand_5yr,
        # disclosed data OUTSIDE the complete years (partial quarters) — shown beneath the headline
        # as addenda (e.g. 2026 year-to-date, split by chamber + projected), NEVER summed into the
        # totals above.
        "addenda": addenda,
        "projection_track_record": _projection_track_record(engine, series, by_year, current_year),
        "_note": (
            _NOTE
            + "; headline totals cover the {0} COMPLETE fiscal years {1}-{2} only (partial "
            "years are reported separately as addenda, never summed in); mp_indemnity_total "
            "includes PM/minister top-ups (current cabinet applied across years -- approximate); "
            "senator_total = senator office expenses + base indemnity (matched current senators; "
            "some former-senator spend is unattributed); ministerial_grand_5yr = cabinet "
            "ministers' departmental travel + hospitality borne centrally (open.canada.ca "
            "proactive disclosure), reported separately, NOT part of grand_total_5yr"
        ).format(len(complete_years), complete_years[0], complete_years[-1]),
    }


def _projection_track_record(engine, series, by_year, current_year) -> dict:
    """How the projection has performed. `backtest` = what the method WOULD have projected for past complete years
    (out-of-sample); `snapshots` = what we ACTUALLY published for the current / since-completed years, each compared
    with the actual once that year is complete. The snapshots table is read in its own connection and a missing table
    (migration 093 not applied yet) just means no history."""
    backtest = projection_backtest(series)
    errs = {}
    for stage in (2, 3):
        e = [abs(r["error_pct"]) for r in backtest if r["stage_quarters"] == stage]
        errs[str(stage)] = round(_median(e), 1) if e else None
    actual = {r["year"]: r["total"] for r in by_year}
    snaps = []
    try:
        with engine.connect() as c:
            rows = c.execute(text(
                "SELECT year, quarters_key, as_of, parliamentary_cad, combined_cad, low_cad, high_cad, method "
                "FROM parliament.cost_projection_snapshots ORDER BY year, as_of")).fetchall()
        for yr, qk, as_of, parl, comb, lo, hi, method in rows:
            yr = int(yr)
            row = {"year": yr, "quarters": qk.split(","), "as_of": as_of.isoformat() if hasattr(as_of, "isoformat") else str(as_of),
                   "parliamentary": float(parl), "combined": float(comb), "low": float(lo) if lo is not None else None,
                   "high": float(hi) if hi is not None else None, "method": method}
            if yr in actual and actual[yr]:       # the year is complete: show how far off this snapshot was
                row["actual"] = actual[yr]
                row["error_pct"] = round((float(parl) - actual[yr]) / actual[yr] * 100, 1)
            snaps.append(row)
    except Exception:  # noqa: BLE001 — no table / no history yet: the page just shows the backtest
        snaps = []
    return {"backtest": backtest, "typical_error_pct": errs, "snapshots": snaps}


def snapshot_projection(engine) -> dict:
    """Record the CURRENT year's projection once per disclosed-quarter set (idempotent), so the page can later show
    what we projected at each stage and how far off it was. Run weekly: the first run after a new quarter lands
    writes the new row; every other run is a no-op."""
    d = parliament_cost_summary(engine)
    ytd = [a for a in d["addenda"] if a["kind"] == "latest_ytd" and a.get("projected")]
    if not ytd or not ytd[-1]["projected"].get("parliamentary"):
        return {"recorded": False, "reason": "no projection available"}
    a = ytd[-1]
    p = a["projected"]
    key = ",".join(sorted(a["quarters"]))
    with engine.begin() as c:
        n = c.execute(text("""
            INSERT INTO parliament.cost_projection_snapshots
                (year, quarters_key, parliamentary_cad, combined_cad, low_cad, high_cad, method)
            VALUES (:y, :k, :p, :c, :lo, :hi, :m)
            ON CONFLICT (year, quarters_key) DO NOTHING"""),
            {"y": a["year"], "k": key, "p": p["parliamentary"], "c": p["combined"], "lo": p.get("low"),
             "hi": p.get("high"), "m": p.get("method")}).rowcount
    return {"recorded": bool(n), "year": a["year"], "quarters": key, "parliamentary": p["parliamentary"]}


def run_cost_projection_snapshot(engine) -> dict:
    """Weekly entry point; self-logs to parliament.ingest_log (task='cost_projection') like the other syncs."""
    import time as _t
    t0 = _t.time()
    try:
        result = snapshot_projection(engine)
    except Exception as exc:  # noqa: BLE001
        result = {"error": str(exc)}
    try:
        with engine.begin() as c:
            if result.get("error"):
                c.execute(text("INSERT INTO parliament.ingest_log (task, error) VALUES ('cost_projection', :e)"),
                          {"e": str(result["error"])[:500]})
            else:
                c.execute(text("INSERT INTO parliament.ingest_log (task, records_fetched, records_upserted) "
                               "VALUES ('cost_projection', 1, :u)"), {"u": 1 if result.get("recorded") else 0})
    except Exception:  # noqa: BLE001
        pass
    result["elapsed_s"] = round(_t.time() - t0, 1)
    return result


def officials_cost(engine, officials) -> list:
    """Approximate 5-year taxpayer cost for a batch of NAMED civic officials.

    Cross-product entry point (civic-watch transparency registry). Each official is
    name-matched to the WTF parliamentary roster, then costed via the EXISTING single
    source of truth (mp_cost_5yr / senator_cost_5yr) -- never recomputed here.

        officials: [{"name": "Given Surname", "role": "minister" | "senator"}, ...]
          role 'minister' -> parliament.mps WHERE cabinet_role IS NOT NULL
          role 'senator'  -> parliament.senators (current)

    Returns a list (INPUT ORDER preserved):
        [{name, role, matched, subject_type, subject_id,
          five_year_total, latest_year, latest_total, _note}, ...]
    On a miss (unknown role, no surname match, ambiguous surname): matched=False and
    every figure is None -- a public financial figure is never guessed.
    """
    # ONE connection for the whole batch: build both surname indexes, preload the rate
    # table once, then cost every matched member through the core SSOT helpers
    # (_mp_cost / _senator_cost — the exact math mp_cost_5yr / senator_cost_5yr use).
    # A per-member mp_cost_5yr(engine, id) would open a fresh connection AND re-query the
    # rates for each of ~46 officials — ~10s cold over the mesh. Sharing one connection +
    # one rate preload brings the batch well under the caller's timeout. Same figures.
    with engine.connect() as conn:
        min_idx = _index_by_family(
            conn.execute(
                text(
                    "SELECT id, name, COALESCE(given_name, ''), COALESCE(family_name, '') "
                    "FROM parliament.mps WHERE cabinet_role IS NOT NULL"
                )
            ).fetchall()
        )
        sen_idx = _index_by_family(
            conn.execute(
                text(
                    "SELECT id, name, COALESCE(given_name, ''), COALESCE(family_name, '') "
                    "FROM parliament.senators WHERE is_current = true"
                )
            ).fetchall()
        )
        rates = _all_rates(conn)  # preload once — shared across every member below
        cy = _complete_years(conn)  # dynamic window (auto-advances) — same for every member

        out = []
        for off in officials or []:
            name = (off.get("name") or "").strip() if isinstance(off, dict) else ""
            role = (off.get("role") or "").strip().lower() if isinstance(off, dict) else ""
            rec = {
                "name": name,
                "role": role,
                "matched": False,
                "subject_type": None,
                "subject_id": None,
                "five_year_total": None,
                "ministerial_5yr": None,   # departmental travel/hospitality (ministers only)
                "latest_year": None,
                "latest_total": None,
                "current": None,   # current partial year (year-to-date) + projected — matched only
                "contracts": None, # portfolio contract volume (#373 Contract link) — ministers only
                "_note": "no matching MP or senator in the parliamentary roster",
            }

            if role == "minister":
                member, subject_type, core = _match_official(min_idx, name), "mp", _mp_cost
            elif role == "senator":
                member, subject_type, core = _match_official(sen_idx, name), "senator", _senator_cost
            else:
                member, subject_type, core = None, None, None
                rec["_note"] = "unsupported role (expected 'minister' or 'senator')"

            if member:
                # one row per year the member served (mirrors *_cost_5yr), on the shared conn
                years = [core(conn, member["id"], y, rates) for y in cy]
                years = [c for c in years if c["served"]]
                latest = years[-1] if years else None
                cur_tbl, cur_id = (
                    ("parliament.mp_expenses", "mp_id") if subject_type == "mp"
                    else ("parliament.senator_expenses", "senator_id")
                )
                rec.update(
                    {
                        "matched": True,
                        "subject_type": subject_type,
                        "subject_id": member["id"],
                        "five_year_total": sum(c["total"] for c in years),
                        "latest_year": latest["year"] if latest else None,
                        "latest_total": latest["total"] if latest else None,
                        # current partial year (year-to-date) + projected full year — the same
                        # block the WTF member pages show (never part of five_year_total)
                        "current": _current_year_block(conn, core, cur_tbl, cur_id, member["id"], rates),
                        "_note": _NOTE,
                    }
                )
            out.append(rec)

        # Ministerial (departmental) travel + hospitality for the matched MINISTERS — ONE batched
        # query (borne centrally, NOT in the MP office budget). Senators aren't in this dataset.
        min_ids = [r["subject_id"] for r in out if r.get("subject_type") == "mp" and r.get("subject_id")]
        if min_ids:
            mrows = conn.execute(
                text(
                    "SELECT mp_id, COALESCE(SUM(total_cad), 0) AS t FROM parliament.minister_travel "
                    "WHERE mp_id = ANY(:ids) AND LEFT(period, 4)::int BETWEEN :y0 AND :y1 "
                    "GROUP BY mp_id"
                ),
                {"ids": min_ids, "y0": cy[0], "y1": cy[-1]},
            ).fetchall()
            mmap = {int(mid): round(float(t)) for mid, t in mrows}
            for r in out:
                if r.get("subject_id") in mmap:
                    r["ministerial_5yr"] = mmap[r["subject_id"]]

            # Contract chain link (#373): each matched minister's CURRENT department (the most
            # recent minister_travel.owner_org) -> the federal contract volume their portfolio
            # oversees (parliament.dept_contracts, mirrored from Gov Watch). Batched + fail-soft;
            # only confidently-crosswalked departments carry a figure.
            drows = conn.execute(
                text(
                    "SELECT DISTINCT ON (mp_id) mp_id, owner_org FROM parliament.minister_travel "
                    "WHERE mp_id = ANY(:ids) AND COALESCE(owner_org, '') <> '' "
                    "ORDER BY mp_id, " + CHRONO_DESC_SQL
                ),
                {"ids": min_ids},
            ).fetchall()
            dept_by_mp = {int(mid): _canonical_dept(org) for mid, org in drows}
            cmap = _dept_contracts_map(conn, sorted(set(dept_by_mp.values())))
            for r in out:
                canon = dept_by_mp.get(r.get("subject_id"))
                if canon and canon in cmap:
                    r["contracts"] = {**cmap[canon], "department": canon}

    return out


def cost_reconciliation(engine) -> dict:
    """Member-by-member reconciliation of the national headline — the public "show your work".

    Independently re-sums EVERY MP + senator over the window (using the exact per-member SSOT
    math that each member page shows) plus the ministerial line, then confirms the parts equal
    the parliament_cost_summary headline. Read-only. Powers the /cost methodology surface.

    Returns {window, reconciles, discrepancy, headline{parliamentary,ministerial,combined},
             member_sum{mp_total,senator_total,parliamentary,ministerial,combined},
             counts{mps,senators,ministers}, coverage[...], synced{...}, members[...], _note}.
    A tiny discrepancy (<= a dollar or two per member) is presentational rounding: each member
    page rounds its own annual figures, while the headline rounds each year's national aggregate.
    """
    from collections import defaultdict

    with engine.connect() as conn:
        cy = _complete_years(conn)      # dynamic window — same the summary/member pages use
        y0, y1 = cy[0], cy[-1]
        rates = _all_rates(conn)

        # MPs — per (mp, year) office + role over the window; cost each exactly as _mp_cost does
        # (round office per year, add base indemnity + any top-up for a served year).
        mp_tot: dict = defaultdict(lambda: {"name": None, "total": 0})
        for mid, yr, office, role, name in conn.execute(
            text(
                "SELECT e.mp_id, LEFT(e.period,4)::int AS yr, "
                "SUM(e.travel_cad+e.hospitality_cad+e.contracts_cad+e.salaries_cad) AS office, "
                "MAX(m.cabinet_role) AS role, MAX(m.name) AS name "
                "FROM parliament.mp_expenses e JOIN parliament.mps m ON m.id=e.mp_id "
                "WHERE LEFT(e.period,4)::int BETWEEN :y0 AND :y1 GROUP BY e.mp_id, yr"
            ),
            {"y0": y0, "y1": y1},
        ).fetchall():
            rate = rates.get(int(yr), {})
            tu = _topup_role(role)
            mp_tot[int(mid)]["total"] += (
                round(float(office or 0))
                + round(rate.get("mp", 0.0))
                + (round(rate.get(tu, 0.0)) if tu else 0)
            )
            mp_tot[int(mid)]["name"] = name
        mp_total = sum(v["total"] for v in mp_tot.values())

        # Senators — per (senator, year) office over the window + base senator indemnity.
        sen_tot: dict = defaultdict(lambda: {"name": None, "total": 0})
        for sid, yr, office, name in conn.execute(
            text(
                "SELECT e.senator_id, LEFT(e.period,4)::int AS yr, "
                "SUM(COALESCE(e.travel_cad,0)+COALESCE(e.hospitality_cad,0)+COALESCE(e.contracts_cad,0)"
                "+COALESCE(e.office_cad,0)+COALESCE(e.living_cad,0)) AS office, MAX(s.name) AS name "
                "FROM parliament.senator_expenses e JOIN parliament.senators s ON s.id=e.senator_id "
                "WHERE LEFT(e.period,4)::int BETWEEN :y0 AND :y1 GROUP BY e.senator_id, yr"
            ),
            {"y0": y0, "y1": y1},
        ).fetchall():
            sen_tot[int(sid)]["total"] += round(float(office or 0)) + round(
                rates.get(int(yr), {}).get("senator", 0.0)
            )
            sen_tot[int(sid)]["name"] = name
        senator_total = sum(v["total"] for v in sen_tot.values())

        # Ministerial (departmental) travel + hospitality over the window (separate line).
        mrow = conn.execute(
            text(
                "SELECT COALESCE(SUM(total_cad),0), COUNT(DISTINCT mp_id) "
                "FROM parliament.minister_travel WHERE LEFT(period,4)::int BETWEEN :y0 AND :y1"
            ),
            {"y0": y0, "y1": y1},
        ).fetchone()
        ministerial_total, n_ministers = round(float(mrow[0] or 0)), int(mrow[1] or 0)

        # Provenance for the methodology page: coverage + last successful sync per source.
        coverage = []
        for src, tbl in (
            ("MP office expenditures", "parliament.mp_expenses"),
            ("Senator expenditures", "parliament.senator_expenses"),
            ("Ministerial travel & hospitality", "parliament.minister_travel"),
        ):
            coverage.append({"source": src, **series_coverage(conn, tbl)})
        synced = {
            task: (run.isoformat() if run else None)
            for task, run in conn.execute(
                text(
                    "SELECT task, MAX(run_at) FROM parliament.ingest_log "
                    "WHERE COALESCE(error,'')='' GROUP BY task"
                )
            ).fetchall()
        }

    headline = parliament_cost_summary(engine)
    member_parl = mp_total + senator_total
    diff = member_parl - headline["grand_total_5yr"]
    min_diff = ministerial_total - headline["ministerial_grand_5yr"]
    tolerance = max(2, len(mp_tot) + len(sen_tot))   # <= ~$1-2/member = pure rounding
    # both sides sum the same records; any residual is per-year vs window rounding (the headline
    # rounds each year's aggregate, the member sum rounds each member's annual figures).
    reconciles = abs(diff) <= tolerance and abs(min_diff) <= max(2, len(cy) * 2)

    members = sorted(
        [{"name": v["name"], "type": "mp", "five_year_total": v["total"]} for v in mp_tot.values()]
        + [{"name": v["name"], "type": "senator", "five_year_total": v["total"]}
           for v in sen_tot.values()],
        key=lambda m: m["five_year_total"],
        reverse=True,
    )
    return {
        "window": headline["window"],
        "reconciles": reconciles,
        "discrepancy": diff,
        "headline": {
            "parliamentary": headline["grand_total_5yr"],
            "ministerial": headline["ministerial_grand_5yr"],
            "combined": headline["combined_grand_5yr"],
        },
        "member_sum": {
            "mp_total": mp_total,
            "senator_total": senator_total,
            "parliamentary": member_parl,
            "ministerial": ministerial_total,
            "combined": member_parl + ministerial_total,
        },
        "counts": {"mps": len(mp_tot), "senators": len(sen_tot), "ministers": n_ministers},
        "coverage": coverage,
        "synced": synced,
        "members": members,
        "_note": (
            "member-by-member reconciliation: the national headline equals the independent sum of "
            "every MP + senator over the {0} complete fiscal years {1}-{2}, plus the ministerial "
            "line (reported separately). Any residual is presentational rounding. Figures are "
            "approximate; a public figure is never guessed — an unmatched official is not counted."
        ).format(len(cy), y0, y1),
    }
