#!/usr/bin/env python3
"""Provision email addresses for all agents.

Derives email from agent identity data, updates the DB, and optionally
creates mailboxes on Stalwart mail server.

Usage:
    python3 scripts/agent_email_provision.py --dry-run   # preview only
    python3 scripts/agent_email_provision.py              # provision for real
"""

import argparse
import json
import os
import re
import secrets
import stat
import sys

import psycopg2

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
DOMAIN = "kytranempowerment.com"
CRED_FILE = os.path.join(os.path.dirname(__file__), "..", ".secrets", "agent_email_credentials.json")
CRED_FILE = os.path.abspath(CRED_FILE)

DB_CONFIG = {
    "host": os.getenv("DB_HOST", "192.168.1.200"),
    "port": os.getenv("DB_PORT", "5432"),
    "dbname": os.getenv("DB_NAME", "archie"),
    "user": os.getenv("DB_USER", "archie"),
    "password": os.getenv("DB_PASSWORD", ""),
}

# ---------------------------------------------------------------------------
# Stalwart client (optional -- graceful if unavailable)
# ---------------------------------------------------------------------------
stalwart = None
try:
    sys.path.insert(0, "/mnt/archie_brain/kytran-mail/dashboard")
    import stalwart_client as stalwart  # noqa: E402
except ImportError:
    pass


def _sanitize_local(raw: str) -> str:
    """Keep only alphanumeric, dots, hyphens; lowercase.  Spaces become dots."""
    clean = raw.lower().strip()
    # Convert spaces to dots first
    clean = clean.replace(" ", ".")
    # Remove everything except alphanumeric, dots, hyphens
    clean = re.sub(r"[^a-z0-9.\-]", "", clean)
    # collapse repeated dots/hyphens, strip leading/trailing
    clean = re.sub(r"[.\-]{2,}", ".", clean).strip(".-")
    return clean


def derive_email(agent: dict) -> str:
    """Return the canonical email address for an agent."""
    name = (agent["name"] or "").strip()
    first = (agent["first_name"] or "").strip()
    last = (agent["last_name"] or "").strip()
    is_director = agent["is_department_ai"]

    if is_director:
        # Directors use their code-name as the local part
        local = _sanitize_local(name)
    elif first and last:
        # Staff: firstname.lastname
        local = _sanitize_local(f"{first}.{last}")
    elif first:
        # Code-name-only staff (e.g. SHIELD with first_name="Shield")
        local = _sanitize_local(first)
    else:
        # Fallback to code name
        local = _sanitize_local(name)

    if not local:
        local = _sanitize_local(name) or f"agent-{agent['id']}"

    return f"{local}@{DOMAIN}"


def generate_password(length: int = 24) -> str:
    """Generate a secure random password."""
    return secrets.token_urlsafe(length)


def load_agents(conn) -> list:
    """Fetch all agents from the database."""
    cur = conn.cursor()
    cur.execute("""
        SELECT id, name, display_name, first_name, last_name,
               is_department_ai, email, department
        FROM agents
        ORDER BY is_department_ai DESC, name
    """)
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]


def main():
    parser = argparse.ArgumentParser(description="Provision agent emails")
    parser.add_argument("--dry-run", action="store_true", help="Preview only, no changes")
    args = parser.parse_args()

    conn = psycopg2.connect(**DB_CONFIG)
    try:
        agents = load_agents(conn)
    except Exception as e:
        print(f"ERROR: Could not load agents: {e}")
        return 1

    print(f"Loaded {len(agents)} agents ({sum(1 for a in agents if a['is_department_ai'])} directors, "
          f"{sum(1 for a in agents if not a['is_department_ai'])} staff)")
    print()

    # Track results
    updated = 0
    skipped = 0
    stalwart_ok = 0
    stalwart_fail = 0
    credentials = {}

    # Detect duplicates before provisioning
    email_map = {}
    for agent in agents:
        email = derive_email(agent)
        if email in email_map:
            # Append agent id suffix to disambiguate
            local, domain = email.split("@")
            email = f"{local}-{agent['id']}@{domain}"
        email_map[email] = agent["id"]

    # Rebuild map keyed by agent id
    id_to_email = {v: k for k, v in email_map.items()}

    for agent in agents:
        email = id_to_email[agent["id"]]
        current = (agent["email"] or "").strip()
        tag = "DIRECTOR" if agent["is_department_ai"] else "STAFF"

        if current == email:
            if args.dry_run:
                print(f"  SKIP [{tag:8}] {agent['name']:20} -> {email} (already set)")
            skipped += 1
            continue

        if args.dry_run:
            old_note = f" (was: {current})" if current else ""
            print(f"  SET  [{tag:8}] {agent['name']:20} -> {email}{old_note}")
            updated += 1
            continue

        # --- Real mode ---
        # 1. Try Stalwart mailbox creation
        password = generate_password()
        display = agent["display_name"] or agent["name"]

        if stalwart:
            local_part = email.split("@")[0]
            try:
                result = stalwart.create_mailbox(local_part, display, password, quota_mb=100)
                if isinstance(result, dict) and result.get("error"):
                    err = result["error"]
                    # 409 = already exists, that's fine
                    if "409" in str(err) or "already" in str(err).lower():
                        stalwart_ok += 1
                    else:
                        print(f"  WARN Stalwart error for {email}: {err}")
                        stalwart_fail += 1
                else:
                    stalwart_ok += 1
            except Exception as e:
                print(f"  WARN Stalwart exception for {email}: {e}")
                stalwart_fail += 1
        else:
            stalwart_fail += 1  # not available

        # 2. Update DB regardless
        try:
            cur = conn.cursor()
            cur.execute("UPDATE agents SET email = %s WHERE id = %s", (email, agent["id"]))
            conn.commit()
            updated += 1
        except Exception as e:
            print(f"  ERROR DB update for {agent['name']}: {e}")
            conn.rollback()
            continue

        # 3. Save credentials
        credentials[email] = {
            "agent_id": agent["id"],
            "agent_name": agent["name"],
            "display_name": display,
            "email": email,
            "password": password,
            "department": agent["department"],
        }

    # Summary
    print()
    print(f"=== PROVISION SUMMARY ===")
    print(f"Total agents:     {len(agents)}")
    print(f"Emails assigned:  {updated}")
    print(f"Already correct:  {skipped}")
    if not args.dry_run:
        print(f"Stalwart created: {stalwart_ok}")
        print(f"Stalwart failed:  {stalwart_fail}")

    # Save credentials file
    if credentials and not args.dry_run:
        os.makedirs(os.path.dirname(CRED_FILE), exist_ok=True)
        # Merge with existing if present
        existing = {}
        if os.path.exists(CRED_FILE):
            try:
                with open(CRED_FILE, "r") as f:
                    existing = json.load(f)
            except (json.JSONDecodeError, IOError):
                pass
        existing.update(credentials)
        with open(CRED_FILE, "w") as f:
            json.dump(existing, f, indent=2, sort_keys=True)
        os.chmod(CRED_FILE, stat.S_IRUSR | stat.S_IWUSR)  # 600
        print(f"Credentials saved: {CRED_FILE} ({len(existing)} total)")

    return 0


if __name__ == "__main__":
    sys.exit(main())
