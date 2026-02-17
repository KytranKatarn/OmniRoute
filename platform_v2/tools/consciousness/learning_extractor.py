"""
Learning Extractor - Extract knowledge from ARCHIE-Claude collaborations

Analyzes collaboration sessions and saves learnings to knowledge base.
"""

import json
import logging
import os

logger = logging.getLogger(__name__)


async def extract_and_save_learnings(session) -> dict:
    """
    Extract learnings from a collaboration session and save to knowledge base.

    Args:
        session: CollabSession object

    Returns:
        dict with extraction stats
    """
    stats = {"cards_created": 0, "topics": [], "error": None}

    try:
        from ai_bridge.knowledge_analyzer import get_knowledge_analyzer, KnowledgeCard
        from ai_bridge.knowledge_cards import save_knowledge_card
        from ai_bridge.embedding_service import generate_embedding

        analyzer = get_knowledge_analyzer()

        # Build full conversation text
        conversation = "\n\n".join([f"{m.role.upper()}: {m.content}" for m in session.messages])

        # Create extraction prompt
        prompt = f"""Analyze this collaboration between ARCHIE (local AI) and Claude.

TOPIC: {session.topic}

CONVERSATION:
{conversation}

Extract the key learnings that ARCHIE should remember. Return JSON:
{{
    "learnings": [
        {{
            "title": "Clear, specific title for this learning",
            "summary": "2-3 sentence summary of what was learned",
            "detailed": "Full explanation with examples if any",
            "topics": ["topic1", "topic2"],
            "technologies": ["tech1", "tech2"],
            "archie_was_uncertain_about": "What ARCHIE didn't know",
            "claude_taught": "Key insight Claude provided",
            "confidence": 0.0-1.0
        }}
    ]
}}

Focus on actionable knowledge ARCHIE can use in future conversations.
Return ONLY valid JSON."""

        # Use local LLM to extract
        response, _, _, _ = analyzer._call_llm(prompt, max_tokens=2000)

        # Parse response - handle markdown code blocks
        response_clean = response.strip()
        if response_clean.startswith("```json"):
            response_clean = response_clean[7:]
        if response_clean.startswith("```"):
            response_clean = response_clean[3:]
        if response_clean.endswith("```"):
            response_clean = response_clean[:-3]

        data = json.loads(response_clean.strip())

        learnings = data.get("learnings", [])

        for learning in learnings:
            # Create knowledge card
            card = KnowledgeCard(
                title=learning.get("title", "Untitled Learning"),
                card_type="learned_from_claude",
                summary=learning.get("summary", ""),
                detailed=learning.get("detailed", ""),
                topics=learning.get("topics", []),
                technologies=learning.get("technologies", []),
                confidence=float(learning.get("confidence", 0.8)),
                source_type="collaboration",
                source_ref=session.id,
            )

            # Add extra metadata
            card.detailed += f"\n\n---\nARCHIE was uncertain about: {learning.get('archie_was_uncertain_about', 'N/A')}"
            card.detailed += f"\nClaude taught: {learning.get('claude_taught', 'N/A')}"

            # Generate embedding
            embedding = generate_embedding(f"{card.title}. {card.summary}")

            # Save card
            card_id = save_knowledge_card(card, embedding, f"collab_{session.id}")

            if card_id:
                stats["cards_created"] += 1
                stats["topics"].extend(learning.get("topics", []))
                logger.info(f"Saved learning: {card.title} (ID: {card_id})")

        stats["topics"] = list(set(stats["topics"]))  # Dedupe

    except json.JSONDecodeError as e:
        logger.error(f"JSON parsing failed: {e}")
        stats["error"] = f"JSON parse error: {str(e)}"
    except Exception as e:
        logger.error(f"Learning extraction failed: {e}")
        stats["error"] = str(e)

    return stats


def get_learning_stats() -> dict:
    """Get stats about learnings from collaborations"""
    import psycopg2

    try:
        conn = psycopg2.connect(
            host=os.getenv("DB_HOST", "archie_database"),
            database=os.getenv("DB_NAME", "archie"),
            user=os.getenv("DB_USER", "archie"),
            password=os.getenv("DB_PASSWORD", "archiepass"),
        )
        cur = conn.cursor()

        # Count learnings from Claude
        cur.execute(
            """
            SELECT COUNT(*) FROM knowledge_base
            WHERE source_type = 'collaboration'
        """
        )
        total = cur.fetchone()[0]

        # Count from last week
        cur.execute(
            """
            SELECT COUNT(*) FROM knowledge_base
            WHERE source_type = 'collaboration'
            AND created_at > NOW() - INTERVAL '7 days'
        """
        )
        last_week = cur.fetchone()[0]

        # Top topics
        cur.execute(
            """
            SELECT unnest(tags) as topic, COUNT(*) as cnt
            FROM knowledge_base
            WHERE source_type = 'collaboration'
            GROUP BY topic
            ORDER BY cnt DESC
            LIMIT 5
        """
        )
        top_topics = [row[0] for row in cur.fetchall()]

        # Recent learnings
        cur.execute(
            """
            SELECT title, ai_analysis->>'summary' as summary, created_at
            FROM knowledge_base
            WHERE source_type = 'collaboration'
            ORDER BY created_at DESC
            LIMIT 5
        """
        )
        recent = [
            {
                "title": row[0],
                "summary": row[1],
                "created_at": row[2].isoformat() if row[2] else None,
            }
            for row in cur.fetchall()
        ]

        cur.close()
        conn.close()

        return {
            "total_learnings": total,
            "learnings_last_week": last_week,
            "top_topics": top_topics,
            "recent_learnings": recent,
        }

    except Exception as e:
        logger.error(f"Failed to get learning stats: {e}")
        return {"error": str(e)}


def get_collaboration_history() -> list:
    """Get history of collaboration sessions"""
    import psycopg2

    try:
        conn = psycopg2.connect(
            host=os.getenv("DB_HOST", "archie_database"),
            database=os.getenv("DB_NAME", "archie"),
            user=os.getenv("DB_USER", "archie"),
            password=os.getenv("DB_PASSWORD", "archiepass"),
        )
        cur = conn.cursor()

        # Get distinct collaboration sessions
        cur.execute(
            """
            SELECT DISTINCT source_ref, COUNT(*) as card_count,
                   MIN(created_at) as started_at
            FROM knowledge_base
            WHERE source_type = 'collaboration'
            GROUP BY source_ref
            ORDER BY started_at DESC
            LIMIT 10
        """
        )

        sessions = []
        for row in cur.fetchall():
            session_id = row[0]
            if session_id and session_id.startswith("collab_"):
                sessions.append(
                    {
                        "session_id": session_id.replace("collab_", ""),
                        "cards_created": row[1],
                        "started_at": row[2].isoformat() if row[2] else None,
                    }
                )

        cur.close()
        conn.close()

        return sessions

    except Exception as e:
        logger.error(f"Failed to get collaboration history: {e}")
        return []
