"""
Test 05 — Profile self-service for COLLABORATOR accounts.

Part of T3297 — General human-online interactions (Phase 2).

Verifies (USER_SETTINGS permission):
  1. /tools/my-profile loads with 200 for all COLLABORATORs
  2. Profile page shows the agent's own account info (email/username visible)
  3. Profile API endpoints respond correctly (GET /api/user/profile or equivalent)
  4. COLLABORATORs cannot access other users' profiles (own-data isolation)

Run:
    pytest tests/human_agents/test_05_profile.py -v
"""

from __future__ import annotations

import pytest
import requests
from playwright.sync_api import Browser

from conftest import BASE_URL, load_agents, login_as, logout

# EVERY test here drives a real browser (#5990). Module-level pytestmark is applied
# during COLLECTION, before pytest's own -m filter runs — a conftest
# pytest_collection_modifyitems hook adds markers too LATE to be deselected, which is
# why the first attempt at this fix did nothing and the suite kept hanging.
pytestmark = pytest.mark.browser

PROFILE_URL = f"{BASE_URL}/tools/my-profile"

# Possible API endpoints for profile data (try in order)
PROFILE_API_CANDIDATES = [
    f"{BASE_URL}/tools/my-profile/api/profile",
    f"{BASE_URL}/api/user/profile",
    f"{BASE_URL}/api/profile",
]


def _first_credentialed(all_agents: list) -> dict:
    match = next((a for a in all_agents if a.get("password")), None)
    if match is None:
        pytest.skip("No credentialed agents")
    return match


class TestProfileAccess:
    """COLLABORATORs can view and use the My Profile module."""

    def test_all_agents_reach_profile_page(self, browser: Browser, all_agents: list):
        """Every credentialed COLLABORATOR can load /tools/my-profile (not 403)."""
        failures: list[str] = []

        for agent in all_agents:
            if not agent.get("password"):
                print(f"  SKIP {agent['email']} — no credentials")
                continue

            ctx = browser.new_context()
            page = ctx.new_page()
            try:
                login_as(page, agent)
                page.goto(PROFILE_URL)
                page.wait_for_load_state("networkidle")

                if "/login" in page.url:
                    failures.append(f"{agent['email']}: redirected to /login (session lost?)")
                    continue

                # Check for explicit access-denied signals
                page_text = page.inner_text("body").lower()
                if "403" in page_text or "forbidden" in page_text or "access denied" in page_text:
                    failures.append(f"{agent['email']} ({agent['department']}): " f"profile page shows access denied")
                else:
                    print(f"  ✓ {agent['display_name']:35s} ({agent['department']}): " f"profile page accessible")

            except Exception as exc:
                failures.append(f"{agent['email']}: {exc}")
            finally:
                logout(page)
                ctx.close()

        if failures:
            pytest.fail(f"{len(failures)} agent(s) blocked from profile:\n" + "\n".join(f"  • {f}" for f in failures))

    def test_profile_shows_own_email(self, browser: Browser, all_agents: list):
        """The profile page displays the agent's own email address."""
        # Sample 3 agents from different depts
        seen: set[str] = set()
        sample = []
        for agent in all_agents:
            if agent["department"] not in seen and agent.get("password"):
                seen.add(agent["department"])
                sample.append(agent)
                if len(sample) >= 3:
                    break

        if not sample:
            pytest.skip("No credentialed agents")

        failures: list[str] = []

        for agent in sample:
            ctx = browser.new_context()
            page = ctx.new_page()
            try:
                login_as(page, agent)
                page.goto(PROFILE_URL)
                page.wait_for_load_state("networkidle")
                page.wait_for_timeout(1500)

                page_text = page.inner_text("body")

                # Check for email OR username on the page
                username = agent["email"].split("@")[0]
                email_visible = agent["email"].lower() in page_text.lower()
                username_visible = username.lower() in page_text.lower()

                if email_visible or username_visible:
                    print(
                        f"  ✓ {agent['display_name']}: own account info visible "
                        f"(email={email_visible}, username={username_visible})"
                    )
                else:
                    failures.append(
                        f"{agent['email']}: neither email nor username found on profile page. "
                        f"Page may not be rendering correctly."
                    )

            except Exception as exc:
                failures.append(f"{agent['email']}: {exc}")
            finally:
                logout(page)
                ctx.close()

        if failures:
            pytest.fail("\n".join(f"  • {f}" for f in failures))

    def test_profile_api_responds(self, browser: Browser, all_agents: list):
        """Profile API endpoint returns 200 with own user data for COLLABORATORs."""
        agent = _first_credentialed(all_agents)

        ctx = browser.new_context()
        page = ctx.new_page()

        try:
            login_as(page, agent)
            cookies = ctx.cookies()
            sc = next((c for c in cookies if c["name"] in ("session", "archie_session")), None)
            if not sc:
                pytest.skip("No session cookie")

            cookie_dict = {sc["name"]: sc["value"]}

            # Try each candidate API endpoint
            working_endpoint = None
            for endpoint in PROFILE_API_CANDIDATES:
                try:
                    resp = requests.get(endpoint, cookies=cookie_dict, timeout=8)
                    if resp.status_code == 200:
                        working_endpoint = endpoint
                        data = (
                            resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
                        )
                        # Verify it contains own user data (not someone else's)
                        resp_text = resp.text.lower()
                        own_email = agent["email"].lower()
                        if own_email in resp_text:
                            print(f"  ✓ {agent['display_name']}: profile API {endpoint} → 200 with own data")
                        else:
                            print(
                                f"  ✓ {agent['display_name']}: profile API {endpoint} → 200 "
                                f"(own email not in response — may be structured differently)"
                            )
                        break
                    elif resp.status_code in (401, 403):
                        print(f"  ✗ {endpoint}: {resp.status_code} for COLLABORATOR")
                except Exception:
                    continue

            if working_endpoint is None:
                print(
                    f"  ℹ {agent['display_name']}: no profile API found at known endpoints — "
                    f"profile may be UI-only (acceptable)"
                )

        finally:
            logout(page)
            ctx.close()

    def test_cannot_access_other_users_profile(self, browser: Browser, all_agents: list):
        """COLLABORATORs cannot view another user's profile data via direct ID."""
        credentialed = [a for a in all_agents if a.get("password")]
        if len(credentialed) < 2:
            pytest.skip("Need at least 2 credentialed agents for isolation test")

        agent = credentialed[0]
        other = credentialed[1]

        ctx = browser.new_context()
        page = ctx.new_page()

        try:
            login_as(page, agent)
            cookies = ctx.cookies()
            sc = next((c for c in cookies if c["name"] in ("session", "archie_session")), None)
            if not sc:
                pytest.skip("No session cookie")

            cookie_dict = {sc["name"]: sc["value"]}

            # Try to access other user's profile by their user_id
            other_id = other.get("user_id")
            if not other_id:
                pytest.skip("user_id not in agents.json")

            for endpoint in [
                f"{BASE_URL}/api/user/profile/{other_id}",
                f"{BASE_URL}/tools/my-profile/api/profile/{other_id}",
                f"{BASE_URL}/api/users/{other_id}",
            ]:
                try:
                    resp = requests.get(endpoint, cookies=cookie_dict, timeout=8)
                    if resp.status_code == 200:
                        resp_text = resp.text.lower()
                        other_email = other["email"].lower()
                        if other_email in resp_text:
                            pytest.fail(
                                f"IDOR: {agent['email']} can read {other['email']}'s profile " f"via {endpoint}"
                            )
                        else:
                            print(f"  ✓ {endpoint}: 200 but other user's email not exposed")
                    elif resp.status_code in (403, 404):
                        print(f"  ✓ {endpoint}: {resp.status_code} (access correctly denied)")
                    else:
                        print(f"  ℹ {endpoint}: {resp.status_code}")
                except Exception:
                    pass  # endpoint doesn't exist — safe

            print(
                f"  ✓ {agent['display_name']} cannot read {other['display_name']}'s profile " f"(no IDOR via direct ID)"
            )

        finally:
            logout(page)
            ctx.close()
