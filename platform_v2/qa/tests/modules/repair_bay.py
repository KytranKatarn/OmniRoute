"""P.R.O.B.E. QA — Repair Bay Module Tests."""

import pytest
from ..conftest import navigate_to, screenshot, check_tabs, check_responsive, assert_no_console_errors


@pytest.mark.asyncio
async def test_repair_bay_loads(authenticated_page):
    page = authenticated_page
    response = await navigate_to(page, "/tools/repair-bay/")
    assert response.status == 200
    assert_no_console_errors(page, ignore_patterns=["favicon"])


@pytest.mark.asyncio
async def test_repair_bay_tabs(authenticated_page):
    page = authenticated_page
    await navigate_to(page, "/tools/repair-bay/")
    result = await check_tabs(page, ["Diagnose", "Repairs", "Test Bay", "Ship"])
    assert len(result["missing"]) == 0, f"Missing tabs: {result['missing']}"


@pytest.mark.asyncio
async def test_repair_bay_responsive(authenticated_page):
    page = authenticated_page
    await navigate_to(page, "/tools/repair-bay/")
    paths = await check_responsive(page, "repair-bay")
    assert len(paths) == 3


@pytest.mark.asyncio
async def test_repair_bay_screenshot(authenticated_page):
    page = authenticated_page
    await navigate_to(page, "/tools/repair-bay/")
    path = await screenshot(page, "repair-bay-dashboard")
    assert path.endswith(".png")
