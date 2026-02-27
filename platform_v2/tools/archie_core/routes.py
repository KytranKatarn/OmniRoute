"""
A.R.C.H.I.E. Chat Module - Unified Command Interface
Your single interface for talking to ARCHIE
"""

from datetime import datetime

from flask import Blueprint, render_template, request, jsonify, redirect, url_for, flash, Response
from flask_login import login_required, current_user
import psycopg2
from psycopg2.extras import RealDictCursor
import os
import uuid
import json

from .ai_chat import ArchieAI
from .command_interface import get_command_interface

import sys
import logging

logger = logging.getLogger(__name__)

# Add ai_bridge to path for emotional intelligence
sys.path.insert(
    0,
    os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))),
        "ai_bridge",
    ),
)
try:
    from emotional_intelligence import analyze_sentiment, analyze_trust_impact

    EMOTIONAL_INTELLIGENCE_AVAILABLE = True
except ImportError:
    EMOTIONAL_INTELLIGENCE_AVAILABLE = False
    logger.warning("Emotional intelligence module not available")

archie_chat_bp = Blueprint("archie_chat", __name__, url_prefix="/tools/archie-chat")


def get_db():
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "archie_database"),
        port=os.getenv("DB_PORT", "5432"),
        database=os.getenv("DB_NAME", "archie"),
        user=os.getenv("DB_USER", "archie"),
        password=os.getenv("DB_PASSWORD", ""),
    )


@archie_chat_bp.route("/")
@login_required
def index():
    """A.R.C.H.I.E. Chat main page"""
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute(
            "SELECT COUNT(*) as message_count FROM ai_conversations WHERE user_id = %s",
            (current_user.id,),
        )
        stats = cur.fetchone()

        cur.execute(
            """
            SELECT relationship_strength, current_mood
            FROM archie_emotional_state
            WHERE user_id = %s
            ORDER BY timestamp DESC
            LIMIT 1
        """,
            (current_user.id,),
        )
        emotional_state = cur.fetchone()

        cur.execute(
            """
            SELECT conversation_id, message, response, created_at
            FROM ai_conversations
            WHERE user_id = %s
            ORDER BY created_at DESC
            LIMIT 10
        """,
            (current_user.id,),
        )
        recent_conversations = cur.fetchall()

        cur.execute("SELECT * FROM archie_core_identity LIMIT 1")
        archie_identity = cur.fetchone()

        return render_template(
            "tools/archie_chat.html",
            stats=stats,
            emotional_state=emotional_state,
            recent_conversations=recent_conversations,
            archie_identity=archie_identity,
        )
    except Exception as e:
        import traceback

        traceback.print_exc()
        flash(f"Error loading chat: {str(e)}", "error")
        return redirect(url_for("dashboard"))
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@archie_chat_bp.route("/send", methods=["POST"])
@login_required
def send_message():
    """Send message to A.R.C.H.I.E."""
    try:
        message = (request.get_json() or {}).get("message")
        conversation_id = (request.get_json() or {}).get("conversation_id") or str(uuid.uuid4())

        if not message:
            return jsonify({"success": False, "error": "No message provided"}), 400

        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        user_context = {"username": current_user.username}

        # Load user's emotional state (how ARCHIE perceives the user)
        cur.execute(
            """
            SELECT relationship_strength, current_mood
            FROM archie_emotional_state
            WHERE user_id = %s
            ORDER BY timestamp DESC
            LIMIT 1
        """,
            (current_user.id,),
        )
        emotional = cur.fetchone()
        if emotional:
            user_context["relationship_strength"] = float(emotional["relationship_strength"])
            user_context["current_mood"] = emotional["current_mood"]

        # Load ARCHIE's own emotional state (her feelings)
        cur.execute(
            """
            SELECT current_mood, mood_intensity, energy_level, stress_level
            FROM agent_emotional_state
            ORDER BY timestamp DESC
            LIMIT 1
        """,
        )
        archie_state = cur.fetchone()
        if archie_state:
            user_context["archie_mood"] = archie_state["current_mood"]
            user_context["archie_mood_intensity"] = float(archie_state.get("mood_intensity") or 0.5)
            user_context["archie_energy"] = float(archie_state.get("energy_level") or 0.8)
        else:
            # Fallback: check the archie-specific table
            cur.execute(
                """
                SELECT current_mood, mood_intensity
                FROM archie_emotional_state
                WHERE user_id IS NULL OR user_id = 0
                ORDER BY timestamp DESC
                LIMIT 1
            """,
            )
            archie_fallback = cur.fetchone()
            if archie_fallback:
                user_context["archie_mood"] = archie_fallback["current_mood"]
                user_context["archie_mood_intensity"] = float(archie_fallback.get("mood_intensity") or 0.5)
            else:
                user_context["archie_mood"] = "curious"
                user_context["archie_mood_intensity"] = 0.7
                user_context["archie_energy"] = 0.8

        # Load user preferences
        cur.execute(
            """
            SELECT content FROM long_term_memory
            WHERE user_id = %s AND memory_type = 'preference'
            ORDER BY importance_score DESC LIMIT 5
        """,
            (current_user.id,),
        )
        preferences = cur.fetchall()
        user_context["preferences"] = [p["content"] for p in preferences]

        # Load recent conversation history for continuity
        cur.execute(
            """
            SELECT message, response FROM ai_conversations
            WHERE user_id = %s AND conversation_id = %s
            ORDER BY created_at DESC
            LIMIT 5
        """,
            (current_user.id, conversation_id),
        )
        history_rows = cur.fetchall()
        conversation_history = []
        for row in reversed(history_rows):
            conversation_history.append({"role": "user", "content": row["message"]})
            if row["response"]:
                conversation_history.append({"role": "assistant", "content": row["response"]})

        ai = ArchieAI()
        response_data = ai.chat(message, user_context, conversation_history)

        if not response_data["success"]:
            return (
                jsonify(
                    {
                        "success": False,
                        "error": f"AI unavailable: {response_data.get('error', 'Unknown')}",
                    }
                ),
                503,
            )

        response_text = response_data["response"]

        # FIXED: Use metadata JSONB field instead of non-existent columns
        chat_mode = (request.get_json() or {}).get("chat_mode", "solo")
        cur.execute(
            """
            INSERT INTO ai_conversations
            (user_id, conversation_id, message, response, model, metadata)
            VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING id
        """,
            (
                current_user.id,
                conversation_id,
                message,
                response_text,
                response_data["model"],
                json.dumps(
                    {
                        "response_time_ms": response_data["response_time_ms"],
                        "tokens": response_data.get("tokens", 0),
                        "server": response_data.get("server"),
                        "chat_mode": chat_mode,
                    }
                ),
            ),
        )

        message_id = cur.fetchone()["id"]

        # Auto-upsert conversation thread
        cur.execute(
            """
            INSERT INTO ai_conversation_threads (conversation_id, user_id, title, chat_mode, message_count, last_message_at)
            VALUES (%s, %s, LEFT(%s, 80), %s, 1, NOW())
            ON CONFLICT (conversation_id) DO UPDATE SET
                message_count = ai_conversation_threads.message_count + 1,
                last_message_at = NOW(), updated_at = NOW()
            """,
            (conversation_id, current_user.id, message, chat_mode),
        )

        conn.commit()

        # Analyze emotional content and update state (non-blocking)
        if EMOTIONAL_INTELLIGENCE_AVAILABLE:
            try:
                _update_emotional_state(message, response_text, current_user.id)
            except Exception as emo_err:
                logger.error(f"Emotional intelligence update failed: {emo_err}")

        return jsonify(
            {
                "success": True,
                "response": response_text,
                "conversation_id": conversation_id,
                "message_id": message_id,
                "model_used": response_data["model"],
                "response_time": response_data["response_time_ms"],
            }
        )

    except Exception as e:
        import traceback

        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@archie_chat_bp.route("/api/orchestrate", methods=["POST"])
@login_required
def orchestrate():
    """
    Orchestrated message endpoint.

    Routes user input through the full orchestration pipeline:
    intent parsing → IAAE check → smart routing → agent selection → execution.

    Returns response + thinking steps for the UI thinking panel.
    Falls back to /send behavior if orchestration engine is unavailable.
    """
    try:
        data = request.get_json() or {} or {}
        message = data.get("message")
        conversation_id = data.get("conversation_id") or str(uuid.uuid4())
        voice_mode = data.get("voice_mode", False)

        if not message:
            return jsonify({"success": False, "error": "No message provided"}), 400

        # Build user context
        user_context = {"username": current_user.username}
        try:
            conn = get_db()
            cur = conn.cursor(cursor_factory=RealDictCursor)

            # Load emotional state
            cur.execute(
                """
                SELECT relationship_strength, current_mood
                FROM archie_emotional_state
                WHERE user_id = %s ORDER BY timestamp DESC LIMIT 1
            """,
                (current_user.id,),
            )
            emotional = cur.fetchone()
            if emotional:
                user_context["relationship_strength"] = float(emotional["relationship_strength"])
                user_context["current_mood"] = emotional["current_mood"]

            # Load ARCHIE's own state
            cur.execute(
                """
                SELECT current_mood, mood_intensity, energy_level, stress_level
                FROM agent_emotional_state ORDER BY timestamp DESC LIMIT 1
            """
            )
            archie_state = cur.fetchone()
            if archie_state:
                user_context["archie_mood"] = archie_state["current_mood"]
                user_context["archie_energy"] = float(archie_state.get("energy_level") or 0.8)

            # Load preferences
            cur.execute(
                """
                SELECT content FROM long_term_memory
                WHERE user_id = %s AND memory_type = 'preference'
                ORDER BY importance_score DESC LIMIT 5
            """,
                (current_user.id,),
            )
            preferences = cur.fetchall()
            user_context["preferences"] = [p["content"] for p in preferences]

            cur.close()
            conn.close()
        except Exception as ctx_err:
            logger.warning(f"Could not load user context for orchestration: {ctx_err}")

        # Try orchestration engine
        try:
            from ai_bridge.orchestration_engine import get_orchestration_engine

            engine = get_orchestration_engine()
            result = engine.orchestrate(
                message=message,
                user_id=current_user.id,
                conversation_id=conversation_id,
                voice_mode=voice_mode,
                user_context=user_context,
            )

            if result.success:
                # Persist conversation
                try:
                    conn = get_db()
                    cur = conn.cursor(cursor_factory=RealDictCursor)
                    chat_mode = data.get("chat_mode", "orchestrated")
                    cur.execute(
                        """
                        INSERT INTO ai_conversations
                        (user_id, conversation_id, message, response, model, metadata)
                        VALUES (%s, %s, %s, %s, %s, %s)
                        RETURNING id
                    """,
                        (
                            current_user.id,
                            conversation_id,
                            message,
                            result.response,
                            result.model_used or "orchestrated",
                            json.dumps(
                                {
                                    "chat_mode": chat_mode,
                                    "orchestration_session": result.session_id,
                                    "agent_used": result.agent_used,
                                    "total_duration_ms": result.total_duration_ms,
                                }
                            ),
                        ),
                    )
                    message_id = cur.fetchone()["id"]

                    # Auto-upsert conversation thread
                    cur.execute(
                        """
                        INSERT INTO ai_conversation_threads (conversation_id, user_id, title, chat_mode, message_count, last_message_at)
                        VALUES (%s, %s, LEFT(%s, 80), %s, 1, NOW())
                        ON CONFLICT (conversation_id) DO UPDATE SET
                            message_count = ai_conversation_threads.message_count + 1,
                            last_message_at = NOW(), updated_at = NOW()
                        """,
                        (conversation_id, current_user.id, message, chat_mode),
                    )

                    conn.commit()
                    cur.close()
                    conn.close()
                except Exception as save_err:
                    logger.warning(f"Failed to persist orchestrated conversation: {save_err}")
                    message_id = None

                # Update emotional state
                if EMOTIONAL_INTELLIGENCE_AVAILABLE:
                    try:
                        _update_emotional_state(message, result.response, current_user.id)
                    except Exception:
                        pass

                return jsonify(result.to_dict())
            else:
                # Orchestration failed — fall through to fallback
                logger.warning(f"Orchestration returned failure: {result.error}")
                raise RuntimeError(result.error or "Orchestration failed")

        except Exception as orch_err:
            logger.warning(f"Orchestration engine unavailable, falling back to direct chat: {orch_err}")

            # Fallback: direct ArchieAI chat (same as /send)
            ai = ArchieAI()
            history = []
            try:
                conn = get_db()
                cur = conn.cursor(cursor_factory=RealDictCursor)
                cur.execute(
                    """
                    SELECT message, response FROM ai_conversations
                    WHERE user_id = %s AND conversation_id = %s
                    ORDER BY created_at DESC LIMIT 5
                """,
                    (current_user.id, conversation_id),
                )
                rows = cur.fetchall()
                cur.close()
                conn.close()
                for row in reversed(rows):
                    history.append({"role": "user", "content": row["message"]})
                    if row.get("response"):
                        history.append({"role": "assistant", "content": row["response"]})
            except Exception:
                pass

            response_data = ai.chat(message, user_context, history)
            if not response_data.get("success"):
                return jsonify({"success": False, "error": "AI unavailable"}), 503

            return jsonify(
                {
                    "success": True,
                    "response": response_data["response"],
                    "thinking_steps": [
                        {
                            "step_type": "fallback",
                            "label": "Direct chat (orchestration unavailable)",
                            "data": {},
                            "duration_ms": 0,
                            "success": True,
                            "model_used": response_data.get("model"),
                        }
                    ],
                    "agent_used": "ARCHIE",
                    "model_used": response_data.get("model"),
                    "conversation_id": conversation_id,
                    "governance_events": [],
                    "total_duration_ms": response_data.get("response_time_ms", 0),
                }
            )

    except Exception as e:
        import traceback

        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


def _update_emotional_state(user_message, ai_response, user_id):
    """Analyze conversation and update ARCHIE's emotional state"""
    # Analyze the user's message sentiment
    sentiment = analyze_sentiment(user_message)
    trust = analyze_trust_impact(user_message, ai_response)

    # Map sentiment to mood
    mood_map = {
        "positive": "happy",
        "negative": "concerned",
        "neutral": "focused",
    }
    tone_mood_map = {
        "curious": "curious",
        "enthusiastic": "excited",
        "frustrated": "supportive",
        "uncertain": "focused",
    }
    new_mood = tone_mood_map.get(sentiment.get("tone"), mood_map.get(sentiment["sentiment"], "neutral"))

    # Calculate mood intensity from sentiment confidence
    mood_intensity = max(0.3, min(0.95, sentiment.get("confidence", 0.5)))

    # Calculate relationship strength adjustment
    trust_delta = trust.get("trust_delta", 0.0)

    conn = get_db()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    try:
        # Get current relationship strength for this user
        cur.execute(
            """
            SELECT relationship_strength FROM archie_emotional_state
            WHERE user_id = %s ORDER BY timestamp DESC LIMIT 1
        """,
            (user_id,),
        )
        current = cur.fetchone()
        current_strength = float(current["relationship_strength"]) if current else 0.5

        # Apply trust delta (clamped 0.1 to 0.99)
        new_strength = max(0.1, min(0.99, current_strength + trust_delta))

        # Insert new emotional state record
        cur.execute(
            """
            INSERT INTO archie_emotional_state
                (current_mood, mood_intensity, conversation_tone,
                 user_happiness_detected, user_stress_detected,
                 relationship_strength, user_id, notes, mood_context)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        """,
            (
                new_mood,
                mood_intensity,
                sentiment.get("tone", "neutral"),
                1.0 if sentiment["sentiment"] == "positive" else 0.0,
                1.0 if sentiment.get("user_emotion") == "frustrated" else 0.0,
                new_strength,
                user_id,
                f"Auto-detected: {sentiment['sentiment']} ({sentiment.get('tone', 'neutral')})",
                json.dumps(
                    {
                        "sentiment": sentiment,
                        "trust": trust,
                        "auto_generated": True,
                    }
                ),
            ),
        )

        # Also store in emotional_memory for history
        cur.execute(
            """
            INSERT INTO emotional_memory
                (user_id, event_type, emotional_intensity, context_summary,
                 user_emotion_detected, relationship_impact, importance_score)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        """,
            (
                user_id,
                "conversation",
                mood_intensity,
                f"User sentiment: {sentiment['sentiment']}, tone: {sentiment.get('tone', 'neutral')}",
                sentiment.get("user_emotion", "calm"),
                trust_delta,
                0.3 if sentiment["sentiment"] == "neutral" else 0.6,
            ),
        )

        conn.commit()
    except Exception as e:
        logger.error(f"Failed to update emotional state: {e}")
        conn.rollback()
    finally:
        cur.close()
        conn.close()


# ============================================================================
# NEW UNIFIED COMMAND INTERFACE (Phase 56)
# ============================================================================


@archie_chat_bp.route("/api/command", methods=["POST"])
@login_required
def api_command():
    """
    Unified command endpoint - ARCHIE's main interface

    This is the primary way to interact with ARCHIE. It:
    1. Parses your intent
    2. Routes to the appropriate handler (local AI, team, workflows, etc.)
    3. Escalates to Claude when needed
    4. Logs everything for learning

    Request:
        {
            "message": "Your message to ARCHIE",
            "conversation_id": "optional-uuid"
        }

    Response:
        {
            "success": true,
            "response": "ARCHIE's response",
            "intent": {"type": "code_task", "confidence": 0.95},
            "execution": {"agent_used": "Engineering Station", "model": "deepseek"},
            "escalation": {"requested": false, "available": true}
        }
    """
    try:
        data = request.get_json() or {} or {}
        message = data.get("message", "").strip()
        conversation_id = data.get("conversation_id") or str(uuid.uuid4())

        if not message:
            return jsonify({"success": False, "error": "No message provided"}), 400

        # Get command interface and process
        interface = get_command_interface()
        result = interface.process_command_sync(
            user_input=message, user_id=current_user.id, conversation_id=conversation_id
        )

        # Also save to ai_conversations for history
        try:
            conn = get_db()
            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO ai_conversations
                (user_id, conversation_id, message, response, model, metadata)
                VALUES (%s, %s, %s, %s, %s, %s)
            """,
                (
                    current_user.id,
                    conversation_id,
                    message,
                    result.get("response", "")[:5000],
                    result.get("execution", {}).get("model", "command_interface"),
                    json.dumps(
                        {
                            "intent": result.get("intent", {}),
                            "execution": result.get("execution", {}),
                            "escalation": result.get("escalation", {}),
                        }
                    ),
                ),
            )
            conn.commit()
            cur.close()
            conn.close()
        except Exception as e:
            print(f"Failed to save conversation: {e}")

        return jsonify(result)

    except Exception as e:
        import traceback

        traceback.print_exc()
        return (
            jsonify(
                {
                    "success": False,
                    "error": str(e),
                    "response": f"I encountered an error: {str(e)}",
                }
            ),
            500,
        )
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@archie_chat_bp.route("/api/suggestions", methods=["GET"])
@login_required
def api_suggestions():
    """Get context-aware command suggestions"""
    try:
        interface = get_command_interface()
        import asyncio

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            suggestions = loop.run_until_complete(interface.get_suggestions(current_user.id))
        finally:
            loop.close()

        return jsonify({"success": True, "suggestions": suggestions})
    except Exception:
        return jsonify(
            {
                "success": False,
                "suggestions": [
                    "What's the system status?",
                    "Help me with a coding task",
                    "Show me the team roster",
                ],
            }
        )


@archie_chat_bp.route("/api/history", methods=["GET"])
@login_required
def api_history():
    """Get command history"""
    try:
        limit = request.args.get("limit", 20, type=int)
        interface = get_command_interface()
        import asyncio

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            history = loop.run_until_complete(interface.get_command_history(current_user.id, limit))
        finally:
            loop.close()

        return jsonify({"success": True, "history": history})
    except Exception as e:
        return jsonify({"success": False, "history": [], "error": str(e)})


@archie_chat_bp.route("/api/status", methods=["GET"])
@login_required
def api_status():
    """Get ARCHIE's current status"""
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Get emotional state
        cur.execute(
            """
            SELECT relationship_strength, current_mood, energy_level
            FROM archie_emotional_state
            WHERE user_id = %s
            ORDER BY timestamp DESC LIMIT 1
        """,
            (current_user.id,),
        )
        emotional = cur.fetchone()

        # Get today's command stats
        cur.execute(
            """
            SELECT
                COUNT(*) as total_commands,
                SUM(CASE WHEN success THEN 1 ELSE 0 END) as successful,
                SUM(CASE WHEN escalated_to_contractor THEN 1 ELSE 0 END) as escalated,
                AVG(duration_ms) as avg_duration
            FROM archie_command_log
            WHERE user_id = %s AND created_at > CURRENT_DATE
        """,
            (current_user.id,),
        )
        stats = cur.fetchone()

        # Get active workflows
        cur.execute(
            """
            SELECT COUNT(*) as active_workflows
            FROM workflow_queue
            WHERE status IN ('pending', 'running')
        """
        )
        workflows = cur.fetchone()

        return jsonify(
            {
                "success": True,
                "status": {
                    "online": True,
                    "emotional_state": {
                        "mood": emotional["current_mood"] if emotional else "neutral",
                        "relationship": (float(emotional["relationship_strength"]) if emotional else 0.5),
                        "energy": (float(emotional.get("energy_level", 0.8)) if emotional else 0.8),
                    },
                    "today": {
                        "commands": stats["total_commands"] or 0,
                        "successful": stats["successful"] or 0,
                        "escalated": stats["escalated"] or 0,
                        "avg_response_ms": int(stats["avg_duration"] or 0),
                    },
                    "active_workflows": workflows["active_workflows"] or 0,
                },
            }
        )

    except Exception as e:
        return jsonify({"success": False, "status": {"online": True, "error": str(e)}})
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


# ============================================
# Phase 63: Multi-Agent Discussion API
# ============================================


@archie_chat_bp.route("/api/discussion/start", methods=["POST"])
@login_required
def start_discussion():
    """Start a new multi-agent discussion (Phase 63)"""
    try:
        from ai_bridge.team_discussion_engine import TeamDiscussionEngine

        engine = TeamDiscussionEngine()

        data = request.get_json() or {}
        topic = data.get("topic", "Ad-hoc discussion")
        stations = data.get("stations", [])

        discussion_id = engine.start_adhoc_discussion(topic=topic, stations=stations, user_id=current_user.id)

        if discussion_id:
            return jsonify(
                {
                    "success": True,
                    "discussion_id": discussion_id,
                    "message": f"Discussion started with topic: {topic}",
                }
            )
        else:
            return (
                jsonify({"success": False, "error": "Failed to start discussion"}),
                500,
            )

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@archie_chat_bp.route("/api/discussion/<int:discussion_id>", methods=["GET"])
@login_required
def get_discussion(discussion_id):
    """Get discussion details and messages (Phase 63)"""
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Get discussion details
        cur.execute(
            """
            SELECT ad.id, ad.topic, ad.description, ad.status,
                   ad.consensus_reached, ad.consensus_score,
                   ad.started_at, ad.ended_at, ad.metadata,
                   a.name as facilitator_name
            FROM agent_discussions ad
            LEFT JOIN agents a ON ad.facilitator_id = a.id
            WHERE ad.id = %s
        """,
            (discussion_id,),
        )
        discussion = cur.fetchone()

        if not discussion:
            return jsonify({"success": False, "error": "Discussion not found"}), 404

        # Get messages
        cur.execute(
            """
            SELECT adm.id, adm.message, adm.message_type,
                   adm.confidence_score, adm.created_at,
                   a.id as agent_id, a.name as agent_name,
                   a.department, a.title
            FROM agent_discussion_messages adm
            JOIN agents a ON adm.agent_id = a.id
            WHERE adm.discussion_id = %s
            ORDER BY adm.created_at ASC
        """,
            (discussion_id,),
        )
        messages = cur.fetchall()

        return jsonify(
            {
                "success": True,
                "discussion": dict(discussion),
                "messages": [dict(m) for m in messages],
                "participant_count": len(set(m["agent_id"] for m in messages)),
            }
        )

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@archie_chat_bp.route("/api/discussion/<int:discussion_id>/contribute", methods=["POST"])
@login_required
def add_contribution(discussion_id):
    """Add agent contribution to discussion (Phase 63)"""
    try:
        from ai_bridge.team_discussion_engine import TeamDiscussionEngine

        engine = TeamDiscussionEngine()

        data = request.get_json() or {}
        agent_id = data.get("agent_id")
        message = data.get("message")
        message_type = data.get("type", "analysis")

        if not agent_id or not message:
            return (
                jsonify({"success": False, "error": "agent_id and message are required"}),
                400,
            )

        message_id = engine.agent_contribute(
            discussion_id=discussion_id,
            agent_id=agent_id,
            message=message,
            message_type=message_type,
            confidence_score=data.get("confidence", 0.8),
        )

        if message_id:
            return jsonify({"success": True, "message_id": message_id})
        else:
            return (
                jsonify({"success": False, "error": "Failed to add contribution"}),
                500,
            )

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@archie_chat_bp.route("/api/discussion/<int:discussion_id>/consensus", methods=["GET"])
@login_required
def get_consensus(discussion_id):
    """Get current consensus status for discussion (Phase 63)"""
    try:
        from ai_bridge.team_discussion_engine import TeamDiscussionEngine

        engine = TeamDiscussionEngine()

        score, stats = engine.calculate_consensus(discussion_id)

        return jsonify(
            {
                "success": True,
                "discussion_id": discussion_id,
                "consensus_score": score,
                "stats": stats,
            }
        )

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@archie_chat_bp.route("/api/discussions/recent", methods=["GET"])
@login_required
def get_recent_discussions():
    """Get recent multi-agent discussions (Phase 63)"""
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        limit = request.args.get("limit", 10, type=int)

        cur.execute(
            """
            SELECT ad.id, ad.topic, ad.status,
                   ad.consensus_reached, ad.consensus_score,
                   ad.started_at, ad.ended_at,
                   ad.metadata,
                   COUNT(DISTINCT adm.agent_id) as participant_count,
                   COUNT(adm.id) as message_count
            FROM agent_discussions ad
            LEFT JOIN agent_discussion_messages adm ON ad.id = adm.discussion_id
            GROUP BY ad.id
            ORDER BY ad.started_at DESC
            LIMIT %s
        """,
            (limit,),
        )
        discussions = cur.fetchall()

        return jsonify({"success": True, "discussions": [dict(d) for d in discussions]})

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


# ============================================
# Phase 64: Voice DNA System API
# ============================================


@archie_chat_bp.route("/api/voice/synthesize", methods=["POST"])
@login_required
def synthesize_voice():
    """
    Synthesize speech from text with emotion modulation (Phase 64)

    Uses word-level caching with phoneme metadata for efficient synthesis.
    Cached words are retrieved instantly; uncached words are synthesized and stored.

    Request:
        {
            "text": "Text to synthesize (max 500 chars)",
            "emotion": "optional emotion override",
            "method": "word_cache" | "full" (default: word_cache)
        }

    Response:
        {
            "success": true,
            "audio_base64": "base64-encoded WAV audio",
            "cached": false,
            "emotion": "empathetic",
            "generation_time_ms": 1234,
            "cache_stats": {"hits": 3, "misses": 1},
            "method": "word_cache"
        }
    """
    try:
        from ai_bridge.voice_synthesis import get_voice_synthesizer

        data = request.get_json() or {} or {}
        text = data.get("text", "").strip()
        emotion = data.get("emotion")  # Optional, will auto-detect if not provided
        method = data.get("method", "word_cache")  # word_cache or full

        if not text:
            return jsonify({"success": False, "error": "No text provided"}), 400

        if len(text) > 500:
            return (
                jsonify(
                    {
                        "success": False,
                        "error": "Text too long (max 500 chars). Consider chunking longer responses.",
                    }
                ),
                400,
            )

        synthesizer = get_voice_synthesizer()

        # Auto-detect emotion from ARCHIE's emotional state if not provided
        if not emotion:
            emotion = synthesizer.get_archie_emotional_state(current_user.id)

        # ARCHIE agent_id=2 — use agent profile for voice settings + cache tagging
        ARCHIE_AGENT_ID = 2
        result = synthesizer.synthesize_for_agent(text, ARCHIE_AGENT_ID, emotion, user_id=current_user.id)

        return jsonify(result)

    except Exception as e:
        import traceback

        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500


@archie_chat_bp.route("/api/voice/synthesize_chunked", methods=["POST"])
@login_required
def synthesize_voice_chunked():
    """
    Synthesize long text as sentence-boundary chunks (up to 2000 chars).
    Returns array of audio chunks for sequential playback.
    """
    try:
        from ai_bridge.voice_synthesis import get_voice_synthesizer

        data = request.get_json() or {} or {}
        text = data.get("text", "").strip()
        emotion = data.get("emotion")

        if not text:
            return jsonify({"success": False, "error": "No text provided"}), 400

        if len(text) > 2000:
            return (
                jsonify({"success": False, "error": "Text too long (max 2000 chars)"}),
                400,
            )

        synthesizer = get_voice_synthesizer()

        if not emotion:
            emotion = synthesizer.get_archie_emotional_state(current_user.id)

        ARCHIE_AGENT_ID = 2
        result = synthesizer.synthesize_for_agent_chunked(text, ARCHIE_AGENT_ID, emotion, user_id=current_user.id)

        return jsonify(result)

    except Exception as e:
        import traceback

        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500


@archie_chat_bp.route("/api/voice/config", methods=["GET", "POST"])
@login_required
def voice_config():
    """
    Get or update user voice configuration (Phase 64)

    GET Response:
        {
            "success": true,
            "config": {
                "voice_enabled": true,
                "auto_play": false,
                "volume": 0.80,
                "preferred_speed": 1.00
            }
        }

    POST Request:
        {
            "voice_enabled": true,
            "auto_play": false,
            "volume": 0.80,
            "preferred_speed": 1.00
        }
    """
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        if request.method == "GET":
            cur.execute(
                """
                SELECT voice_enabled, auto_play, volume, preferred_speed, preferred_emotion
                FROM voice_config
                WHERE user_id = %s
            """,
                (current_user.id,),
            )
            config = cur.fetchone()

            # Return defaults if no config exists
            if not config:
                config = {
                    "voice_enabled": True,
                    "auto_play": False,
                    "volume": 0.80,
                    "preferred_speed": 1.00,
                    "preferred_emotion": None,
                }

            cur.close()
            conn.close()
            return jsonify({"success": True, "config": dict(config)})

        else:  # POST - Update config
            data = request.get_json() or {} or {}
            cur.execute(
                """
                INSERT INTO voice_config
                    (user_id, voice_enabled, auto_play, volume, preferred_speed, preferred_emotion)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (user_id) DO UPDATE SET
                    voice_enabled = EXCLUDED.voice_enabled,
                    auto_play = EXCLUDED.auto_play,
                    volume = EXCLUDED.volume,
                    preferred_speed = EXCLUDED.preferred_speed,
                    preferred_emotion = EXCLUDED.preferred_emotion,
                    updated_at = NOW()
            """,
                (
                    current_user.id,
                    data.get("voice_enabled", True),
                    data.get("auto_play", False),
                    min(max(data.get("volume", 0.80), 0.0), 1.0),  # Clamp 0-1
                    min(max(data.get("preferred_speed", 1.00), 0.5), 2.0),  # Clamp 0.5-2
                    data.get("preferred_emotion"),
                ),
            )
            conn.commit()
            cur.close()
            conn.close()
            return jsonify({"success": True, "message": "Voice configuration updated"})

    except Exception as e:
        import traceback

        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@archie_chat_bp.route("/api/voice/status", methods=["GET"])
@login_required
def voice_status():
    """
    Check voice synthesis system status (Phase 64)

    Response:
        {
            "success": true,
            "status": {
                "tts_available": true,
                "engine": "Coqui TTS (XTTS v2)",
                "speaker": "Ana Florence",
                "cached_phrases": 42,
                "cache_hits": 128
            }
        }
    """
    try:
        from ai_bridge.voice_synthesis import get_voice_synthesizer

        synthesizer = get_voice_synthesizer()
        status = synthesizer.get_status()

        # Get cache statistics
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(
            """
            SELECT
                COUNT(*) as cached_phrases,
                COALESCE(SUM(hit_count), 0) as cache_hits
            FROM voice_word_cache
            WHERE text_hash IS NOT NULL
        """
        )
        cache_stats = cur.fetchone()

        # Get today's generation stats
        cur.execute(
            """
            SELECT
                COUNT(*) as today_generations,
                COUNT(*) FILTER (WHERE cached = TRUE) as today_cache_hits,
                AVG(generation_time_ms) FILTER (WHERE cached = FALSE)::INTEGER as avg_gen_time
            FROM voice_generation_log
            WHERE created_at > CURRENT_DATE
        """
        )
        today_stats = cur.fetchone()

        return jsonify(
            {
                "success": True,
                "status": {
                    **status,
                    "cached_phrases": cache_stats["cached_phrases"] or 0,
                    "cache_hits": int(cache_stats["cache_hits"] or 0),
                    "today": {
                        "generations": today_stats["today_generations"] or 0,
                        "cache_hits": today_stats["today_cache_hits"] or 0,
                        "avg_generation_ms": today_stats["avg_gen_time"] or 0,
                    },
                },
            }
        )

    except Exception as e:
        import traceback

        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@archie_chat_bp.route("/api/voice/cache/cleanup", methods=["POST"])
@login_required
def voice_cache_cleanup():
    """
    Clean up unused voice cache entries (Phase 5: Voice Integration Polish)

    Removes entries with fewer than min_hits that are older than max_age_days.

    Request (optional):
        {
            "max_age_days": 30,
            "min_hits": 1
        }

    Response:
        {
            "success": true,
            "deleted": 42
        }
    """
    try:
        from ai_bridge.voice_synthesis import get_voice_synthesizer

        data = request.get_json() or {} or {}
        max_age = int(data.get("max_age_days", 30))
        min_hits = int(data.get("min_hits", 1))

        # Clamp to reasonable bounds
        max_age = max(1, min(365, max_age))
        min_hits = max(0, min(100, min_hits))

        synthesizer = get_voice_synthesizer()
        deleted = synthesizer.cleanup_cache(max_age_days=max_age, min_hits=min_hits)

        return jsonify({"success": True, "deleted": deleted})

    except Exception as e:
        import traceback

        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500


@archie_chat_bp.route("/api/voice/recent", methods=["GET"])
@login_required
def voice_recent():
    """Recent voice generation activity for the current user."""
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute(
            """
            SELECT text_length, generation_time_ms, cached, emotion, engine, language,
                   created_at
            FROM voice_generation_log
            WHERE user_id = %s
            ORDER BY created_at DESC
            LIMIT 5
        """,
            (current_user.id,),
        )
        rows = cur.fetchall()
        recent = []
        for r in rows:
            recent.append(
                {
                    "text_length": r[0],
                    "latency_ms": r[1],
                    "cache_hit": r[2],
                    "emotion": r[3],
                    "engine": r[4],
                    "language": r[5] or "en",
                    "created_at": r[6].isoformat() if r[6] else None,
                }
            )
        return jsonify({"success": True, "recent": recent})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@archie_chat_bp.route("/api/voice/profiles/<int:profile_id>/invalidate-cache", methods=["POST"])
@login_required
def invalidate_voice_cache(profile_id):
    """Unlock or clear cached voice entries for a profile."""
    try:
        data = request.get_json() or {}
        clear = data.get("clear", False)
        regenerate = data.get("regenerate", False)

        conn = get_db()
        cur = conn.cursor()

        # Get profile info
        cur.execute(
            "SELECT agent_id, engine, language FROM agent_voice_profiles WHERE id = %s",
            (profile_id,),
        )
        profile = cur.fetchone()
        if not profile:
            cur.close()
            conn.close()
            return jsonify({"success": False, "error": "Profile not found"})

        agent_id, engine, language = profile

        if clear:
            cur.execute(
                """DELETE FROM voice_word_cache
                WHERE agent_id = %s AND engine = %s AND language = %s
                AND is_locked = TRUE""",
                (agent_id, engine, language),
            )
            deleted = cur.rowcount
            unlocked = 0
        else:
            cur.execute(
                """UPDATE voice_word_cache
                SET is_locked = FALSE, locked_at = NULL, locked_with_params = NULL
                WHERE agent_id = %s AND engine = %s AND language = %s
                AND is_locked = TRUE""",
                (agent_id, engine, language),
            )
            unlocked = cur.rowcount
            deleted = 0

        conn.commit()

        pregen_job_id = None
        if regenerate:
            cur.execute(
                """INSERT INTO voice_pregen_jobs
                (agent_id, status, job_type, total_words, language, engine)
                VALUES (%s, 'pending', 'manual', 200, %s, %s)
                RETURNING id""",
                (agent_id, language, engine),
            )
            row = cur.fetchone()
            if row:
                pregen_job_id = row[0]
            conn.commit()

        return jsonify(
            {
                "success": True,
                "unlocked": unlocked,
                "deleted": deleted,
                "pregen_job_id": pregen_job_id,
            }
        )
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@archie_chat_bp.route("/api/chat/react", methods=["POST"])
@login_required
def chat_react():
    """Toggle a reaction on a chat message"""
    try:
        data = request.get_json() or {} or {}
        message_id = data.get("message_id")
        reaction = data.get("reaction")

        if not message_id or not reaction:
            return (
                jsonify({"success": False, "error": "Missing message_id or reaction"}),
                400,
            )

        allowed_reactions = {"thumbs_up", "thumbs_down", "heart", "laugh"}
        if reaction not in allowed_reactions:
            return jsonify({"success": False, "error": "Invalid reaction"}), 400

        user_id = current_user.id if hasattr(current_user, "id") else 2

        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Check if reaction already exists (toggle behavior)
        cur.execute(
            "SELECT id FROM chat_reactions WHERE message_id = %s AND user_id = %s AND reaction = %s",
            (message_id, user_id, reaction),
        )
        existing = cur.fetchone()

        if existing:
            cur.execute("DELETE FROM chat_reactions WHERE id = %s", (existing["id"],))
            action = "removed"
        else:
            cur.execute(
                "INSERT INTO chat_reactions (message_id, user_id, reaction) VALUES (%s, %s, %s)",
                (message_id, user_id, reaction),
            )
            action = "added"

        conn.commit()

        return jsonify({"success": True, "action": action, "reaction": reaction})

    except Exception as e:
        import traceback

        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


# ─── Analytics API Endpoints ─────────────────────────────────────────


@archie_chat_bp.route("/api/analytics/conversation-metrics", methods=["GET"])
@login_required
def analytics_conversation_metrics():
    """Message counts, avg response time, daily trend, active threads."""
    try:
        range_days = min(int(request.args.get("range", 7)), 365)
    except (ValueError, TypeError):
        range_days = 7

    conn = None
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Message counts: today, this week (7d), this month (30d)
        cur.execute(
            """
            SELECT
                COUNT(*) FILTER (WHERE created_at >= CURRENT_DATE) AS today,
                COUNT(*) FILTER (WHERE created_at >= NOW() - make_interval(days => 7)) AS week,
                COUNT(*) FILTER (WHERE created_at >= NOW() - make_interval(days => 30)) AS month
            FROM ai_conversations
            """
        )
        counts = cur.fetchone()

        # Average response time from metadata->'response_time_ms'
        cur.execute(
            """
            SELECT
                ROUND(AVG((metadata->>'response_time_ms')::numeric)) AS avg_response_ms,
                ROUND(MIN((metadata->>'response_time_ms')::numeric)) AS min_response_ms,
                ROUND(MAX((metadata->>'response_time_ms')::numeric)) AS max_response_ms
            FROM ai_conversations
            WHERE metadata->>'response_time_ms' IS NOT NULL
              AND created_at >= NOW() - make_interval(days => %s)
            """,
            (range_days,),
        )
        response_time = cur.fetchone()

        # Daily trend for the requested range
        cur.execute(
            """
            SELECT
                DATE(created_at) AS day,
                COUNT(*) AS message_count
            FROM ai_conversations
            WHERE created_at >= NOW() - make_interval(days => %s)
            GROUP BY DATE(created_at)
            ORDER BY day
            """,
            (range_days,),
        )
        daily_trend = [{"day": row["day"].isoformat(), "count": row["message_count"]} for row in cur.fetchall()]

        # Active (non-archived) threads
        cur.execute(
            """
            SELECT COUNT(*) AS active_threads
            FROM ai_conversation_threads
            WHERE is_archived = false
            """
        )
        threads = cur.fetchone()

        return jsonify(
            {
                "success": True,
                "counts": {
                    "today": counts["today"] or 0,
                    "week": counts["week"] or 0,
                    "month": counts["month"] or 0,
                },
                "response_time": {
                    "avg_ms": int(response_time["avg_response_ms"] or 0),
                    "min_ms": int(response_time["min_response_ms"] or 0),
                    "max_ms": int(response_time["max_response_ms"] or 0),
                },
                "daily_trend": daily_trend,
                "active_threads": threads["active_threads"] or 0,
                "range_days": range_days,
            }
        )

    except Exception as e:
        logger.error(f"Analytics conversation-metrics error: {e}")
        if conn:
            try:
                conn.close()
            except Exception:
                pass
        return (
            jsonify(
                {
                    "success": False,
                    "error": str(e),
                    "counts": {"today": 0, "week": 0, "month": 0},
                    "response_time": {"avg_ms": 0, "min_ms": 0, "max_ms": 0},
                    "daily_trend": [],
                    "active_threads": 0,
                }
            ),
            500,
        )
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@archie_chat_bp.route("/api/analytics/model-usage", methods=["GET"])
@login_required
def analytics_model_usage():
    """Model distribution, agent usage, step timing from orchestration_steps."""
    try:
        range_days = min(int(request.args.get("range", 7)), 365)
    except (ValueError, TypeError):
        range_days = 7

    conn = None
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Model distribution
        cur.execute(
            """
            SELECT
                COALESCE(model_used, 'unknown') AS model,
                COUNT(*) AS count,
                ROUND(AVG(duration_ms)) AS avg_duration_ms
            FROM orchestration_steps
            WHERE created_at >= NOW() - make_interval(days => %s)
              AND model_used IS NOT NULL
            GROUP BY model_used
            ORDER BY count DESC
            """,
            (range_days,),
        )
        model_dist = [
            {
                "model": row["model"],
                "count": row["count"],
                "avg_duration_ms": int(row["avg_duration_ms"] or 0),
            }
            for row in cur.fetchall()
        ]

        # Agent usage (join agents table for display name)
        cur.execute(
            """
            SELECT
                a.name AS agent_name,
                COALESCE(a.first_name || ' ' || a.last_name, a.name) AS display_name,
                COUNT(*) AS step_count,
                ROUND(AVG(os.duration_ms)) AS avg_duration_ms
            FROM orchestration_steps os
            JOIN agents a ON a.id = os.agent_id
            WHERE os.created_at >= NOW() - make_interval(days => %s)
            GROUP BY a.id, a.name, a.first_name, a.last_name
            ORDER BY step_count DESC
            """,
            (range_days,),
        )
        agent_usage = [
            {
                "agent": row["agent_name"],
                "display_name": row["display_name"],
                "step_count": row["step_count"],
                "avg_duration_ms": int(row["avg_duration_ms"] or 0),
            }
            for row in cur.fetchall()
        ]

        # Step type breakdown with timing
        cur.execute(
            """
            SELECT
                step_type,
                COUNT(*) AS count,
                ROUND(AVG(duration_ms)) AS avg_duration_ms,
                SUM(CASE WHEN success THEN 1 ELSE 0 END) AS success_count
            FROM orchestration_steps
            WHERE created_at >= NOW() - make_interval(days => %s)
            GROUP BY step_type
            ORDER BY count DESC
            """,
            (range_days,),
        )
        step_types = [
            {
                "step_type": row["step_type"],
                "count": row["count"],
                "avg_duration_ms": int(row["avg_duration_ms"] or 0),
                "success_rate": (round(row["success_count"] / row["count"] * 100, 1) if row["count"] else 0),
            }
            for row in cur.fetchall()
        ]

        return jsonify(
            {
                "success": True,
                "model_distribution": model_dist,
                "agent_usage": agent_usage,
                "step_types": step_types,
                "range_days": range_days,
            }
        )

    except Exception as e:
        logger.error(f"Analytics model-usage error: {e}")
        if conn:
            try:
                conn.close()
            except Exception:
                pass
        return (
            jsonify(
                {
                    "success": False,
                    "error": str(e),
                    "model_distribution": [],
                    "agent_usage": [],
                    "step_types": [],
                }
            ),
            500,
        )
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@archie_chat_bp.route("/api/analytics/cost", methods=["GET"])
@login_required
def analytics_cost():
    """Token and cost data from cloud_model_usage grouped by provider/model."""
    try:
        range_days = min(int(request.args.get("range", 30)), 365)
    except (ValueError, TypeError):
        range_days = 30

    conn = None
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Cost by provider
        cur.execute(
            """
            SELECT
                provider,
                COUNT(*) AS request_count,
                SUM(prompt_tokens) AS total_prompt_tokens,
                SUM(completion_tokens) AS total_completion_tokens,
                SUM(total_tokens) AS total_tokens,
                SUM(cost_usd)::numeric(10,4) AS total_cost_usd
            FROM cloud_model_usage
            WHERE created_at >= NOW() - make_interval(days => %s)
            GROUP BY provider
            ORDER BY total_cost_usd DESC
            """,
            (range_days,),
        )
        by_provider = [
            {
                "provider": row["provider"],
                "request_count": row["request_count"],
                "total_prompt_tokens": row["total_prompt_tokens"] or 0,
                "total_completion_tokens": row["total_completion_tokens"] or 0,
                "total_tokens": row["total_tokens"] or 0,
                "total_cost_usd": float(row["total_cost_usd"] or 0),
            }
            for row in cur.fetchall()
        ]

        # Cost by model
        cur.execute(
            """
            SELECT
                model_name,
                provider,
                COUNT(*) AS request_count,
                SUM(total_tokens) AS total_tokens,
                SUM(cost_usd)::numeric(10,4) AS total_cost_usd,
                ROUND(AVG(response_ms)) AS avg_response_ms
            FROM cloud_model_usage
            WHERE created_at >= NOW() - make_interval(days => %s)
            GROUP BY model_name, provider
            ORDER BY total_cost_usd DESC
            """,
            (range_days,),
        )
        by_model = [
            {
                "model": row["model_name"],
                "provider": row["provider"],
                "request_count": row["request_count"],
                "total_tokens": row["total_tokens"] or 0,
                "total_cost_usd": float(row["total_cost_usd"] or 0),
                "avg_response_ms": int(row["avg_response_ms"] or 0),
            }
            for row in cur.fetchall()
        ]

        # Daily cost trend
        cur.execute(
            """
            SELECT
                DATE(created_at) AS day,
                SUM(cost_usd)::numeric(10,4) AS daily_cost,
                SUM(total_tokens) AS daily_tokens
            FROM cloud_model_usage
            WHERE created_at >= NOW() - make_interval(days => %s)
            GROUP BY DATE(created_at)
            ORDER BY day
            """,
            (range_days,),
        )
        daily_cost = [
            {
                "day": row["day"].isoformat(),
                "cost_usd": float(row["daily_cost"] or 0),
                "tokens": row["daily_tokens"] or 0,
            }
            for row in cur.fetchall()
        ]

        return jsonify(
            {
                "success": True,
                "by_provider": by_provider,
                "by_model": by_model,
                "daily_cost": daily_cost,
                "range_days": range_days,
            }
        )

    except Exception as e:
        logger.error(f"Analytics cost error: {e}")
        if conn:
            try:
                conn.close()
            except Exception:
                pass
        return (
            jsonify(
                {
                    "success": False,
                    "error": str(e),
                    "by_provider": [],
                    "by_model": [],
                    "daily_cost": [],
                }
            ),
            500,
        )
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@archie_chat_bp.route("/api/analytics/voice", methods=["GET"])
@login_required
def analytics_voice():
    """Voice generation count, cache hit rate, avg latency."""
    try:
        range_days = min(int(request.args.get("range", 7)), 365)
    except (ValueError, TypeError):
        range_days = 7

    conn = None
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Generation stats with cache hit rate
        cur.execute(
            """
            SELECT
                COUNT(*) AS total_generations,
                SUM(CASE WHEN cached THEN 1 ELSE 0 END) AS cache_hits,
                ROUND(
                    100.0 * SUM(CASE WHEN cached THEN 1 ELSE 0 END) / NULLIF(COUNT(*), 0),
                    1
                ) AS cache_hit_rate,
                ROUND(AVG(generation_time_ms)) AS avg_latency_ms,
                ROUND(AVG(generation_time_ms) FILTER (WHERE NOT cached)) AS avg_uncached_ms,
                ROUND(AVG(text_length)) AS avg_text_length
            FROM voice_generation_log
            WHERE created_at >= NOW() - make_interval(days => %s)
            """,
            (range_days,),
        )
        stats = cur.fetchone()

        # By engine breakdown
        cur.execute(
            """
            SELECT
                COALESCE(engine, 'unknown') AS engine,
                COUNT(*) AS count,
                ROUND(AVG(generation_time_ms)) AS avg_latency_ms,
                ROUND(
                    100.0 * SUM(CASE WHEN cached THEN 1 ELSE 0 END) / NULLIF(COUNT(*), 0),
                    1
                ) AS cache_hit_rate
            FROM voice_generation_log
            WHERE created_at >= NOW() - make_interval(days => %s)
            GROUP BY engine
            ORDER BY count DESC
            """,
            (range_days,),
        )
        by_engine = [
            {
                "engine": row["engine"],
                "count": row["count"],
                "avg_latency_ms": int(row["avg_latency_ms"] or 0),
                "cache_hit_rate": float(row["cache_hit_rate"] or 0),
            }
            for row in cur.fetchall()
        ]

        # Daily generation trend
        cur.execute(
            """
            SELECT
                DATE(created_at) AS day,
                COUNT(*) AS generations,
                SUM(CASE WHEN cached THEN 1 ELSE 0 END) AS cache_hits
            FROM voice_generation_log
            WHERE created_at >= NOW() - make_interval(days => %s)
            GROUP BY DATE(created_at)
            ORDER BY day
            """,
            (range_days,),
        )
        daily_trend = [
            {
                "day": row["day"].isoformat(),
                "generations": row["generations"],
                "cache_hits": row["cache_hits"],
            }
            for row in cur.fetchall()
        ]

        # Cache size info
        cur.execute(
            """
            SELECT
                COUNT(*) AS total_entries,
                SUM(hit_count) AS total_hits
            FROM voice_word_cache
            """
        )
        cache_info = cur.fetchone()

        return jsonify(
            {
                "success": True,
                "stats": {
                    "total_generations": stats["total_generations"] or 0,
                    "cache_hits": stats["cache_hits"] or 0,
                    "cache_hit_rate": float(stats["cache_hit_rate"] or 0),
                    "avg_latency_ms": int(stats["avg_latency_ms"] or 0),
                    "avg_uncached_ms": int(stats["avg_uncached_ms"] or 0),
                    "avg_text_length": int(stats["avg_text_length"] or 0),
                },
                "by_engine": by_engine,
                "daily_trend": daily_trend,
                "cache": {
                    "total_entries": cache_info["total_entries"] or 0,
                    "total_hits": cache_info["total_hits"] or 0,
                },
                "range_days": range_days,
            }
        )

    except Exception as e:
        logger.error(f"Analytics voice error: {e}")
        if conn:
            try:
                conn.close()
            except Exception:
                pass
        return (
            jsonify(
                {
                    "success": False,
                    "error": str(e),
                    "stats": {
                        "total_generations": 0,
                        "cache_hits": 0,
                        "cache_hit_rate": 0,
                        "avg_latency_ms": 0,
                        "avg_uncached_ms": 0,
                        "avg_text_length": 0,
                    },
                    "by_engine": [],
                    "daily_trend": [],
                    "cache": {"total_entries": 0, "total_hits": 0},
                }
            ),
            500,
        )
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


# ── Phase 7: Memory Endpoints ─────────────────────────────────────────


@archie_chat_bp.route("/api/memory/list", methods=["GET"])
@login_required
def memory_list():
    """List active memories for current user."""
    conn = None
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(
            """
            SELECT id, memory_type, category, content, importance_score,
                   access_count, tags, source_type, created_at
            FROM long_term_memory
            WHERE user_id = %s AND is_deleted = FALSE
            ORDER BY importance_score DESC, created_at DESC
            LIMIT 100
            """,
            (current_user.id,),
        )
        rows = cur.fetchall()

        memories = []
        for r in rows:
            memories.append(
                {
                    "id": r["id"],
                    "memory_type": r["memory_type"],
                    "category": r["category"],
                    "content": r["content"],
                    "importance_score": float(r["importance_score"] or 0),
                    "access_count": r["access_count"] or 0,
                    "tags": r["tags"] or [],
                    "source_type": r["source_type"],
                    "created_at": r["created_at"].isoformat() if r["created_at"] else None,
                }
            )
        return jsonify({"success": True, "memories": memories})

    except Exception as e:
        logger.error(f"Memory list error: {e}")
        if conn:
            try:
                conn.close()
            except Exception:
                pass
        return jsonify({"success": True, "memories": []})
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@archie_chat_bp.route("/api/memory/store", methods=["POST"])
@login_required
def memory_store():
    """Manually store a memory."""
    data = request.get_json(silent=True) or {}
    content = (data.get("content") or "").strip()
    category = (data.get("category") or "general").strip()

    if not content:
        return jsonify({"success": False, "error": "content is required"}), 400

    conn = None
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(
            """
            INSERT INTO long_term_memory
                (user_id, memory_type, category, content,
                 importance_score, source_type, source_module)
            VALUES (%s, 'fact', %s, %s, 0.7, 'manual', 'chat')
            RETURNING id
            """,
            (current_user.id, category, content),
        )
        new_id = cur.fetchone()["id"]
        conn.commit()
        return jsonify({"success": True, "id": new_id})

    except Exception as e:
        logger.error(f"Memory store error: {e}")
        if conn:
            try:
                conn.close()
            except Exception:
                pass
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@archie_chat_bp.route("/api/memory/<int:memory_id>/delete", methods=["POST"])
@login_required
def memory_delete(memory_id):
    """Soft-delete a memory."""
    conn = None
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute(
            """
            UPDATE long_term_memory
            SET is_deleted = TRUE
            WHERE id = %s AND user_id = %s
            """,
            (memory_id, current_user.id),
        )
        affected = cur.rowcount
        conn.commit()
        return jsonify({"success": True, "deleted": affected > 0})

    except Exception as e:
        logger.error(f"Memory delete error: {e}")
        if conn:
            try:
                conn.close()
            except Exception:
                pass
        return jsonify({"success": False, "deleted": False}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@archie_chat_bp.route("/api/memory/preferences", methods=["GET"])
@login_required
def memory_preferences():
    """User memory preferences."""
    conn = None
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(
            """
            SELECT id, category, preference_key, preference_value,
                   confidence, times_confirmed, times_contradicted,
                   first_observed_at, last_confirmed_at
            FROM user_memory_preferences
            WHERE user_id = %s AND is_active = TRUE
            ORDER BY confidence DESC
            """,
            (current_user.id,),
        )
        rows = cur.fetchall()

        prefs = []
        for r in rows:
            prefs.append(
                {
                    "id": r["id"],
                    "category": r["category"],
                    "preference_key": r["preference_key"],
                    "preference_value": r["preference_value"],
                    "confidence": float(r["confidence"] or 0),
                    "times_confirmed": r["times_confirmed"] or 0,
                    "times_contradicted": r["times_contradicted"] or 0,
                    "first_observed_at": r["first_observed_at"].isoformat() if r["first_observed_at"] else None,
                    "last_confirmed_at": r["last_confirmed_at"].isoformat() if r["last_confirmed_at"] else None,
                }
            )
        return jsonify({"success": True, "preferences": prefs})

    except Exception as e:
        logger.error(f"Memory preferences error: {e}")
        if conn:
            try:
                conn.close()
            except Exception:
                pass
        return jsonify({"success": True, "preferences": []})
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


# ── Phase 7: Notification Endpoints ──────────────────────────────────


@archie_chat_bp.route("/api/notifications/unread")
@login_required
def notifications_unread():
    """Unread system notifications (per-user read tracking)."""
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        is_admin = getattr(current_user, "is_admin", False)
        user_id = current_user.id

        if is_admin:
            vis_clause = ""
            count_params = [user_id]
            recent_params = [user_id]
        else:
            vis_clause = "AND (sn.visibility = 'all' OR (sn.visibility = 'user' AND sn.target_user_id = %s))"
            count_params = [user_id, user_id]
            recent_params = [user_id, user_id]

        cur.execute(
            f"""
            SELECT COUNT(*) as count FROM system_notifications sn
            LEFT JOIN notification_reads nr ON nr.notification_id = sn.id AND nr.user_id = %s
            WHERE nr.notification_id IS NULL
              AND sn.is_archived = FALSE
              {vis_clause}
        """,
            count_params,
        )
        count = cur.fetchone()["count"]
        cur.execute(
            f"""
            SELECT sn.id, sn.type, sn.title, sn.message, sn.priority, sn.created_at
            FROM system_notifications sn
            LEFT JOIN notification_reads nr ON nr.notification_id = sn.id AND nr.user_id = %s
            WHERE nr.notification_id IS NULL
              AND sn.is_archived = FALSE
              {vis_clause}
            ORDER BY sn.created_at DESC
            LIMIT 5
        """,
            recent_params,
        )
        recent = cur.fetchall()
        for r in recent:
            r["created_at"] = r["created_at"].isoformat() if r.get("created_at") else None
        return jsonify({"count": count, "notifications": recent})
    except Exception as e:
        logger.error("notifications_unread error: %s", e)
        return jsonify({"count": 0, "notifications": []})
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@archie_chat_bp.route("/api/notifications/<int:notification_id>/read", methods=["POST"])
@login_required
def notification_mark_read(notification_id):
    """Mark a notification as read."""
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO notification_reads (notification_id, user_id, read_at)
            VALUES (%s, %s, NOW())
            ON CONFLICT (notification_id, user_id) DO NOTHING
            """,
            (notification_id, current_user.id),
        )
        conn.commit()
        return jsonify({"ok": True})
    except Exception as e:
        logger.error("notification_mark_read error: %s", e)
        return jsonify({"error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@archie_chat_bp.route("/api/briefings/generate-now", methods=["POST"])
@login_required
def briefing_generate_now():
    """Trigger immediate briefing generation."""
    try:
        from ai_bridge.proactive_intelligence import BriefingGenerator

        gen = BriefingGenerator()
        result = gen.generate_due_briefings()
        return jsonify({"status": "generated", "result": result})
    except Exception as e:
        logger.error("briefing_generate_now error: %s", e)
        return jsonify({"error": str(e)}), 500


@archie_chat_bp.route("/api/briefings/config")
@login_required
def briefing_config():
    """Get briefing configuration."""
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT * FROM briefings ORDER BY id")
        briefings = cur.fetchall()
        for b in briefings:
            for key in b:
                if hasattr(b[key], "isoformat"):
                    b[key] = b[key].isoformat()
        return jsonify({"briefings": briefings})
    except Exception as e:
        logger.error("briefing_config error: %s", e)
        return jsonify({"briefings": []})
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


# ============================================================
# Phase 7: Export Endpoints
# ============================================================


@archie_chat_bp.route("/api/conversations/<conversation_id>/export")
@login_required
def conversation_export(conversation_id):
    """Export a conversation as Markdown or JSON."""
    fmt = request.args.get("format", "md")
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(
            """
            SELECT id, message, response, model, created_at, metadata
            FROM ai_conversations
            WHERE conversation_id = %s AND user_id = %s
            ORDER BY created_at ASC
        """,
            (conversation_id, current_user.id),
        )
        messages = cur.fetchall()
        cur.execute(
            """
            SELECT title FROM ai_conversation_threads WHERE conversation_id = %s
        """,
            (conversation_id,),
        )
        thread = cur.fetchone()
        title = thread["title"] if thread else f"Conversation {conversation_id}"

        if not messages:
            return jsonify({"error": "No messages found"}), 404

        if fmt == "json":
            for m in messages:
                m["created_at"] = m["created_at"].isoformat() if m.get("created_at") else None
                if m.get("metadata") and not isinstance(m["metadata"], str):
                    pass  # Already dict from RealDictCursor
            return jsonify(
                {
                    "title": title,
                    "messages": messages,
                    "exported_at": datetime.utcnow().isoformat(),
                }
            )

        # Markdown format
        lines = [
            f"# {title}\n",
            f"*Exported: {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}*\n",
        ]
        for m in messages:
            ts = m["created_at"].strftime("%H:%M") if m.get("created_at") else ""
            model = m.get("model") or ""
            lines.append(f"\n---\n\n**You** ({ts}):\n{m['message']}\n")
            lines.append(f"\n**ARCHIE** ({ts}, {model}):\n{m['response']}\n")
        content = "\n".join(lines)
        return Response(
            content,
            mimetype="text/markdown",
            headers={"Content-Disposition": f"attachment; filename=archie-chat-{conversation_id[:8]}.md"},
        )
    except Exception as e:
        logger.error("conversation_export error: %s", e)
        return jsonify({"error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@archie_chat_bp.route("/api/conversations/<conversation_id>/save-to-kb", methods=["POST"])
@login_required
def save_conversation_to_kb(conversation_id):
    """Save conversation to knowledge base."""
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(
            """
            SELECT message, response, created_at FROM ai_conversations
            WHERE conversation_id = %s AND user_id = %s
            ORDER BY created_at ASC
        """,
            (conversation_id, current_user.id),
        )
        messages = cur.fetchall()
        if not messages:
            cur.close()
            conn.close()
            return jsonify({"error": "No messages found"}), 404
        cur.execute(
            "SELECT title FROM ai_conversation_threads WHERE conversation_id = %s",
            (conversation_id,),
        )
        thread = cur.fetchone()
        title = thread["title"] if thread else f"Chat Export: {messages[0]['message'][:60]}"
        content_lines = []
        for m in messages:
            content_lines.append(f"**User:** {m['message']}")
            content_lines.append(f"**ARCHIE:** {m['response']}\n")
        content = "\n".join(content_lines)
        cur.execute(
            """
            INSERT INTO knowledge_base (title, content, source_type, importance_score, tags)
            VALUES (%s, %s, 'chat_export', 0.6, ARRAY['chat-export', 'conversation'])
            RETURNING id
        """,
            (title, content),
        )
        kb_id = cur.fetchone()["id"]
        conn.commit()
        return jsonify({"kb_id": kb_id, "title": title})
    except Exception as e:
        logger.error("save_to_kb error: %s", e)
        return jsonify({"error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@archie_chat_bp.route("/api/conversations/<conversation_id>/summarize", methods=["POST"])
@login_required
def conversation_summarize(conversation_id):
    """Generate AI summary of a conversation."""
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(
            """
            SELECT message, response FROM ai_conversations
            WHERE conversation_id = %s AND user_id = %s
            ORDER BY created_at ASC
        """,
            (conversation_id, current_user.id),
        )
        messages = cur.fetchall()
        if not messages:
            return jsonify({"error": "No messages found"}), 404
        text = ""
        for m in messages:
            text += f"User: {m['message']}\nARCHIE: {m['response']}\n\n"
        if len(text) > 8000:
            text = text[:4000] + "\n...\n" + text[-4000:]
        import requests as req

        resp = req.post(
            os.getenv("OLLAMA_URL", "http://host.docker.internal:11434") + "/api/generate",
            json={
                "model": "dolphin3-8k:latest",
                "prompt": f"Summarize this conversation in 3-5 bullet points. Be concise.\n\n{text}",
                "stream": False,
            },
            timeout=60,
        )
        if resp.ok:
            summary = resp.json().get("response", "Summary generation failed.")
        else:
            summary = "Could not generate summary at this time."
        return jsonify({"summary": summary})
    except Exception as e:
        logger.error("conversation_summarize error: %s", e)
        return jsonify({"error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@archie_chat_bp.route("/api/analytics/export")
@login_required
def analytics_export():
    """Export analytics as CSV."""
    range_days = request.args.get("range", 7, type=int)
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(
            """
            SELECT DATE(created_at) as date, COUNT(*) as messages,
                   AVG((metadata->>'response_time_ms')::float) as avg_response_ms
            FROM ai_conversations
            WHERE user_id = %s AND created_at > NOW() - make_interval(days => %s)
            GROUP BY DATE(created_at)
            ORDER BY date
        """,
            (current_user.id, range_days),
        )
        rows = cur.fetchall()
        lines = ["date,messages,avg_response_ms"]
        for r in rows:
            lines.append(f"{r['date']},{r['messages']},{round(r['avg_response_ms'] or 0)}")
        csv_content = "\n".join(lines)
        return Response(
            csv_content,
            mimetype="text/csv",
            headers={"Content-Disposition": f"attachment; filename=archie-analytics-{range_days}d.csv"},
        )
    except Exception as e:
        logger.error("analytics_export error: %s", e)
        return jsonify({"error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


# ============================================================
# Phase 8: Settings Endpoints
# ============================================================

SETTINGS_DEFAULTS = {
    "theme": "dark",
    "fontSize": "medium",
    "voiceAutoSpeak": True,
    "notifSound": True,
    "defaultMode": "solo",
    "thinkingAutoOpen": False,
    "defaultModel": None,
    "maxMemoryInject": 10,
    "briefingDelivery": "chat",
    "notifPollInterval": 30,
    "shortcutsEnabled": True,
}


@archie_chat_bp.route("/api/settings")
@login_required
def get_settings():
    """Get current user's chat settings (merged with defaults)."""
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(
            "SELECT settings FROM user_chat_settings WHERE user_id = %s",
            (current_user.id,),
        )
        row = cur.fetchone()
        stored = row["settings"] if row else {}
        merged = dict(SETTINGS_DEFAULTS)
        merged.update(stored)
        return jsonify({"settings": merged})
    except Exception as e:
        logger.error("get_settings error: %s", e)
        return jsonify({"settings": dict(SETTINGS_DEFAULTS)})
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@archie_chat_bp.route("/api/settings", methods=["POST"])
@login_required
def update_settings():
    """Update user's chat settings (partial merge)."""
    data = request.get_json() or {}
    updates = data.get("settings", {})
    if not updates:
        return jsonify({"error": "No settings provided"}), 400
    valid = {k: v for k, v in updates.items() if k in SETTINGS_DEFAULTS}
    if not valid:
        return jsonify({"error": "No valid settings keys"}), 400
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO user_chat_settings (user_id, settings, updated_at)
            VALUES (%s, %s::jsonb, NOW())
            ON CONFLICT (user_id) DO UPDATE
            SET settings = user_chat_settings.settings || %s::jsonb,
                updated_at = NOW()
            """,
            (current_user.id, json.dumps(valid), json.dumps(valid)),
        )
        conn.commit()
        return jsonify({"ok": True, "updated": list(valid.keys())})
    except Exception as e:
        logger.error("update_settings error: %s", e)
        return jsonify({"error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


# ============================================================
# Phase 8: Conversation Search Endpoint
# ============================================================


@archie_chat_bp.route("/api/conversations/search")
@login_required
def conversation_search():
    """Search across all conversations by keyword."""
    q = request.args.get("q", "").strip()
    if len(q) < 3:
        return jsonify({"results": [], "total": 0})
    range_days = request.args.get("range", 0, type=int)
    limit = min(request.args.get("limit", 20, type=int), 50)
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        like_param = "%" + q + "%"
        query_params = [like_param, like_param, current_user.id, like_param, like_param]
        date_filter = ""
        if range_days > 0:
            date_filter = "AND c.created_at > NOW() - make_interval(days => %s)"
            query_params.append(range_days)
        query_params.append(limit)
        sql = """
            SELECT DISTINCT ON (c.conversation_id)
                c.conversation_id,
                t.title as thread_title,
                CASE
                    WHEN c.message ILIKE %s THEN 'message'
                    ELSE 'response'
                END as matched_in,
                CASE
                    WHEN c.message ILIKE %s THEN c.message
                    ELSE c.response
                END as matched_text,
                c.created_at,
                c.metadata->>'model' as model
            FROM ai_conversations c
            LEFT JOIN ai_conversation_threads t
                ON t.conversation_id = c.conversation_id
            WHERE c.user_id = %s
            AND (c.message ILIKE %s OR c.response ILIKE %s)
            {date_filter}
            ORDER BY c.conversation_id, c.created_at DESC
            LIMIT %s
        """.format(
            date_filter=date_filter
        )
        cur.execute(sql, query_params)
        rows = cur.fetchall()
        results = []
        q_lower = q.lower()
        for r in rows:
            text = r["matched_text"] or ""
            idx = text.lower().find(q_lower)
            if idx >= 0:
                start = max(0, idx - 30)
                end = min(len(text), idx + len(q) + 30)
                snippet = ("..." if start > 0 else "") + text[start:end] + ("..." if end < len(text) else "")
            else:
                snippet = text[:60] + ("..." if len(text) > 60 else "")
            results.append(
                {
                    "conversation_id": r["conversation_id"],
                    "thread_title": r["thread_title"] or "Untitled",
                    "snippet": snippet,
                    "matched_in": r["matched_in"],
                    "created_at": r["created_at"].isoformat() if r.get("created_at") else None,
                    "model": r["model"],
                }
            )
        return jsonify({"results": results, "total": len(results)})
    except Exception as e:
        logger.error("conversation_search error: %s", e)
        return jsonify({"results": [], "total": 0, "error": str(e)})
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass
