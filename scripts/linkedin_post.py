#!/usr/bin/env python3
"""linkedin_post.py — Post to LinkedIn as an ARCHIE agent using stored credentials.

Usage:
    # Agent posts to their own profile:
    python3 scripts/linkedin_post.py --agent-id 141 --content "..." --target personal

    # A.R.C.H.I.E. posts to Kytran's company page (managed account):
    python3 scripts/linkedin_post.py --managed-user-id 2 --content "..." --target company

    # A.R.C.H.I.E. posts to Kytran's personal profile:
    python3 scripts/linkedin_post.py --managed-user-id 2 --content "..." --target personal

Requirements:
    - CREDENTIAL_VAULT_KEY set in environment
    - Account must exist in agent_platform_accounts (run provision_agent_linkedin.py first)
"""

from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "platform_v2"))

from services.credential_vault_service import get_vault


def _load_and_login(page, vault, agent_id: int | None, user_id: int | None) -> dict:
    """Load credentials from vault, try cookies first, fall back to password login."""
    creds = vault.get_credentials(platform="linkedin", agent_id=agent_id, user_id=user_id)
    if not creds:
        raise ValueError(
            f"No LinkedIn credentials found for agent_id={agent_id} user_id={user_id}. "
            "Run provision_agent_linkedin.py first."
        )

    # Try session cookies first (avoids password login)
    cookies = vault.load_session_cookies(creds["id"], "linkedin")
    if cookies:
        page.context.add_cookies(cookies)
        page.goto(
            "https://www.linkedin.com/feed/",
            wait_until="networkidle",
            timeout=20000,
        )
        if "feed" in page.url or "mynetwork" in page.url:
            print("[post] Session cookie login successful")
            return creds

    # Fall back to password login
    print("[post] Session expired — logging in with credentials...")
    page.goto(
        "https://www.linkedin.com/login",
        wait_until="networkidle",
        timeout=20000,
    )
    page.fill('input[name="session_key"]', creds["email"])
    page.fill('input[name="session_password"]', creds["password"])
    page.click('button[type="submit"]')
    page.wait_for_url("**/feed/**", timeout=15000)

    # Persist fresh cookies
    new_cookies = page.context.cookies()
    vault.save_session_cookies(creds["id"], "linkedin", new_cookies)
    vault.mark_login(creds["id"])
    print("[post] Password login successful, cookies saved")
    return creds


def _post_personal(page, content: str) -> str:
    """Post to the agent's personal LinkedIn feed. Returns current URL."""
    page.goto(
        "https://www.linkedin.com/feed/",
        wait_until="networkidle",
        timeout=20000,
    )
    # Open post composer — LinkedIn uses various class names; try common ones
    for sel in [
        'button[class*="share-box-feed-entry__trigger"]',
        'button[class*="share-creation-state__toggle"]',
        '[data-test-id="share-creation-trigger"]',
    ]:
        if page.locator(sel).count() > 0:
            page.click(sel, timeout=5000)
            break

    page.wait_for_selector('div[role="textbox"]', timeout=10000)
    page.locator('div[role="textbox"]').click()
    page.keyboard.type(content)
    page.wait_for_timeout(1000)

    for sel in [
        'button[class*="share-actions__primary-action"]',
        'button[class*="artdeco-button--primary"][type="submit"]',
    ]:
        if page.locator(sel).count() > 0:
            page.click(sel, timeout=5000)
            break

    page.wait_for_timeout(3000)
    print("[post] Posted to personal feed")
    return page.url


def _post_company(page, content: str) -> str:
    """Post to Kytran Empowerment Inc. company page. Returns current URL."""
    page.goto(
        "https://www.linkedin.com/company/kytran-empowerment-inc/admin/",
        wait_until="networkidle",
        timeout=20000,
    )
    page.wait_for_timeout(2000)

    for sel in [
        'button[class*="share-box-feed-entry__trigger"]',
        'button[class*="share-creation-state__toggle"]',
        '[data-test-id="share-creation-trigger"]',
    ]:
        if page.locator(sel).count() > 0:
            page.click(sel, timeout=5000)
            break

    page.wait_for_selector('div[role="textbox"]', timeout=10000)
    page.locator('div[role="textbox"]').click()
    page.keyboard.type(content)
    page.wait_for_timeout(1000)

    for sel in [
        'button[class*="share-actions__primary-action"]',
        'button[class*="artdeco-button--primary"][type="submit"]',
    ]:
        if page.locator(sel).count() > 0:
            page.click(sel, timeout=5000)
            break

    page.wait_for_timeout(3000)
    print("[post] Posted to Kytran Empowerment Inc. company page")
    return page.url


def post(
    content: str,
    target: str,
    agent_id: int | None = None,
    managed_user_id: int | None = None,
    screenshot_path: str = "/tmp/linkedin_post_confirm.png",
) -> dict:
    """Post content to LinkedIn. Returns result dict."""
    if agent_id is None and managed_user_id is None:
        raise ValueError("Pass either agent_id or managed_user_id")
    if target not in ("personal", "company"):
        raise ValueError("target must be 'personal' or 'company'")

    vault = get_vault()
    post_url: str | None = None

    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 900})

        _load_and_login(page, vault, agent_id=agent_id, user_id=managed_user_id)

        if target == "personal":
            post_url = _post_personal(page, content)
        else:
            post_url = _post_company(page, content)

        page.screenshot(path=screenshot_path)
        browser.close()

    result = {
        "status": "posted",
        "target": target,
        "agent_id": agent_id,
        "managed_user_id": managed_user_id,
        "post_url": post_url,
        "screenshot": screenshot_path,
    }
    print(json.dumps(result, indent=2))
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Post to LinkedIn as an ARCHIE agent.")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--agent-id", type=int, help="Post as this agent's account")
    source.add_argument("--managed-user-id", type=int, help="Post as a managed human user account")
    parser.add_argument("--content", required=True, help="Post text content")
    parser.add_argument(
        "--target",
        choices=["personal", "company"],
        default="personal",
        help="'personal' = agent's own profile; 'company' = Kytran Empowerment Inc. page",
    )
    parser.add_argument(
        "--screenshot",
        default="/tmp/linkedin_post_confirm.png",
        help="Path to save confirmation screenshot",
    )
    args = parser.parse_args()
    post(
        content=args.content,
        target=args.target,
        agent_id=args.agent_id,
        managed_user_id=args.managed_user_id,
        screenshot_path=args.screenshot,
    )


if __name__ == "__main__":
    main()
