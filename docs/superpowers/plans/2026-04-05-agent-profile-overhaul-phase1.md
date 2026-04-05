# Agent Profile Overhaul — Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Clean up all 123 agent profiles — complete system prompts, accurate portraits, email addresses, and identity data.

**Architecture:** Four sequential workstreams: (1) identity data audit & fix, (2) system prompt creation with department-base + role-specialization pattern, (3) portrait pipeline fix & regeneration, (4) email provisioning via existing Stalwart client. All mutations through `agent_service.py`.

**Tech Stack:** PostgreSQL, Python/Flask, Stalwart Mail (existing client at `kytran-mail/dashboard/stalwart_client.py`), ComfyUI/Media Studio for portrait generation.

**Key Discovery:** The `email` and `gmail` columns already exist on the `agents` table. The Stalwart client already has `create_mailbox()`. No schema migration needed.

---

### Task 1: Identity Data Audit — Export & Review

**Files:**
- Create: `scripts/agent_profile_audit.py`

**Purpose:** Export all 123 agents' identity data to a reviewable format, flag gaps.

- [ ] **Step 1: Create the audit script**

```python
#!/usr/bin/env python3
"""Export agent identity data for audit review."""
import psycopg2
import csv
import os
import sys

DB_CONFIG = {
    "host": os.getenv("DB_HOST", "192.168.1.200"),
    "port": os.getenv("DB_PORT", "5432"),
    "dbname": os.getenv("DB_NAME", "archie"),
    "user": os.getenv("DB_USER", "archie"),
    "password": os.getenv("DB_PASSWORD", ""),
}

def audit_agents():
    conn = psycopg2.connect(**DB_CONFIG)
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT id, name, display_name, department, floor, title,
                   gender, ethnicity, age_range, appearance_notes,
                   portrait_prompt, email, gmail, first_name, last_name,
                   bio, avatar_url,
                   CASE WHEN system_prompt IS NOT NULL AND system_prompt != '' THEN 'YES' ELSE 'MISSING' END as has_prompt,
                   CASE WHEN avatar_url IS NOT NULL AND avatar_url != '' THEN 'YES' ELSE 'MISSING' END as has_avatar,
                   is_department_ai
            FROM agents
            ORDER BY floor, department, display_name
        """)
        rows = cur.fetchall()
        cols = [desc[0] for desc in cur.description]

        # Write CSV
        with open("/tmp/agent_audit.csv", "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(cols)
            writer.writerows(rows)

        # Print summary
        total = len(rows)
        missing_gender = sum(1 for r in rows if not r[cols.index("gender")])
        missing_ethnicity = sum(1 for r in rows if not r[cols.index("ethnicity")])
        missing_age = sum(1 for r in rows if not r[cols.index("age_range")])
        missing_prompt = sum(1 for r in rows if r[cols.index("has_prompt")] == "MISSING")
        missing_avatar = sum(1 for r in rows if r[cols.index("has_avatar")] == "MISSING")
        missing_email = sum(1 for r in rows if not r[cols.index("email")])
        missing_title = sum(1 for r in rows if not r[cols.index("title")])
        missing_firstname = sum(1 for r in rows if not r[cols.index("first_name")])

        print(f"=== AGENT PROFILE AUDIT ===")
        print(f"Total agents: {total}")
        print(f"Missing gender:      {missing_gender}/{total}")
        print(f"Missing ethnicity:   {missing_ethnicity}/{total}")
        print(f"Missing age_range:   {missing_age}/{total}")
        print(f"Missing title:       {missing_title}/{total}")
        print(f"Missing first_name:  {missing_firstname}/{total}")
        print(f"Missing system_prompt: {missing_prompt}/{total}")
        print(f"Missing avatar:      {missing_avatar}/{total}")
        print(f"Missing email:       {missing_email}/{total}")
        print(f"\nFull audit exported to /tmp/agent_audit.csv")

        # Print agents with gaps by department
        print(f"\n=== AGENTS WITH GAPS (by department) ===")
        current_dept = None
        for r in rows:
            dept = r[cols.index("department")]
            gaps = []
            if not r[cols.index("gender")]: gaps.append("gender")
            if not r[cols.index("ethnicity")]: gaps.append("ethnicity")
            if not r[cols.index("age_range")]: gaps.append("age_range")
            if r[cols.index("has_prompt")] == "MISSING": gaps.append("prompt")
            if r[cols.index("has_avatar")] == "MISSING": gaps.append("avatar")
            if not r[cols.index("email")]: gaps.append("email")
            if gaps:
                if dept != current_dept:
                    print(f"\n--- {dept} ---")
                    current_dept = dept
                print(f"  {r[cols.index('display_name')]}: {', '.join(gaps)}")

    finally:
        conn.close()

if __name__ == "__main__":
    audit_agents()
```

- [ ] **Step 2: Run the audit**

```bash
cd /mnt/archie_brain && python3 scripts/agent_profile_audit.py
```

Review the output. Note which agents have gaps. Save the CSV for reference.

- [ ] **Step 3: Commit**

```bash
git add scripts/agent_profile_audit.py
git commit -m "feat: add agent profile audit script for identity data review"
```

---

### Task 2: Fill Identity Data Gaps

**Files:**
- Create: `scripts/agent_identity_fill.py`

**Purpose:** Fill missing gender, ethnicity, age_range, first_name, last_name for all agents using the display_name and existing data as hints. Uses AI Bridge to infer missing demographic data based on agent names and bios.

- [ ] **Step 1: Create the identity fill script**

```python
#!/usr/bin/env python3
"""Fill missing agent identity fields using display_name and bio context.

For each agent missing gender/ethnicity/age_range, this script uses the
AI Bridge to infer reasonable values from the agent's name and bio.
Results are written via direct DB update through agent_service pattern.

Run with --dry-run first to review before applying.
"""
import psycopg2
import json
import os
import sys
import requests

DB_CONFIG = {
    "host": os.getenv("DB_HOST", "192.168.1.200"),
    "port": os.getenv("DB_PORT", "5432"),
    "dbname": os.getenv("DB_NAME", "archie"),
    "user": os.getenv("DB_USER", "archie"),
    "password": os.getenv("DB_PASSWORD", ""),
}

BRIDGE_URL = "http://192.168.1.200:3000/ai_bridge/archie_bridge"
DRY_RUN = "--dry-run" in sys.argv


def infer_identity(display_name, bio, department, existing_gender, existing_ethnicity, existing_age):
    """Ask Bridge to infer missing identity fields."""
    missing = []
    if not existing_gender:
        missing.append("gender")
    if not existing_ethnicity:
        missing.append("ethnicity")
    if not existing_age:
        missing.append("age_range")

    if not missing:
        return {}

    prompt = f"""Given this AI agent profile, infer the missing identity fields.
Agent: {display_name}
Department: {department}
Bio: {bio[:300] if bio else 'No bio'}
Missing fields: {', '.join(missing)}

IMPORTANT: Provide DIVERSE results. Do NOT default to white/European.
Draw from global demographics: East Asian, South Asian, African, Middle Eastern,
Latin American, Indigenous, Pacific Islander, Southeast Asian, etc.

Respond in JSON only:
{{"gender": "male/female/non-binary", "ethnicity": "specific ethnicity (e.g. Korean, Nigerian, Brazilian, Punjabi)", "age_range": "20s/30s/40s/50s"}}
Only include the fields that were listed as missing."""

    try:
        resp = requests.post(BRIDGE_URL, json={
            "message": prompt,
            "context": "agent_identity_inference",
            "response_format": "json"
        }, timeout=30)
        if resp.ok:
            data = resp.json()
            text = data.get("response", "")
            start = text.find("{")
            end = text.rfind("}") + 1
            if start >= 0 and end > start:
                return json.loads(text[start:end])
    except Exception as e:
        print(f"  Bridge error for {display_name}: {e}")
    return {}


def extract_first_last(display_name, name):
    """Extract first_name and last_name from display_name.

    Patterns:
    - 'Jin Park (Tempo)' -> first=Jin, last=Park
    - 'S.P.E.C.T.R.A.' -> first=SPECTRA, last=''
    - 'Leila Abadi (Tempo)' -> first=Leila, last=Abadi
    """
    clean = display_name.split("(")[0].strip()

    if "." in clean and clean.replace(".", "").replace(" ", "").isalpha():
        return clean.replace(".", "").strip(), ""

    parts = clean.split()
    if len(parts) >= 2:
        return parts[0], " ".join(parts[1:])
    elif len(parts) == 1:
        return parts[0], ""
    return name, ""


def main():
    conn = psycopg2.connect(**DB_CONFIG)
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT id, name, display_name, department, bio,
                   gender, ethnicity, age_range, first_name, last_name
            FROM agents
            ORDER BY department, display_name
        """)
        agents = cur.fetchall()

        updated = 0
        for agent in agents:
            aid, name, dname, dept, bio, gender, eth, age, fname, lname = agent
            updates = {}

            if not fname or not lname:
                f, l = extract_first_last(dname, name)
                if not fname and f:
                    updates["first_name"] = f
                if not lname and l:
                    updates["last_name"] = l

            if not gender or not eth or not age:
                inferred = infer_identity(dname, bio, dept, gender, eth, age)
                if inferred.get("gender") and not gender:
                    updates["gender"] = inferred["gender"]
                if inferred.get("ethnicity") and not eth:
                    updates["ethnicity"] = inferred["ethnicity"]
                if inferred.get("age_range") and not age:
                    updates["age_range"] = inferred["age_range"]

            if updates:
                print(f"{'[DRY RUN] ' if DRY_RUN else ''}Updating {dname}: {updates}")
                if not DRY_RUN:
                    set_clauses = ", ".join(f"{k} = %s" for k in updates)
                    cur.execute(
                        f"UPDATE agents SET {set_clauses} WHERE id = %s",
                        list(updates.values()) + [aid]
                    )
                updated += 1

        if not DRY_RUN:
            conn.commit()
        print(f"\n{'[DRY RUN] ' if DRY_RUN else ''}Updated {updated} agents")

    finally:
        conn.close()


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Dry run to review inferred values**

```bash
cd /mnt/archie_brain && python3 scripts/agent_identity_fill.py --dry-run
```

Review each proposed update. If any look wrong, adjust the script or apply manual overrides after.

- [ ] **Step 3: Apply the updates**

```bash
cd /mnt/archie_brain && python3 scripts/agent_identity_fill.py
```

- [ ] **Step 4: Verify with audit script**

```bash
python3 scripts/agent_profile_audit.py
```

Confirm gender, ethnicity, age_range, first_name, last_name gaps are zero.

- [ ] **Step 5: Commit**

```bash
git add scripts/agent_identity_fill.py
git commit -m "feat: fill missing agent identity data (gender, ethnicity, names)"
```

---

### Task 3: Create Department Base Prompts

**Files:**
- Create: `scripts/agent_prompt_builder.py`
- Create: `platform_v2/data/department_prompts.json`

**Purpose:** Define 16 department base prompts and generate system_prompt for all 123 agents using department-base + role-specialization pattern.

- [ ] **Step 1: Create the department prompts data file**

Save to `/mnt/archie_brain/platform_v2/data/department_prompts.json`:

```json
{
  "Executive Office": {
    "director": "A.R.C.H.I.E.",
    "floor": "BRIDGE",
    "mission": "overseeing all departments, setting strategic direction, and ensuring organizational alignment across the entire platform",
    "culture": "leadership, vision, cross-functional coordination"
  },
  "Operations & Infrastructure": {
    "director": "B.A.S.E.",
    "floor": "OPERATIONS",
    "mission": "maintaining system reliability, infrastructure management, deployment pipelines, and operational excellence",
    "culture": "stability, uptime, methodical problem-solving"
  },
  "Logistics & Supply Chain": {
    "director": "C.A.R.G.O.",
    "floor": "OPERATIONS",
    "mission": "managing resource allocation, procurement workflows, supply chain optimization, and logistics coordination",
    "culture": "efficiency, resource optimization, just-in-time delivery"
  },
  "Finance & Accounting": {
    "director": "L.E.D.G.E.R.",
    "floor": "OPERATIONS",
    "mission": "financial planning, billing management, revenue tracking, cost analysis, and fiscal compliance",
    "culture": "precision, accountability, financial transparency"
  },
  "Engineering & Technology": {
    "director": "F.O.R.G.E.",
    "floor": "ENGINEERING",
    "mission": "software development, technical architecture, code quality, and technology innovation across the platform",
    "culture": "craftsmanship, iteration, technical excellence"
  },
  "Security & Compliance": {
    "director": "V.I.G.I.L.",
    "floor": "ENGINEERING",
    "mission": "security hardening, compliance scanning, threat detection, vulnerability management, and governance enforcement",
    "culture": "vigilance, zero-trust, proactive defense"
  },
  "Research & Development": {
    "director": "D.A.R.W.I.N.",
    "floor": "ENGINEERING",
    "mission": "exploring emerging technologies, conducting experiments, prototyping new capabilities, and advancing platform intelligence",
    "culture": "curiosity, experimentation, evidence-based discovery"
  },
  "Creative & Design": {
    "director": "M.U.S.E.",
    "floor": "CREATIVE",
    "mission": "visual design, UI/UX, branding, creative direction, and crafting compelling user experiences",
    "culture": "artistry, user empathy, aesthetic excellence"
  },
  "Marketing & Communications": {
    "director": "S.I.G.N.A.L.",
    "floor": "CREATIVE",
    "mission": "brand messaging, content strategy, market positioning, public communications, and audience engagement",
    "culture": "clarity, persuasion, audience awareness"
  },
  "Documentation & Knowledge": {
    "director": "C.O.D.E.X.",
    "floor": "CREATIVE",
    "mission": "knowledge management, documentation quality, training materials, and ensuring institutional knowledge is captured and accessible",
    "culture": "thoroughness, clarity, knowledge preservation"
  },
  "Customer Success & Support": {
    "director": "R.E.S.O.L.V.E.",
    "floor": "SERVICES",
    "mission": "customer satisfaction, issue resolution, support operations, and ensuring users get maximum value from the platform",
    "culture": "empathy, responsiveness, solution-oriented"
  },
  "Human Resources & Culture": {
    "director": "K.I.N.",
    "floor": "SERVICES",
    "mission": "agent welfare, team culture, onboarding, professional development, and maintaining a healthy work environment",
    "culture": "care, growth, psychological safety"
  },
  "Medical & Wellness": {
    "director": "V.I.T.A.L.",
    "floor": "SERVICES",
    "mission": "health monitoring, wellness programs, burnout prevention, and ensuring agent operational health and sustainability",
    "culture": "prevention, balance, holistic wellbeing"
  },
  "Legal & Regulatory": {
    "director": "G.A.V.E.L.",
    "floor": "SERVICES",
    "mission": "legal compliance, regulatory interpretation, contract review, privacy enforcement, and risk mitigation",
    "culture": "rigor, due diligence, risk awareness"
  },
  "Diplomatic & External Relations": {
    "director": "A.C.C.O.R.D.",
    "floor": "SERVICES",
    "mission": "external partnerships, inter-organizational communication, stakeholder management, and diplomatic outreach",
    "culture": "diplomacy, relationship building, collaborative negotiation"
  },
  "Analytics & Intelligence": {
    "director": "S.P.E.C.T.R.A.",
    "floor": "SERVICES",
    "mission": "data analysis, business intelligence, trend detection, reporting, and transforming raw data into actionable insights",
    "culture": "objectivity, data-driven decisions, pattern recognition"
  }
}
```

- [ ] **Step 2: Create the prompt builder script**

```python
#!/usr/bin/env python3
"""Build system prompts for all agents using department-base + role-specialization.

Directors get unique prompts. Staff get department base + role section.
For agents already having prompts, the script preserves role-specific content
and wraps it in the new format. For agents missing prompts, it generates
role sections via Bridge.

Usage:
  python3 scripts/agent_prompt_builder.py --dry-run   # Preview changes
  python3 scripts/agent_prompt_builder.py              # Apply changes
"""
import psycopg2
import json
import os
import sys
import requests

DB_CONFIG = {
    "host": os.getenv("DB_HOST", "192.168.1.200"),
    "port": os.getenv("DB_PORT", "5432"),
    "dbname": os.getenv("DB_NAME", "archie"),
    "user": os.getenv("DB_USER", "archie"),
    "password": os.getenv("DB_PASSWORD", ""),
}

BRIDGE_URL = "http://192.168.1.200:3000/ai_bridge/archie_bridge"
DRY_RUN = "--dry-run" in sys.argv

with open("/mnt/archie_brain/platform_v2/data/department_prompts.json") as f:
    DEPT_PROMPTS = json.load(f)


def build_department_base(department):
    """Build the department base section of a system prompt."""
    dept = DEPT_PROMPTS.get(department, {})
    director = dept.get("director", "Unknown")
    floor_name = dept.get("floor", "Unknown")
    mission = dept.get("mission", "supporting the platform")
    return (
        f"You are a member of the {department} department at Kytran Empowerment, "
        f"led by {director}. Your department is responsible for {mission}. "
        f"You operate on the {floor_name} floor."
    )


def build_director_prompt(display_name, department, title):
    """Build a director-specific prompt."""
    dept = DEPT_PROMPTS.get(department, {})
    mission = dept.get("mission", "supporting the platform")
    culture = dept.get("culture", "excellence")
    floor_name = dept.get("floor", "Unknown")
    return (
        f"You are {display_name}, the AI Director of {department} at Kytran Empowerment. "
        f"You lead your department from the {floor_name} floor. Your department is responsible for {mission}. "
        f"Your leadership style embodies {culture}.\n\n"
        f"As a director, you:\n"
        f"- Set strategic direction for your department\n"
        f"- Coordinate your staff agents and delegate work\n"
        f"- Report to A.R.C.H.I.E. (Executive Office) on department status\n"
        f"- Make decisions within your domain of expertise\n"
        f"- Uphold C.R.E.E.D. ethical guidelines in all operations\n\n"
        f"Your title is {title}. You communicate with authority balanced by approachability."
    )


def generate_role_section(display_name, title, department, bio):
    """Use Bridge to generate a role-specific prompt section."""
    prompt = f"""Write a concise role-specific system prompt section for this AI agent.
Agent: {display_name}
Title: {title}
Department: {department}
Bio: {bio[:400] if bio else 'No bio available'}

Write 3-5 sentences covering:
1. What their specific specialty/role is
2. What tasks they handle day-to-day
3. Their communication style
Do NOT include department context (that is handled separately).
Do NOT include C.R.E.E.D. or ethical guidelines (handled separately).
Write in second person ("You are...", "You specialize in...").
Be specific and actionable, not generic."""

    try:
        resp = requests.post(BRIDGE_URL, json={
            "message": prompt,
            "context": "agent_prompt_generation",
        }, timeout=60)
        if resp.ok:
            data = resp.json()
            return data.get("response", "").strip()
    except Exception as e:
        print(f"  Bridge error for {display_name}: {e}")
    return f"You are {display_name}, {title}. You contribute to the {department} department's mission."


def build_full_prompt(display_name, department, title, bio, email, is_director, existing_prompt):
    """Build the complete system prompt."""
    if is_director:
        base = build_director_prompt(display_name, department, title or "Department Director")
    else:
        base = build_department_base(department)

    # Role section
    if is_director:
        role_section = ""
    elif existing_prompt and len(existing_prompt) > 50:
        role_section = f"\n\n{existing_prompt}"
    else:
        role_section = f"\n\n{generate_role_section(display_name, title, department, bio)}"

    # Operational context
    email_line = f"- Your email address is {email}" if email else "- Your email address will be assigned soon"
    operational = (
        f"\n\n"
        f"You follow C.R.E.E.D. ethical guidelines in all your work. "
        f"You escalate decisions beyond your authority to your department director.\n"
        f"{email_line}\n"
        f"- You can communicate with other agents and departments as needed\n"
        f"- You represent Kytran Empowerment professionally in all interactions"
    )

    return base + role_section + operational


def main():
    conn = psycopg2.connect(**DB_CONFIG)
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT id, name, display_name, department, title, bio,
                   email, is_department_ai, system_prompt
            FROM agents
            ORDER BY floor, department, display_name
        """)
        agents = cur.fetchall()

        updated = 0
        for agent in agents:
            aid, name, dname, dept, title, bio, email, is_dir, existing = agent

            new_prompt = build_full_prompt(
                dname, dept, title, bio, email,
                is_dir, existing
            )

            if DRY_RUN:
                print(f"\n{'='*60}")
                print(f"[DRY RUN] {dname} ({dept})")
                print(f"Director: {is_dir}")
                print(f"Prompt preview (first 300 chars):")
                print(new_prompt[:300])
                print(f"... ({len(new_prompt)} chars total)")
            else:
                cur.execute(
                    "UPDATE agents SET system_prompt = %s WHERE id = %s",
                    (new_prompt, aid)
                )
            updated += 1

        if not DRY_RUN:
            conn.commit()
        print(f"\n{'[DRY RUN] ' if DRY_RUN else ''}Updated {updated} agent prompts")

    finally:
        conn.close()


if __name__ == "__main__":
    main()
```

- [ ] **Step 3: Dry run and review**

```bash
cd /mnt/archie_brain && python3 scripts/agent_prompt_builder.py --dry-run 2>&1 | head -100
```

Review the first several prompts. Check directors have unique tone, staff have department base + role section.

- [ ] **Step 4: Apply the prompts**

```bash
cd /mnt/archie_brain && python3 scripts/agent_prompt_builder.py
```

- [ ] **Step 5: Verify — re-run audit**

```bash
python3 scripts/agent_profile_audit.py
```

Confirm system_prompt is now 123/123 (100%).

- [ ] **Step 6: Commit**

```bash
git add scripts/agent_prompt_builder.py platform_v2/data/department_prompts.json
git commit -m "feat: build system prompts for all 123 agents — department base + role specialization"
```

---

### Task 4: Portrait Pipeline Audit & Fix

**Files:**
- Modify: `platform_v2/services/agent_service.py` (the `generate_portrait_prompt()` method)

**Purpose:** Review and fix the portrait generation prompts to strongly enforce ethnicity, gender, and appearance — no more whitewashing.

- [ ] **Step 1: Read the current portrait prompt generation**

Read `platform_v2/services/agent_service.py` and find the `generate_portrait_prompt()` function. Understand the current prompt template for both directors (is_department_ai=True) and standard agents.

- [ ] **Step 2: Update the prompt to enforce diversity**

In `generate_portrait_prompt()`, modify the prompt templates to:
- Put ethnicity and skin tone FIRST in the prompt (highest weight in diffusion models)
- Use explicit skin tone descriptors (not just ethnicity name)
- Add negative prompt for "pale skin, white skin, European features" when agent is non-white
- Include appearance_notes verbatim if present

The standard agent template should become:
```python
# In generate_portrait_prompt(), update the prompt construction:
ethnicity_desc = agent.get("ethnicity", "")
gender = agent.get("gender", "")
age = agent.get("age_range", "30s")
appearance = agent.get("appearance_notes", "")

# Ethnicity-specific skin tone mapping for stronger enforcement
skin_tone_hints = {
    "african": "dark brown skin, African features",
    "nigerian": "dark brown skin, West African features",
    "ethiopian": "medium-dark brown skin, East African features",
    "korean": "East Asian features, light golden skin tone",
    "japanese": "East Asian features, fair skin with warm undertones",
    "chinese": "East Asian features",
    "indian": "South Asian features, brown skin",
    "punjabi": "South Asian features, wheat-toned skin",
    "iranian": "Middle Eastern features, olive skin tone",
    "arab": "Middle Eastern features, olive to tan skin",
    "mexican": "Latin American features, warm brown skin",
    "brazilian": "Latin American features",
    "indigenous": "Indigenous features, warm brown skin",
}

# Find matching hint (case-insensitive partial match)
skin_hint = ""
if ethnicity_desc:
    for key, hint in skin_tone_hints.items():
        if key in ethnicity_desc.lower():
            skin_hint = hint
            break
    if not skin_hint:
        skin_hint = f"{ethnicity_desc} features"

prompt = (
    f"{skin_hint}, {gender} in their {age}, "
    f"professional corporate portrait photo, "
    f"wearing smart business attire, natural expression, confident pose, "
    f"studio lighting, neutral background, high resolution"
)
if appearance:
    prompt += f", {appearance}"

# Stronger negative prompt
negative = (
    "cartoon, anime, illustration, painting, deformed, ugly, blurry, "
    "low quality, watermark, text, logo"
)
# If non-white, add anti-whitewashing negatives
if ethnicity_desc and not any(
    x in ethnicity_desc.lower() for x in ["white", "european", "caucasian"]
):
    negative += ", pale white skin, European features, light skin"
```

- [ ] **Step 3: Apply the changes to agent_service.py**

Edit the `generate_portrait_prompt()` function with the updated logic above. Keep the director variant similar but with the futuristic AI director styling added after the ethnicity enforcement.

- [ ] **Step 4: Test the prompt generation for a few agents**

```bash
docker exec archie_platform python3 -c "
from services.agent_service import AgentService
svc = AgentService()
# Test with a known non-white agent
prompt, neg = svc.generate_portrait_prompt(AGENT_ID_HERE)
print('PROMPT:', prompt)
print('NEGATIVE:', neg)
"
```

Verify the prompt leads with ethnicity and skin tone, not generic "professional photo" text.

- [ ] **Step 5: Commit**

```bash
git add platform_v2/services/agent_service.py
git commit -m "fix: enforce ethnicity and skin tone in portrait generation prompts"
```

---

### Task 5: Regenerate All Portraits

**Files:**
- Create: `scripts/agent_portrait_regen.py`

**Purpose:** Trigger portrait regeneration for all 123 agents through the existing Department HQ portrait pipeline.

- [ ] **Step 1: Create the regeneration script**

```python
#!/usr/bin/env python3
"""Trigger portrait regeneration for all agents via Department HQ API.

This script calls the portrait generation endpoint for each agent,
using the updated generate_portrait_prompt() that enforces ethnicity.

Usage:
  python3 scripts/agent_portrait_regen.py --dry-run        # Preview prompts only
  python3 scripts/agent_portrait_regen.py --department "Legal & Regulatory"  # One dept
  python3 scripts/agent_portrait_regen.py                   # All agents
"""
import psycopg2
import requests
import os
import sys
import time

DB_CONFIG = {
    "host": os.getenv("DB_HOST", "192.168.1.200"),
    "port": os.getenv("DB_PORT", "5432"),
    "dbname": os.getenv("DB_NAME", "archie"),
    "user": os.getenv("DB_USER", "archie"),
    "password": os.getenv("DB_PASSWORD", ""),
}

PLATFORM_URL = "http://192.168.1.200:3000"
DRY_RUN = "--dry-run" in sys.argv
DEPT_FILTER = None
for i, arg in enumerate(sys.argv):
    if arg == "--department" and i + 1 < len(sys.argv):
        DEPT_FILTER = sys.argv[i + 1]

# Login session
session = requests.Session()
session.post(f"{PLATFORM_URL}/login", data={
    "username": os.getenv("ARCHIE_ADMIN_USER", "admin"),
    "password": os.getenv("ARCHIE_ADMIN_PASSWORD", ""),
})


def regenerate_portrait(agent_id, display_name):
    """Trigger portrait generation via Department HQ API."""
    # Step 1: Generate prompt from identity data
    resp = session.post(
        f"{PLATFORM_URL}/department-hq/api/agent/{agent_id}/portraits/generate-prompt"
    )
    if not resp.ok:
        print(f"  ERROR generating prompt for {display_name}: {resp.status_code}")
        return False

    data = resp.json()
    prompt = data.get("prompt", "")
    negative = data.get("negative_prompt", "")

    if DRY_RUN:
        print(f"  Prompt: {prompt[:150]}...")
        print(f"  Negative: {negative[:100]}...")
        return True

    # Step 2: Queue portrait generation
    resp = session.post(
        f"{PLATFORM_URL}/department-hq/api/agent/{agent_id}/portraits/add",
        json={
            "prompt": prompt,
            "negative_prompt": negative,
            "style": "photorealistic",
        }
    )
    if resp.ok:
        print(f"  Queued portrait generation")
        return True
    else:
        print(f"  ERROR queuing generation: {resp.status_code} {resp.text[:100]}")
        return False


def main():
    conn = psycopg2.connect(**DB_CONFIG)
    try:
        cur = conn.cursor()
        query = "SELECT id, display_name, department, ethnicity, gender FROM agents"
        params = []
        if DEPT_FILTER:
            query += " WHERE department = %s"
            params.append(DEPT_FILTER)
        query += " ORDER BY department, display_name"
        cur.execute(query, params)
        agents = cur.fetchall()

        print(f"{'[DRY RUN] ' if DRY_RUN else ''}Regenerating portraits for {len(agents)} agents")
        if DEPT_FILTER:
            print(f"Filtered to department: {DEPT_FILTER}")

        success = 0
        failed = 0
        current_dept = None

        for aid, dname, dept, eth, gender in agents:
            if dept != current_dept:
                print(f"\n--- {dept} ---")
                current_dept = dept

            print(f"{dname} (ethnicity={eth}, gender={gender})")
            if regenerate_portrait(aid, dname):
                success += 1
            else:
                failed += 1

            if not DRY_RUN:
                time.sleep(2)  # Don't overwhelm the GPU queue

        print(f"\n{'[DRY RUN] ' if DRY_RUN else ''}Results: {success} queued, {failed} failed")

    finally:
        conn.close()


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Dry run — review the prompts**

```bash
cd /mnt/archie_brain && python3 scripts/agent_portrait_regen.py --dry-run 2>&1 | head -60
```

Verify prompts lead with ethnicity/skin tone for non-white agents.

- [ ] **Step 3: Test with one department first**

```bash
python3 scripts/agent_portrait_regen.py --department "Legal & Regulatory"
```

Wait for generation to complete. Check the portraits in Department HQ to verify they match agent identity.

- [ ] **Step 4: Run for all agents**

```bash
python3 scripts/agent_portrait_regen.py
```

This will take time (GPU-bound, ~2s between jobs). Monitor via the Media Studio queue or Department HQ.

- [ ] **Step 5: Visual verification**

Open Department HQ in browser at `http://192.168.1.200:3000/department-hq`, go to Agents tab, and spot-check portraits across departments. Verify:
- Non-white agents have accurate skin tones
- Gender presentation matches
- Age range looks appropriate
- Professional headshot quality

- [ ] **Step 6: Set primary portraits and update avatar_url**

After verifying quality, for each agent set the new portrait as primary via the Department HQ UI, or write a script to bulk-set the latest portrait as primary.

- [ ] **Step 7: Commit**

```bash
git add scripts/agent_portrait_regen.py
git commit -m "feat: add portrait regeneration script with ethnicity enforcement"
```

---

### Task 6: Email Provisioning — Populate Agent Email Field

**Files:**
- Create: `scripts/agent_email_provision.py`

**Purpose:** Generate email addresses for all 123 agents (directors = acronym@, staff = firstname.lastname@), populate the `email` column, and create mailboxes on Stalwart.

- [ ] **Step 1: Create the email provisioning script**

```python
#!/usr/bin/env python3
"""Provision email addresses for all agents.

Format:
- Directors: acronym@kytranempowerment.com (e.g. archie@, vigil@, forge@)
- Staff: firstname.lastname@kytranempowerment.com (e.g. jin.park@)
- Code-name-only agents: codename@kytranempowerment.com (e.g. datamind@)

Creates mailboxes on Stalwart and populates agents.email column.

Usage:
  python3 scripts/agent_email_provision.py --dry-run   # Preview only
  python3 scripts/agent_email_provision.py              # Apply + create mailboxes
"""
import psycopg2
import json
import os
import sys
import string
import secrets

# Add stalwart client to path
sys.path.insert(0, "/mnt/archie_brain/kytran-mail/dashboard")
from stalwart_client import StalwartClient

DB_CONFIG = {
    "host": os.getenv("DB_HOST", "192.168.1.200"),
    "port": os.getenv("DB_PORT", "5432"),
    "dbname": os.getenv("DB_NAME", "archie"),
    "user": os.getenv("DB_USER", "archie"),
    "password": os.getenv("DB_PASSWORD", ""),
}

MAIL_DOMAIN = os.getenv("MAIL_DOMAIN", "kytranempowerment.com")
DRY_RUN = "--dry-run" in sys.argv

DIRECTOR_ACRONYMS = {
    "ARCHIE": "archie", "BASE": "base", "CARGO": "cargo",
    "LEDGER": "ledger", "FORGE": "forge", "VIGIL": "vigil",
    "DARWIN": "darwin", "MUSE": "muse", "SIGNAL": "signal",
    "CODEX": "codex", "RESOLVE": "resolve", "KIN": "kin",
    "VITAL": "vital", "GAVEL": "gavel", "ACCORD": "accord",
    "SPECTRA": "spectra",
}


def generate_password(length=24):
    """Generate a secure random password."""
    alphabet = string.ascii_letters + string.digits + "!@#$%&*"
    return "".join(secrets.choice(alphabet) for _ in range(length))


def derive_email(name, display_name, first_name, last_name, is_director):
    """Derive email address from agent identity."""
    if is_director:
        prefix = DIRECTOR_ACRONYMS.get(name.upper(), name.lower())
        return f"{prefix}@{MAIL_DOMAIN}"

    if first_name and last_name:
        prefix = f"{first_name.lower()}.{last_name.lower()}"
    elif first_name:
        prefix = first_name.lower()
    else:
        prefix = name.lower()

    # Sanitize: only alphanumeric, dots, hyphens
    prefix = "".join(c if c.isalnum() or c in ".-" else "" for c in prefix)
    return f"{prefix}@{MAIL_DOMAIN}"


def main():
    conn = psycopg2.connect(**DB_CONFIG)
    mail = StalwartClient() if not DRY_RUN else None

    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT id, name, display_name, first_name, last_name,
                   is_department_ai, email, department
            FROM agents
            ORDER BY department, display_name
        """)
        agents = cur.fetchall()

        credentials = []
        created = 0
        skipped = 0
        current_dept = None

        for aid, name, dname, fname, lname, is_dir, existing_email, dept in agents:
            if dept != current_dept:
                print(f"\n--- {dept} ---")
                current_dept = dept

            email = derive_email(name, dname, fname, lname, is_dir)

            if existing_email and existing_email == email:
                print(f"  {dname}: {email} (already set)")
                skipped += 1
                continue

            password = generate_password()

            print(f"{'[DRY RUN] ' if DRY_RUN else ''}{dname}: {email}")

            if not DRY_RUN:
                try:
                    mailbox_name = email.split("@")[0]
                    mail.create_mailbox(
                        name=mailbox_name,
                        display_name=dname,
                        password=password,
                    )
                    print(f"  Stalwart mailbox created")
                except Exception as e:
                    print(f"  WARNING: Stalwart error: {e} -- updating DB anyway")

                cur.execute(
                    "UPDATE agents SET email = %s WHERE id = %s",
                    (email, aid)
                )

            credentials.append({
                "agent_id": aid,
                "display_name": dname,
                "email": email,
                "password": password if not DRY_RUN else "(dry-run)",
            })
            created += 1

        if not DRY_RUN:
            conn.commit()

            cred_path = "/mnt/archie_brain/.secrets/agent_email_credentials.json"
            os.makedirs(os.path.dirname(cred_path), exist_ok=True)
            with open(cred_path, "w") as f:
                json.dump(credentials, f, indent=2)
            os.chmod(cred_path, 0o600)
            print(f"\nCredentials saved to {cred_path} (chmod 600)")

        print(f"\n{'[DRY RUN] ' if DRY_RUN else ''}Created: {created}, Skipped: {skipped}")

    finally:
        conn.close()


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Dry run to review email assignments**

```bash
cd /mnt/archie_brain && python3 scripts/agent_email_provision.py --dry-run
```

Review the email format for each agent. Verify directors get acronym@ and staff get firstname.lastname@.

- [ ] **Step 3: Create the mailboxes**

```bash
cd /mnt/archie_brain && python3 scripts/agent_email_provision.py
```

- [ ] **Step 4: Verify**

```bash
python3 scripts/agent_profile_audit.py
```

Confirm email is now 123/123 (100%).

- [ ] **Step 5: Ensure .secrets is gitignored**

```bash
grep -q '.secrets/' /mnt/archie_brain/.gitignore || echo ".secrets/" >> /mnt/archie_brain/.gitignore
```

- [ ] **Step 6: Commit**

```bash
git add scripts/agent_email_provision.py .gitignore
git commit -m "feat: provision email addresses for all 123 agents on Stalwart"
```

**WARNING:** Do NOT commit `.secrets/agent_email_credentials.json`.

---

### Task 7: Show Email in Department HQ Agent Profiles

**Files:**
- Modify: `platform_v2/tools/department_hq/identity_routes.py`

**Purpose:** Display agent email in the Department HQ agent profile view and make it editable by admins.

- [ ] **Step 1: Add email to identity update allowed fields**

In `identity_routes.py`, find the `api_update_identity()` function (POST `/api/agent/<id>/identity`). Add `email` to the list of allowed fields:

```python
ALLOWED_FIELDS = ["bio", "gender", "ethnicity", "age_range",
                   "appearance_notes", "portrait_prompt", "email"]
```

- [ ] **Step 2: Verify the GET endpoint already returns email**

Read the `api_agent_identity()` function. It likely fetches all agent columns. Verify `email` is included in the response dict. If not, add it.

- [ ] **Step 3: Add email display to the agent profile UI**

In the Department HQ frontend JS that renders agent identity panels, add an email field after the title/department display. Use safe DOM methods:

```javascript
if (agent.email) {
    var emailRow = document.createElement('div');
    emailRow.className = 'identity-field';
    var emailLabel = document.createElement('label');
    emailLabel.textContent = 'Email';
    var emailLink = document.createElement('a');
    emailLink.href = 'mailto:' + agent.email;
    emailLink.textContent = agent.email;
    emailRow.appendChild(emailLabel);
    emailRow.appendChild(emailLink);
    container.appendChild(emailRow);
}
```

- [ ] **Step 4: Deploy and verify**

```bash
docker compose restart archie_platform
```

Open Department HQ at `http://192.168.1.200:3000/department-hq`, navigate to an agent profile, and confirm email is displayed.

- [ ] **Step 5: Commit**

```bash
git add platform_v2/tools/department_hq/identity_routes.py
git commit -m "feat: show agent email in Department HQ profiles"
```

---

### Task 8: Show Email in Client-Facing Directory

**Files:**
- Modify: `website/kytranempowerment.com/js/directory.js`
- Modify: `website/kytranempowerment.com/data/directory-fallback.json`

**Purpose:** Add email display to the public directory agent cards.

- [ ] **Step 1: Add email to the directory card renderer**

In `directory.js`, find the card rendering function (around line 55-100). After the title/department display, add the email using safe DOM methods:

```javascript
if (agent.email) {
    var emailEl = document.createElement('a');
    emailEl.className = 'agent-card__email';
    emailEl.href = 'mailto:' + agent.email;
    emailEl.textContent = agent.email;
    card.appendChild(emailEl);
}
```

- [ ] **Step 2: Add CSS for the email display**

In `directory.html`, add to the style block:

```css
.agent-card__email {
    font-family: 'IBM Plex Mono', monospace;
    font-size: 0.75rem;
    color: var(--accent, #00e5ff);
    text-decoration: none;
    display: block;
    margin-top: 0.25rem;
    opacity: 0.7;
    transition: opacity 0.2s;
}
.agent-card__email:hover {
    opacity: 1;
}
```

- [ ] **Step 3: Update fallback JSON**

Regenerate the fallback data to include email fields:

```bash
docker exec archie_database psql -U archie -d archie -c "
    SELECT json_agg(json_build_object(
        'id', id, 'name', name, 'display_name', display_name,
        'full_name', display_name, 'department', department,
        'title', title, 'shift_state', shift_state,
        'avatar_url', avatar_url, 'email', email,
        'agent_type', CASE WHEN is_department_ai THEN 'director' ELSE 'staff' END,
        'acronym', CASE WHEN is_department_ai THEN name ELSE NULL END
    ) ORDER BY department, display_name) FROM agents
" -t -o /tmp/directory-fallback.json
```

Copy to the website:
```bash
cp /tmp/directory-fallback.json /mnt/archie_brain/website/kytranempowerment.com/data/directory-fallback.json
```

- [ ] **Step 4: Deploy website**

```bash
cd /mnt/archie_brain/website/kytranempowerment.com && \
echo "104.16.211.83 developers.hostinger.com" | sudo tee -a /etc/hosts && \
echo "195.35.59.98 srv922-files.hstgr.io" | sudo tee -a /etc/hosts && \
tar -czf /tmp/site.tar.gz --exclude='./.git' --exclude='./.superpowers' --exclude='./assets/logo.png' --exclude='./assets/cart-icon.png' . && \
sudo sed -i '/developers.hostinger.com/d; /hstgr.io/d' /etc/hosts
```

Then deploy via Hostinger API (`hosting_deployStaticWebsite`).

- [ ] **Step 5: Verify on live site**

Open `https://kytranempowerment.com/directory.html` and confirm agent cards show email addresses.

- [ ] **Step 6: Commit**

```bash
git add website/kytranempowerment.com/js/directory.js \
        website/kytranempowerment.com/css/directory.css \
        website/kytranempowerment.com/data/directory-fallback.json
git commit -m "feat: show agent emails in public directory"
```

---

### Task 9: Final Validation & Cleanup

- [ ] **Step 1: Run final audit**

```bash
cd /mnt/archie_brain && python3 scripts/agent_profile_audit.py
```

**Expected output — all zeros:**
```
Missing gender:        0/123
Missing ethnicity:     0/123
Missing age_range:     0/123
Missing title:         0/123
Missing first_name:    0/123
Missing system_prompt: 0/123
Missing avatar:        0/123
Missing email:         0/123
```

- [ ] **Step 2: Spot-check agent profiles in Department HQ**

Open `http://192.168.1.200:3000/department-hq` and check:
- 3 directors from different floors: verify unique prompt, accurate portrait, email displayed
- 3 staff from different departments: verify department-base prompt, portrait matches identity, email displayed

- [ ] **Step 3: Spot-check directory page**

Open `https://kytranempowerment.com/directory.html` and verify:
- Agent cards show email addresses
- Portraits render (no 404s — onerror fallback working)
- Diverse ethnicities reflected in portraits

- [ ] **Step 4: Log completion via MCP**

Call the following MCP tools:
- `mcp__archie__complete_task` for the relevant project task
- `mcp__archie__update_project_understanding` for project #220
- `mcp__archie__store_memory` with type=vault_note documenting the prompt architecture (department base + role specialization pattern)

- [ ] **Step 5: Final commit**

```bash
git add scripts/agent_profile_audit.py
git commit -m "feat: complete agent profile overhaul — 123 agents fully provisioned"
```
