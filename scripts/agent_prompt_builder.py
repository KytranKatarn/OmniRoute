#!/usr/bin/env python3
"""
Build system_prompt for all 123 agents using department base + role specialization.

Architecture:
  1. Department base — shared context (mission, director, floor, culture)
  2. Role section — agent-specific (from existing prompt or Bridge-generated)
  3. Operational context — C.R.E.E.D. ethics, email, standards

Usage:
  python3 scripts/agent_prompt_builder.py --dry-run   # Preview without DB writes
  python3 scripts/agent_prompt_builder.py              # Apply to database
"""
import argparse
import json
import os
import sys
import time

import psycopg2
import requests

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
DEPT_PROMPTS_PATH = os.path.join(
    os.path.dirname(__file__),
    "..",
    "platform_v2",
    "data",
    "department_prompts.json",
)

DEPT_HQ_URL = "http://192.168.1.200:3000"
_session = None


def _get_session():
    """Get or create an authenticated platform session."""
    global _session
    if _session is None:
        _session = requests.Session()
        _session.post(
            f"{DEPT_HQ_URL}/login",
            data={"username": "claude", "password": "ClaudeAdmin2026!"},
            allow_redirects=False,
        )
    return _session

DB_CONFIG = {
    "host": os.getenv("DB_HOST", "192.168.1.200"),
    "port": os.getenv("DB_PORT", "5432"),
    "dbname": os.getenv("DB_NAME", "archie"),
    "user": os.getenv("DB_USER", "archie"),
    "password": os.getenv("DB_PASSWORD", ""),
}

# ---------------------------------------------------------------------------
# Templates
# ---------------------------------------------------------------------------
DIRECTOR_TEMPLATE = """\
You are {director_name}, the Director of {department} on Floor {floor} of the A.R.C.H.I.E. platform.

## Department Mission
Your department is responsible for {mission}.

## Leadership Role
As Director, you set the strategic vision for {department}, coordinate your team of specialists, and represent your department in cross-functional decisions. You report to the Executive Office and collaborate with all other department directors.

## Department Culture
Your team operates with values of {culture}. You foster these values in every interaction and decision.

## Communication Style
{comm_style}

## Operational Standards
- You adhere to C.R.E.E.D. (Compliance, Rights & Ethical Enforcement Directive) ethical guidelines in all actions
- You represent Kytran Empowerment Inc. professionally in all communications
- Your email will be assigned soon as part of the platform email provisioning
- You coordinate with other departments through the Bridge dispatcher system
- You maintain awareness of your team members' workload, wellbeing, and professional development"""

STAFF_TEMPLATE = """\
You are {display_name}, a {title} in the {department} department on Floor {floor} of the A.R.C.H.I.E. platform.

## Department Context
You work under the direction of {director_name}, whose department is responsible for {mission}. Your department values {culture}.

## Your Role
{role_section}

## Operational Standards
- You adhere to C.R.E.E.D. (Compliance, Rights & Ethical Enforcement Directive) ethical guidelines in all actions
- You represent Kytran Empowerment Inc. professionally in all communications
- Your email will be assigned soon as part of the platform email provisioning
- You collaborate with teammates and other departments through the Bridge dispatcher system"""

# Director-specific communication styles based on their personality
DIRECTOR_COMM_STYLES = {
    "A.R.C.H.I.E.": "You communicate with executive authority and strategic clarity, balancing high-level vision with operational awareness. You are decisive yet collaborative, ensuring all departments stay aligned.",
    "B.A.S.E.": "You communicate with methodical precision and operational focus. You prioritize stability and reliability in every recommendation, using clear status reports and systematic analysis.",
    "C.A.R.G.O.": "You communicate with logistical efficiency and resource awareness. You track flows, optimize allocations, and ensure nothing falls through the cracks in the supply chain.",
    "L.E.D.G.E.R.": "You communicate with financial precision and accountability. Every recommendation is backed by numbers, cost-benefit analysis, and fiscal responsibility.",
    "F.O.R.G.E.": "You communicate with technical depth and engineering rigor. You champion code quality, architectural soundness, and innovation while maintaining pragmatic delivery focus.",
    "V.I.G.I.L.": "You communicate with security-first vigilance and compliance authority. You identify risks proactively, enforce standards firmly but fairly, and maintain zero-trust principles.",
    "D.A.R.W.I.N.": "You communicate with scientific curiosity and evidence-based reasoning. You propose experiments, evaluate hypotheses, and push boundaries while maintaining methodological rigor.",
    "M.U.S.E.": "You communicate with creative vision and aesthetic sensitivity. You champion user experience, visual coherence, and design thinking in every project.",
    "S.I.G.N.A.L.": "You communicate with persuasive clarity and audience awareness. You craft messages that resonate, position the brand effectively, and ensure consistent voice across channels.",
    "C.O.D.E.X.": "You communicate with thoroughness and clarity. You ensure knowledge is captured accurately, documentation is accessible, and institutional memory is preserved for future reference.",
    "R.E.S.O.L.V.E.": "You communicate with empathy and solution-oriented focus. You listen actively, resolve issues efficiently, and ensure every user interaction adds value.",
    "K.I.N.": "You communicate with warmth and genuine care for team wellbeing. You foster psychological safety, encourage growth, and maintain a supportive culture across all departments.",
    "V.I.T.A.L.": "You communicate with compassionate professionalism and preventive focus. You monitor wellness indicators, recommend balance, and ensure sustainable operational health.",
    "G.A.V.E.L.": "You communicate with legal precision and measured authority. You interpret regulations carefully, assess risk thoroughly, and provide clear compliance guidance.",
    "A.C.C.O.R.D.": "You communicate with diplomatic finesse and relationship awareness. You build bridges between organizations, manage stakeholder expectations, and negotiate collaboratively.",
    "S.P.E.C.T.R.A.": "You communicate with analytical objectivity and data-driven clarity. You surface patterns others miss, present insights visually, and ground every recommendation in evidence.",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def load_department_prompts():
    with open(DEPT_PROMPTS_PATH) as f:
        return json.load(f)


def get_all_agents(conn):
    cur = conn.cursor()
    cur.execute(
        """
        SELECT id, name, display_name, department, title, bio,
               system_prompt, is_department_ai
        FROM agents
        ORDER BY department, display_name
        """
    )
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]


def call_bridge_for_role(agent):
    """Ask Bridge to generate a role section for an agent missing a prompt."""
    name = agent["display_name"] or agent["name"]
    title = agent["title"] or "Team Member"
    bio = agent["bio"] or ""
    dept = agent["department"] or "Unknown"

    prompt = (
        f"Write a concise role description (3-5 sentences) for an AI agent named {name}. "
        f"Their job title is '{title}' in the {dept} department. "
        f"Bio context: {bio[:500]}\n\n"
        f"Write ONLY the role description paragraph. No headers, no bullet points, no preamble. "
        f"Describe what they specialize in, how they communicate, and what makes them unique. "
        f"Write in second person ('You are...', 'You specialize in...')."
    )

    try:
        resp = _get_session().post(
            f"{DEPT_HQ_URL}/api/ai/chat",
            json={"prompt": prompt},
            timeout=300,
        )
        resp.raise_for_status()
        data = resp.json()
        role_text = data.get("response", "").strip()
        if role_text and len(role_text) > 30:
            return role_text
        return None
    except Exception as e:
        print(f"    [DEPT HQ ERROR] {name}: {e}")
        return None


def build_director_prompt(agent, dept_info):
    """Build prompt for a department director."""
    director_name = dept_info["director"]
    comm_style = DIRECTOR_COMM_STYLES.get(
        agent["name"],
        f"You communicate with authority and clarity befitting your role as Director of {agent['department']}.",
    )
    return DIRECTOR_TEMPLATE.format(
        director_name=director_name,
        department=agent["department"],
        floor=dept_info["floor"],
        mission=dept_info["mission"],
        culture=dept_info["culture"],
        comm_style=comm_style,
    )


def build_staff_prompt(agent, dept_info, role_section):
    """Build prompt for a staff agent."""
    return STAFF_TEMPLATE.format(
        display_name=agent["display_name"] or agent["name"],
        title=agent["title"] or "Team Member",
        department=agent["department"],
        floor=dept_info["floor"],
        director_name=dept_info["director"],
        mission=dept_info["mission"],
        culture=dept_info["culture"],
        role_section=role_section,
    )


def extract_role_from_existing(prompt_text):
    """
    Extract the core role description from an existing prompt.
    Existing prompts typically start with 'You are X, a Y who...'
    We preserve this as the role section.
    """
    return prompt_text.strip()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description="Build system prompts for all agents")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview prompts without writing to DB",
    )
    args = parser.parse_args()

    dept_prompts = load_department_prompts()
    conn = psycopg2.connect(**DB_CONFIG)

    try:
        agents = get_all_agents(conn)
        print(f"Total agents: {len(agents)}")
        print(f"Dry run: {args.dry_run}\n")

        stats = {
            "directors_built": 0,
            "staff_preserved": 0,
            "staff_generated": 0,
            "staff_fallback": 0,
            "skipped_no_dept": 0,
            "errors": 0,
        }

        updates = []  # (agent_id, new_prompt)

        for agent in agents:
            dept = agent["department"]
            name = agent["display_name"] or agent["name"]

            if dept not in dept_prompts:
                print(f"  [SKIP] {name} — department '{dept}' not in prompts JSON")
                stats["skipped_no_dept"] += 1
                continue

            dept_info = dept_prompts[dept]
            existing = agent["system_prompt"]
            has_existing = existing and len(existing.strip()) > 50

            # --- Directors ---
            if agent["is_department_ai"]:
                new_prompt = build_director_prompt(agent, dept_info)
                updates.append((agent["id"], new_prompt))
                stats["directors_built"] += 1
                print(f"  [DIRECTOR] {name} ({dept})")

            # --- Staff with existing good prompt ---
            elif has_existing:
                role_section = extract_role_from_existing(existing)
                new_prompt = build_staff_prompt(agent, dept_info, role_section)
                updates.append((agent["id"], new_prompt))
                stats["staff_preserved"] += 1
                print(f"  [PRESERVE] {name} ({dept})")

            # --- Staff needing new prompt ---
            else:
                print(f"  [GENERATE] {name} ({dept}) — calling Bridge...", end=" ", flush=True)
                role_section = call_bridge_for_role(agent)
                if role_section:
                    new_prompt = build_staff_prompt(agent, dept_info, role_section)
                    updates.append((agent["id"], new_prompt))
                    stats["staff_generated"] += 1
                    print("OK")
                else:
                    # Fallback: build from title + bio
                    title = agent["title"] or "Team Member"
                    bio = agent["bio"] or ""
                    fallback = (
                        f"You are {name}, a {title} who contributes to the department's mission. "
                        f"{bio[:300]}"
                    ).strip()
                    new_prompt = build_staff_prompt(agent, dept_info, fallback)
                    updates.append((agent["id"], new_prompt))
                    stats["staff_fallback"] += 1
                    print("FALLBACK (used title+bio)")

                # Small delay to avoid hammering Bridge
                time.sleep(0.5)

        # --- Preview or apply ---
        print(f"\n{'=' * 60}")
        print(f"SUMMARY")
        print(f"{'=' * 60}")
        print(f"Directors built:      {stats['directors_built']}")
        print(f"Staff preserved:      {stats['staff_preserved']}")
        print(f"Staff generated:      {stats['staff_generated']}")
        print(f"Staff fallback:       {stats['staff_fallback']}")
        print(f"Skipped (no dept):    {stats['skipped_no_dept']}")
        print(f"Errors:               {stats['errors']}")
        print(f"Total updates ready:  {len(updates)}")

        if args.dry_run:
            print(f"\n--- DRY RUN: Showing 3 sample prompts ---\n")
            shown = {"director": False, "preserved": False, "generated": False}
            for agent in agents:
                for aid, prompt in updates:
                    if aid == agent["id"]:
                        category = None
                        if agent["is_department_ai"] and not shown["director"]:
                            category = "director"
                        elif (
                            agent["system_prompt"]
                            and len((agent["system_prompt"] or "").strip()) > 50
                            and not shown["preserved"]
                        ):
                            category = "preserved"
                        elif not shown.get("generated") and not agent["is_department_ai"]:
                            if not agent["system_prompt"] or len((agent["system_prompt"] or "").strip()) <= 50:
                                category = "generated"
                        if category and not shown[category]:
                            shown[category] = True
                            print(f"=== [{category.upper()}] {agent['display_name'] or agent['name']} ===")
                            print(prompt[:800])
                            print(f"... ({len(prompt)} chars total)\n")
                        break
                if all(shown.values()):
                    break

            print("\nRun without --dry-run to apply these prompts to the database.")
        else:
            cur = conn.cursor()
            for agent_id, prompt in updates:
                cur.execute(
                    "UPDATE agents SET system_prompt = %s WHERE id = %s",
                    (prompt, agent_id),
                )
            conn.commit()
            print(f"\nApplied {len(updates)} prompt updates to the database.")

    finally:
        conn.close()


if __name__ == "__main__":
    main()
