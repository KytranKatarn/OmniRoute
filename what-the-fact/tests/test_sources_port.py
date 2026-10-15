"""/sources port (design-handoff/wtf-sources.html): header tiles, ownership/language filter chips, and the lean marker bar. Built only from data the
route already fetches; an outlet below the MIN_N floor gets no marker at all."""

import pathlib

from jinja2 import ChoiceLoader, DictLoader, Environment, FileSystemLoader

from consumer.sources_stats import build_stats

TPL = pathlib.Path(__file__).resolve().parents[1] / "consumer" / "templates"
BASE = "{% block title %}{% endblock %}{% block meta %}{% endblock %}<body>{% block content %}{% endblock %}</body>"


def _o(name, **kw):
    d = {"id": 1, "slug": name.lower().replace(" ", "-"), "name": name, "bias_lean": "center", "owner_name": "Acme", "owner_type": "corporate",
         "language": "en", "avg_score": 0.0, "rolling_band": "center", "scored_article_count": 10, "total_articles": 12, "articles_7d": 2,
         "below_min_n": False, "fact_checked_count": 3}
    d.update(kw)
    return d


def _render(sources, q=""):
    env = Environment(loader=ChoiceLoader([DictLoader({"base.html": BASE}), FileSystemLoader(str(TPL))]))
    env.globals["url_for"] = lambda *a, **k: "#"
    return env.get_template("sources.html").render(sources=sources, q=q, sort="articles", min_n=5, stats=build_stats(sources))


SET = [_o("Alpha", avg_score=-0.5, rolling_band="center-left", owner_name="A Corp", owner_type="corporate"),
       _o("Beta", avg_score=0.5, rolling_band="center-right", owner_name="B Coop", owner_type="non_profit", language="fr"),
       _o("Gamma", avg_score=None, rolling_band=None, below_min_n=True, scored_article_count=2, owner_name="A Corp", owner_type="corporate")]


class TestStats:
    def test_counts_come_from_the_rows(self):
        s = build_stats(SET)
        assert (s["outlets"], s["measured"], s["owners"], s["scored_articles"]) == (3, 2, 2, 22)
        assert s["types"] == {"public": 0, "corporate": 2, "non_profit": 1, "independent": 0}
        assert s["languages"] == {"en": 2, "fr": 1}

    def test_empty_set_does_not_crash(self):
        assert build_stats([])["outlets"] == 0


class TestRender:
    def test_tiles_chips_and_cards_render(self):
        h = _render(SET)
        for needle in ("Outlets tracked", "Articles scored", "2 with a measured band", 'data-kind="type" data-val="corporate"',
                       'data-kind="lang" data-val="fr"', 'data-type="non_profit"', 'data-lang="fr"'):
            assert needle in h, needle

    def test_marker_position_follows_the_score(self):
        h = _render(SET)
        assert "left:25.0%" in h   # -0.5 -> a quarter of the way along
        assert "left:75.0%" in h   # +0.5 -> three quarters
        assert "lean -0.50" in h and "lean +0.50" in h

    def test_an_outlet_below_the_floor_gets_no_marker(self):
        h = _render([SET[2]])
        assert "wtf-src-tick" not in h.split("</style>")[1] and "Not enough to average" in h

    def test_extreme_scores_are_clamped_onto_the_bar(self):
        h = _render([_o("Edge", avg_score=1.4)])
        assert "left:100.0%" in h

    def test_filter_row_is_hidden_until_script_runs_and_absent_for_one_outlet(self):
        assert 'id="wtf-src-filters"' in _render(SET) and " hidden>" in _render(SET)
        assert 'id="wtf-src-filters"' not in _render([SET[0]]).split("</style>")[1].split("<script>")[0]

    def test_no_chip_for_a_type_with_no_outlets(self):
        h = _render(SET)
        assert 'data-val="public"' not in h and 'data-val="independent"' not in h
