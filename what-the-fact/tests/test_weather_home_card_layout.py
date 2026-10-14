"""/weather: the My-city card no longer becomes a stretched vertical tile (owner report 2026-10-14, caused by #3855).

#3855 made the home city's card show its whole forecast. In the narrow auto-fill grid that made one very tall tile, and CSS Grid's default
`align-items: stretch` stretched every card in its row to the same height (blank tiles). Fix: cards size to their own content, the home card spans
the full grid width and goes first. The REAL page CSS runs in a real browser; the control re-applies the old rules and must show the bug.
"""
import re
from pathlib import Path

import pytest

C = Path(__file__).resolve().parents[1] / "consumer"
HTML = (C / "templates" / "weather.html").read_text(encoding="utf-8")


def _css():
    css = "\n".join(re.findall(r"<style[^>]*>(.*?)</style>", HTML, flags=re.S))
    return re.sub(r"\{#.*?#\}|\{%.*?%\}|\{\{.*?\}\}", "", css, flags=re.S)


def _fn(name):
    m = re.search(r"  function %s\(.*?\n  \}\n" % re.escape(name), HTML, flags=re.S)
    assert m, f"function {name} not found"
    return m.group(0)


TOKENS = ":root{--wtf-bg-card:#0b1220;--wtf-border:#1f2937;--wtf-text:#f3f4f6;--wtf-text-2:#d1d5db;--wtf-text-muted:#6b7280;--wtf-local:#3b82f6;--wtf-aurora:#8b5cf6;--wtf-developing:#f59e0b}body{margin:0;padding:0 16px;font-family:sans-serif}"


def _card(name, periods, home=False):
    fc = "".join(
        f'<div class="wtf-wx-fc-day"><div class="wtf-wx-fc-lbl">DAY{i}</div><div class="wtf-wx-fc-t">1{i}&deg;</div>'
        + ('<div class="wtf-wx-fc-sum">A mix of sun and cloud</div>' if home else "")
        + "</div>"
        for i in range(periods)
    )
    cls = "wtf-wx-citycard is-capital" + (" is-home" if home else "")
    return (
        f'<a class="{cls}" href="#"><div class="wtf-wx-city-top"><span class="wtf-wx-city-name">{name}</span></div>'
        f'<div class="wtf-wx-city-row"><span>WIND 10 km/h</span><span>RH 60%</span></div>'
        f'<div class="wtf-wx-city-fc{" is-full" if home else ""}">{fc}</div><div class="wtf-wx-city-age">2 h ago</div></a>'
    )


def _measure(width, control=False, home_first=True):
    sync_api = pytest.importorskip("playwright.sync_api", reason="playwright is not installed: the real-browser layout check did NOT run")
    cards = [_card("Calgary", 13, home=True)] if home_first else []
    cards += [_card(n, 4) for n in ("Charlottetown", "Edmonton", "Fredericton", "Halifax", "Iqaluit", "Regina")]
    extra = ".wtf-wx-citygrid{align-items:stretch}.wtf-wx-citycard.is-home{grid-column:auto}" if control else ""
    pw = sync_api.sync_playwright().start()
    try:
        try:
            browser = pw.chromium.launch()
        except Exception as exc:  # noqa: BLE001
            pytest.skip(f"chromium is not available ({str(exc)[:60]}): the real-browser layout check did NOT run")
        page = browser.new_page(viewport={"width": width, "height": 900})
        page.set_content(f"<!doctype html><meta name=viewport content='width=device-width'><style>{TOKENS}{_css()}{extra}</style>"
                         f'<div class="wtf-wx-citygrid" id="g">{"".join(cards)}</div>')
        out = page.evaluate("""() => {
          const g = document.getElementById('g').getBoundingClientRect();
          const cs = [...document.querySelectorAll('.wtf-wx-citycard')];
          const rows = cs.map(c => { const r = c.getBoundingClientRect(); const last = c.lastElementChild.getBoundingClientRect();
            return {home: c.classList.contains('is-home'), w: r.width, h: r.height, slack: r.bottom - last.bottom, top: r.top}; });
          return {gridW: g.width, rows, over: document.documentElement.scrollWidth - window.innerWidth};}""")
        browser.close()
        return out
    finally:
        pw.stop()


@pytest.mark.parametrize("width", [1280, 390])
def test_home_card_spans_the_full_grid_width_and_leads(width):
    out = _measure(width)
    home = next(r for r in out["rows"] if r["home"])
    assert abs(home["w"] - out["gridW"]) <= 1, "the home card must span the whole grid"
    assert home["top"] == min(r["top"] for r in out["rows"]), "the home card must come first"
    assert out["over"] <= 1


@pytest.mark.parametrize("width", [1280, 390])
def test_no_card_is_stretched_taller_than_its_own_content(width):
    out = _measure(width)
    # a stretched card has a big empty gap below its last child; padding+border is ~14px
    for r in out["rows"]:
        assert r["slack"] <= 22, f"a card is stretched: {r['slack']:.0f}px of empty space under its content"


def test_control_the_old_rules_do_stretch_the_neighbours():
    out = _measure(1280, control=True)
    non_home = [r for r in out["rows"] if not r["home"]]
    assert max(r["slack"] for r in non_home) > 60, "the control should reproduce the stretched-tile bug"


def test_home_first_reorders_only_when_there_is_a_home_city():
    pw_mod = pytest.importorskip("playwright.sync_api")
    pw = pw_mod.sync_playwright().start()
    try:
        try:
            browser = pw.chromium.launch()
        except Exception as exc:  # noqa: BLE001
            pytest.skip(f"chromium is not available ({str(exc)[:60]})")
        page = browser.new_page()
        page.set_content("<body></body>")
        res = page.evaluate("() => {" + _fn("_homeFirst") + """
          const L = [{name:'A'},{name:'B'},{name:'C'}];
          return [_homeFirst(L,'C').map(x=>x.name).join(''), _homeFirst(L,'A').map(x=>x.name).join(''), _homeFirst(L,null).map(x=>x.name).join(''),
                  _homeFirst(L,'Z').map(x=>x.name).join(''), L.map(x=>x.name).join('')];}""")
        browser.close()
    finally:
        pw.stop()
    assert res == ["CAB", "ABC", "ABC", "ABC", "ABC"]  # input never mutated; unknown/absent home leaves the order alone
