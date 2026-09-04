"""/economy — one real economic indicator card (#6272, Batch 9).

design-handoff/wtf-economy.html's 6-card indicator grid is entirely
fabricated: its `IND` array is a hardcoded JS const (24-month sparklines +
fake "release dates"), not a fetch, for CPI/unemployment/GDP/overnight-
rate/FX/housing-starts. Scoping found real ingested data for exactly ONE
of the six on this platform — market_watch.boc_rate_decisions, the same
table /rates already reads — and it was 5 months stale because its only
puller was a manual one-off script with no schedule and no heartbeat (see
test_boc_rates_heartbeat.py for that half of the fix).

This file covers the OTHER half: the /economy route now surfaces that one
real indicator, honestly labeled as 1-of-6, with an explicit fallback when
the table is briefly unreachable — no invented numbers for the other five.
"""

import pathlib

import pytest
from jinja2 import ChoiceLoader, DictLoader, Environment, FileSystemLoader, select_autoescape

TPL = pathlib.Path(__file__).resolve().parents[1] / "consumer" / "templates"
ROUTES = pathlib.Path(__file__).resolve().parents[1] / "consumer" / "routes.py"

_STUB = ("{% block title %}{% endblock %}{% block meta %}{% endblock %}"
         "<body>{% block content %}{% endblock %}</body>")


@pytest.fixture(scope="module")
def env():
    return Environment(
        loader=ChoiceLoader([DictLoader({"base.html": _STUB}), FileSystemLoader(str(TPL))]),
        autoescape=select_autoescape(["html"]),
    )


def _render(env, boc_current, **overrides):
    kwargs = dict(articles=[], economy_count=3, business_count=2, foreign_count=1,
                  boc_current=boc_current, is_subscriber=False)
    kwargs.update(overrides)
    return env.get_template("economy.html").render(**kwargs)


def _body(html):
    return html.split("</style>", 1)[1]


class TestIndicatorCardWithRealData:
    def test_rate_and_date_render(self, env):
        import datetime
        b = _body(_render(env, {"rate_pct": "2.235", "decision_date": datetime.date(2026, 4, 1)}))
        assert "2.235%" in b
        assert "2026-04-01" in b

    def test_links_to_the_real_rates_page(self, env):
        b = _body(_render(env, {"rate_pct": "2.235", "decision_date": "2026-04-01"}))
        assert 'href="/rates"' in b

    def test_discloses_this_is_one_of_six_planned(self, env):
        b = _body(_render(env, {"rate_pct": "2.235", "decision_date": "2026-04-01"}))
        assert "one of six planned indicators" in b
        assert "invented numbers" in b


class TestNoDataFallback:
    def test_none_renders_an_honest_unavailable_state_not_a_crash(self, env):
        b = _body(_render(env, None))
        assert "temporarily unavailable" in b
        assert "None" not in b

    def test_none_does_not_link_to_rates(self, env):
        """A dead link with no data behind it is worse than no link."""
        b = _body(_render(env, None))
        assert 'href="/rates"' not in b


class TestNoFabricatedIndicators:
    """The five indicators with no real ingest must never render as their
    own card with a number — only appear (if at all) in the disclosure
    prose naming what's honestly missing."""

    def test_only_one_indicator_stat_box_renders(self, env):
        import datetime
        html = _render(env, {"rate_pct": "2.235", "decision_date": datetime.date(2026, 4, 1)})
        b = _body(html)
        assert b.count("wtf-ec-indicator-box") == 1

    @pytest.mark.parametrize("fake_indicator", [
        "CPI", "Unemployment rate", "Real GDP", "CAD per USD", "Housing starts",
    ])
    def test_fabricated_indicator_names_never_appear_as_a_card_label(self, env, fake_indicator):
        import datetime, re
        b = _body(_render(env, {"rate_pct": "2.235", "decision_date": datetime.date(2026, 4, 1)}))
        labels = re.findall(r'class="wtf-ec-stat-lbl"[^>]*>([^<]*)<', b)
        assert not any(fake_indicator in label for label in labels), labels


class TestEconomyRouteWiring:
    def test_route_queries_boc_rate_decisions_and_passes_it(self):
        src = ROUTES.read_text(encoding="utf-8")
        start = src.index("def economy(")
        end = src.index("\n\n\n", start)
        body = src[start:end]
        assert "market_watch.boc_rate_decisions" in body
        assert "boc_current=" in body

    def test_query_is_best_effort_and_cannot_crash_the_page(self):
        """The indicator table is a nice-to-have on this page — a query
        failure here must not 500 the whole /economy route."""
        src = ROUTES.read_text(encoding="utf-8")
        start = src.index("def economy(")
        end = src.index("\n\n\n", start)
        body = src[start:end]
        boc_block_start = body.index("boc_current = None")
        boc_block = body[boc_block_start:boc_block_start + 400]
        assert "except Exception:" in boc_block
