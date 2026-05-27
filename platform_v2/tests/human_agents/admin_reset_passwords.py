"""
Admin Password Reset Utility — Human Agent Accounts (Project #360 T3293)

No UI force-change flow exists yet (T3295). This script uses the admin API
to set a known permanent password for each of the 21 COLLABORATOR accounts,
then clears must_change_password=FALSE.

Usage (run inside container OR on hub with ARCHIE_ADMIN_* set):

    # Dry run — show what would be changed:
    python admin_reset_passwords.py --dry-run

    # Reset all 21 accounts to auto-generated passwords:
    python admin_reset_passwords.py --generate

    # Reset one specific account:
    python admin_reset_passwords.py --email jin.park@kytranempowerment.com --password NewPass123!

    # Reset all using passwords from a CSV file (email,password per line):
    python admin_reset_passwords.py --from-csv new_passwords.csv

After running --generate, passwords are written to new_credentials.env (gitignored).
Distribute to agents and delete new_credentials.env.
"""

import argparse
import os
import secrets
import sys
from pathlib import Path

import requests

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
BASE_URL = os.environ.get("ARCHIE_BASE_URL", "http://192.168.1.200:3000")
ADMIN_USER = os.environ.get("ARCHIE_ADMIN_USER", "claude")
ADMIN_PASS = os.environ.get("ARCHIE_ADMIN_PASS", "")
SUITE_DIR = Path(__file__).parent


def _get_admin_session() -> requests.Session:
    """Authenticate as admin and return a requests.Session with session cookie."""
    s = requests.Session()
    resp = s.post(
        f"{BASE_URL}/login",
        data={"username": ADMIN_USER, "password": ADMIN_PASS},
        allow_redirects=True,
        timeout=15,
    )
    if "/login" in resp.url or resp.status_code >= 400:
        print(f"ERROR: Admin login failed (status={resp.status_code}, url={resp.url})")
        print("Set ARCHIE_ADMIN_USER and ARCHIE_ADMIN_PASS environment variables.")
        sys.exit(1)
    print(f"✓ Admin session established as '{ADMIN_USER}'")
    return s


def _reset_password_api(session: requests.Session, user_id: int, email: str, new_password: str, dry_run: bool) -> bool:
    """
    Reset a user's password via Account Center admin API.
    Endpoint: POST /tools/account-center/api/users/{user_id}/set-password
    Also clears must_change_password flag.
    """
    if dry_run:
        print(f"  [DRY RUN] Would reset password for {email} (user_id={user_id})")
        return True

    # Try Account Center admin API
    resp = session.post(
        f"{BASE_URL}/tools/account-center/api/users/{user_id}/set-password",
        json={"password": new_password, "must_change_password": False},
        timeout=15,
    )

    if resp.status_code == 404:
        # Fallback: try generic user update endpoint
        resp = session.patch(
            f"{BASE_URL}/tools/account-center/api/users/{user_id}",
            json={"password": new_password, "must_change_password": False},
            timeout=15,
        )

    if resp.ok:
        return True
    else:
        print(f"  ✗ API reset failed for {email}: {resp.status_code} — {resp.text[:200]}")
        return False


def _reset_password_db(user_id: int, email: str, new_password: str, dry_run: bool) -> bool:
    """
    Direct DB reset (fallback if API not available).
    Run via: docker exec archie_platform python3 -c "..."
    """
    import subprocess

    cmd = f"""
import sys; sys.path.insert(0, '/app')
from werkzeug.security import generate_password_hash
from database import get_db_cursor
pw_hash = generate_password_hash({new_password!r})
with get_db_cursor(commit=True) as (conn, cur):
    cur.execute(
        "UPDATE users SET password_hash=%s, must_change_password=FALSE, updated_at=NOW() WHERE id=%s",
        (pw_hash, {user_id})
    )
    print('ROWS:', cur.rowcount)
"""

    if dry_run:
        print(f"  [DRY RUN] Would DB-reset {email} (user_id={user_id})")
        return True

    result = subprocess.run(
        ["docker", "exec", "archie_platform", "python3", "-c", cmd],
        capture_output=True,
        text=True,
        timeout=30,
    )
    if "ROWS: 1" in result.stdout:
        return True
    print(f"  ✗ DB reset failed for {email}: {result.stderr[:300]}")
    return False


def generate_password() -> str:
    """Generate a strong 16-char password meeting platform complexity rules:
    8+ chars, upper+lower+digit+special.
    Uses secrets.choice() — cryptographically secure PRNG.
    """
    import string

    special = "!@#$%^&*"
    chars = string.ascii_letters + string.digits + special
    while True:
        pw = "".join(secrets.choice(chars) for _ in range(16))
        if (
            any(c.isupper() for c in pw)
            and any(c.islower() for c in pw)
            and any(c.isdigit() for c in pw)
            and any(c in special for c in pw)
        ):
            return pw


def load_agents() -> list[dict]:
    import json

    agents_file = SUITE_DIR / "agents.json"
    return json.loads(agents_file.read_text())


def main():
    parser = argparse.ArgumentParser(description="Reset passwords for human agent COLLABORATOR accounts")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be done without making changes")
    parser.add_argument("--generate", action="store_true", help="Generate new passwords for all 21 agents")
    parser.add_argument("--email", help="Reset a specific agent's password")
    parser.add_argument("--password", help="New password for --email")
    parser.add_argument("--from-csv", help="CSV file with email,password lines")
    parser.add_argument(
        "--method",
        choices=["api", "db"],
        default="api",
        help="Reset method (api=Account Center API, db=direct DB via docker exec)",
    )
    args = parser.parse_args()

    agents = load_agents()

    if args.email and not args.password:
        parser.error("--password required with --email")

    # Build the work list
    work: list[tuple[int, str, str]] = []  # (user_id, email, new_password)

    if args.email and args.password:
        agent = next((a for a in agents if a["email"] == args.email), None)
        if not agent:
            print(f"ERROR: {args.email} not found in agents.json")
            sys.exit(1)
        work.append((agent["user_id"], agent["email"], args.password))

    elif args.generate:
        for agent in agents:
            work.append((agent["user_id"], agent["email"], generate_password()))

    elif args.from_csv:
        with open(args.from_csv) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                email, _, pw = line.partition(",")
                agent = next((a for a in agents if a["email"] == email.strip()), None)
                if not agent:
                    print(f"WARN: {email} not in agents.json — skipping")
                    continue
                work.append((agent["user_id"], email.strip(), pw.strip()))
    else:
        parser.print_help()
        sys.exit(0)

    if not work:
        print("Nothing to do.")
        sys.exit(0)

    print(f"\n{'[DRY RUN] ' if args.dry_run else ''}Resetting {len(work)} account(s) via {args.method.upper()}...\n")

    # Admin session (only needed for API method)
    session = None
    if args.method == "api" and not args.dry_run:
        session = _get_admin_session()

    results: list[tuple[str, str, bool]] = []

    for user_id, email, new_password in work:
        if args.method == "api":
            ok = _reset_password_api(session, user_id, email, new_password, args.dry_run)
        else:
            ok = _reset_password_db(user_id, email, new_password, args.dry_run)

        status = "✓" if ok else "✗"
        print(f"  {status} {email}")
        results.append((email, new_password, ok))

    # Write new credentials file (gitignored) — 0o600 so only owner can read
    if args.generate and not args.dry_run:
        out_file = SUITE_DIR / "new_credentials.env"
        fd = os.open(out_file, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            f.write("# New passwords after admin reset — distribute and delete\n")
            for email, pw, ok in results:
                if ok:
                    f.write(f"{email}={pw}\n")
        print(f"\nNew credentials written to {out_file}")
        print("Distribute to agents, then delete this file and KB #269019.")

    ok_count = sum(1 for _, _, ok in results if ok)
    print(f"\n{'[DRY RUN] ' if args.dry_run else ''}Done: {ok_count}/{len(results)} succeeded")


if __name__ == "__main__":
    main()
