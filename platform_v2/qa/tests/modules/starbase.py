"""P.R.O.B.E. QA — Starbase compat.

Starbase Command was merged into the Department HQ **Fleet** tab (2026-04-08)
and decommissioned. The Fleet UI itself is covered by the department_hq suite
(see test_fleet_subtabs_render / test_fleet_node_*). The only remaining
"starbase" contract is the back-compat redirect for old URLs:

    /tools/starbase/<subpath>  --307-->  /tools/department-hq/<subpath>

These tests assert that contract instead of the old (removed) Fleet/Operations
tab labels.
"""

import pytest
from ..conftest import navigate_to, BASE_URL


@pytest.mark.asyncio
async def test_starbase_subpath_redirects_to_department_hq(authenticated_page):
    page = authenticated_page
    # The compat route 307s /tools/starbase/<subpath> -> /tools/department-hq/<subpath>.
    # DHQ uses hash-based tabs, so that intermediate path then bounces on to
    # /dashboard — assert the redirect CHAIN passed through Department HQ rather
    # than the (further-redirected) final URL.
    resp = await page.goto(f"{BASE_URL}/tools/starbase/roster", wait_until="domcontentloaded", timeout=15000)
    chain = []
    req = resp.request if resp else None
    while req is not None:
        chain.append(req.url)
        req = req.redirected_from
    assert any(
        "/tools/department-hq" in u for u in chain
    ), f"starbase compat redirect did not pass through Department HQ; chain={chain}"


@pytest.mark.asyncio
async def test_starbase_bare_path_resolves(authenticated_page):
    page = authenticated_page
    # Bare path no longer serves a Starbase page; it must still resolve (no 5xx).
    response = await navigate_to(page, "/tools/starbase/")
    assert response.status == 200, f"bare /tools/starbase/ returned {response.status}"
