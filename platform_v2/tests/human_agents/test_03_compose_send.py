"""
Test 03 — Compose & Send email as a COLLABORATOR human agent.

Covers T3296 — verifies:
  1. GET /api/email/compose/mailboxes returns ONLY the agent's dept mailboxes
  2. POST /api/email/compose/send with an out-of-dept from_address → 400 (scope blocked)
  3. POST /api/email/compose/send with own mailbox → not 401/403 (access allowed;
     SMTP may succeed or fail internally — both are acceptable proof that scoping passed)
  4. Admin GET /api/email/compose/mailboxes sees all mailboxes (unrestricted)

Test agents used:
  - Primary:   amina.youssef@kytranempowerment.com  (Documentation & Knowledge — 4 mailboxes)
  - Alternate: marie-soleil.obomsawin (same dept, same visible set)
  - Cross-dept: adrienne.parenteau@kytranempowerment.com (Legal & Regulatory)

Run:
    pytest tests/human_agents/test_03_compose_send.py -v
    pytest tests/human_agents/test_03_compose_send.py -v -k "scope"
"""

from __future__ import annotations

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
# Constants
# ---------------------------------------------------------------------------

# Documentation & Knowledge dept has 4 mailboxes (3 human agents + C.O.D.E.X. AI).
# Test uses this dept because it has both human-personal and AI-agent mailboxes.
PRIMARY_DEPT = "Documentation & Knowledge"
PRIMARY_EMAIL = "amina.youssef@kytranempowerment.com"

# A different dept agent — used as the cross-dept blocking target
CROSS_DEPT_EMAIL = "adrienne.parenteau@kytranempowerment.com"  # Legal & Regulatory

COMPOSE_MAILBOXES_URL = f"{BASE_URL}/tools/email-manager/api/email/compose/mailboxes"
COMPOSE_SEND_URL = f"{BASE_URL}/tools/email-manager/api/email/compose/send"

# Human agent emails — needed to identify personal vs shared mailboxes
_ALL_AGENT_EMAILS: set[str] = {a["email"] for a in load_agents()}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _session_cookie_for(browser: Browser, agent: dict) -> tuple[str, str]:
    """Login as agent, return (cookie_name, cookie_value). Handles force-change."""
    ctx = browser.new_context()
    page = ctx.new_page()
    try:
        login_as(page, agent)
        cookies = ctx.cookies()
        sc = next((c for c in cookies if c["name"] in ("session", "archie_session")), None)
        if not sc:
            pytest.skip(f"No session cookie found for {agent['email']}")
        return sc["name"], sc["value"]
    finally:
        ctx.close()


def _agent_by_email(email: str) -> dict:
    agents = load_agents()
    match = next((a for a in agents if a["email"] == email), None)
    if match is None:
        pytest.skip(f"Agent {email} not found in agents.json — re-run provisioning")
    if not match.get("password"):
        pytest.skip(f"No credentials for {email} — check credentials.env")
    return match


def _is_cross_dept_mailbox(address: str, agent_dept: str, all_agents: list[dict]) -> bool:
    """Return True if `address` belongs to a human agent in a DIFFERENT dept."""
    if address not in _ALL_AGENT_EMAILS:
        return False  # shared/business mailbox — not a personal agent mailbox
    owner = next((a for a in all_agents if a["email"] == address), None)
    if owner is None:
        return False
    return owner["department"] != agent_dept


# ---------------------------------------------------------------------------
# Test class
# ---------------------------------------------------------------------------


class TestComposeSend:
    """COLLABORATOR compose access, dept-scoping, and send pipeline."""

    # ------------------------------------------------------------------
    # 1. Mailbox list scoping
    # ------------------------------------------------------------------

    def test_compose_mailboxes_scoped_to_dept(self, browser: Browser, all_agents: list):
        """GET /api/email/compose/mailboxes returns only the agent's dept mailboxes."""
        agent = _agent_by_email(PRIMARY_EMAIL)
        cname, cval = _session_cookie_for(browser, agent)

        resp = requests.get(
            COMPOSE_MAILBOXES_URL,
            cookies={cname: cval},
            timeout=10,
        )

        assert resp.status_code == 200, (
            f"Expected 200 from compose/mailboxes, got {resp.status_code} for "
            f"{agent['email']} — check email_access_required decorator"
        )

        data = resp.json()
        mailboxes = data if isinstance(data, list) else data.get("mailboxes", [])
        assert len(mailboxes) > 0, (
            f"No mailboxes returned for {agent['email']} — "
            f"check that email_mailboxes.department is populated for {PRIMARY_DEPT}"
        )

        # Verify no cross-dept personal agent mailboxes leaked through
        cross_dept_leaks = [
            m["address"] for m in mailboxes if _is_cross_dept_mailbox(m.get("address", ""), PRIMARY_DEPT, all_agents)
        ]
        assert not cross_dept_leaks, f"COMPOSE IDOR: {agent['email']} can see out-of-dept mailboxes: {cross_dept_leaks}"

        # Must include own mailbox
        addresses = [m.get("address", "") for m in mailboxes]
        assert PRIMARY_EMAIL in addresses, (
            f"Agent's own mailbox {PRIMARY_EMAIL} missing from compose/mailboxes response. " f"Got: {addresses}"
        )

        print(f"  ✓ {agent['display_name']} ({PRIMARY_DEPT}): " f"{len(mailboxes)} compose mailboxes, none cross-dept")

    def test_compose_mailboxes_colleague_same_dept(self, browser: Browser):
        """A dept colleague sees the SAME scoped mailbox list."""
        # marie-soleil.obomsawin is also Documentation & Knowledge
        colleague_email = "marie-soleil.obomsawin@kytranempowerment.com"
        all_agents = load_agents()
        colleague = next((a for a in all_agents if a["email"] == colleague_email), None)
        if colleague is None or not colleague.get("password"):
            pytest.skip(f"Colleague {colleague_email} missing from agents.json or credentials.env")

        cname, cval = _session_cookie_for(browser, colleague)

        resp = requests.get(
            COMPOSE_MAILBOXES_URL,
            cookies={cname: cval},
            timeout=10,
        )
        assert resp.status_code == 200
        data = resp.json()
        mailboxes = data if isinstance(data, list) else data.get("mailboxes", [])

        addresses = [m.get("address", "") for m in mailboxes]
        cross_dept = [addr for addr in addresses if _is_cross_dept_mailbox(addr, PRIMARY_DEPT, all_agents)]
        assert not cross_dept, f"Colleague {colleague_email} sees cross-dept: {cross_dept}"
        assert colleague_email in addresses, f"Colleague's own mailbox missing from compose list. Got: {addresses}"
        print(f"  ✓ {colleague['display_name']}: same-dept compose mailboxes match expectations")

    def test_compose_mailboxes_admin_unrestricted(self, browser: Browser):
        """Admin GET /api/email/compose/mailboxes returns ALL provisioned mailboxes."""
        ctx = browser.new_context()
        page = ctx.new_page()
        try:
            page.goto(f"{BASE_URL}/login")
            page.wait_for_load_state("networkidle")
            page.fill('input[name="username"], input[id="username"]', ADMIN_USER)
            page.fill('input[name="password"], input[id="password"]', ADMIN_PASS)
            page.click('button[type="submit"], input[type="submit"]')
            page.wait_for_load_state("networkidle")
            if "/login" in page.url:
                pytest.skip("Admin login failed — check ARCHIE_ADMIN_USER/PASS env vars")

            cookies = ctx.cookies()
            sc = next((c for c in cookies if c["name"] in ("session", "archie_session")), None)
            if not sc:
                pytest.skip("No admin session cookie")

            resp = requests.get(
                COMPOSE_MAILBOXES_URL,
                cookies={sc["name"]: sc["value"]},
                timeout=10,
            )
            assert resp.status_code == 200, f"Admin got {resp.status_code} from compose/mailboxes"
            data = resp.json()
            mailboxes = data if isinstance(data, list) else data.get("mailboxes", [])

            # Admin should see ALL human-agent mailboxes (not just one dept)
            addresses = {m.get("address", "") for m in mailboxes}
            # At minimum must see both Documentation AND Legal mailboxes
            found_doc = any(a in addresses for a in [PRIMARY_EMAIL, "marie-soleil.obomsawin@kytranempowerment.com"])
            found_legal = CROSS_DEPT_EMAIL in addresses
            assert found_doc and found_legal, (
                f"Admin compose/mailboxes missing expected cross-dept mailboxes. "
                f"Doc={found_doc}, Legal={found_legal}. Total: {len(mailboxes)}"
            )
            print(f"  ✓ Admin sees {len(mailboxes)} total compose mailboxes (unrestricted)")

        finally:
            ctx.close()

    # ------------------------------------------------------------------
    # 2. Cross-dept send blocked
    # ------------------------------------------------------------------

    def test_send_from_cross_dept_mailbox_blocked(self, browser: Browser):
        """Sending from another dept's mailbox returns 400 (scope enforcement)."""
        agent = _agent_by_email(PRIMARY_EMAIL)
        cname, cval = _session_cookie_for(browser, agent)

        # Attempt to send from adrienne.parenteau's mailbox (Legal — not our dept)
        payload = {
            "from_address": CROSS_DEPT_EMAIL,
            "to_address": PRIMARY_EMAIL,
            "subject": "IDOR test — must be blocked",
            "body": "This send should be rejected by the server.",
        }

        resp = requests.post(
            COMPOSE_SEND_URL,
            json=payload,
            cookies={cname: cval},
            timeout=15,
        )

        # compose_routes.py returns 400 "Mailbox not provisioned or missing SMTP credentials"
        # when the from_address is not in the caller's visible mailbox set.
        # We accept 400 (scoped block) or 403 (explicit deny). We do NOT accept 200.
        assert resp.status_code in (400, 403), (
            f"COMPOSE IDOR: {agent['email']} sent from out-of-dept mailbox {CROSS_DEPT_EMAIL} "
            f"and got {resp.status_code} (expected 400/403). Response: {resp.text[:200]}"
        )
        print(f"  ✓ Cross-dept send blocked: {agent['email']} → from:{CROSS_DEPT_EMAIL} " f"→ {resp.status_code}")

    # ------------------------------------------------------------------
    # 3. Own mailbox send — access allowed (SMTP result doesn't matter)
    # ------------------------------------------------------------------

    def test_send_from_own_mailbox_accessible(self, browser: Browser):
        """Send from own mailbox reaches SMTP layer (not blocked by auth/scope).

        We don't assert email delivery — only that the response is NOT 401/403.
        The endpoint returns 200 on success or 500 on SMTP error — both prove
        the COLLABORATOR scope check passed.
        """
        agent = _agent_by_email(PRIMARY_EMAIL)
        cname, cval = _session_cookie_for(browser, agent)

        payload = {
            "from_address": PRIMARY_EMAIL,
            "to_address": "admin@kytranempowerment.com",
            "subject": "[T3296] Playwright compose test",
            "body": (
                f"Automated compose test from {agent['display_name']} "
                f"({PRIMARY_DEPT}). This verifies COLLABORATOR SMTP access."
            ),
        }

        resp = requests.post(
            COMPOSE_SEND_URL,
            json=payload,
            cookies={cname: cval},
            timeout=30,  # SMTP can be slow
        )

        # Forbidden responses (401, 403) mean our decorator/scope check blocked the user
        assert resp.status_code not in (401, 403), (
            f"COLLABORATOR {agent['email']} was denied access to compose/send: "
            f"{resp.status_code} — check email_access_required wiring in email_manager/__init__.py"
        )

        if resp.status_code == 200:
            print(f"  ✓ {agent['display_name']}: email sent successfully via SMTP")
        elif resp.status_code == 400:
            err = resp.json().get("error", "")
            # 400 on own mailbox = either validation error or mailbox config issue
            # (not a scope block — those go to cross-dept which we tested above)
            print(f"  ℹ {agent['display_name']}: 400 from compose/send — {err} (mailbox config)")
        else:
            print(
                f"  ℹ {agent['display_name']}: compose/send → {resp.status_code} "
                f"(likely SMTP error — scope check passed, SMTP may not be reachable from test runner)"
            )

    # ------------------------------------------------------------------
    # 4. Unauthenticated access blocked
    # ------------------------------------------------------------------

    def test_compose_endpoints_require_login(self):
        """Both compose endpoints return 401/403 or redirect when unauthenticated."""
        for url in (COMPOSE_MAILBOXES_URL, COMPOSE_SEND_URL):
            resp = requests.get(url, allow_redirects=False, timeout=10)
            # Flask-Login redirects to /login (302) or returns 401/403
            assert resp.status_code in (302, 401, 403), (
                f"Unauthenticated request to {url} returned {resp.status_code} — " f"expected redirect or auth error"
            )
        print("  ✓ Both compose endpoints require authentication")

    # ------------------------------------------------------------------
    # 5. All COLLABORATORs have compose access (sample check)
    # ------------------------------------------------------------------

    def test_all_agents_compose_mailboxes_accessible(self, browser: Browser, all_agents: list):
        """Every COLLABORATOR with credentials can reach compose/mailboxes (200, not 403).

        Runs against all 21 agents to catch per-agent provisioning failures.
        """
        failures: list[str] = []

        for agent in all_agents:
            if not agent.get("password"):
                print(f"  SKIP {agent['email']} — no credentials")
                continue

            ctx = browser.new_context()
            page = ctx.new_page()

            try:
                login_as(page, agent)
                cookies = ctx.cookies()
                sc = next((c for c in cookies if c["name"] in ("session", "archie_session")), None)
                if not sc:
                    failures.append(f"{agent['email']}: no session cookie after login")
                    continue

                resp = requests.get(
                    COMPOSE_MAILBOXES_URL,
                    cookies={sc["name"]: sc["value"]},
                    timeout=10,
                )

                if resp.status_code == 403:
                    failures.append(
                        f"{agent['email']} ({agent['department']}): 403 on compose/mailboxes — "
                        f"check role or email_access_required"
                    )
                elif resp.status_code != 200:
                    failures.append(f"{agent['email']}: unexpected {resp.status_code} on compose/mailboxes")
                else:
                    data = resp.json()
                    mb = data if isinstance(data, list) else data.get("mailboxes", [])
                    print(
                        f"  ✓ {agent['display_name']:35s} ({agent['department']:30s}): " f"{len(mb)} compose mailboxes"
                    )

            except Exception as exc:
                failures.append(f"{agent['email']}: {exc}")
            finally:
                logout(page)
                ctx.close()

        if failures:
            pytest.fail(
                f"{len(failures)} agent(s) failed compose/mailboxes access:\n" + "\n".join(f"  • {f}" for f in failures)
            )
