"""/ridings navigation aids: ridings-per-province bars and the A-Z jump (design-handoff/wtf-ridings.html, reduced to what the data supports)."""

import pathlib

from jinja2 import ChoiceLoader, DictLoader, Environment, FileSystemLoader

from consumer import riding_index as ri

TPL = pathlib.Path(__file__).resolve().parents[1] / "consumer" / "templates"
BASE = "{% block title %}{% endblock %}{% block meta %}{% endblock %}<body>{% block content %}{% endblock %}</body>"


def _r(num, name, prov="ON"):
    return {"district_number": num, "district_name": name, "province": prov, "candidate_name": "X", "party": "P", "vote_share": 40.0}


class TestLetterOf:
    def test_accents_fold_to_the_base_letter(self):
        assert ri.letter_of("Épinay") == "E" and ri.letter_of("Ça va") == "C" and ri.letter_of("  Ahuntsic") == "A"

    def test_a_name_with_no_leading_letter_has_no_group(self):
        assert ri.letter_of("123 Ridge") is None and ri.letter_of("") is None and ri.letter_of(None) is None


class TestProvinceCounts:
    def test_largest_first_ties_alphabetical_and_blank_province_skipped(self):
        rows = [_r(1, "A", "ON"), _r(2, "B", "ON"), _r(3, "C", "BC"), _r(4, "D", "AB"), _r(5, "E", None)]
        assert ri.province_counts(rows) == [("ON", 2), ("AB", 1), ("BC", 1)]


class TestBuildIndex:
    def test_first_row_of_each_letter_opens_its_group(self):
        listed = [_r(10, "Aurora"), _r(11, "Avalon"), _r(12, "Banff"), _r(13, "Éloi")]
        strip, first = ri.build_index(listed)
        assert first == {10: "A", 12: "B", 13: "E"}
        present = {lt for lt, ok in strip if ok}
        assert present == {"A", "B", "E"} and len(strip) == 26

    def test_empty_listing_has_every_letter_absent(self):
        strip, first = ri.build_index([])
        assert first == {} and not any(ok for _, ok in strip)


def _render(ridings, province="", q="", province_counts=None):
    env = Environment(loader=ChoiceLoader([DictLoader({"base.html": BASE}), FileSystemLoader(str(TPL))]))
    env.globals["url_for"] = lambda *a, **k: "#"
    az, first = ri.build_index(ridings)
    return env.get_template("ridings.html").render(
        elections=[], ge=44, election_date=None, tiles=[], ridings=ridings, total_ridings=len(ridings), provinces=["AB", "ON"], province=province, q=q,
        empty_msg="none", province_counts=province_counts if province_counts is not None else ri.province_counts(ridings), az=az, az_first=first)


MANY = [_r(i, f"{c}{i}", "ON" if i % 3 else "AB") for i, c in enumerate("ABCDEFGHIJKLMN", start=1)]


class TestRender:
    def test_chart_bars_link_to_the_province_filter_and_print_the_count(self):
        h = _render(MANY)
        assert "Ridings by province" in h and "/ridings?ge=44&province=ON" in h and "ON: 10 ridings" in h and 'width:100.0%' in h

    def test_az_strip_links_present_letters_and_mutes_absent_ones(self):
        h = _render(MANY)
        assert 'href="#az-A"' in h and 'id="az-A"' in h
        assert 'href="#az-Z"' not in h

    def test_a_short_listing_gets_no_az_strip(self):
        assert "Jump to letter" not in _render(MANY[:5])

    def test_one_province_means_no_chart(self):
        assert "Ridings by province" not in _render([_r(i, f"R{i}") for i in range(1, 15)])

    def test_current_province_bar_is_marked(self):
        assert 'aria-current="true"' in _render(MANY, province="ON")
