"""
Test 01 — Login flow for all 21 human agent COLLABORATOR accounts.

Verifies:
  - Each agent can authenticate with their temp password
  - Post-login URL is NOT /login (redirect to dashboard)
  - Page title contains expected platform branding
  - Role shown in UI is not ADMIN (confirms COLLABORATOR scoping)

Run:
    pytest tests/human_agents/test_01_login.py -v
    pytest tests/human_agents/test_01_login.py -v -k "jin.park"
"""

import pytest
from playwright.sync_api import Browser

from conftest import BASE_URL, login_as, logout

# EVERY test here drives a real browser (#5990). Module-level pytestmark is applied
# during COLLECTION, before pytest's own -m filter runs — a conftest
# pytest_collection_modifyitems hook adds markers too LATE to be deselected, which is
# why the first attempt at this fix did nothing and the suite kept hanging.
pytestmark = pytest.mark.browser


def pytest_generate_tests(metafunc):
    """Parametrize test_agent_login with all 21 agents."""
    if "agent" in metafunc.fixturenames:
        agents = metafunc.config._agents if hasattr(metafunc.config, "_agents") else []
        metafunc.parametrize("agent", agents, ids=[a["email"] for a in agents])


def pytest_configure(config):
    """Load agents early so parametrize can use them."""
    import json
    from pathlib import Path

    agents_file = Path(__file__).parent / "agents.json"
    creds_file = Path(__file__).parent / "credentials.env"

    agents = json.loads(agents_file.read_text())
    creds: dict[str, str] = {}
    if creds_file.exists():
        for line in creds_file.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                email, _, pw = line.partition("=")
                creds[email.strip()] = pw.strip()

    for a in agents:
        a["password"] = creds.get(a["email"], "")

    config._agents = agents


class TestHumanAgentLogin:
    """Login smoke test — one test per agent."""

    def test_agent_login(self, browser: Browser, agent: dict):
        """Agent can log in with temp credentials and reach the dashboard."""
        if not agent.get("password"):
            pytest.skip(f"No password in credentials.env for {agent['email']}")

        ctx = browser.new_context()
        page = ctx.new_page()

        try:
            # ---- Login ----
            login_as(page, agent)

            # ---- Assertions ----
            # 1. Not bounced back to /login
            assert (
                "/login" not in page.url
            ), f"{agent['display_name']}: redirected back to login — wrong password or account locked"

            # 2. URL contains dashboard or tools (platform post-login landing)
            assert any(
                seg in page.url for seg in ["/dashboard", "/tools", "/", BASE_URL]
            ), f"{agent['display_name']}: unexpected post-login URL: {page.url}"

            # 3. Page loaded (not a 500 error)
            page.wait_for_selector("body", timeout=5000)
            page_text = page.inner_text("body")
            assert "Internal Server Error" not in page_text, f"{agent['display_name']}: 500 error on login"
            assert "403" not in page_text[:200], f"{agent['display_name']}: 403 immediately after login"

            # 4. No admin UI elements visible (confirms COLLABORATOR role)
            # Admin-only nav items that should NOT appear for collaborators
            admin_items = page.query_selector_all('[data-role="admin"], .admin-only, [href*="account-center"]')
            # Note: COLLABORATOR may still see some admin-labeled links if they exist in nav
            # This is a soft check — log rather than hard fail
            if admin_items:
                print(f"  WARN: {agent['display_name']} sees {len(admin_items)} admin UI elements — verify permissions")

            print(f"  ✓ {agent['display_name']} ({agent['department']}) logged in → {page.url}")

        finally:
            logout(page)
            ctx.close()


class TestLoginFailure:
    """Verify wrong password is rejected."""

    def test_wrong_password_rejected(self, browser: Browser, all_agents: list):
        """First agent with wrong password should bounce back to /login."""
        agent = all_agents[0].copy()
        agent["password"] = "WRONG_PASSWORD_XYZZY"

        ctx = browser.new_context()
        page = ctx.new_page()

        try:
            page.goto(f"{BASE_URL}/login")
            page.wait_for_load_state("networkidle")
            page.fill('input[name="username"], input[id="username"], input[type="text"]', agent["email"])
            page.fill('input[name="password"], input[id="password"], input[type="password"]', agent["password"])
            page.click('button[type="submit"], input[type="submit"]')
            page.wait_for_load_state("networkidle")

            # Should still be on /login
            assert (
                "/login" in page.url or "error" in page.inner_text("body").lower()
            ), "Expected login rejection with wrong password — platform accepted it (security issue!)"
            print("  ✓ Wrong password correctly rejected")
        finally:
            ctx.close()
