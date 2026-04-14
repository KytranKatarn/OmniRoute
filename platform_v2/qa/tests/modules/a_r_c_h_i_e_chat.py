"""P.R.O.B.E. QA — A.R.C.H.I.E. Chat Module Tests."""

import pytest
from ..conftest import navigate_to, screenshot, check_tabs, check_responsive, assert_no_console_errors


@pytest.mark.asyncio
async def test_archie_chat_loads(authenticated_page):
    page = authenticated_page
    response = await navigate_to(page, "/tools/archie-chat/")
    assert response.status == 200
    assert_no_console_errors(page, ignore_patterns=["favicon"])


@pytest.mark.asyncio
async def test_archie_chat_tabs(authenticated_page):
    page = authenticated_page
    await navigate_to(page, "/tools/archie-chat/")
    result = await check_tabs(page, ["Chat", "Collaboration", "Claude TTY", "History", "Settings"])
    assert len(result["missing"]) == 0, f"Missing tabs: {result['missing']}"


@pytest.mark.asyncio
async def test_archie_chat_responsive(authenticated_page):
    page = authenticated_page
    await navigate_to(page, "/tools/archie-chat/")
    paths = await check_responsive(page, "archie-chat")
    assert len(paths) == 3


@pytest.mark.asyncio
async def test_archie_chat_screenshot(authenticated_page):
    page = authenticated_page
    await navigate_to(page, "/tools/archie-chat/")
    path = await screenshot(page, "archie-chat-dashboard")
    assert path.endswith(".png")
