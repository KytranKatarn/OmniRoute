"""Synchronous knowledge-write adapter for platform routes."""

import asyncio


def store_knowledge(
    title, content, knowledge_type="conversation_memory", category="general", tags=None, importance_score=0.6
):
    """Store route-authored knowledge using the validated platform memory writer.

    Returns the knowledge ID; propagates a rejected/failed write as an error so
    callers cannot report a successful export when no knowledge was stored.
    """
    from mcp_server.tools.knowledge import store_memory_handler

    result = asyncio.run(
        store_memory_handler(
            {
                "title": title,
                "content": content,
                "knowledge_type": knowledge_type,
                "category": category,
                "tags": tags or [],
                "importance": importance_score,
            }
        )
    )
    if not result.get("success") or not result.get("memory_id"):
        raise RuntimeError(result.get("error") or "Knowledge write failed")
    return result["memory_id"]
