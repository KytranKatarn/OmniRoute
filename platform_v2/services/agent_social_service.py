"""Agent Social Presence Service — manages digital personas, content, and social profiles.

Import:
    from services.agent_social_service import (
        get_social_profiles, add_social_profile, get_posts, create_post,
        generate_post_content, get_writing_voice, update_writing_voice,
    )
"""

import json
import logging
from database import get_db_cursor

logger = logging.getLogger(__name__)


def get_social_profiles(agent_id):
    """Get all social media profiles for an agent."""
    with get_db_cursor() as (conn, cur):
        cur.execute(
            "SELECT * FROM agent_social_profiles WHERE agent_id = %s ORDER BY platform",
            (agent_id,),
        )
        return [dict(r) for r in cur.fetchall()]


def add_social_profile(agent_id, platform, handle, profile_url=""):
    """Add/update a social media profile."""
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            """INSERT INTO agent_social_profiles (agent_id, platform, handle, profile_url)
               VALUES (%s, %s, %s, %s)
               ON CONFLICT (agent_id, platform) DO UPDATE
               SET handle = EXCLUDED.handle, profile_url = EXCLUDED.profile_url
               RETURNING id""",
            (agent_id, platform, handle, profile_url),
        )
        return cur.fetchone()["id"]


def remove_social_profile(agent_id, platform):
    """Remove a social media profile."""
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            "DELETE FROM agent_social_profiles WHERE agent_id = %s AND platform = %s",
            (agent_id, platform),
        )


def get_writing_voice(agent_id):
    """Get agent's writing voice settings."""
    with get_db_cursor() as (conn, cur):
        cur.execute(
            "SELECT writing_tone, writing_style, social_topics FROM agents WHERE id = %s",
            (agent_id,),
        )
        row = cur.fetchone()
        if not row:
            return None
        return {
            "tone": row["writing_tone"] or "professional",
            "style": row["writing_style"] or "",
            "topics": (
                row["social_topics"]
                if isinstance(row["social_topics"], list)
                else json.loads(row["social_topics"] or "[]")
            ),
        }


def update_writing_voice(agent_id, tone=None, style=None, topics=None):
    """Update agent's writing voice."""
    updates = {}
    if tone is not None:
        updates["writing_tone"] = tone
    if style is not None:
        updates["writing_style"] = style
    if topics is not None:
        updates["social_topics"] = json.dumps(topics) if isinstance(topics, list) else topics

    if not updates:
        return

    from services.agent_service import update_agent

    update_agent(agent_id, **updates)


def get_posts(agent_id=None, status=None, platform=None, limit=50):
    """Get content posts with optional filters."""
    conditions = []
    params = []
    if agent_id:
        conditions.append("p.agent_id = %s")
        params.append(agent_id)
    if status:
        conditions.append("p.status = %s")
        params.append(status)
    if platform:
        conditions.append("p.platform = %s")
        params.append(platform)

    where = "WHERE " + " AND ".join(conditions) if conditions else ""
    params.append(limit)

    with get_db_cursor() as (conn, cur):
        cur.execute(
            f"""SELECT p.*, a.name, a.display_name, a.department
                FROM agent_content_posts p
                JOIN agents a ON a.id = p.agent_id
                {where}
                ORDER BY p.created_at DESC LIMIT %s""",
            params,
        )
        return [dict(r) for r in cur.fetchall()]


def create_post(agent_id, content, platform=None, post_type="update", media_urls=None, scheduled_at=None):
    """Create a content post (draft by default)."""
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            """INSERT INTO agent_content_posts
               (agent_id, platform, content, post_type, media_urls, status, scheduled_at)
               VALUES (%s, %s, %s, %s, %s, %s, %s)
               RETURNING id""",
            (
                agent_id,
                platform,
                content,
                post_type,
                json.dumps(media_urls or []),
                "scheduled" if scheduled_at else "draft",
                scheduled_at,
            ),
        )
        return cur.fetchone()["id"]


def publish_post(post_id):
    """Mark a post as published."""
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            "UPDATE agent_content_posts SET status = 'published', posted_at = NOW() WHERE id = %s",
            (post_id,),
        )


def generate_post_content(agent_id, topic=None):
    """Generate a social media post in the agent's writing voice.
    Returns the generated text (does NOT save -- caller decides).
    """
    from services.agent_service import get_agent

    agent = get_agent(agent_id)
    if not agent:
        return ""

    voice = get_writing_voice(agent_id)
    name = agent.get("display_name") or agent.get("name", "")
    dept = agent.get("department", "")
    tone = voice.get("tone", "professional") if voice else "professional"
    style = voice.get("style", "") if voice else ""
    topics = voice.get("topics", []) if voice else []

    topic_hint = topic or (topics[0] if topics else f"working in {dept}")

    prompt = (
        f"Write a short social media post (2-3 sentences) as {name}, "
        f"who works in {dept}. "
        f"Tone: {tone}. "
        f"{f'Style notes: {style}. ' if style else ''}"
        f"Topic: {topic_hint}. "
        f"Write in first person. Be authentic and engaging. No hashtags."
    )

    try:
        import urllib.request

        model = agent.get("model", "qwen2.5:1.5b")
        data = json.dumps(
            {
                "model": model,
                "prompt": prompt,
                "stream": False,
                "options": {"temperature": 0.8, "num_ctx": 1024},
            }
        ).encode()
        req = urllib.request.Request(
            "http://192.168.1.200:11434/api/generate",
            data=data,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=60) as resp:
            result = json.loads(resp.read())
            return result.get("response", "").strip()
    except Exception as e:
        logger.warning("Post generation failed for agent #%d: %s", agent_id, e)
        return ""
