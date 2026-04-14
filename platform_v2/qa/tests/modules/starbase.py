"""P.R.O.B.E. QA — Starbase Command Module Tests."""

import pytest
from ..conftest import navigate_to, screenshot, check_tabs, check_responsive, assert_no_console_errors


@pytest.mark.asyncio
async def test_starbase_loads(authenticated_page):
    page = authenticated_page
    response = await navigate_to(page, "/tools/starbase/")
    assert response.status == 200
    assert_no_console_errors(page, ignore_patterns=["favicon"])


@pytest.mark.asyncio
async def test_starbase_tabs(authenticated_page):
    page = authenticated_page
    await navigate_to(page, "/tools/starbase/")
    result = await check_tabs(page, ["Fleet", "Operations"])
    assert len(result["missing"]) == 0, f"Missing tabs: {result['missing']}"


@pytest.mark.asyncio
async def test_starbase_responsive(authenticated_page):
    page = authenticated_page
    await navigate_to(page, "/tools/starbase/")
    paths = await check_responsive(page, "starbase")
    assert len(paths) == 3


@pytest.mark.asyncio
async def test_starbase_screenshot(authenticated_page):
    page = authenticated_page
    await navigate_to(page, "/tools/starbase/")
    path = await screenshot(page, "starbase-dashboard")
    assert path.endswith(".png")
