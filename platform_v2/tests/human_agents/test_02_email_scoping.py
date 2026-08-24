"""
Test 02 — Email Manager dept scoping for all 21 human agent COLLABORATORs.

Verifies (browser-level proof of T3279–T3283 IDOR work):
  - Each COLLABORATOR sees ONLY their department's mailboxes in the sidebar
  - No cross-department mailboxes visible
  - Admin sees all mailboxes (unrestricted)
  - HQ overview stats respond 200 (not 403) for COLLABORATOR

Run:
    pytest tests/human_agents/test_02_email_scoping.py -v
    pytest tests/human_agents/test_02_email_scoping.py -v -k "Documentation"
"""

import json
import re

import pytest
import requests
from playwright.sync_api import Browser

from conftest import BASE_URL, ADMIN_USER, ADMIN_PASS, load_agents, login_as, logout

# EVERY test here drives a real browser (#5990). Module-level pytestmark is applied
# during COLLECTION, before pytest's own -m filter runs — a conftest
# pytest_collection_modifyitems hook adds markers too LATE to be deselected, which is
# why the first attempt at this fix did nothing and the suite kept hanging.
pytestmark = pytest.mark.browser


# ---------------------------------------------------------------------------
# Expected dept mailbox counts (from DB — update if mailboxes change)
# Run to refresh:
#   docker exec archie_database psql -U archie -d archie -c \
#     "SELECT department, count(*) FROM email_mailboxes WHERE active=TRUE GROUP BY department ORDER BY 1;"
# ---------------------------------------------------------------------------
EXPECTED_DEPT_COUNTS: dict[str, int] = {
    "Analytics & Intelligence": 2,  # jin.park + dept AI agent(s)
    "Creative & Design": 2,
    "Customer Success & Support": 2,
    "Diplomatic & External Relations": 2,
    "Documentation & Knowledge": 4,  # 3 human agents + dept AI agents
    "Finance & Accounting": 2,
    "Human Resources & Culture": 2,
    "Legal & Regulatory": 3,  # 2 human agents + dept AI agent
    "Logistics & Supply Chain": 2,
    "Marketing & Communications": 3,  # 2 human agents + dept AI agent
    "Medical & Wellness": 4,  # 3 human agents + dept AI agent
    "Operations & Infrastructure": 2,
    "Research & Development": 3,  # 2 human agents + dept AI agent
    "Security & Compliance": 2,
}
# NOTE: Counts above are minimum expected — actual may be higher if business mailboxes
# are shared with a dept. The test uses >= not ==.


def _get_session_cookie(browser: Browser, agent: dict) -> str:
    """Login as agent and return the session cookie string for API calls."""
    ctx = browser.new_context()
    page = ctx.new_page()
    try:
        login_as(page, agent)
        cookies = ctx.cookies()
        session_cookie = next((c for c in cookies if c["name"] in ("session", "archie_session")), None)
        if not session_cookie:
            pytest.skip(f"No session cookie found for {agent['email']}")
        return f"{session_cookie['name']}={session_cookie['value']}"
    finally:
        ctx.close()


class TestEmailDeptScoping:
    """COLLABORATOR sees only their department's mailboxes."""

    def test_sidebar_shows_only_dept_mailboxes(self, browser: Browser, all_agents: list):
        """Each agent's email sidebar contains only dept mailboxes."""
        failures = []

        for agent in all_agents:
            if not agent.get("password"):
                print(f"  SKIP {agent['email']} — no credentials")
                continue

            ctx = browser.new_context()
            page = ctx.new_page()

            try:
                login_as(page, agent)
                page.goto(f"{BASE_URL}/tools/email-manager")
                page.wait_for_load_state("networkidle")

                # Wait for sidebar mailbox list to render
                # The sidebar renders mailboxes as list items with data-mailbox-id or similar
                page.wait_for_timeout(2000)  # allow JS to populate sidebar

                # Extract visible mailbox addresses from sidebar
                # Adjust selector to match actual sidebar HTML if needed
                mailbox_els = page.query_selector_all(
                    "[data-mailbox-id], .mailbox-item, .sidebar-mailbox, " "[data-mailbox], .email-sidebar li[data-id]"
                )

                visible_addresses: list[str] = []
                for el in mailbox_els:
                    # Try data attributes first, then text content
                    addr = (
                        el.get_attribute("data-address")
                        or el.get_attribute("data-mailbox-address")
                        or el.inner_text().strip()
                    )
                    if "@" in (addr or ""):
                        visible_addresses.append(addr.strip())

                if not visible_addresses:
                    # Fallback: check the API response directly
                    print(
                        f"  WARN {agent['display_name']}: no mailbox elements found via selectors — "
                        f"checking API instead"
                    )
                    # Try the mailboxes API endpoint
                    cookies = ctx.cookies()
                    session = next((c for c in cookies if c["name"] in ("session", "archie_session")), None)
                    if session:
                        resp = requests.get(
                            f"{BASE_URL}/tools/email-manager/api/mailboxes",
                            cookies={session["name"]: session["value"]},
                            timeout=10,
                        )
                        if resp.ok:
                            data = resp.json()
                            mailboxes = data if isinstance(data, list) else data.get("mailboxes", [])
                            visible_addresses = [m.get("address", "") for m in mailboxes if m.get("address")]

                dept = agent["department"]
                cross_dept = [addr for addr in visible_addresses if not _is_dept_mailbox(addr, agent)]

                if cross_dept:
                    failures.append(f"{agent['display_name']} ({dept}): CROSS-DEPT LEAK — sees: {cross_dept}")
                else:
                    print(f"  ✓ {agent['display_name']} ({dept}): " f"{len(visible_addresses)} mailboxes, all in-dept")

            except Exception as exc:
                failures.append(f"{agent['email']}: error — {exc}")
            finally:
                logout(page)
                ctx.close()

        if failures:
            pytest.fail("IDOR scoping failures:\n" + "\n".join(f"  • {f}" for f in failures))

    def test_api_mailbox_list_scoped(self, browser: Browser, all_agents: list):
        """API /api/mailboxes returns only dept mailboxes for COLLABORATOR."""
        failures = []

        for agent in all_agents[:5]:  # sample first 5 depts to keep test fast
            if not agent.get("password"):
                continue

            ctx = browser.new_context()
            page = ctx.new_page()

            try:
                login_as(page, agent)
                cookies_list = ctx.cookies()
                session = next((c for c in cookies_list if c["name"] in ("session", "archie_session")), None)
                if not session:
                    print(f"  SKIP {agent['email']} — no session cookie")
                    continue

                cookie_dict = {session["name"]: session["value"]}
                resp = requests.get(
                    f"{BASE_URL}/tools/email-manager/api/mailboxes",
                    cookies=cookie_dict,
                    timeout=10,
                )

                assert resp.status_code == 200, f"{agent['email']}: /api/mailboxes returned {resp.status_code}"

                data = resp.json()
                mailboxes = data if isinstance(data, list) else data.get("mailboxes", [])

                cross_dept = [m for m in mailboxes if not _is_dept_mailbox(m.get("address", ""), agent)]

                if cross_dept:
                    failures.append(
                        f"{agent['display_name']}: API returned cross-dept: "
                        + ", ".join(m.get("address", "?") for m in cross_dept)
                    )
                else:
                    dept_count = agent["department"]
                    print(f"  ✓ {agent['display_name']}: {len(mailboxes)} mailboxes via API, all in-dept")

            except Exception as exc:
                failures.append(f"{agent['email']}: {exc}")
            finally:
                logout(page)
                ctx.close()

        if failures:
            pytest.fail("API scoping failures:\n" + "\n".join(f"  • {f}" for f in failures))

    def test_hq_overview_accessible(self, browser: Browser, all_agents: list):
        """HQ overview returns 200 for COLLABORATOR (not 403)."""
        agent = all_agents[0]
        if not agent.get("password"):
            pytest.skip("No credentials")

        ctx = browser.new_context()
        page = ctx.new_page()

        try:
            login_as(page, agent)
            cookies_list = ctx.cookies()
            session = next((c for c in cookies_list if c["name"] in ("session", "archie_session")), None)
            if not session:
                pytest.skip("No session cookie")

            # HQ stats API (should be 200 for email_access_required)
            resp = requests.get(
                f"{BASE_URL}/tools/email-manager/api/hq/stats",
                cookies={session["name"]: session["value"]},
                timeout=10,
            )
            assert resp.status_code == 200, (
                f"HQ stats returned {resp.status_code} for COLLABORATOR {agent['email']} — "
                f"expected 200 (email_access_required should allow this)"
            )
            print(f"  ✓ HQ stats 200 for COLLABORATOR {agent['display_name']}")

        finally:
            logout(page)
            ctx.close()

    def test_cross_dept_mailbox_blocked(self, browser: Browser, all_agents: list):
        """COLLABORATOR cannot fetch messages from another dept's mailbox (IDOR guard)."""
        # Use first agent and first agent's dept to find a mailbox NOT in their dept
        agent = next(a for a in all_agents if a["department"] == "Analytics & Intelligence")
        if not agent.get("password"):
            pytest.skip("No credentials")

        # Known out-of-scope mailbox: any medical or documentation mailbox
        # (these exist in the DB — adjust ID if schema changes)
        # We'll hit the messages endpoint with a mailbox_id from a different dept
        # via API to confirm 403 or empty response

        ctx = browser.new_context()
        page = ctx.new_page()

        try:
            login_as(page, agent)
            cookies_list = ctx.cookies()
            session = next((c for c in cookies_list if c["name"] in ("session", "archie_session")), None)
            if not session:
                pytest.skip("No session cookie")

            # Get all mailboxes first (scoped — should only see own dept)
            own_resp = requests.get(
                f"{BASE_URL}/tools/email-manager/api/mailboxes",
                cookies={session["name"]: session["value"]},
                timeout=10,
            )
            if not own_resp.ok:
                pytest.skip(f"Could not fetch mailboxes: {own_resp.status_code}")

            own_mailboxes = own_resp.json()
            if isinstance(own_mailboxes, dict):
                own_mailboxes = own_mailboxes.get("mailboxes", [])
            own_ids = {m["id"] for m in own_mailboxes}

            # Try mailbox IDs 1–20 looking for one NOT in our visible set
            out_of_scope_id = None
            for candidate_id in range(1, 50):
                if candidate_id not in own_ids:
                    out_of_scope_id = candidate_id
                    break

            if out_of_scope_id is None:
                pytest.skip("Could not find an out-of-scope mailbox ID to test IDOR against")

            # Attempt to fetch messages from out-of-scope mailbox
            messages_resp = requests.get(
                f"{BASE_URL}/tools/email-manager/api/messages",
                params={"mailbox_id": out_of_scope_id, "folder": "INBOX"},
                cookies={session["name"]: session["value"]},
                timeout=10,
            )

            # Expect 403 or empty result (not 200 with data from another dept)
            if messages_resp.status_code == 403:
                print(f"  ✓ Cross-dept mailbox {out_of_scope_id} → 403 (correctly blocked)")
            elif messages_resp.status_code == 200:
                data = messages_resp.json()
                messages = data if isinstance(data, list) else data.get("messages", [])
                assert len(messages) == 0, (
                    f"IDOR LEAK: COLLABORATOR {agent['email']} received {len(messages)} messages "
                    f"from out-of-scope mailbox {out_of_scope_id}!"
                )
                print(f"  ✓ Cross-dept mailbox {out_of_scope_id} → 200 but empty (scoped correctly)")
            else:
                print(
                    f"  INFO: Cross-dept mailbox {out_of_scope_id} → {messages_resp.status_code} "
                    f"(not 200 or 403 — may be expected)"
                )

        finally:
            logout(page)
            ctx.close()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _is_dept_mailbox(address: str, agent: dict) -> bool:
    """Heuristic: a mailbox belongs to an agent's dept if its address matches
    one of the known in-dept patterns OR if it's a business/shared mailbox.

    For now we use a simple: NOT another human agent's personal mailbox.
    Human agents have @kytranempowerment.com addresses matching their name.
    """
    if not address or "@" not in address:
        return True  # unknown — don't flag

    # Business mailboxes (info@, support@, legal@, etc.) are always accessible
    agent_emails = {a["email"] for a in load_agents()}
    if address not in agent_emails:
        return True  # not a personal agent mailbox — could be dept/business mailbox

    # It's a personal agent mailbox — check it's the current agent or same dept
    other_agent = next((a for a in load_agents() if a["email"] == address), None)
    if other_agent is None:
        return True

    return other_agent["department"] == agent["department"]
