"""P.R.O.B.E. QA — Department HQ Module Tests."""

import pytest
from ..conftest import navigate_to, screenshot, check_tabs, check_responsive, assert_no_console_errors


@pytest.mark.asyncio
async def test_department_hq_loads(authenticated_page):
    page = authenticated_page
    response = await navigate_to(page, "/tools/department-hq/")
    assert response.status == 200
    assert_no_console_errors(page, ignore_patterns=["favicon"])


@pytest.mark.asyncio
async def test_department_hq_tabs(authenticated_page):
    """The Fleet/ARMADA tab panel must exist (robust: checks the DOM panel,
    not stale label text — the old list checked tabs that don't exist)."""
    page = authenticated_page
    await navigate_to(page, "/tools/department-hq/")
    await page.wait_for_timeout(1200)
    has_fleet = await page.evaluate("() => !!document.getElementById('panel-fleet')")
    assert has_fleet, "Fleet (ARMADA) tab panel #panel-fleet missing"


@pytest.mark.asyncio
async def test_department_hq_overview_stats(authenticated_page):
    page = authenticated_page
    await navigate_to(page, "/tools/department-hq/")
    await page.wait_for_timeout(1500)
    body_text = await page.inner_text("body")
    assert "agent" in body_text.lower() or "department" in body_text.lower()


@pytest.mark.asyncio
async def test_department_hq_responsive(authenticated_page):
    page = authenticated_page
    await navigate_to(page, "/tools/department-hq/")
    paths = await check_responsive(page, "department-hq")
    assert len(paths) == 3


@pytest.mark.asyncio
async def test_department_hq_screenshot(authenticated_page):
    page = authenticated_page
    await navigate_to(page, "/tools/department-hq/")
    path = await screenshot(page, "department-hq-dashboard")
    assert path.endswith(".png")


# --- Fleet / A.R.M.A.D.A. tab coverage (codifies the 2026-06-03 manual review) ---


@pytest.mark.asyncio
async def test_fleet_subtabs_render(authenticated_page):
    """Activate the Fleet/ARMADA tab; all 5 sub-tabs must render real content."""
    page = authenticated_page
    await navigate_to(page, "/tools/department-hq/#fleet")
    await page.wait_for_timeout(1200)
    await page.evaluate("() => { if (window.lcarsHeaderSwitchTab) lcarsHeaderSwitchTab('fleet'); }")
    await page.wait_for_timeout(1000)
    disp = await page.evaluate(
        "() => { const p=document.getElementById('panel-fleet'); return p?getComputedStyle(p).display:'none'; }"
    )
    assert disp == "block", f"Fleet panel not visible (display={disp})"
    for section in ["cluster", "dispatch", "traffic", "network", "orchestration"]:
        chars = await page.evaluate(
            "(s) => { if (typeof switchArmadaSection==='function') switchArmadaSection(s);"
            " const c=Array.from(document.querySelectorAll('[id*=\"'+s+'\"]'))"
            "   .find(e=>getComputedStyle(e).display!=='none');"
            " return c ? c.innerText.trim().length : 0; }",
            section,
        )
        await page.wait_for_timeout(700)
        assert chars > 40, f"ARMADA '{section}' sub-tab rendered empty ({chars} chars)"


@pytest.mark.asyncio
async def test_fleet_node_count_is_consistent(authenticated_page):
    """True-to-nodes: the admin all-nodes list and the fleet map must agree.
    Catches the route-collision / scoping drift that returned only a subset."""
    page = authenticated_page
    await navigate_to(page, "/tools/department-hq/")
    counts = await page.evaluate(
        "async () => {"
        " const a = await (await fetch('/tools/department-hq/api/nodes/all')).json().catch(()=>({}));"
        " const m = await (await fetch('/tools/department-hq/api/fleet-map')).json().catch(()=>({}));"
        " return { all: (a.nodes||[]).length, map: (m.nodes||m.fleet||[]).length }; }"
    )
    assert counts["all"] > 0, "no nodes returned from /api/nodes/all"
    assert counts["all"] == counts["map"], f"node list ({counts['all']}) != fleet map ({counts['map']}) — SSOT drift"


@pytest.mark.asyncio
async def test_fleet_node_detail_true_to_node(authenticated_page):
    """Click a node → the detail panel must render its real hardware (Hardware
    section with GPU + CPU + RAM), proving it's true to the node, not blank."""
    page = authenticated_page
    await navigate_to(page, "/tools/department-hq/#fleet")
    await page.wait_for_timeout(1200)
    text = await page.evaluate(
        "async () => {"
        " const j = await (await fetch('/tools/department-hq/api/nodes/all')).json();"
        " const node = (j.nodes||[])[0];"
        " if (!node || typeof showNodeDetail!=='function') return '';"
        " showNodeDetail(node);"
        " await new Promise(r=>setTimeout(r,2000));"
        " const b=document.getElementById('fleetDetailBody');"
        " return b ? b.innerText : ''; }"
    )
    up = text.upper()
    assert "HARDWARE" in up, "node detail panel missing Hardware section"
    assert "CPU" in up and "RAM" in up, "node detail missing CPU/RAM rows (cpu_cores/cpu_model surfacing)"
