"""
A.R.C.H.I.E. Chat Module - Unified Command Interface
Your single interface for talking to ARCHIE
"""

from flask import Blueprint, render_template, request, jsonify, redirect, url_for, flash
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
    0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))), "ai_bridge")
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

        cur.execute("SELECT COUNT(*) as message_count FROM ai_conversations WHERE user_id = %s", (current_user.id,))
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

        cur.close()
        conn.close()

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


@archie_chat_bp.route("/send", methods=["POST"])
@login_required
def send_message():
    """Send message to A.R.C.H.I.E."""
    try:
        message = request.json.get("message")
        conversation_id = request.json.get("conversation_id") or str(uuid.uuid4())

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
            return jsonify({"success": False, "error": f"AI unavailable: {response_data.get('error', 'Unknown')}"}), 503

        response_text = response_data["response"]

        # FIXED: Use metadata JSONB field instead of non-existent columns
        chat_mode = request.json.get("chat_mode", "solo")
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
        conn.commit()
        cur.close()
        conn.close()

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
        data = request.json or {}
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
        data = request.json or {}
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
        return jsonify({"success": False, "error": str(e), "response": f"I encountered an error: {str(e)}"}), 500


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
                "suggestions": ["What's the system status?", "Help me with a coding task", "Show me the team roster"],
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

        cur.close()
        conn.close()

        return jsonify(
            {
                "success": True,
                "status": {
                    "online": True,
                    "emotional_state": {
                        "mood": emotional["current_mood"] if emotional else "neutral",
                        "relationship": float(emotional["relationship_strength"]) if emotional else 0.5,
                        "energy": float(emotional.get("energy_level", 0.8)) if emotional else 0.8,
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

        data = request.json
        topic = data.get("topic", "Ad-hoc discussion")
        stations = data.get("stations", [])

        discussion_id = engine.start_adhoc_discussion(topic=topic, stations=stations, user_id=current_user.id)

        if discussion_id:
            return jsonify(
                {"success": True, "discussion_id": discussion_id, "message": f"Discussion started with topic: {topic}"}
            )
        else:
            return jsonify({"success": False, "error": "Failed to start discussion"}), 500

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

        cur.close()
        conn.close()

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


@archie_chat_bp.route("/api/discussion/<int:discussion_id>/contribute", methods=["POST"])
@login_required
def add_contribution(discussion_id):
    """Add agent contribution to discussion (Phase 63)"""
    try:
        from ai_bridge.team_discussion_engine import TeamDiscussionEngine

        engine = TeamDiscussionEngine()

        data = request.json
        agent_id = data.get("agent_id")
        message = data.get("message")
        message_type = data.get("type", "analysis")

        if not agent_id or not message:
            return jsonify({"success": False, "error": "agent_id and message are required"}), 400

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
            return jsonify({"success": False, "error": "Failed to add contribution"}), 500

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

        return jsonify({"success": True, "discussion_id": discussion_id, "consensus_score": score, "stats": stats})

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

        cur.close()
        conn.close()

        return jsonify({"success": True, "discussions": [dict(d) for d in discussions]})

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


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

        data = request.json or {}
        text = data.get("text", "").strip()
        emotion = data.get("emotion")  # Optional, will auto-detect if not provided
        method = data.get("method", "word_cache")  # word_cache or full

        if not text:
            return jsonify({"success": False, "error": "No text provided"}), 400

        if len(text) > 500:
            return (
                jsonify(
                    {"success": False, "error": "Text too long (max 500 chars). Consider chunking longer responses."}
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

        data = request.json or {}
        text = data.get("text", "").strip()
        emotion = data.get("emotion")

        if not text:
            return jsonify({"success": False, "error": "No text provided"}), 400

        if len(text) > 2000:
            return jsonify({"success": False, "error": "Text too long (max 2000 chars)"}), 400

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
            data = request.json or {}
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

        cur.close()
        conn.close()

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

    @archie_chat_bp.route("/api/chat/react", methods=["POST"])
    @login_required
    def chat_react():
        """Toggle a reaction on a chat message"""
        try:
            data = request.json or {}
            message_id = data.get("message_id")
            reaction = data.get("reaction")

            if not message_id or not reaction:
                return jsonify({"success": False, "error": "Missing message_id or reaction"}), 400

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
            cur.close()
            conn.close()

            return jsonify({"success": True, "action": action, "reaction": reaction})

        except Exception as e:
            import traceback

            traceback.print_exc()
            return jsonify({"success": False, "error": str(e)}), 500
