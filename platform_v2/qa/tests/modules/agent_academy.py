"""P.R.O.B.E. QA — Agent Academy Module Tests."""

import pytest
from ..conftest import navigate_to, screenshot, check_tabs, check_responsive, assert_no_console_errors


@pytest.mark.asyncio
async def test_agent_academy_loads(authenticated_page):
    page = authenticated_page
    response = await navigate_to(page, "/tools/agent-academy/")
    assert response.status == 200
    assert_no_console_errors(page, ignore_patterns=["favicon"])


@pytest.mark.asyncio
async def test_agent_academy_tabs(authenticated_page):
    page = authenticated_page
    await navigate_to(page, "/tools/agent-academy/")
    result = await check_tabs(page, ["Benchmarks", "Training", "A/B Testing", "Skills", "Reports"])
    assert len(result["missing"]) == 0, f"Missing tabs: {result['missing']}"


@pytest.mark.asyncio
async def test_agent_academy_responsive(authenticated_page):
    page = authenticated_page
    await navigate_to(page, "/tools/agent-academy/")
    paths = await check_responsive(page, "agent-academy")
    assert len(paths) == 3


@pytest.mark.asyncio
async def test_agent_academy_screenshot(authenticated_page):
    page = authenticated_page
    await navigate_to(page, "/tools/agent-academy/")
    path = await screenshot(page, "agent-academy-dashboard")
    assert path.endswith(".png")
