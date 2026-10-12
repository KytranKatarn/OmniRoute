"""/cost and /senator/<slug>: the Senate's 2010-2016 expenses (parliament.senator_expenses_legacy), shown with NO caucus label.

Why no caucus (task 7173, option D): those 23 quarterly PDFs name no party and the database holds no dated caucus source before
2016-Q3, so any label would be a guess about a named person. Pinned here: the builders never read or emit a caucus, roster senators
link to their profile while former senators are plain text, names are escaped, a repayment prints as a negative, and a missing table
hides the panel instead of 500ing the page.
"""
import datetime
import re
from pathlib import Path

import jinja2

ROOT = Path(__file__).resolve().parent.parent
SRC = (ROOT / "consumer" / "routes.py").read_text(encoding="utf-8")
COST = (ROOT / "consumer" / "templates" / "cost.html").read_text(encoding="utf-8")
SEN = (ROOT / "consumer" / "templates" / "senator.html").read_text(encoding="utf-8")


def _ns():
    pre = re.search(r"^_PARTY_COST_CACHE: dict.*?(?=^def _party_cost_panel)", SRC, re.S | re.M).group(0)       # _fmt_m + TTL
    panel = re.search(r"^_SENATE_LEGACY_CACHE: dict.*?(?=^@bp\.get\(\"/cost\"\))", SRC, re.S | re.M).group(0)
    helper = re.search(r"^def _senator_legacy_expense_rows.*?(?=^def _senator_travel)", SRC, re.S | re.M).group(0)
    ns = {"os": __import__("os"), "time": __import__("time"), "text": lambda s: s}
    for block in (pre, panel, helper):
        exec(block, ns)
    return ns


class _Res:
    def __init__(self, rows):
        self._r = rows

    def mappings(self):
        return self

    def all(self):
        return self._r


class _Conn:
    def __init__(self, results):
        self.results = list(results)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, *_):
        return _Res(self.results.pop(0))


def _db(*results):
    class _E:
        def begin(self):
            return _Conn(results)
    return lambda: _E()


def _broken_db():
    class _E:
        def begin(self):
            raise RuntimeError("relation parliament.senator_expenses_legacy does not exist")
    return lambda: _E()


D = datetime.date


def _row(slug, sid, name, q, total, first=D(2010, 9, 1), last=D(2016, 6, 30)):
    return {"slug": slug, "senator_id": sid, "published": name, "quarters": q, "total": total, "first_start": first, "last_end": last}


META = [{"periods": 23, "first": D(2010, 9, 1), "last": D(2016, 6, 30), "total": 106907889.0}]


def _panel(rows, meta=META):
    ns = _ns()
    ns["_db"] = _db(rows, meta)
    return ns["_senate_legacy_panel"](), ns


# --- the builder -----------------------------------------------------------------------------------------------------------------------


def test_display_names_use_the_loaders_normaliser():
    ns = _ns()
    f = ns["_legacy_display_name"]
    assert f("NGO, HON. THANH HAI") == "Thanh Hai Ngo"
    assert f("HON. DON MEREDITH") == "Don Meredith"
    assert f("POULIN(CHARETTE), HON.MARIE-P.") == "Marie-P. Poulin(Charette)"
    assert f(None) == ""


def test_rows_keep_the_sql_order_and_link_only_roster_senators():
    out, _ = _panel([
        _row("don-meredith", 5, "HON. DON MEREDITH", 20, 900000.0),
        _row(None, None, "LEBRETON, HON. MARJORY", 18, 650000.5),
    ])
    a, b = out["rows"]
    assert (a["name"], a["slug"]) == ("Don Meredith", "don-meredith")
    assert (b["name"], b["slug"]) == ("Marjory Lebreton", None)                 # a former senator has no profile page: plain text
    assert a["total"] == "$900,000" and a["avg"] == "$45,000" and a["quarters"] == 20
    assert out["senators"] == 2 and out["periods"] == 23 and out["total"] == "$106.9M"
    assert (out["first"], out["last"]) == ("September 2010", "June 2016")
    assert a["span"] == "2010–2016"


def test_the_builder_never_reads_or_emits_a_caucus():
    out, _ = _panel([_row("don-meredith", 5, "HON. DON MEREDITH", 4, 1000.0)])
    flat = repr(out).lower()
    assert "caucus" not in flat and "party" not in flat
    sql = " ".join(re.findall(r'text\("""(.*?)"""\)', re.search(r"def _senate_legacy_panel.*?(?=^@bp\.get)", SRC, re.S | re.M).group(0), re.S)).lower()
    assert "caucus" not in sql and "party" not in sql                                   # nobody adds a guessed label to the query


def test_a_missing_or_empty_table_hides_the_panel_instead_of_raising():
    ns = _ns()
    ns["_db"] = _broken_db()
    assert ns["_senate_legacy_panel"]()["rows"] == []
    out, _ = _panel([], [{"periods": 0, "first": None, "last": None, "total": None}])
    assert out["rows"] == []


def test_the_profile_helper_returns_rows_and_swallows_a_missing_table():
    ns = _ns()
    rows = [{"period_start": D(2016, 3, 1), "period_end": D(2016, 6, 30), "travel_cad": 100.0, "hospitality_cad": 0.0, "office_cad": 5.0, "living_cad": 0.0, "total_cad": 105.0}]
    ns["_db"] = _db(rows)
    assert ns["_senator_legacy_expense_rows"](7)[0]["total_cad"] == 105.0
    ns["_db"] = _broken_db()
    assert ns["_senator_legacy_expense_rows"](7) == []


def test_the_profile_route_attaches_the_legacy_rows():
    assert 'senator["legacy_expense_periods"] = _senator_legacy_expense_rows(senator["id"])' in SRC
    assert "senate_legacy=_senate_legacy_panel()" in SRC


# --- the templates ---------------------------------------------------------------------------------------------------------------------


def _render(src, start, end, **ctx):
    """Render one template block; whitespace is collapsed and &ndash; read as the character, so assertions test words, not line wraps."""
    a = src.index(start)
    b = src.index(end, a)
    html = jinja2.Environment(autoescape=True).from_string(src[a:b]).render(**ctx)
    return re.sub(r"\s+", " ", html.replace("&ndash;", "\u2013"))


def _cost_html(rows):
    panel = {"rows": rows, "senators": len(rows), "total": "$106.9M", "periods": 23, "first": "September 2010", "last": "June 2016"}
    return _render(COST, "{% if senate_legacy and senate_legacy.rows %}", "{% if annual_costs and annual_costs.blocks %}", senate_legacy=panel)


def _r(name, slug=None, q=10, total="$100,000", avg="$10,000"):
    return {"name": name, "slug": slug, "quarters": q, "total": total, "avg": avg, "span": "2010–2016"}


def test_the_cost_panel_says_why_there_is_no_caucus_and_links_only_roster_senators():
    html = _cost_html([_r("Don Meredith", "don-meredith"), _r("Marjory Lebreton")])
    assert "No caucus is shown for this period" in html and "rather than guess" in html
    assert 'href="/senator/don-meredith"' in html
    assert html.count("/senator/") == 1                                            # the former senator is not linked
    assert "<th>Caucus</th>" not in html
    assert "do not line up with the calendar-year caucus table" in html


def test_the_cost_panel_escapes_a_hostile_name_and_folds_the_long_tail_into_details():
    rows = [_r("<script>alert(1)</script>")] + [_r(f"Senator {i}") for i in range(29)]
    html = _cost_html(rows)
    assert "<script>" not in html and "&lt;script&gt;" in html
    assert "Show the other 5 senators" in html and html.count("<details") == 1


def test_the_cost_panel_is_absent_without_data():
    assert "data-cost-senate-legacy" not in _render(COST, "{% if senate_legacy and senate_legacy.rows %}", "{% if annual_costs and annual_costs.blocks %}",
                                                    senate_legacy={"rows": []})


def test_the_profile_section_formats_money_with_repayments_and_a_note_about_party():
    rows = [
        {"period_start": D(2016, 3, 1), "period_end": D(2016, 6, 30), "travel_cad": 1234.4, "hospitality_cad": 0.0, "office_cad": 30000.0, "living_cad": -6045.54, "total_cad": 25188.86},
        {"period_start": D(2010, 9, 1), "period_end": D(2010, 11, 30), "travel_cad": 0.0, "hospitality_cad": 0.0, "office_cad": 100.0, "living_cad": 0.0, "total_cad": 100.0},
    ]
    html = _render(SEN, "{# Earlier expenses, Sept 2010", "{# Biography #}", senator={"legacy_expense_periods": rows})
    assert "Earlier quarterly expenses (Sep 2010 – Jun 2016)" in html
    assert "-$6,046" in html and "$25,189" in html and "$1,234" in html          # a repayment keeps its sign
    assert "—" in html                                                      # zero shows as an em dash, like the 2016+ table
    assert "name no party, so no caucus is shown" in html and "Caucus" not in html.replace("no caucus is shown", "")


def test_the_profile_section_is_absent_without_legacy_rows():
    assert "Earlier quarterly expenses" not in _render(SEN, "{# Earlier expenses, Sept 2010", "{# Biography #}", senator={"legacy_expense_periods": []})


def test_the_new_panel_sits_after_the_caucus_panel_and_the_section_inside_the_subscriber_gate():
    assert COST.index("data-cost-by-caucus") < COST.index("data-cost-senate-legacy") < COST.index("data-cost-by-fiscal-year")
    gate_open, gate_close = SEN.index("{% if is_subscriber %}"), SEN.index("{% else %}\n  {{ paywall(")
    assert gate_open < SEN.index("Earlier expenses, Sept 2010") < gate_close
