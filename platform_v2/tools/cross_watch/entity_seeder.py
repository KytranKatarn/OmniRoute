"""Cross-Watch entity seeder — populates shared.entities on startup.

Seeds:
  1. gov_watch.departments  → entity_type='department'
  2. Hard-coded topic list  → entity_type='topic'

Idempotent: INSERT ... ON CONFLICT (slug) DO NOTHING — safe to call repeatedly.
"""

import logging
import re

from database import get_db_cursor

logger = logging.getLogger(__name__)

TOPICS = [
    "Climate Change",
    "Housing",
    "Healthcare",
    "National Defence",
    "Immigration",
    "Indigenous Affairs",
    "Infrastructure",
    "Energy",
    "Trade",
    "Finance",
    "Technology",
    "Agriculture",
    "Environment",
    "Justice",
    "Transport",
    "Education",
    "Labour",
    "Public Safety",
    "Privacy",
    "Democracy",
    "Cannabis",
    "Cybersecurity",
    "Arctic",
    "Foreign Policy",
]


def _slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def seed_entities() -> None:
    """Seed shared.entities from gov_watch.departments and hard-coded topics."""
    dept_count = 0
    topic_count = 0

    try:
        with get_db_cursor(commit=True) as (conn, cur):
            # ── Departments from gov_watch ─────────────────────────────────────
            cur.execute("SELECT name, abbreviation FROM gov_watch.departments ORDER BY name")
            depts = cur.fetchall()
            for dept in depts:
                name = dept["name"]
                abbr = dept["abbreviation"] or ""
                slug = _slugify(name)
                aliases = [abbr] if abbr else []
                cur.execute(
                    """
                    INSERT INTO shared.entities
                        (entity_type, name, slug, aliases, source, source_id)
                    VALUES ('department', %s, %s, %s, 'gov_watch', %s)
                    ON CONFLICT (slug) DO NOTHING
                    """,
                    (name, slug, aliases, slug),
                )
                if cur.rowcount:
                    dept_count += 1

            # ── Hard-coded topics ──────────────────────────────────────────────
            for topic in TOPICS:
                slug = _slugify(topic)
                cur.execute(
                    """
                    INSERT INTO shared.entities
                        (entity_type, name, slug, source)
                    VALUES ('topic', %s, %s, 'platform')
                    ON CONFLICT (slug) DO NOTHING
                    """,
                    (topic, slug),
                )
                if cur.rowcount:
                    topic_count += 1

        logger.info(
            "[cross_watch] entity_seeder: inserted %d departments, %d topics",
            dept_count,
            topic_count,
        )

    except Exception as e:
        logger.error("[cross_watch] entity_seeder failed: %s", e)
