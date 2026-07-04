"""
Provision all @kytranempowerment.com mailboxes on Stalwart Mail Server.

Creates: 107 individual agent mailboxes + functional + department + leadership + aliases
Uses Stalwart REST API at http://localhost:8880/api/principal

Run: python3 /mnt/archie_brain/scripts/provision_mailboxes.py
"""

import json
import os
import sys
import urllib.request
import base64
import secrets
import string

# Stalwart API config
API_BASE = "http://localhost:8880"
ADMIN_USER = "admin"
ADMIN_PASS = "xq8ayjITim"
DOMAIN = "kytranempowerment.com"

# DB config
DB_HOST = os.environ.get("DB_HOST", "192.168.1.200")
DB_NAME = os.environ.get("DB_NAME", "archie")
DB_USER = os.environ.get("DB_USER", "archie")
DB_PASSWORD = os.environ.get("DB_PASSWORD", "")
DB_PORT = os.environ.get("DB_PORT", "5432")


def api_request(method, path, data=None):
    """Make authenticated request to Stalwart API."""
    creds = base64.b64encode(f"{ADMIN_USER}:{ADMIN_PASS}".encode()).decode()
    headers = {
        "Authorization": f"Basic {creds}",
        "Content-Type": "application/json",
    }
    body = json.dumps(data).encode() if data else None
    req = urllib.request.Request(f"{API_BASE}{path}", data=body, headers=headers, method=method)
    try:
        r = urllib.request.urlopen(req, timeout=10)
        return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        return {"error": e.code, "message": e.read().decode()[:200]}
    except Exception as e:
        return {"error": str(e)}


def generate_password(length=16):
    """Generate a secure random password."""
    chars = string.ascii_letters + string.digits + "!@#$%"
    return "".join(secrets.choice(chars) for _ in range(length))


def create_account(name, email, display_name, password=None, account_type="individual"):
    """Create a mail account on Stalwart."""
    if not password:
        password = generate_password()

    principal = {
        "type": account_type,
        "name": email.split("@")[0],
        "emails": [email],
        "secrets": [password],
        "description": display_name,
    }

    result = api_request("POST", "/api/principal", principal)
    return result, password


def create_mailing_list(name, email, members, display_name):
    """Create a mailing list / group."""
    principal = {
        "type": "list",
        "name": name,
        "emails": [email],
        "members": members,
        "description": display_name,
    }
    return api_request("POST", "/api/principal", principal)


def get_agents():
    """Get all active agents from DB."""
    try:
        import psycopg2
        import psycopg2.extras

        conn = psycopg2.connect(
            host=DB_HOST,
            dbname=DB_NAME,
            user=DB_USER,
            password=DB_PASSWORD,
            port=DB_PORT,
        )
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(
            """SELECT id, name, display_name, first_name, last_name, email,
                      department, title
               FROM agents WHERE status = 'active' ORDER BY id"""
        )
        agents = cur.fetchall()
        cur.close()
        conn.close()
        return agents
    except Exception as e:
        print(f"[!!] DB error: {e}")
        return []


def main():
    print()
    print("=" * 60)
    print("  A.R.C.H.I.E. Mail Server — Mailbox Provisioning")
    print(f"  Domain: {DOMAIN}")
    print("=" * 60)
    print()

    created = 0
    failed = 0
    passwords = {}

    # ── 1. FUNCTIONAL MAILBOXES ──
    print("[>>] Creating functional mailboxes...")
    functional = [
        ("info", "General Inquiries"),
        ("support", "Customer Support"),
        ("billing", "Billing & Payments"),
        ("sales", "Sales Inquiries"),
        ("hr", "Human Resources"),
        ("legal", "Legal & Compliance"),
        ("security", "Security Reports"),
        ("privacy", "Data Privacy Requests"),
        ("admin", "System Administration"),
        ("noreply", "Automated Notifications"),
        ("contact", "Public Contact"),
        ("careers", "Job Applications"),
        ("press", "Media Inquiries"),
        ("abuse", "Abuse Reports"),
        ("postmaster", "Mail Administration"),
    ]
    for name, desc in functional:
        email = f"{name}@{DOMAIN}"
        result, pwd = create_account(name, email, desc)
        if "error" not in result:
            print(f"  [OK] {email} — {desc}")
            passwords[email] = pwd
            created += 1
        else:
            print(f"  [!!] {email} — {result}")
            failed += 1

    # ── 2. DEPARTMENT SHARED MAILBOXES ──
    print()
    print("[>>] Creating department mailboxes...")
    departments = [
        ("analytics", "Analytics Station Team"),
        ("creative", "Creative Station Team"),
        ("engineering", "Engineering Station Team"),
        ("communications", "Communications Station Team"),
        ("research", "Research Station Team"),
        ("security-team", "Security Team (Vigil)"),
        ("logistics", "Logistics Station Team"),
        ("operations", "Operations Station Team"),
        ("devops", "DevOps Team (Vigil)"),
        ("diplomatic", "Diplomatic Station Team"),
    ]
    for name, desc in departments:
        email = f"{name}@{DOMAIN}"
        result, pwd = create_account(name, email, desc)
        if "error" not in result:
            print(f"  [OK] {email} — {desc}")
            passwords[email] = pwd
            created += 1
        else:
            print(f"  [!!] {email} — {result}")
            failed += 1

    # ── 3. LEADERSHIP MAILBOXES ──
    print()
    print("[>>] Creating leadership mailboxes...")
    leadership = [
        ("kytran", "Kytran Tran — CEO & Founder"),
        ("archie", "A.R.C.H.I.E. — AI Director"),
        ("vigil", "Vigil — Ethics & Governance Officer"),
    ]
    for name, desc in leadership:
        email = f"{name}@{DOMAIN}"
        result, pwd = create_account(name, email, desc)
        if "error" not in result:
            print(f"  [OK] {email} — {desc}")
            passwords[email] = pwd
            created += 1
        else:
            print(f"  [!!] {email} — {result}")
            failed += 1

    # ── 4. INDIVIDUAL AGENT MAILBOXES ──
    print()
    print("[>>] Creating agent mailboxes (from DB)...")
    agents = get_agents()
    if not agents:
        print("  [!!] No agents found in DB — skipping")
    else:
        for agent in agents:
            email = agent.get("email")
            if not email or not email.endswith(f"@{DOMAIN}"):
                continue
            display = agent.get("display_name") or agent.get("name") or "Agent"
            title = agent.get("title") or ""
            desc = f"{display} — {title}" if title else display
            local = email.split("@")[0]

            result, pwd = create_account(local, email, desc)
            if "error" not in result:
                print(f"  [OK] {email}")
                passwords[email] = pwd
                created += 1
            else:
                # Might already exist (e.g., kytran@, archie@, vigil@ from leadership)
                err_msg = str(result.get("message", ""))
                if "already exists" in err_msg.lower() or result.get("error") == 409:
                    print(f"  [--] {email} (already exists)")
                else:
                    print(f"  [!!] {email} — {result}")
                    failed += 1

    # ── 5. SAVE PASSWORDS ──
    print()
    pw_file = "/mnt/archie_brain/secrets/mail_passwords.json"
    os.makedirs(os.path.dirname(pw_file), exist_ok=True)
    with open(pw_file, "w") as f:
        json.dump(passwords, f, indent=2)
    os.chmod(pw_file, 0o600)
    print(f"[>>] Passwords saved to {pw_file} (chmod 600)")

    # ── SUMMARY ──
    print()
    print("=" * 60)
    print(f"  Created: {created}")
    print(f"  Failed:  {failed}")
    print(f"  Total:   {created + failed}")
    print("=" * 60)


if __name__ == "__main__":
    main()
