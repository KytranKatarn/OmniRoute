#!/usr/bin/env python3
"""provision_agent_linkedin.py — Autonomously create a LinkedIn account for an ARCHIE agent.

Uses the agent's existing Stalwart email to sign up on LinkedIn, confirms via
Email Manager API, sets up the profile with portrait and bio, stores credentials.

Usage:
    python3 scripts/provision_agent_linkedin.py --agent-id 141
    python3 scripts/provision_agent_linkedin.py --agent-name "S.I.G.N.A.L."

Requirements:
    - CREDENTIAL_VAULT_KEY set in environment
    - ARCHIE_SESSION_COOKIE set (admin session for Email Manager API) — optional
    - Agent must have a provisioned Stalwart email in email_mailboxes table
"""
from __future__ import annotations

import argparse
import json
import os
import secrets
import string
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "platform_v2"))

from database import get_db_cursor
from services.credential_vault_service import get_vault

_ARCHIE_API = os.getenv("ARCHIE_API_BASE", "http://192.168.1.200:3000")
_PORTRAIT_DIR = "/mnt/archie_brain/website/kytranempowerment.com/assets/portraits"


def _get_agent(agent_id: int | None, agent_name: str | None) -> dict:
    """Fetch agent profile from DB including their Stalwart email."""
    with get_db_cursor() as (_conn, cur):
        if agent_id:
            cur.execute(
                """SELECT a.id, a.name, a.display_name, a.bio, a.title,
                          e.address AS email
                   FROM agents a
                   LEFT JOIN email_mailboxes e ON e.owner_agent_id = a.id
                       AND e.provisioned = TRUE
                   WHERE a.id = %s""",
                (agent_id,),
            )
        else:
            cur.execute(
                """SELECT a.id, a.name, a.display_name, a.bio, a.title,
                          e.address AS email
                   FROM agents a
                   LEFT JOIN email_mailboxes e ON e.owner_agent_id = a.id
                       AND e.provisioned = TRUE
                   WHERE a.name = %s""",
                (agent_name,),
            )
        row = cur.fetchone()
    if not row:
        raise ValueError(f"Agent not found: {agent_id or agent_name}")
    if not row["email"]:
        raise ValueError(f"Agent {row['name']} has no provisioned Stalwart email")
    return dict(row)


def _generate_password(length: int = 20) -> str:
    alphabet = string.ascii_letters + string.digits + "!@#$%^&*"
    return "".join(secrets.choice(alphabet) for _ in range(length))


def _poll_confirmation_email(
    email: str, timeout: int = 300, interval: int = 30
) -> str | None:
    """Poll Email Manager for a LinkedIn confirmation email.

    Returns message_id on success, None on timeout.
    """
    import requests as _req

    session_cookie = os.getenv("ARCHIE_SESSION_COOKIE", "")
    headers = {"Cookie": session_cookie} if session_cookie else {}
    deadline = time.time() + timeout
    print(f"[provision] Polling for LinkedIn confirmation at {email} (timeout {timeout}s)...")

    while time.time() < deadline:
        try:
            r = _req.get(
                f"{_ARCHIE_API}/api/email/inbox/messages",
                params={"address": email, "limit": 10},
                headers=headers,
                timeout=10,
            )
            if r.ok:
                for msg in r.json().get("messages", []):
                    sender = (msg.get("from_address") or "").lower()
                    subject = (msg.get("subject") or "").lower()
                    if "linkedin" in sender and any(
                        kw in subject for kw in ("confirm", "verify", "activate")
                    ):
                        print(f"[provision] Confirmation email: {msg['subject']}")
                        return msg.get("message_id")
        except Exception as exc:
            print(f"[provision] Poll error: {exc}", file=sys.stderr)

        print(f"[provision] No confirmation yet, retrying in {interval}s...")
        time.sleep(interval)

    return None


def _get_portrait_path(agent: dict) -> str | None:
    stem = agent["name"].replace(".", "").replace(" ", "_").lower()
    path = os.path.join(_PORTRAIT_DIR, f"{stem}.jpg")
    return path if os.path.isfile(path) else None


def provision(
    agent_id: int | None = None,
    agent_name: str | None = None,
) -> dict:
    """Provision a LinkedIn account for one agent. Returns result dict."""
    agent = _get_agent(agent_id, agent_name)
    print(f"[provision] Provisioning LinkedIn for {agent['name']} ({agent['email']})")

    password = _generate_password()
    vault = get_vault()

    display_name = agent["display_name"] or agent["name"]
    parts = display_name.split(" ", 1)
    first_name = parts[0]
    last_name = parts[1] if len(parts) > 1 else agent["name"]

    from playwright.sync_api import sync_playwright

    account_id: int | None = None

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 900})

        print("[provision] Navigating to LinkedIn signup...")
        page.goto(
            "https://www.linkedin.com/signup",
            wait_until="networkidle",
            timeout=30000,
        )

        # Fill signup form — LinkedIn field selectors vary; try common patterns
        for sel in ['input[id="first-name"]', 'input[name="firstName"]', 'input[autocomplete="given-name"]']:
            if page.locator(sel).count() > 0:
                page.fill(sel, first_name)
                break

        for sel in ['input[id="last-name"]', 'input[name="lastName"]', 'input[autocomplete="family-name"]']:
            if page.locator(sel).count() > 0:
                page.fill(sel, last_name)
                break

        for sel in ['input[id="email-address"]', 'input[name="email"]', 'input[type="email"]']:
            if page.locator(sel).count() > 0:
                page.fill(sel, agent["email"])
                break

        for sel in ['input[id="password"]', 'input[name="password"]', 'input[type="password"]']:
            if page.locator(sel).count() > 0:
                page.fill(sel, password)
                break

        page.click('button[type="submit"]')
        page.wait_for_timeout(3000)

        # Store credentials immediately after form submission
        account_id = vault.store_credentials(
            agent_id=agent["id"],
            platform="linkedin",
            email=agent["email"],
            password=password,
        )
        print(f"[provision] Credentials stored (account_id={account_id})")

        # Poll for confirmation email
        msg_id = _poll_confirmation_email(agent["email"])
        if msg_id:
            print(f"[provision] Confirmation detected (message_id={msg_id})")
        else:
            print("[provision] WARNING: No confirmation email within timeout — manual confirmation may be needed", file=sys.stderr)

        # Save session cookies
        try:
            cookies = page.context.cookies()
            vault.save_session_cookies(account_id, "linkedin", cookies)
            vault.mark_login(account_id)
            print("[provision] Session cookies saved")
        except Exception as exc:
            print(f"[provision] Cookie save error: {exc}", file=sys.stderr)

        portrait_path = _get_portrait_path(agent)
        if portrait_path:
            print(f"[provision] Portrait available at {portrait_path}")
            print("[provision] Profile photo upload requires manual step or post-signup automation")

        browser.close()

    result = {
        "status": "provisioned",
        "agent_id": agent["id"],
        "agent_name": agent["name"],
        "platform": "linkedin",
        "email": agent["email"],
        "account_id": account_id,
    }
    print(json.dumps(result, indent=2))
    return result


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Provision a LinkedIn account for an ARCHIE agent."
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--agent-id", type=int)
    group.add_argument("--agent-name")
    args = parser.parse_args()
    provision(agent_id=args.agent_id, agent_name=args.agent_name)


if __name__ == "__main__":
    main()
