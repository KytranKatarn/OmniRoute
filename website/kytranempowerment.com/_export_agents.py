#!/usr/bin/env python3
"""
Export agent data from ARCHIE platform DB to website JSON files.

Outputs:
  data/directory-fallback.json  — all active agents
  data/directors.json           — AI directors only (is_department_ai=true)

Usage:
  DB_PASSWORD=xxx python3 _export_agents.py
  # or reads from platform_v2/.env automatically
"""

import json
import os
import sys

try:
    import psycopg2
    import psycopg2.extras
except ImportError:
    print("ERROR: psycopg2 not installed. Run: pip install psycopg2-binary")
    sys.exit(1)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
DB_HOST = "192.168.1.200"
DB_NAME = "archie"
DB_USER = "archie"
DB_PASSWORD = os.environ.get("DB_PASSWORD", "")

# Try loading from platform_v2/.env if not set
if not DB_PASSWORD:
    env_path = os.path.join(os.path.dirname(__file__), "..", "..", "platform_v2", ".env")
    env_path = os.path.normpath(env_path)
    if os.path.exists(env_path):
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line.startswith("DB_PASSWORD=") and not line.startswith("#"):
                    DB_PASSWORD = line.split("=", 1)[1].strip().strip('"').strip("'")
                    break

if not DB_PASSWORD:
    print("ERROR: DB_PASSWORD not found in env or platform_v2/.env")
    sys.exit(1)

# Floor color mapping
FLOOR_COLORS = {
    "BRIDGE": "#00e5ff",
    "OPERATIONS": "#fbbf24",
    "ENGINEERING": "#8b5cf6",
    "CREATIVE": "#f472b6",
    "SERVICES": "#10b981",
}

# Floor sort order
FLOOR_ORDER = ["BRIDGE", "OPERATIONS", "ENGINEERING", "CREATIVE", "SERVICES"]

# Department-to-floor mapping (fallback if floor column is null)
DEPT_FLOOR_MAP = {
    "Executive Office": "BRIDGE",
    "Operations & Infrastructure": "OPERATIONS",
    "Logistics & Supply Chain": "OPERATIONS",
    "Finance & Accounting": "OPERATIONS",
    "Engineering & Technology": "ENGINEERING",
    "Security & Compliance": "ENGINEERING",
    "Research & Development": "ENGINEERING",
    "Creative & Design": "CREATIVE",
    "Marketing & Communications": "CREATIVE",
    "Documentation & Knowledge": "CREATIVE",
    "Customer Success & Support": "SERVICES",
    "Human Resources & Culture": "SERVICES",
    "Medical & Wellness": "SERVICES",
    "Legal & Regulatory": "SERVICES",
    "Diplomatic & External Relations": "SERVICES",
    "Analytics & Intelligence": "SERVICES",
}


PORTRAIT_HOST = "https://kytranempowerment.com"


def _thumb_url(raw_avatar_url):
    """Derive Hostinger thumbnail URL from agents.avatar_url."""
    if not raw_avatar_url:
        return ""
    stem = os.path.splitext(os.path.basename(raw_avatar_url))[0]
    return f"{PORTRAIT_HOST}/assets/portraits/{stem}.jpg"


def get_connection():
    return psycopg2.connect(
        host=DB_HOST, dbname=DB_NAME, user=DB_USER, password=DB_PASSWORD
    )


def export_agents():
    conn = get_connection()
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("""
            SELECT id, name, display_name, first_name, last_name,
                   department, title, worker_type, is_department_ai,
                   shift_state, avatar_url, email, acronym,
                   acronym_expansion, bio, floor
            FROM agents
            WHERE status = 'active'
            ORDER BY id
        """)
        rows = cur.fetchall()
    finally:
        conn.close()

    # Build directory list (all agents)
    directory = []
    for r in rows:
        name_lower = (r["name"] or "").lower().replace(" ", "_").replace(".", "")
        full_name = " ".join(filter(None, [r["first_name"], r["last_name"]])) or r["display_name"] or r["name"]

        # Determine agent_type string for frontend
        if r["is_department_ai"]:
            agent_type = "director"
        elif r["worker_type"] == "ai":
            agent_type = "ai"
        elif r["worker_type"] == "contractor":
            agent_type = "contractor"
        else:
            agent_type = "staff"

        directory.append({
            "id": r["id"],
            "name": r["name"],
            "display_name": r["display_name"],
            "full_name": full_name,
            "department": r["department"],
            "title": r["title"],
            "agent_type": agent_type,
            "shift_state": r["shift_state"],
            "avatar_url": r["avatar_url"] or f"/assets/portraits/{name_lower}.png",
            "avatar_thumb_url": _thumb_url(r["avatar_url"]),
            "email": r["email"],
            "acronym": r["acronym"],
            "acronym_expansion": r["acronym_expansion"],
        })

    # Build directors list
    directors = []
    for r in rows:
        if not r["is_department_ai"]:
            continue

        floor = r["floor"] or DEPT_FLOOR_MAP.get(r["department"], "SERVICES")
        floor_color = FLOOR_COLORS.get(floor, "#10b981")
        name_lower = (r["name"] or "").lower().replace(" ", "_").replace(".", "")
        full_name = " ".join(filter(None, [r["first_name"], r["last_name"]])) or r["display_name"] or r["name"]

        directors.append({
            "id": r["id"],
            "name": r["name"],
            "display_name": r["display_name"],
            "full_name": full_name,
            "department": r["department"],
            "title": r["title"],
            "agent_type": "director",
            "shift_state": r["shift_state"],
            "avatar_url": r["avatar_url"] or f"/assets/portraits/{name_lower}.png",
            "avatar_thumb_url": _thumb_url(r["avatar_url"]),
            "email": r["email"],
            "acronym": r["acronym"],
            "acronym_expansion": r["acronym_expansion"],
            "description": r["bio"],
            "floor": floor,
            "floor_color": floor_color,
        })

    # Sort directors by floor order
    directors.sort(key=lambda d: (
        FLOOR_ORDER.index(d["floor"]) if d["floor"] in FLOOR_ORDER else 99,
        d["name"]
    ))

    # Write files
    data_dir = os.path.join(os.path.dirname(__file__), "data")
    os.makedirs(data_dir, exist_ok=True)

    dir_path = os.path.join(data_dir, "directory-fallback.json")
    with open(dir_path, "w") as f:
        json.dump(directory, f, indent=2, default=str)

    directors_path = os.path.join(data_dir, "directors.json")
    with open(directors_path, "w") as f:
        json.dump(directors, f, indent=2, default=str)

    # Report
    print(f"Exported {len(directory)} agents to {dir_path}")
    print(f"Exported {len(directors)} directors to {directors_path}")
    print()
    print("Directors:")
    for d in directors:
        print(f"  {d['floor']:12s}  {d['acronym'] or '-':12s}  {d['display_name'] or d['name']}")


if __name__ == "__main__":
    export_agents()
