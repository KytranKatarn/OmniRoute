"""
A.R.C.H.I.E. Consciousness Scheduler
Unified background scheduler for all consciousness-related tasks

Tasks:
- Hourly conversation consolidation (stores to knowledge_base)
- Time tracking per user
- 6-hour improvement detection
- Daily self-reflection
- Weekly memory consolidation
"""

import sys
import logging
import threading
from datetime import datetime, timedelta
from typing import Dict, Any, Optional
from psycopg2.extras import RealDictCursor
import requests
import json
from db import get_db

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("archie.scheduler")

# Add paths for imports
sys.path.insert(0, "/app")
sys.path.insert(0, "/app/ai_bridge")
sys.path.insert(0, "/mnt/archie_brain/ai_bridge")

# Try to import learning loop modules
try:
    from ai_bridge.conversation_ingest import ingest_conversation, retrieve_similar_conversations
    from ai_bridge.auto_tagger import generate_tags_from_conversation as auto_tag_conversation

    LEARNING_AVAILABLE = True
except ImportError as e:
    logger.warning(f"Learning modules not available: {e}")
    LEARNING_AVAILABLE = False

try:
    from tools.repair_bay.services.improvement_engine import run_auto_improvement_detection
    from ai_bridge.improvement_chat import self_reflection_chat

    IMPROVEMENT_AVAILABLE = True
except ImportError as e:
    logger.warning(f"Improvement modules not available: {e}")
    IMPROVEMENT_AVAILABLE = False


def log_task_start(task_name: str) -> int:
    """Log scheduler task start, return log ID"""
    try:
        conn = get_db()
        try:
            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO consciousness_scheduler_log (task_name, status)
                VALUES (%s, 'running')
                RETURNING id
            """,
                (task_name,),
            )
            log_id = cur.fetchone()[0]
            conn.commit()
            return log_id
        finally:
            try:
                cur.close()
            except Exception:
                pass
            try:
                conn.close()
            except Exception:
                pass
    except Exception as e:
        logger.error(f"Failed to log task start: {e}")
        return 0


def log_task_complete(log_id: int, status: str, result: Dict = None, error: str = None):
    """Log scheduler task completion"""
    if log_id == 0:
        return
    try:
        conn = get_db()
        try:
            cur = conn.cursor()
            cur.execute(
                """
                UPDATE consciousness_scheduler_log
                SET completed_at = NOW(),
                    status = %s,
                    result_summary = %s,
                    error_message = %s,
                    duration_ms = EXTRACT(EPOCH FROM (NOW() - started_at)) * 1000
                WHERE id = %s
            """,
                (status, json.dumps(result) if result else None, error, log_id),
            )
            conn.commit()
        finally:
            try:
                cur.close()
            except Exception:
                pass
            try:
                conn.close()
            except Exception:
                pass
    except Exception as e:
        logger.error(f"Failed to log task completion: {e}")


def hourly_conversation_consolidation():
    """
    Consolidate conversations from the past hour into knowledge_base.
    This is the main task for long-term memory persistence.
    """
    task_name = "hourly_conversation_consolidation"
    log_id = log_task_start(task_name)

    logger.info(f"[{task_name}] Starting hourly consolidation...")

    try:
        conn = get_db()
        try:
            cur = conn.cursor(cursor_factory=RealDictCursor)

            # Get conversations from the last hour that haven't been consolidated
            hour_ago = datetime.now() - timedelta(hours=1)

            cur.execute(
                """
                SELECT
                    ac.user_id,
                    ac.conversation_id,
                    ac.message,
                    ac.response,
                    ac.model,
                    ac.created_at
                FROM ai_conversations ac
                WHERE ac.created_at >= %s
                  AND ac.created_at < NOW()
                  AND NOT EXISTS (
                      SELECT 1 FROM conversation_consolidation_log ccl
                      WHERE ccl.user_id = ac.user_id
                        AND ccl.consolidation_hour = date_trunc('hour', ac.created_at)
                  )
                ORDER BY ac.user_id, ac.created_at
            """,
                (hour_ago,),
            )

            conversations = cur.fetchall()

            if not conversations:
                logger.info(f"[{task_name}] No new conversations to consolidate")
                log_task_complete(log_id, "success", {"messages_processed": 0})
                return {"success": True, "consolidated": 0}

            # Group by user
            user_conversations = {}
            for conv in conversations:
                user_id = conv["user_id"] or 0  # Handle null user_id
                if user_id not in user_conversations:
                    user_conversations[user_id] = []
                user_conversations[user_id].append(conv)

            total_consolidated = 0
            consolidation_hour = hour_ago.replace(minute=0, second=0, microsecond=0)
            entries_to_score = []  # collect (knowledge_id, title, full_text) for async scoring

            for user_id, convs in user_conversations.items():
                # Build conversation text
                conversation_text = []
                for c in convs:
                    conversation_text.append(f"USER: {c['message']}")
                    conversation_text.append(f"A.R.C.H.I.E.: {c['response']}")

                full_text = "\n\n".join(conversation_text)

                # Generate title from first message
                first_message = convs[0]["message"][:100]
                title = f"Conversation - {consolidation_hour.strftime('%Y-%m-%d %H:00')}"
                if first_message:
                    title = f"{first_message[:50]}..."

                # Auto-tag the conversation
                tags = ["conversation", "hourly_consolidation"]
                if LEARNING_AVAILABLE:
                    try:
                        tag_result = auto_tag_conversation(full_text, first_message)
                        tags.extend(tag_result.get("tags", []))
                    except Exception as e:
                        logger.warning(f"Auto-tagging failed: {e}")

                # Store in knowledge_base
                cur.execute(
                    """
                    INSERT INTO knowledge_base (
                        knowledge_type, title, content, category, tags,
                        importance_score, source_type, source_id, metadata
                    ) VALUES (
                        'conversation_memory', %s, %s, 'Conversations', %s,
                        0.75, 'hourly_consolidation', %s, %s
                    )
                    RETURNING id
                """,
                    (
                        title,
                        full_text,
                        tags,
                        str(consolidation_hour),
                        json.dumps(
                            {
                                "user_id": user_id,
                                "message_count": len(convs),
                                "consolidated_at": datetime.now().isoformat(),
                                "hour": consolidation_hour.isoformat(),
                                "models_used": list(set(c["model"] for c in convs if c["model"])),
                            }
                        ),
                    ),
                )

                knowledge_id = cur.fetchone()["id"]
                entries_to_score.append((knowledge_id, title, full_text))

                # Log the consolidation
                cur.execute(
                    """
                    INSERT INTO conversation_consolidation_log (
                        user_id, consolidation_hour, messages_consolidated,
                        knowledge_entry_id, tags
                    ) VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (user_id, consolidation_hour) DO NOTHING
                """,
                    (
                        user_id if user_id != 0 else None,
                        consolidation_hour,
                        len(convs),
                        knowledge_id,
                        tags,
                    ),
                )

                # Update user session time
                for c in convs:
                    if c["user_id"]:
                        cur.execute(
                            "SELECT update_user_session_time(%s, %s)",
                            (c["user_id"], c["created_at"]),
                        )

                total_consolidated += len(convs)

            conn.commit()
        finally:
            try:
                cur.close()
            except Exception:
                pass
            try:
                conn.close()
            except Exception:
                pass

        # Quality gate: score each new conversation_memory entry asynchronously
        def _score_conv(eid, t, c):
            try:
                from services.quality_scoring_service import score_entry

                score_entry(eid, t, c, "conversation_memory", save_to_db=True)
            except Exception as e:
                logger.debug("Async quality scoring failed for conversation %d: %s", eid, e)

        for eid, t, c in entries_to_score:
            threading.Thread(target=_score_conv, args=(eid, t, c), daemon=True).start()

        result = {
            "users_processed": len(user_conversations),
            "messages_consolidated": total_consolidated,
            "consolidation_hour": consolidation_hour.isoformat(),
        }

        logger.info(f"[{task_name}] Completed: {total_consolidated} messages consolidated")
        log_task_complete(log_id, "success", result)

        return {"success": True, "consolidated": total_consolidated, **result}

    except Exception as e:
        logger.error(f"[{task_name}] Error: {e}")
        log_task_complete(log_id, "failed", error=str(e))
        return {"success": False, "error": str(e)}


def improvement_detection():
    """Run automatic improvement detection (every 6 hours)"""
    task_name = "improvement_detection"
    log_id = log_task_start(task_name)

    logger.info(f"[{task_name}] Starting improvement detection...")

    if not IMPROVEMENT_AVAILABLE:
        logger.warning(f"[{task_name}] Improvement modules not available")
        log_task_complete(log_id, "skipped", {"reason": "modules_unavailable"})
        return {"success": False, "error": "Improvement modules not available"}

    try:
        summary = run_auto_improvement_detection()

        result = {
            "opportunities_detected": summary.get("opportunities_detected", 0),
            "proposals_created": summary.get("proposals_created", 0),
            "breakdown": summary.get("breakdown", {}),
        }

        logger.info(f"[{task_name}] Completed: {result['proposals_created']} proposals created")
        log_task_complete(log_id, "success", result)

        return {"success": True, **result}

    except Exception as e:
        logger.error(f"[{task_name}] Error: {e}")
        log_task_complete(log_id, "failed", error=str(e))
        return {"success": False, "error": str(e)}


def daily_self_reflection():
    """Run daily self-reflection (at midnight)"""
    task_name = "daily_self_reflection"
    log_id = log_task_start(task_name)

    logger.info(f"[{task_name}] Starting daily self-reflection...")

    if not IMPROVEMENT_AVAILABLE:
        logger.warning(f"[{task_name}] Improvement modules not available")
        log_task_complete(log_id, "skipped", {"reason": "modules_unavailable"})
        return {"success": False, "error": "Improvement modules not available"}

    try:
        result = self_reflection_chat(topic="overall performance")

        if result.get("success"):
            summary = {
                "personality_summary": result.get("personality", {}).get("personality_summary", ""),
                "opportunities_count": result.get("opportunities_count", 0),
                "reflection_length": len(result.get("reflection", "")),
            }
            logger.info(f"[{task_name}] Completed: {summary['opportunities_count']} opportunities found")
            log_task_complete(log_id, "success", summary)
            return {"success": True, **summary}
        else:
            error = result.get("error", "Unknown error")
            log_task_complete(log_id, "failed", error=error)
            return {"success": False, "error": error}

    except Exception as e:
        logger.error(f"[{task_name}] Error: {e}")
        log_task_complete(log_id, "failed", error=str(e))
        return {"success": False, "error": str(e)}


def weekly_memory_consolidation():
    """Consolidate and clean up old memories (weekly)"""
    task_name = "weekly_memory_consolidation"
    log_id = log_task_start(task_name)

    logger.info(f"[{task_name}] Starting weekly memory consolidation...")

    try:
        conn = get_db()
        try:
            cur = conn.cursor()

            # Apply memory decay to old, low-importance memories
            cur.execute(
                """
                UPDATE knowledge_base
                SET importance_score = importance_score * 0.95
                WHERE created_at < NOW() - INTERVAL '30 days'
                  AND importance_score > 0.3
                  AND access_count < 3
            """
            )
            decayed_count = cur.rowcount

            # Mark very old, never-accessed, low-importance entries for review
            cur.execute(
                """
                UPDATE knowledge_base
                SET memory_metadata = COALESCE(memory_metadata, '{}'::jsonb) || '{"review_suggested": true}'::jsonb
                WHERE created_at < NOW() - INTERVAL '180 days'
                  AND importance_score < 0.3
                  AND access_count = 0
                  AND (memory_metadata->>'review_suggested') IS NULL
            """
            )
            review_count = cur.rowcount

            conn.commit()
        finally:
            try:
                cur.close()
            except Exception:
                pass
            try:
                conn.close()
            except Exception:
                pass

        result = {"memories_decayed": decayed_count, "flagged_for_review": review_count}

        logger.info(f"[{task_name}] Completed: {decayed_count} decayed, {review_count} flagged")
        log_task_complete(log_id, "success", result)

        return {"success": True, **result}

    except Exception as e:
        logger.error(f"[{task_name}] Error: {e}")
        log_task_complete(log_id, "failed", error=str(e))
        return {"success": False, "error": str(e)}


def get_scheduler_status() -> Dict[str, Any]:
    """Get current scheduler status and recent task runs"""
    try:
        conn = get_db()
        try:
            cur = conn.cursor(cursor_factory=RealDictCursor)

            # Get recent task runs
            cur.execute(
                """
                SELECT task_name, started_at, completed_at, status,
                       result_summary, error_message, duration_ms
                FROM consciousness_scheduler_log
                ORDER BY started_at DESC
                LIMIT 20
            """
            )
            recent_tasks = cur.fetchall()

            # Get task summaries
            cur.execute(
                """
                SELECT
                    task_name,
                    COUNT(*) as total_runs,
                    COUNT(*) FILTER (WHERE status = 'success') as successful,
                    COUNT(*) FILTER (WHERE status = 'failed') as failed,
                    AVG(duration_ms) as avg_duration_ms,
                    MAX(started_at) as last_run
                FROM consciousness_scheduler_log
                WHERE started_at > NOW() - INTERVAL '7 days'
                GROUP BY task_name
            """
            )
            task_summaries = cur.fetchall()
        finally:
            try:
                cur.close()
            except Exception:
                pass
            try:
                conn.close()
            except Exception:
                pass

        return {
            "success": True,
            "recent_tasks": [dict(t) for t in recent_tasks],
            "task_summaries": [dict(t) for t in task_summaries],
            "modules_available": {
                "learning": LEARNING_AVAILABLE,
                "improvement": IMPROVEMENT_AVAILABLE,
            },
        }

    except Exception as e:
        logger.error(f"Failed to get scheduler status: {e}")
        return {"success": False, "error": str(e)}


def run_task_now(task_name: str) -> Dict[str, Any]:
    """Manually trigger a scheduled task"""
    tasks = {
        "hourly_conversation_consolidation": hourly_conversation_consolidation,
        "improvement_detection": improvement_detection,
        "daily_self_reflection": daily_self_reflection,
        "weekly_memory_consolidation": weekly_memory_consolidation,
    }

    if task_name not in tasks:
        return {"success": False, "error": f"Unknown task: {task_name}"}

    logger.info(f"Manual trigger: {task_name}")
    return tasks[task_name]()


# For standalone execution (testing)
if __name__ == "__main__":
    print("Testing consciousness scheduler...")

    # Test hourly consolidation
    print("\n1. Testing hourly consolidation:")
    result = hourly_conversation_consolidation()
    print(f"   Result: {result}")

    # Test scheduler status
    print("\n2. Testing scheduler status:")
    status = get_scheduler_status()
    print(f"   Recent tasks: {len(status.get('recent_tasks', []))}")
    print(f"   Modules: {status.get('modules_available', {})}")

    print("\nScheduler test complete!")
