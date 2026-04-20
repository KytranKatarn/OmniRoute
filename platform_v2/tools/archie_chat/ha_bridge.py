"""
A.R.C.H.I.E. ↔ Home Assistant Bridge
REST endpoint so HA can use ARCHIE as a conversation agent.
Mirrors the chat pattern from api_routes.py:send_message with voice-aware prompting.
Uses OrchestrationEngine (ADR-013) — no direct Ollama calls.
"""

import os
from database import _get_db_password
import json
import uuid
import logging
import sys
import base64

import psycopg2
from psycopg2.extras import RealDictCursor
from flask import request, jsonify, Response
from functools import wraps

logger = logging.getLogger(__name__)

# Emotional intelligence (ai_bridge path setup)
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
    logger.warning("Emotional intelligence module not available for HA bridge")

try:
    from voice_synthesis import get_voice_synthesizer

    VOICE_SYNTHESIS_AVAILABLE = True
except ImportError:
    VOICE_SYNTHESIS_AVAILABLE = False
    logger.warning("Voice synthesis module not available for HA bridge")

# Kytran's user_id — she's the homeowner, all HA conversations are hers
KYTRAN_USER_ID = 2


def _get_db():
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "archie_database"),
        port=os.getenv("DB_PORT", "5432"),
        database=os.getenv("DB_NAME", "archie"),
        user=os.getenv("DB_USER", "archie"),
        password=_get_db_password(),
    )


def _require_ha_key(f):
    """Require HA_API_KEY via Bearer token OR Basic Auth (password = key)."""

    @wraps(f)
    def decorated(*args, **kwargs):
        ha_key = os.getenv("HA_API_KEY", "")
        if not ha_key:
            logger.error("HA_API_KEY not configured")
            return jsonify({"error": "HA integration not configured"}), 503

        auth = request.headers.get("Authorization", "")
        authenticated = False

        if auth.startswith("Bearer "):
            # Bearer token auth
            authenticated = auth[7:].strip() == ha_key
        elif auth.startswith("Basic "):
            # Basic auth — password must match HA_API_KEY
            try:
                decoded = base64.b64decode(auth[6:].strip()).decode("utf-8")
                _, password = decoded.split(":", 1)
                authenticated = password == ha_key
            except Exception:
                pass

        if not authenticated:
            return jsonify({"error": "Invalid API key"}), 401

        return f(*args, **kwargs)

    return decorated


def register_ha_routes(bp):
    """Register Home Assistant routes on the archie_chat blueprint."""

    @bp.route("/ha/health", methods=["GET"])
    def ha_health():
        """Health check endpoint for HA integration."""
        ha_key = os.getenv("HA_API_KEY", "")
        return jsonify(
            {
                "status": "ok",
                "ha_configured": bool(ha_key),
                "voice_synthesis": VOICE_SYNTHESIS_AVAILABLE,
                "emotional_intelligence": EMOTIONAL_INTELLIGENCE_AVAILABLE,
            }
        )

    @bp.route("/ha/conversation", methods=["POST"])
    @_require_ha_key
    def ha_conversation():
        """
        Home Assistant conversation agent endpoint.

        Request:  {"conversation_id": "uuid", "query": "...", "language": "en"}
        Response: {"output": "..."}
        """
        try:
            data = request.get_json(silent=True) or {}
            query = data.get("query", "").strip()
            if not query:
                return jsonify({"error": "No query provided"}), 400

            conversation_id = data.get("conversation_id") or str(uuid.uuid4())

            conn = _get_db()
            cur = conn.cursor(cursor_factory=RealDictCursor)

            # --- Build user context (emotional enrichment) ---
            user_context = {"username": "Kytran"}

            # User's emotional relationship with ARCHIE
            cur.execute(
                """
                SELECT relationship_strength, current_mood
                FROM archie_emotional_state
                WHERE user_id = %s
                ORDER BY timestamp DESC LIMIT 1
                """,
                (KYTRAN_USER_ID,),
            )
            emotional = cur.fetchone()
            if emotional:
                user_context["relationship_strength"] = float(emotional["relationship_strength"])
                user_context["current_mood"] = emotional["current_mood"]

            # ARCHIE's own emotional state
            cur.execute(
                """
                SELECT current_mood, mood_intensity, energy_level, stress_level
                FROM agent_emotional_state
                ORDER BY timestamp DESC LIMIT 1
                """
            )
            archie_state = cur.fetchone()
            if archie_state:
                user_context["archie_mood"] = archie_state["current_mood"]
                user_context["archie_mood_intensity"] = float(archie_state.get("mood_intensity") or 0.5)
                user_context["archie_energy"] = float(archie_state.get("energy_level") or 0.8)
            else:
                user_context["archie_mood"] = "curious"
                user_context["archie_mood_intensity"] = 0.7
                user_context["archie_energy"] = 0.8

            # --- Build conversation history for context ---
            cur.execute(
                """
                SELECT message, response FROM ai_conversations
                WHERE user_id = %s AND conversation_id = %s
                ORDER BY created_at DESC LIMIT 5
                """,
                (KYTRAN_USER_ID, conversation_id),
            )
            history_rows = cur.fetchall()
            conversation_history = []

            # Voice-aware instruction injected first
            voice_instruction = {
                "role": "system",
                "content": (
                    "You are responding via voice through Home Assistant. "
                    "Keep responses concise and conversational — 1-3 sentences. "
                    "Speak naturally as if talking aloud. No markdown, no bullet points, "
                    "no code blocks. Just natural speech."
                ),
            }
            conversation_history.append(voice_instruction)

            for row in reversed(history_rows):
                conversation_history.append({"role": "user", "content": row["message"]})
                if row["response"]:
                    conversation_history.append({"role": "assistant", "content": row["response"]})

            # --- Call ARCHIE via Bridge dispatcher (ADR-013) ---
            user_context["voice_mode"] = True
            user_context["conversation_history"] = conversation_history
            user_context["chat_mode"] = "home_assistant"

            try:
                from tools.department_hq.services.department_dispatcher import dispatch

                # Inline the recent conversation into system_prompt — the old
                # user_context dict was dropped silently by the broken call
                # path (dispatcher had no .dispatch method), so voice replies
                # lost context anyway. Now it travels in-prompt.
                history_text = "\n".join(
                    f"{m.get('role', '?')}: {m.get('content', '')}" for m in conversation_history if m.get("content")
                )
                voice_system_prompt = (
                    "You are ARCHIE in Home Assistant voice mode. Keep replies "
                    "short and speakable — no markdown, no code blocks."
                )
                if history_text:
                    voice_system_prompt += f"\n\n## Recent conversation\n{history_text}"

                result = dispatch(
                    capability="chat",
                    prompt=query,
                    module_id="home_assistant",
                    system_prompt=voice_system_prompt,
                    user_id=KYTRAN_USER_ID,
                    prefer_agent="ARCHIE",
                    project_id=user_context.get("project_id") if isinstance(user_context, dict) else None,
                )
            except Exception as orch_err:
                logger.error(f"HA orchestration failed: {orch_err}")
                cur.close()
                conn.close()
                return jsonify({"error": f"AI unavailable: {orch_err}"}), 503

            response_text = result.response if hasattr(result, "response") else str(result)
            model_used = result.model_used if hasattr(result, "model_used") else "unknown"

            # --- Persist conversation ---
            cur.execute(
                """
                INSERT INTO ai_conversations
                (user_id, conversation_id, message, response, model, metadata)
                VALUES (%s, %s, %s, %s, %s, %s)
                RETURNING id
                """,
                (
                    KYTRAN_USER_ID,
                    conversation_id,
                    query,
                    response_text,
                    model_used,
                    json.dumps(
                        {
                            "chat_mode": "home_assistant",
                            "source": "ha_voice",
                            "agent_used": result.agent_used if hasattr(result, "agent_used") else None,
                        }
                    ),
                ),
            )
            cur.fetchone()
            conn.commit()

            # --- Update emotional state (non-blocking) ---
            if EMOTIONAL_INTELLIGENCE_AVAILABLE:
                try:
                    _update_emotional_state_ha(query, response_text, KYTRAN_USER_ID)
                except Exception as emo_err:
                    logger.error(f"HA emotional update failed: {emo_err}")

            return jsonify({"output": response_text})

        except Exception as e:
            import traceback

            traceback.print_exc()
            return jsonify({"error": str(e)}), 500
        finally:
            try:
                cur.close()
                conn.close()
            except Exception:
                pass

    @bp.route("/ha/tts", methods=["POST"])
    @_require_ha_key
    def ha_tts():
        """
        Voice DNA TTS endpoint for Home Assistant.

        Request:  {"text": "Hello!", "language": "en", "voice": "archie"}
        Response: Raw WAV audio bytes (Content-Type: audio/wav)
        """
        if not VOICE_SYNTHESIS_AVAILABLE:
            return jsonify({"error": "Voice synthesis not available"}), 503

        try:
            data = request.get_json(silent=True) or {}
            text = data.get("text", "").strip()
            if not text:
                return jsonify({"error": "No text provided"}), 400

            # Get ARCHIE's emotional state for voice modulation
            synth = get_voice_synthesizer()
            emotion = synth.get_archie_emotional_state(KYTRAN_USER_ID)
            logger.info(f"HA TTS: text='{text[:50]}...' emotion={emotion}")

            # Synthesize speech using ARCHIE's voice profile (agent_id=2)
            ARCHIE_AGENT_ID = 2
            result = synth.synthesize_for_agent(text, ARCHIE_AGENT_ID, emotion=emotion, user_id=KYTRAN_USER_ID)

            if not result.get("success"):
                logger.error(f"HA TTS synthesis failed: {result.get('error')}")
                return jsonify({"error": result.get("error", "Synthesis failed")}), 503

            # Decode base64 audio → raw WAV bytes
            audio_bytes = base64.b64decode(result["audio_base64"])
            logger.info(
                f"HA TTS: generated {len(audio_bytes)} bytes, "
                f"emotion={emotion}, cached={result.get('cached', False)}"
            )

            return Response(audio_bytes, content_type="audio/wav")

        except Exception as e:
            import traceback

            traceback.print_exc()
            logger.error(f"HA TTS error: {e}")
            return jsonify({"error": str(e)}), 500


def _update_emotional_state_ha(user_message, ai_response, user_id):
    """Analyze conversation and update ARCHIE's emotional state (HA variant)."""
    sentiment = analyze_sentiment(user_message)
    trust = analyze_trust_impact(user_message, ai_response)

    mood_map = {"positive": "happy", "negative": "concerned", "neutral": "focused"}
    tone_mood_map = {
        "curious": "curious",
        "enthusiastic": "excited",
        "frustrated": "supportive",
        "uncertain": "focused",
    }
    new_mood = tone_mood_map.get(sentiment.get("tone"), mood_map.get(sentiment["sentiment"], "neutral"))
    mood_intensity = max(0.3, min(0.95, sentiment.get("confidence", 0.5)))
    trust_delta = trust.get("trust_delta", 0.0)

    conn = _get_db()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    try:
        cur.execute(
            """
            SELECT relationship_strength FROM archie_emotional_state
            WHERE user_id = %s ORDER BY timestamp DESC LIMIT 1
            """,
            (user_id,),
        )
        current = cur.fetchone()
        current_strength = float(current["relationship_strength"]) if current else 0.5
        new_strength = max(0.1, min(0.99, current_strength + trust_delta))

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
                f"HA voice: {sentiment['sentiment']} ({sentiment.get('tone', 'neutral')})",
                json.dumps(
                    {
                        "sentiment": sentiment,
                        "trust": trust,
                        "auto_generated": True,
                        "source": "home_assistant",
                    }
                ),
            ),
        )

        cur.execute(
            """
            INSERT INTO emotional_memory
                (user_id, event_type, emotional_intensity, context_summary,
                 user_emotion_detected, relationship_impact, importance_score)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            (
                user_id,
                "ha_conversation",
                mood_intensity,
                f"HA voice — sentiment: {sentiment['sentiment']}, tone: {sentiment.get('tone', 'neutral')}",
                sentiment.get("user_emotion", "calm"),
                trust_delta,
                0.3 if sentiment["sentiment"] == "neutral" else 0.6,
            ),
        )

        conn.commit()
    except Exception as e:
        logger.error(f"Failed to update emotional state (HA): {e}")
        conn.rollback()
    finally:
        cur.close()
        conn.close()
