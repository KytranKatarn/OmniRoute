"""
Human Agent Playwright Test Suite — conftest.py
Project #360 — Human Agent Playwright Simulation System

Shared fixtures and agent loader for all human_agent tests.
Run against: http://192.168.1.200:3000 (hub LAN — user is REMOTE)
"""

import json
import os
from pathlib import Path

import pytest
from playwright.sync_api import Browser, BrowserContext, Page, sync_playwright

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
SUITE_DIR = Path(__file__).parent
AGENTS_FILE = SUITE_DIR / "agents.json"
CREDENTIALS_FILE = SUITE_DIR / "credentials.env"
PROFILES_DIR = SUITE_DIR / "profiles"  # persistent browser profiles per agent

BASE_URL = os.environ.get("ARCHIE_BASE_URL", "http://192.168.1.200:3000")

# How long to wait for the platform before giving up. A browser test with no reachability
# check does not fail when the target is down — it HANGS, which is what took the whole
# suite out (#5990).
_REACHABILITY_TIMEOUT_S = 5


# NOTE — do NOT add a pytest_collection_modifyitems hook here to mark this directory.
# A conftest's modifyitems hook receives EVERY item in the session, not just this
# directory's, so marking `items` marked all 3,910 tests `browser` and the default run
# deselected the ENTIRE suite (measured 2026-08-24: '3910 deselected / 0 selected').
# It also ran AFTER pytest's own -m filter, so it could not have deselected anything
# anyway. The module-level `pytestmark = pytest.mark.browser` in each test file is
# applied during collection and is scoped correctly.


@pytest.fixture(scope="session", autouse=True)
def _platform_must_be_reachable():
    """Skip the whole suite FAST when the platform is not up.

    Without this the tests block on page.goto() with no timeout and the run never ends.
    A skip states plainly that they did not run; a hang states nothing at all.
    """
    import socket
    from urllib.parse import urlparse

    parsed = urlparse(BASE_URL)
    host = parsed.hostname or "192.168.1.200"
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    try:
        with socket.create_connection((host, port), timeout=_REACHABILITY_TIMEOUT_S):
            pass
    except OSError as exc:
        pytest.skip(
            f"platform not reachable at {BASE_URL} ({exc}) — browser E2E skipped",
            allow_module_level=True,
        )


# Admin credentials for reset operations (reads from env or defaults to dev creds)
ADMIN_USER = os.environ.get("ARCHIE_ADMIN_USER", "admin")
ADMIN_PASS = os.environ.get("ARCHIE_ADMIN_PASS", "")

# Deterministic password set on first login (when must_change_password=TRUE).
# On second test run the temp password is gone — login_as falls back to this.
FORCE_CHANGE_PW = os.environ.get("AGENT_FORCE_CHANGE_PW", "ChangeMe#2026!")


# ---------------------------------------------------------------------------
# Credential loader
# ---------------------------------------------------------------------------
def load_credentials() -> dict[str, str]:
    """Load email→password map from credentials.env (gitignored).

    Falls back to environment variables of the form:
        AGENT_CRED_<EMAIL_UPPER_NONDOT>=password
    so CI/CD can inject them without a file on disk.
    """
    creds: dict[str, str] = {}

    if CREDENTIALS_FILE.exists():
        for line in CREDENTIALS_FILE.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                email, _, password = line.partition("=")
                creds[email.strip()] = password.strip()

    # Environment variable overrides (CI/CD pattern)
    for key, val in os.environ.items():
        if key.startswith("AGENT_CRED_"):
            email = key[len("AGENT_CRED_") :].lower().replace("_at_", "@").replace("_dot_", ".")
            creds[email] = val

    return creds


def load_agents() -> list[dict]:
    """Load all 21 human agent records from agents.json."""
    agents = json.loads(AGENTS_FILE.read_text())
    creds = load_credentials()
    for agent in agents:
        agent["password"] = creds.get(agent["email"], "")
    return agents


def agents_by_department() -> dict[str, list[dict]]:
    """Group agents by department."""
    result: dict[str, list[dict]] = {}
    for agent in load_agents():
        dept = agent["department"]
        result.setdefault(dept, []).append(agent)
    return result


# ---------------------------------------------------------------------------
# Pytest fixtures
# ---------------------------------------------------------------------------
@pytest.fixture(scope="session")
def all_agents() -> list[dict]:
    """All 21 COLLABORATOR agents with credentials loaded."""
    agents = load_agents()
    missing = [a["email"] for a in agents if not a.get("password")]
    if missing:
        pytest.skip(f"Missing credentials for: {missing}. Check credentials.env.")
    return agents


@pytest.fixture(scope="session")
def playwright_instance():
    with sync_playwright() as p:
        yield p


@pytest.fixture(scope="session")
def browser(playwright_instance):
    """Single chromium browser for the session."""
    b = playwright_instance.chromium.launch(headless=True)
    yield b
    b.close()


def _agent_profile_dir(agent: dict) -> Path:
    """Persistent profile directory per agent (preserves cookies/localStorage)."""
    safe_name = agent["email"].replace("@", "_at_").replace(".", "_")
    path = PROFILES_DIR / safe_name
    path.mkdir(parents=True, exist_ok=True)
    return path


def _do_login(page: Page, identifier: str, password: str) -> None:
    """Fill and submit the login form (does NOT assert result)."""
    page.goto(f"{BASE_URL}/login")
    page.wait_for_load_state("networkidle")
    page.fill('input[name="username"], input[id="username"], input[type="text"]', identifier)
    page.fill('input[name="password"], input[id="password"], input[type="password"]', password)
    page.click('button[type="submit"], input[type="submit"]')
    page.wait_for_load_state("networkidle")


def _handle_force_change(page: Page) -> None:
    """If redirected to /change-password, set FORCE_CHANGE_PW and continue."""
    if "/change-password" not in page.url:
        return
    page.fill('input[name="new_password"]', FORCE_CHANGE_PW)
    page.fill('input[name="confirm_password"]', FORCE_CHANGE_PW)
    page.click('button[type="submit"]')
    page.wait_for_load_state("networkidle")


def login_as(page: Page, agent: dict) -> None:
    """Log in as a human agent. Handles must_change_password redirect automatically.

    First-run: uses temp password from credentials.env.
    Subsequent runs: temp password is gone — falls back to FORCE_CHANGE_PW.
    Raises AssertionError if login cannot be established.
    """
    # Attempt 1 — credentials.env temp password
    _do_login(page, agent["email"], agent["password"])
    _handle_force_change(page)

    # Attempt 2 — temp password may have been changed on a previous run
    if "/login" in page.url:
        _do_login(page, agent["email"], FORCE_CHANGE_PW)
        _handle_force_change(page)

    assert "/login" not in page.url, (
        f"Login failed for {agent['email']}. "
        f"Tried credentials.env password and FORCE_CHANGE_PW={FORCE_CHANGE_PW!r}. "
        f"Run admin_reset_passwords.py --generate to regenerate temp passwords."
    )


def logout(page: Page) -> None:
    """Log out via GET /logout."""
    page.goto(f"{BASE_URL}/logout")
    page.wait_for_load_state("networkidle")


@pytest.fixture()
def fresh_page(browser: Browser):
    """A fresh incognito page with no session — used for login tests."""
    ctx: BrowserContext = browser.new_context()
    page = ctx.new_page()
    yield page
    ctx.close()


@pytest.fixture()
def admin_page(browser: Browser):
    """Page logged in as admin (claude). Used for reset/provisioning operations."""
    ctx = browser.new_context()
    page = ctx.new_page()
    page.goto(f"{BASE_URL}/login")
    page.wait_for_load_state("networkidle")
    page.fill('input[name="username"], input[id="username"]', ADMIN_USER)
    page.fill('input[name="password"], input[id="password"]', ADMIN_PASS)
    page.click('button[type="submit"], input[type="submit"]')
    page.wait_for_load_state("networkidle")
    assert "/login" not in page.url, "Admin login failed — check ARCHIE_ADMIN_USER/ARCHIE_ADMIN_PASS env vars."
    yield page
    ctx.close()
