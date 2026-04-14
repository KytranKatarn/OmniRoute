"""P.R.O.B.E. QA — Consciousness Module Tests."""

import pytest
from ..conftest import navigate_to, screenshot, check_tabs, check_responsive, assert_no_console_errors


@pytest.mark.asyncio
async def test_consciousness_loads(authenticated_page):
    page = authenticated_page
    response = await navigate_to(page, "/tools/consciousness/")
    assert response.status == 200
    assert_no_console_errors(page, ignore_patterns=["favicon"])


@pytest.mark.asyncio
async def test_consciousness_tabs(authenticated_page):
    page = authenticated_page
    await navigate_to(page, "/tools/consciousness/")
    result = await check_tabs(page, ["Dashboard", "Knowledge", "Team", "GitHub", "Languages"])
    assert len(result["missing"]) == 0, f"Missing tabs: {result['missing']}"


@pytest.mark.asyncio
async def test_consciousness_devhq_tab(authenticated_page):
    page = authenticated_page
    await navigate_to(page, "/tools/consciousness/#devhq")
    await page.wait_for_timeout(1000)
    result = await check_tabs(page, ["Overview", "Projects", "Ideas", "Decisions", "System"])
    assert len(result["missing"]) == 0, f"Missing Dev HQ subtabs: {result['missing']}"


@pytest.mark.asyncio
async def test_consciousness_knowledge_content(authenticated_page):
    page = authenticated_page
    await navigate_to(page, "/tools/consciousness/")
    knowledge_tab = page.locator("text='Knowledge'").first
    await knowledge_tab.click()
    await page.wait_for_timeout(1500)
    body_text = await page.inner_text("body")
    assert len(body_text) > 500, "Knowledge tab appears empty"


@pytest.mark.asyncio
async def test_consciousness_responsive(authenticated_page):
    page = authenticated_page
    await navigate_to(page, "/tools/consciousness/")
    paths = await check_responsive(page, "consciousness")
    assert len(paths) == 3


@pytest.mark.asyncio
async def test_consciousness_screenshot(authenticated_page):
    page = authenticated_page
    await navigate_to(page, "/tools/consciousness/")
    path = await screenshot(page, "consciousness-dashboard")
    assert path.endswith(".png")
