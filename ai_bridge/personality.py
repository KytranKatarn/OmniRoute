"""
A.R.C.H.I.E. Personality System

Extracted from platform_v2/tools/archie_core/archie_core.py.
Manages ARCHIE's personality traits and relationship tracking with users.

DB tables: archie_personality, archie_relationships, archie_scripts
"""

import re

from psycopg2.extras import RealDictCursor

try:
    from db import get_db  # works when ai_bridge/ is on sys.path directly
except ImportError:
    from ai_bridge.db import get_db  # works when imported as a package


def get_personality_trait(trait_name: str) -> str:
    """Get A.R.C.H.I.E.'s personality trait value by name."""
    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(
            "SELECT trait_value FROM archie_personality WHERE trait_name = %s",
            (trait_name,),
        )
        result = cur.fetchone()
        cur.close()
        return result["trait_value"] if result else None
    except Exception:
        return None
    finally:
        conn.close()


def get_relationship(user_id: int) -> dict:
    """Get A.R.C.H.I.E.'s relationship with a user, creating one if it doesn't exist."""
    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(
            "SELECT * FROM archie_relationships WHERE user_id = %s",
            (user_id,),
        )
        relationship = cur.fetchone()

        if not relationship:
            cur.execute(
                """
                INSERT INTO archie_relationships (user_id, relationship_type, trust_level, familiarity_level)
                VALUES (%s, 'team_member', 50, 0)
                RETURNING *
                """,
                (user_id,),
            )
            relationship = cur.fetchone()
            conn.commit()

        cur.close()
        return dict(relationship) if relationship else None
    except Exception:
        return None
    finally:
        conn.close()


def update_relationship(user_id: int) -> None:
    """Increment interaction count and familiarity level for a user."""
    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            UPDATE archie_relationships
            SET total_interactions = total_interactions + 1,
                familiarity_level = LEAST(100, familiarity_level + 1),
                last_interaction = NOW()
            WHERE user_id = %s
            """,
            (user_id,),
        )
        conn.commit()
        cur.close()
    except Exception:
        pass
    finally:
        conn.close()


def check_predefined_script(user_message: str, user_id: int) -> dict:
    """Check if a user message matches any pre-defined script.

    Returns a dict with 'matched' bool, and 'script_type'/'response' if matched.
    """
    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)

        relationship = get_relationship(user_id)
        is_admin = relationship and relationship.get("relationship_type") == "admin"

        cur.execute(
            """
            SELECT * FROM archie_scripts
            WHERE active = TRUE
            ORDER BY priority DESC
            """
        )
        scripts = cur.fetchall()
        cur.close()

        message_lower = user_message.lower().strip()

        for script in scripts:
            if "admin" in script["script_type"] and not is_admin:
                continue

            pattern = script["trigger_pattern"]
            if re.search(pattern, message_lower, re.IGNORECASE):
                response = script["response_template"]

                if relationship and relationship.get("preferred_name"):
                    response = response.replace("{name}", relationship["preferred_name"])

                return {
                    "matched": True,
                    "script_type": script["script_type"],
                    "response": response,
                }

        return {"matched": False}
    except Exception as e:
        print(f"Script check error: {e}")
        return {"matched": False}
    finally:
        conn.close()
