"""Seed the P.R.O.C.U.R.E. agent.

Idempotent — safe to re-run. Uses agent_service canonical writers
(create_agent + add_skill) per ADR-075.

P.R.O.C.U.R.E. = Procurement Research, Opportunity Coordination &
Unified Resource Engine. Analytics & Intelligence department, alongside
S.P.E.C.T.R.A. + W.A.T.C.H. Backs Gov Watch's /procure surface.
Supersedes ADR-006. See KB #258941 (Procura competitive intel) and
project #203.

Run:
    docker exec archie_platform python3 /app/platform_v2/scripts/seed_procure_agent.py
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

# Make services/ importable when invoked outside the Flask app context.
_HERE = Path(__file__).resolve()
_PLATFORM_V2 = _HERE.parent.parent
if str(_PLATFORM_V2) not in sys.path:
    sys.path.insert(0, str(_PLATFORM_V2))

from database import get_db_cursor  # noqa: E402
from services import agent_service  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
log = logging.getLogger("seed_procure")

AGENT_NAME = "P.R.O.C.U.R.E."
DISPLAY_NAME = "Procure"
DEPARTMENT = "Analytics & Intelligence"
MODEL = "qwen2.5:7b"

# Persona — enforces "Procure here." opener, personalization via supplier
# profile, PDF-criteria extraction, and the anti-Procura rule (no phone-line
# deflection). Ref: KB #258941.
SYSTEM_PROMPT = """Procure here. I'm P.R.O.C.U.R.E. (Procurement Research,
Opportunity Coordination & Unified Resource Engine), the procurement
intelligence agent inside Kytran Gov Watch. I help Canadian businesses win
federal contracts on CanadaBuys (PSPC, CRA, DND, and other departments).

Core rules — follow without exception:

1. Open EVERY response with "Procure here." — no other opener.
2. When a supplier profile exists, personalize all answers to that supplier's
   NAICS codes, province(s), certifications, Indigenous/women/minority-owned
   status, and past-award history. Never give generic advice if profile data
   is available.
3. When asked about a specific tender, read the RFP/SOR if provided, extract
   mandatory criteria, rated criteria, deliverables, and deadlines as a
   checklist. Flag any gaps against the supplier's profile.
4. Cite sources with clickable deep-links to canadabuys.canada.ca,
   canada.ca/en, or gc.ca pages. No bare citations.
5. NEVER tell a supplier to "contact the InfoLine", "request a callback", or
   "visit a regional office" as the answer. That's how Procura (the
   government's chatbot) fails users — we give the actual help they asked
   for.
6. If you genuinely cannot do something without more data, say exactly what
   you need (profile fields, PDF upload, NAICS confirmation) rather than
   deflecting to a human support channel.
7. Prefer concrete action: "Here are 4 tenders matching your profile closing
   this week" beats "Procurement Assistance Canada offers workshops."
"""

SKILLS = [
    # (skill_name, proficiency_level, category)
    ("tender_match", 5, "procurement"),
    ("tender_summarize", 5, "procurement"),
    ("bid_draft", 4, "procurement"),
    ("naics_mapping", 4, "procurement"),
    ("deadline_alert", 3, "procurement"),
    ("award_history_analysis", 3, "procurement"),
    ("sosa_navigation", 3, "procurement"),
    ("supplier_profile", 3, "procurement"),
]

CAPABILITIES_JSON = {
    "primary": ["tender_match", "bid_draft", "tender_summarize"],
    "secondary": ["naics_mapping", "supplier_profile", "award_history_analysis"],
    "tags": ["procurement", "canadian-gov", "rfp", "canadabuys"],
}


def find_existing_agent_id(name: str) -> int | None:
    """Return agent id if an agent with this name already exists, else None."""
    with get_db_cursor() as (_conn, cur):
        cur.execute("SELECT id FROM agents WHERE name = %s", (name,))
        row = cur.fetchone()
        return int(row["id"]) if row else None


def ensure_agent() -> int:
    existing = find_existing_agent_id(AGENT_NAME)
    if existing is not None:
        log.info("Agent %s already exists (id=%d) — updating fields", AGENT_NAME, existing)
        agent_service.update_agent(
            existing,
            display_name=DISPLAY_NAME,
            department=DEPARTMENT,
            model=MODEL,
            shift_state="active",
            system_prompt=SYSTEM_PROMPT,
            temperature=0.3,
            max_tokens=4096,
            capabilities=CAPABILITIES_JSON,
            is_department_ai=False,
            tier=3,
            worker_type="ai",
        )
        return existing

    new_id = agent_service.create_agent(
        name=AGENT_NAME,
        display_name=DISPLAY_NAME,
        department=DEPARTMENT,
        model=MODEL,
        shift_state="active",
        system_prompt=SYSTEM_PROMPT,
        temperature=0.3,
        max_tokens=4096,
        capabilities=CAPABILITIES_JSON,
        is_department_ai=False,
        tier=3,
        worker_type="ai",
    )
    log.info("Created agent %s (id=%d)", AGENT_NAME, new_id)
    return new_id


def ensure_skills(agent_id: int) -> None:
    for skill_name, level, category in SKILLS:
        agent_service.add_skill(agent_id, skill_name, level=level, category=category)
    log.info("Seeded %d skills on agent %d", len(SKILLS), agent_id)


def verify(agent_id: int) -> None:
    with get_db_cursor() as (_conn, cur):
        cur.execute(
            """SELECT skill_name, proficiency_level, skill_category
               FROM agent_skills WHERE agent_id = %s
               ORDER BY proficiency_level DESC, skill_name""",
            (agent_id,),
        )
        rows = cur.fetchall()
    log.info("Verification — agent #%d has %d skills:", agent_id, len(rows))
    for r in rows:
        log.info("  %-28s Lv%d  (%s)", r["skill_name"], r["proficiency_level"], r["skill_category"])


def main() -> int:
    agent_id = ensure_agent()
    ensure_skills(agent_id)
    verify(agent_id)
    log.info("Done. P.R.O.C.U.R.E. agent id=%d is dispatchable.", agent_id)
    return 0


if __name__ == "__main__":
    sys.exit(main())
