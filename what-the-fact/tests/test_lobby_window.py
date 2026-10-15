"""/lobbying "Last 30 days": a real zero versus data that does not reach the window (found by looking at the live page, 2026-10-15)."""

import pathlib
from datetime import date

from jinja2 import Environment, FileSystemLoader

from consumer.lobby_window import last_30d_tile

TODAY = date(2026, 10, 15)


class TestTile:
    def test_filings_in_the_window_are_just_the_count(self):
        assert last_30d_tile(12, date(2026, 10, 10), TODAY) == {"value": 12, "detail": None}

    def test_stale_registry_is_a_dash_with_the_date_the_data_ends_not_a_zero(self):
        t = last_30d_tile(0, date(2026, 8, 12), TODAY)     # the live case on 2026-10-15
        assert t["value"] == "—" and t["detail"] == "registry data ends 2026-08-12"

    def test_data_that_reaches_today_but_has_no_filings_is_a_real_zero(self):
        assert last_30d_tile(0, date(2026, 10, 1), TODAY) == {"value": 0, "detail": None}

    def test_no_filings_at_all_is_a_dash(self):
        assert last_30d_tile(0, None, TODAY)["value"] == "—" and last_30d_tile(None, None, TODAY)["detail"] == "no filings on record"

    def test_boundary_exactly_30_days_old_is_still_a_zero_and_31_is_a_dash(self):
        assert last_30d_tile(0, date(2026, 9, 15), TODAY)["value"] == 0
        assert last_30d_tile(0, date(2026, 9, 14), TODAY)["value"] == "—"


C = pathlib.Path(__file__).resolve().parents[1] / "consumer" / "templates"
SRC = (C / "lobbying.html").read_text(encoding="utf-8")
ROUTES = (pathlib.Path(__file__).resolve().parents[1] / "consumer" / "routes.py").read_text()


def _tiles(stats):
    """Render only the stat-tile block, the way tests/test_lobbying_stat_cards.py does (the full page needs a Flask request)."""
    env = Environment(loader=FileSystemLoader(str(C)))
    start = SRC.index("{# Same five figures")
    end = SRC.index("</div>", SRC.index('<div class="wtf-lob-tiles">')) + 6
    tpl = env.from_string('{% from "_archetypes.html" import stat_tiles %}' + SRC[start:end])
    return tpl.render(stats=stats)


BASE = {"contacts": 68015, "orgs": 3619, "mps": 341, "first_seen": date(2008, 1, 1), "last_seen": date(2026, 8, 12), "synced_at": None}


class TestPage:
    def test_a_stale_registry_renders_a_dash_and_the_end_date(self):
        h = _tiles(dict(BASE, last_30d=0, last_30d_tile={"value": "—", "detail": "registry data ends 2026-08-12"}))
        assert "registry data ends 2026-08-12" in h and "Last 30 days" in h and ">0<" not in h.split("Last 30 days")[1][:200]

    def test_a_real_count_renders_without_a_caveat(self):
        h = _tiles(dict(BASE, last_30d=7, last_30d_tile={"value": 7, "detail": None}))
        assert "registry data ends" not in h and ">7<" in h.split("Last 30 days")[1][:200]

    def test_without_the_new_key_the_old_behaviour_is_unchanged(self):
        assert ">0<" in _tiles(dict(BASE, last_30d=0)).split("Last 30 days")[1][:200]

    def test_the_payload_computes_the_tile_from_the_real_last_seen(self):
        assert '_lobby_window.last_30d_tile(stats.get("last_30d"), stats.get("last_seen")' in ROUTES
