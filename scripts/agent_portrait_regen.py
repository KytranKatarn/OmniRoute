#!/usr/bin/env python3
"""
Agent Portrait Regeneration Script
===================================
Queues portrait generation for all agents (or a filtered subset) using
the Department HQ portrait pipeline, which now enforces ethnicity/skin-tone
descriptors in every prompt.

Usage:
  python3 scripts/agent_portrait_regen.py --dry-run                        # preview all prompts
  python3 scripts/agent_portrait_regen.py --dry-run --department "Legal & Regulatory"
  python3 scripts/agent_portrait_regen.py --department "Legal & Regulatory" # queue one dept
  python3 scripts/agent_portrait_regen.py                                  # queue ALL agents
"""

import argparse
import os
import sys
import time

# Ensure unbuffered output for background/pipe usage
sys.stdout.reconfigure(line_buffering=True)
sys.stderr.reconfigure(line_buffering=True)

import psycopg2
import psycopg2.extras
import requests

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
PLATFORM_URL = "http://192.168.1.200:3000"
DEPT_HQ_PREFIX = "/tools/department-hq"
DB_HOST = os.getenv("DB_HOST", "192.168.1.200")
DB_PORT = os.getenv("DB_PORT", "5432")
DB_NAME = os.getenv("DB_NAME", "archie")
DB_USER = os.getenv("DB_USER", "archie")
DB_PASSWORD = os.getenv("DB_PASSWORD", "")

ADMIN_USER = os.getenv("ARCHIE_ADMIN_USER", "admin")
ADMIN_PASSWORD = os.getenv("ARCHIE_ADMIN_PASSWORD", "")

SLEEP_BETWEEN = 2  # seconds between portrait add requests


def get_agents(department_filter=None):
    """Fetch agents from the database."""
    conn = psycopg2.connect(
        host=DB_HOST,
        port=DB_PORT,
        dbname=DB_NAME,
        user=DB_USER,
        password=DB_PASSWORD,
    )
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            sql = """
                SELECT id, name, display_name, department,
                       ethnicity, gender, is_department_ai
                FROM agents
                WHERE status = 'active'
            """
            params = []
            if department_filter:
                sql += " AND department = %s"
                params.append(department_filter)
            sql += " ORDER BY department, display_name"
            cur.execute(sql, params)
            return cur.fetchall()
    finally:
        conn.close()


def login(session):
    """Log in to the platform and return True on success."""
    resp = session.post(
        f"{PLATFORM_URL}/login",
        data={"username": ADMIN_USER, "password": ADMIN_PASSWORD},
        allow_redirects=False,
    )
    # Successful login typically redirects (302) to dashboard
    if resp.status_code in (200, 302):
        # Verify we actually got a session by hitting a protected endpoint
        check = session.get(f"{PLATFORM_URL}{DEPT_HQ_PREFIX}", allow_redirects=False)
        if check.status_code == 200:
            return True
        # If redirected to login, auth failed
        if check.status_code == 302 and "/login" in check.headers.get("Location", ""):
            return False
        return True
    return False


MAX_RETRIES = 3
RETRY_DELAY = 10  # seconds


def _request_with_retry(func, *args, **kwargs):
    """Execute a requests call with retry on connection errors."""
    for attempt in range(MAX_RETRIES):
        try:
            return func(*args, **kwargs)
        except requests.exceptions.ConnectionError:
            if attempt < MAX_RETRIES - 1:
                wait = RETRY_DELAY * (attempt + 1)
                print(f"    Connection error, retrying in {wait}s (attempt {attempt + 2}/{MAX_RETRIES})...")
                time.sleep(wait)
            else:
                raise


def generate_prompt(session, agent_id):
    """Call the generate-prompt endpoint. Returns (prompt, negative, error)."""
    try:
        resp = _request_with_retry(
            session.post,
            f"{PLATFORM_URL}{DEPT_HQ_PREFIX}/api/agent/{agent_id}/portraits/generate-prompt",
            json={},
        )
    except requests.exceptions.ConnectionError:
        return None, None, "Connection failed after retries"
    if resp.status_code != 200:
        return None, None, f"HTTP {resp.status_code}: {resp.text[:200]}"
    try:
        data = resp.json()
    except Exception:
        return None, None, f"Non-JSON response: {resp.text[:200]}"
    if "error" in data:
        return None, None, data["error"]
    return data.get("prompt"), data.get("negative_prompt", ""), None


def queue_portrait(session, agent_id, prompt, negative):
    """Queue a portrait for generation. Returns (success, message)."""
    try:
        resp = _request_with_retry(
            session.post,
            f"{PLATFORM_URL}{DEPT_HQ_PREFIX}/api/agent/{agent_id}/portraits/add",
            json={
                "prompt": prompt,
                "negative_prompt": negative,
                "style": "photorealistic",
            },
        )
    except requests.exceptions.ConnectionError:
        return False, "Connection failed after retries"
    if resp.status_code != 200:
        return False, resp.text
    data = resp.json()
    return data.get("success", False), data.get("message", "")


def main():
    parser = argparse.ArgumentParser(description="Regenerate agent portraits with ethnicity enforcement")
    parser.add_argument("--dry-run", action="store_true", help="Only print prompts, don't queue generation")
    parser.add_argument(
        "--department", type=str, default=None, help='Filter by department name (e.g. "Legal & Regulatory")'
    )
    args = parser.parse_args()

    # 1. Fetch agents
    print("=" * 70)
    print("A.R.C.H.I.E. Agent Portrait Regeneration")
    print("=" * 70)

    agents = get_agents(args.department)
    print(f"\nFound {len(agents)} agent(s)" + (f" in '{args.department}'" if args.department else ""))

    if not agents:
        print("No agents found. Check --department filter.")
        sys.exit(1)

    # 2. Login
    session = requests.Session()
    if not args.dry_run:
        print("\nLogging in to platform...")
        if not login(session):
            print("ERROR: Login failed. Check ARCHIE_ADMIN_USER / ARCHIE_ADMIN_PASSWORD env vars.")
            sys.exit(1)
        print("Login successful.")
    else:
        # Still need to login for generate-prompt endpoint (it's @admin_required)
        print("\n[DRY RUN] Logging in to fetch prompts...")
        if not login(session):
            print("ERROR: Login failed. Check ARCHIE_ADMIN_USER / ARCHIE_ADMIN_PASSWORD env vars.")
            sys.exit(1)
        print("Login successful.")

    # 3. Process agents
    success_count = 0
    fail_count = 0
    skip_count = 0
    current_dept = None

    for agent in agents:
        # Print department header
        if agent["department"] != current_dept:
            current_dept = agent["department"]
            print(f"\n--- {current_dept} ---")

        display = agent["display_name"] or agent["name"]
        agent_id = agent["id"]
        ethnicity = agent.get("ethnicity") or "not set"
        gender = agent.get("gender") or "not set"

        print(f"\n  [{agent_id}] {display} (ethnicity={ethnicity}, gender={gender})")

        # Generate prompt
        prompt, negative, err = generate_prompt(session, agent_id)
        if not prompt:
            print(f"    SKIP: Could not generate prompt - {err}")
            skip_count += 1
            continue

        # Show first 120 chars of prompt
        preview = prompt[:120] + ("..." if len(prompt) > 120 else "")
        print(f"    Prompt: {preview}")

        if args.dry_run:
            print(f"    [DRY RUN] Would queue portrait generation")
            success_count += 1
            continue

        # Queue portrait
        ok, msg = queue_portrait(session, agent_id, prompt, negative)
        if ok:
            print(f"    QUEUED: {msg}")
            success_count += 1
        else:
            print(f"    FAIL: {msg}")
            fail_count += 1

        # Throttle to avoid overwhelming GPU queue
        time.sleep(SLEEP_BETWEEN)

    # 4. Summary
    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)
    mode = "DRY RUN" if args.dry_run else "LIVE"
    print(f"  Mode:      {mode}")
    print(f"  Total:     {len(agents)}")
    print(f"  Success:   {success_count}")
    print(f"  Failed:    {fail_count}")
    print(f"  Skipped:   {skip_count}")
    print("=" * 70)


if __name__ == "__main__":
    main()
