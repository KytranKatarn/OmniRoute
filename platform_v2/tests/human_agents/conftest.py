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
# Admin credentials for reset operations (reads from env or defaults to dev creds)
ADMIN_USER = os.environ.get("ARCHIE_ADMIN_USER", "admin")
ADMIN_PASS = os.environ.get("ARCHIE_ADMIN_PASS", "")


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


def login_as(page: Page, agent: dict) -> None:
    """Log in as a human agent. Raises if login fails."""
    page.goto(f"{BASE_URL}/login")
    page.wait_for_load_state("networkidle")

    # Fill username field — platform accepts email or username
    page.fill('input[name="username"], input[id="username"], input[type="text"]', agent["email"])
    page.fill('input[name="password"], input[id="password"], input[type="password"]', agent["password"])
    page.click('button[type="submit"], input[type="submit"]')
    page.wait_for_load_state("networkidle")

    # Verify we landed on dashboard (not back on /login with error)
    current_url = page.url
    assert "/login" not in current_url, (
        f"Login failed for {agent['email']}. Still on login page. " f"Check credentials.env has the correct password."
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
