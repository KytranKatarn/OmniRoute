"""
Agent Lifecycle Script — A.R.C.H.I.E. Platform
================================================
Handles agent onboarding, offboarding, and profile updates across:
  - Roster (agents table via agent_service)
  - agent_skills table
  - Media Studio / Portraits (agent_portraits + agents.avatar_url)
  - Website thumbnails (auto-synced on portrait approval)

Usage:
    python3 scripts/agent_lifecycle.py onboard   --id 8  --name "I.R.I.S." ...
    python3 scripts/agent_lifecycle.py offboard  --id 8
    python3 scripts/agent_lifecycle.py portrait  --id 8  --approve <media_id>
    python3 scripts/agent_lifecycle.py audit

Run from /mnt/archie_brain inside the platform container or on the host.
"""

import argparse
import json
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "platform_v2"))

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_session_cookies(base_url="http://192.168.1.200:3000"):
    """Login to the platform and return cookie string for API calls."""
    import urllib.request
    import urllib.parse
    import http.cookiejar

    password = os.getenv("ARCHIE_TEST_PASSWORD") or os.getenv("PROBE_TEST_PASS")
    if not password:
        raise RuntimeError(
            "Set ARCHIE_TEST_PASSWORD (or PROBE_TEST_PASS) — no test password is hardcoded."
        )
    cj = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
    opener.open(
        f"{base_url}/login",
        urllib.parse.urlencode({"username": "admin", "password": password}).encode(),
        timeout=10,
    )
    return "; ".join(f"{c.name}={c.value}" for c in cj), opener


def _api(opener, method, url, payload=None, timeout=30):
    """Make an authenticated API call. Returns parsed JSON."""
    import urllib.request
    import urllib.error

    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode() if payload is not None else None,
        headers={"Content-Type": "application/json"},
        method=method,
    )
    try:
        resp = opener.open(req, timeout=timeout)
        return json.loads(resp.read()), resp.status
    except urllib.error.HTTPError as e:
        return json.loads(e.read() or b"{}"), e.code


# ---------------------------------------------------------------------------
# Core operations
# ---------------------------------------------------------------------------

BASE = "http://192.168.1.200:3000"
MEDIA_BASE = f"{BASE}/tools/media-studio/api/portraits"


def onboard(agent_id, name, display_name, department, model, worker_type="ai",
            system_prompt=None, skills=None, portrait_prompt=None, escalate_to=None):
    """
    Full agent onboarding flow:
      1. Update agent profile via agent_service
      2. Set skills in agent_skills
      3. Generate portrait via Media Studio pipeline
      4. Verify status + shift_state are both 'active'

    Parameters
    ----------
    agent_id       : int — existing agent ID (reactivation) or create_agent result
    skills         : list of (skill_name, proficiency_level, escalate_to_id)
    portrait_prompt: str — sci-fi for AI acronym agents, corporate for human agents
    escalate_to    : int — director agent ID for skill escalation
    """
    from services.agent_service import update_agent
    from database import get_db_cursor

    print(f"\n[Onboard] Agent #{agent_id} — {name}")

    # 1. Profile
    fields = dict(
        name=name,
        display_name=display_name,
        department=department,
        model=model,
        worker_type=worker_type,
        shift_state="active",
        # status auto-synced by agent_service when shift_state is set
    )
    if system_prompt:
        fields["system_prompt"] = system_prompt

    ok = update_agent(agent_id, **fields)
    print(f"  Profile: {'OK' if ok else 'FAIL'}")

    # 2. Skills
    if skills:
        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute("DELETE FROM agent_skills WHERE agent_id = %s", (agent_id,))
            cur.executemany(
                "INSERT INTO agent_skills (agent_id, skill_name, proficiency_level, can_escalate_to) "
                "VALUES (%s, %s, %s, %s)",
                [(agent_id, s[0], s[1], s[2] if len(s) > 2 else escalate_to) for s in skills],
            )
            print(f"  Skills: {len(skills)} inserted")

    # 3. Portrait — generate via Media Studio pipeline
    if portrait_prompt:
        print(f"  Portrait: triggering generation...")
        import subprocess

        _, opener = _get_session_cookies(BASE)
        result, status = _api(
            opener, "PUT", f"{MEDIA_BASE}/{agent_id}/identity-prompt",
            {"identity_prompt": portrait_prompt},
        )
        result, status = _api(
            opener, "POST", f"{MEDIA_BASE}/{agent_id}/generate-canonical",
            {"prompt": portrait_prompt}, timeout=300,
        )
        if status in (200, 201):
            queue_id = result.get("queue_id")
            print(f"  Portrait: dispatched (queue_id={queue_id}). Approve via:")
            print(f"    python3 scripts/agent_lifecycle.py portrait --id {agent_id} --approve <media_id>")
        else:
            print(f"  Portrait: dispatch returned {status} — {result}")

    # 4. Verify
    with get_db_cursor() as (conn, cur):
        cur.execute("SELECT name, status, shift_state, avatar_url FROM agents WHERE id = %s", (agent_id,))
        row = dict(cur.fetchone())
    synced = row["status"] == "active" and row["shift_state"] == "active"
    print(f"  Status sync: {'OK' if synced else 'MISMATCH'} "
          f"(status={row['status']}, shift_state={row['shift_state']})")
    print(f"  Avatar URL: {row['avatar_url'] or 'NOT SET — approve portrait first'}")
    print(f"[Onboard] Complete ✓")


def offboard(agent_id):
    """
    Full agent offboarding:
      1. Set shift_state=decommissioned via agent_service (auto-syncs status)
      2. Clears agent from active roster and portrait tab
    """
    from services.agent_service import update_agent

    print(f"\n[Offboard] Agent #{agent_id}")
    ok = update_agent(agent_id, shift_state="decommissioned")
    # status auto-synced to 'decommissioned' by agent_service
    print(f"  Decommissioned: {'OK' if ok else 'FAIL'}")
    print(f"  Agent removed from Roster, portrait tab, and dispatch.\n")


def approve_portrait(agent_id, media_id):
    """
    Approve a generated portrait as canonical:
      - Updates agent_portraits.canonical_image_path
      - Updates agents.avatar_url (syncs Roster + website)
      - Generates 400×400 thumbnail for website repo
    """
    print(f"\n[Portrait] Approve media_id={media_id} for agent #{agent_id}")
    _, opener = _get_session_cookies(BASE)
    result, status = _api(
        opener, "POST", f"{MEDIA_BASE}/{agent_id}/approve", {"media_id": media_id}
    )
    if status == 200:
        print(f"  Approved: {result.get('status')}")
        print(f"  Thumbnail: {result.get('website_thumb')}")
        print(f"  Roster + Media Studio + website thumbnail all synced.\n")
    else:
        print(f"  Failed ({status}): {result}\n")


def audit():
    """
    Audit all non-decommissioned agents for portrait and status completeness.
    Flags: missing portrait, status/shift_state mismatch, no avatar_url.
    """
    from database import get_db_cursor

    print("\n[Audit] Agent portrait + status completeness\n")
    with get_db_cursor() as (conn, cur):
        cur.execute("""
            SELECT a.id, a.name, a.worker_type, a.shift_state, a.status,
                   a.avatar_url,
                   ap.approved, ap.canonical_image_path
            FROM agents a
            LEFT JOIN agent_portraits ap ON ap.agent_id = a.id
            WHERE a.shift_state != 'decommissioned'
            ORDER BY a.worker_type, a.department, a.name
        """)
        rows = [dict(r) for r in cur.fetchall()]

    issues = []
    for r in rows:
        flags = []
        if r["status"] != "active":
            flags.append(f"status={r['status']} (should be active)")
        if not r["canonical_image_path"]:
            flags.append("no portrait record")
        elif not r["approved"]:
            flags.append("portrait not approved")
        if not r["avatar_url"]:
            flags.append("no avatar_url (roster shows placeholder)")
        if flags:
            issues.append((r["id"], r["name"], r["worker_type"], flags))

    if issues:
        print(f"{'ID':<6} {'Name':<22} {'Type':<12} Issues")
        print("-" * 70)
        for agent_id, name, wtype, flags in issues:
            print(f"{agent_id:<6} {name:<22} {wtype:<12} {'; '.join(flags)}")
    else:
        print("All agents fully connected. No issues found.")
    print(f"\n{len(rows)} agents checked, {len(issues)} with issues.\n")


# ---------------------------------------------------------------------------
# Portrait style guide (reference)
# ---------------------------------------------------------------------------
PORTRAIT_STYLE = """
Portrait Style Rules (Decision #282, Portrait Style Rule memory):

  AI acronym agents (worker_type='ai'):
    Prompt: sci-fi aesthetic, abstract/geometric, no human face, no person,
            no ethnicity, no gender. Pure technology visualization.
    Examples: glowing neural networks, scanning grids, data streams,
              abstract eyes, sensor arrays, energy fields.

  Human internal agents (worker_type='internal'):
    Prompt: professional corporate headshot, named ethnicity + role context,
            specific age range, natural lighting, appropriate background.
    Examples: "professional headshot of a Nigerian woman in her 30s, legal
              advisor, neutral background"

  Use identity_prompt field in agent_portraits to store the prompt so
  Media Studio Portraits tab can regenerate consistently.
"""

# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Agent lifecycle management")
    sub = parser.add_subparsers(dest="cmd")

    p_on = sub.add_parser("onboard", help="Activate/create an agent fully")
    p_on.add_argument("--id", type=int, required=True)
    p_on.add_argument("--name", required=True)
    p_on.add_argument("--display-name")
    p_on.add_argument("--department", required=True)
    p_on.add_argument("--model", required=True)
    p_on.add_argument("--worker-type", default="ai")
    p_on.add_argument("--portrait-prompt")

    p_off = sub.add_parser("offboard", help="Decommission an agent")
    p_off.add_argument("--id", type=int, required=True)

    p_por = sub.add_parser("portrait", help="Approve a portrait")
    p_por.add_argument("--id", type=int, required=True)
    p_por.add_argument("--approve", type=int, metavar="MEDIA_ID")

    sub.add_parser("audit", help="Audit all agents for completeness")
    sub.add_parser("style", help="Show portrait style guide")

    args = parser.parse_args()

    if args.cmd == "onboard":
        onboard(
            args.id, args.name, args.display_name or args.name,
            args.department, args.model, args.worker_type,
            portrait_prompt=args.portrait_prompt,
        )
    elif args.cmd == "offboard":
        offboard(args.id)
    elif args.cmd == "portrait" and args.approve:
        approve_portrait(args.id, args.approve)
    elif args.cmd == "audit":
        audit()
    elif args.cmd == "style":
        print(PORTRAIT_STYLE)
    else:
        parser.print_help()
