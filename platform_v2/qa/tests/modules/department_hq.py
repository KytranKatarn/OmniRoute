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
    page = authenticated_page
    await navigate_to(page, "/tools/department-hq/")
    result = await check_tabs(page, ["Overview", "Departments", "Agents", "Training", "Welfare", "Settings"])
    assert len(result["missing"]) == 0, f"Missing tabs: {result['missing']}"


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
