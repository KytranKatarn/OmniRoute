"""Offline browser checks of actual Code Health table renderers and controls."""

from pathlib import Path

import pytest

playwright = pytest.importorskip("playwright.sync_api")
ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def page():
    with playwright.sync_playwright() as runtime:
        browser = runtime.chromium.launch(headless=True, args=["--no-sandbox"])
        page = browser.new_page(viewport={"width": 1300, "height": 900})
        page.route("**/*", lambda route: route.abort())
        page.set_content(
            """<html><body>
          <div id="chModuleTable"></div><div id="chStandaloneTable"></div>
          <div id="chWebsiteTable"></div><div id="chAuditTable"></div>
        </body></html>"""
        )
        page.add_script_tag(content=(ROOT / "static/js/archie-time.js").read_text())
        page.add_script_tag(content=(ROOT / "static/js/consciousness.js").read_text())
        page.evaluate(
            """() => {
          window._chAuditEntries = [{module_name:'alpha',issues_found:2},{module_name:'beta',issues_found:10}];
          window._chDisplayNames = {alpha:'Alpha', beta:'Beta'};
          window._chProposalCounts = {alpha:2};
          window.sortFixture = {
            alpha:{files:2, lines:900, by_type:{}},
            beta:{files:10, lines:10000, by_type:{}},
            '[APP_CORE]':{files:20, lines:20000, by_type:{}}
          };
          window.renderFixture = () => {
            _renderModuleTable(sortFixture, {}, {alpha:'green',beta:'orange'}, {alpha:'Alpha',beta:'Beta','[APP_CORE]':'Core'});
            _renderStandaloneTable(sortFixture, {alpha:'green',beta:'orange'});
            _renderWebsiteTable(sortFixture, {alpha:'green',beta:'orange'});
          };
          renderFixture();
        }"""
        )
        yield page
        browser.close()


def names(page, section):
    return [
        name.replace("✓", "").strip()
        for name in page.locator(f"#{section} tbody tr td:first-child").all_text_contents()
    ]


@pytest.mark.parametrize("section", ["chModuleTable", "chStandaloneTable", "chWebsiteTable"])
def test_all_module_tables_default_to_numeric_lines_and_toggle(section, page):
    rows = names(page, section)
    assert "core" in rows[0].lower()
    assert rows[1].strip().lower() == "beta" and rows[2].strip().lower() == "alpha"
    header = page.locator(f"#{section} th").nth(5)
    assert header.get_attribute("aria-sort") == "descending"
    header.locator("button").click()
    assert names(page, section)[0].strip().lower() == "alpha"
    assert header.get_attribute("aria-sort") == "ascending"
    page.locator(f"#{section} th").nth(3).locator("button").click()
    assert names(page, section)[0].strip().lower() == "beta"  # 10 > 2; not lexical.


def test_keyboard_status_sort_and_independent_refresh_state(page):
    button = page.locator("#chModuleTable th").nth(0).locator("button")
    button.focus()
    page.keyboard.press("Enter")
    assert names(page, "chModuleTable")[0] == "Alpha"
    page.locator("#chWebsiteTable th").nth(2).locator("button").click()
    assert names(page, "chWebsiteTable")[0].strip().lower() == "beta"  # ISSUES first.
    page.evaluate("renderFixture()")
    assert names(page, "chModuleTable")[0] == "Alpha"
    assert names(page, "chWebsiteTable")[0].strip().lower() == "beta"
    assert "core" in names(page, "chStandaloneTable")[0].lower()


def test_sort_preserves_search_filter_and_existing_row_button(page):
    page.locator("#chModuleSearch").fill("Alpha")
    page.evaluate(
        """() => {
      var row = [...document.querySelectorAll('#chModuleTable tbody tr')].find(r => r.cells[0].textContent.trim().startsWith('Alpha'));
      window.originalAuditButton = row.querySelector('button');
      originalAuditButton.addEventListener('click', () => { window.actionStillWorks = true; });
    }"""
    )
    page.locator("#chModuleTable th").nth(4).locator("button").click()
    assert page.locator("#chModuleTable tbody tr:visible").count() == 1
    page.locator("#chModuleTable tbody tr:visible button").click()
    assert page.evaluate("window.actionStillWorks === true")
    assert page.evaluate("window.originalAuditButton.isConnected")


def test_audit_sorts_raw_dates_counts_and_keeps_summary_pinned(page):
    page.evaluate(
        """() => {
      _renderAuditTable([
        {id:3,module_name:'PATTERN_COMPLIANCE',audited_at:'2026-10-15T00:00:00',status:'completed'},
        {id:2,module_name:'beta',audited_at:'2026-10-14T01:00:00',status:'findings_open',issues_found:10,lines_before:10000},
        {id:1,module_name:'alpha',audited_at:'2026-10-13T23:59:00',status:'completed',issues_found:2,lines_before:900}
      ]);
    }"""
    )
    assert names(page, "chAuditTable")[:2] == ["Beta", "Alpha"]
    assert "Pattern Compliance" in names(page, "chAuditTable")[-1]
    page.locator("#chAuditTable th").nth(9).locator("button").click()
    assert names(page, "chAuditTable")[:2] == ["Alpha", "Beta"]
    page.locator("#chAuditTable th").nth(5).locator("button").click()
    assert names(page, "chAuditTable")[:2] == ["Beta", "Alpha"]
    assert "Pattern Compliance" in names(page, "chAuditTable")[-1]


def test_missing_dates_last_in_both_directions_and_sort_does_not_mutate_input(page):
    page.evaluate(
        """() => {
      window.entriesFixture = [
        {id:1,module_name:'alpha',status:'completed'},
        {id:2,module_name:'beta',audited_at:'2026-10-14T01:00:00',status:'completed'}
      ];
      window.originalEntries = JSON.stringify(entriesFixture);
      _renderAuditTable(entriesFixture);
    }"""
    )
    assert names(page, "chAuditTable")[:2] == ["Beta", "Alpha"]
    page.locator("#chAuditTable th").nth(9).locator("button").click()
    assert names(page, "chAuditTable")[:2] == ["Beta", "Alpha"]
    assert page.evaluate("JSON.stringify(entriesFixture) === originalEntries")


def test_offline_visual_preview_and_disabled_sort_negative_control(page):
    import subprocess

    output = Path("/tmp/code-health-table-sorting")
    output.mkdir(exist_ok=True)
    page.add_style_tag(content=(ROOT / "static/css/lcars-tokens.css").read_text())
    page.add_style_tag(content=(ROOT / "static/css/consciousness-dashboard-v2.css").read_text())
    page.add_style_tag(
        content="""body{background:#111827;color:#e2e8f0;font-family:monospace;padding:16px}
      body>div{overflow-x:auto;margin-bottom:28px}table{width:100%;border-collapse:collapse}
      th,td{padding:10px;text-align:left;border-bottom:1px solid #334155}
      th{color:#94a3b8}button{cursor:pointer}"""
    )
    audit = """() => _renderAuditTable([
      {id:2,module_name:'beta',audited_at:'2026-10-14T01:00:00',status:'findings_open',issues_found:10,lines_before:10000},
      {id:1,module_name:'alpha',audited_at:'2026-10-13T23:59:00',status:'completed',issues_found:2,lines_before:900}
    ])"""
    page.evaluate(audit)
    page.screenshot(path=str(output / "after.png"), full_page=True)
    page.set_viewport_size({"width": 390, "height": 844})
    page.screenshot(path=str(output / "after-mobile.png"), full_page=True)
    page.set_viewport_size({"width": 1300, "height": 900})
    before = subprocess.check_output(
        ["git", "show", "HEAD:platform_v2/static/js/consciousness.js"], cwd=ROOT.parent, text=True
    )
    page.add_script_tag(content=before)
    page.evaluate("renderFixture()")
    page.evaluate(audit)
    page.screenshot(path=str(output / "before.png"), full_page=True)
    # Reintroduce the absent sorter in a throwaway browser only. The default
    # largest-first assertion must go red; no production/local source is mutated.
    with pytest.raises(AssertionError):
        assert names(page, "chModuleTable")[0] == "Core"
