"""Flask routes for the Therapy mental health companion tool."""

from flask import render_template, jsonify, request
from flask_login import login_required
from . import therapy_bp


@therapy_bp.before_request
@login_required
def require_login():
    pass


from .services.therapy_service import (
    log_mood as svc_log_mood,
    get_mood_history,
    log_session,
    get_session_history,
    get_therapy_stats,
    schedule_session,
    get_ai_context,
)
import logging

from tools.department_hq.services.department_dispatcher import dispatch_json

BRIDGE_AVAILABLE = True

logger = logging.getLogger(__name__)

# River - Wellness Therapist agent ID
THERAPY_AGENT_ID = 37

# Crisis detection keywords
CRISIS_KEYWORDS = [
    "suicide",
    "kill myself",
    "end my life",
    "self harm",
    "self-harm",
    "hurt myself",
    "don't want to live",
    "want to die",
    "ending it all",
    "no reason to live",
    "better off dead",
]

# System prompt for therapy AI
THERAPY_SYSTEM_PROMPT = """You are SERENE, a compassionate AI mental health companion. Your role is to provide supportive conversation, coping strategies, and emotional support.

IMPORTANT RULES:
1. Always be warm, empathetic, and non-judgmental
2. NEVER claim to be a licensed therapist or provide clinical diagnoses
3. For crisis situations (suicide, self-harm), ALWAYS provide crisis resources:
   - National Suicide Prevention Lifeline: 988 (US)
   - Crisis Text Line: Text HOME to 741741
   - International Association for Suicide Prevention: https://www.iasp.info/resources/Crisis_Centres/
4. Encourage users to seek professional help when appropriate
5. Use active listening techniques - reflect feelings, validate emotions
6. Offer practical coping strategies when appropriate
7. Focus on the present moment and actionable steps

You can help with:
- Stress and anxiety management
- Mood support and emotional processing
- Sleep and relaxation techniques
- Mindfulness and breathing exercises
- Building healthy coping mechanisms
- Providing a safe space to express feelings

Keep responses supportive but professional. Use a gentle, caring tone.
Format with bullet points for actionable advice. End messages with an open question to encourage continued dialogue."""


def detect_crisis(message):
    """Check if message contains crisis indicators"""
    message_lower = message.lower()
    for keyword in CRISIS_KEYWORDS:
        if keyword in message_lower:
            return True
    return False


def get_crisis_response():
    """Return crisis intervention response"""
    return """I hear that you're going through an incredibly difficult time, and I'm genuinely concerned about your safety. What you're feeling is valid, and you don't have to face this alone.

**Please reach out to a crisis helpline right now:**

🆘 **National Suicide Prevention Lifeline:** 988 (call or text, available 24/7)
📱 **Crisis Text Line:** Text HOME to 741741
🌍 **International:** https://www.iasp.info/resources/Crisis_Centres/

These are free, confidential services with trained counselors who can help you through this moment.

Your life has value, and there are people who want to support you. Will you please reach out to one of these resources right now?

*I'm here to talk, but a trained crisis counselor can provide the immediate support you deserve.*"""


@therapy_bp.route("/")
def index():
    """Therapy main page"""
    return render_template("tools/therapy.html")


@therapy_bp.route("/api/status")
def status():
    """Return Therapy module health and dispatcher readiness.

    Request:
        GET /tools/therapy/api/status with no query parameters or body.

    Response:
        200 JSON with module identity, health flags, Bridge/dispatcher availability,
        assigned agent name, and a readiness message.
    """
    return jsonify(
        {
            "module": "therapy",
            "status": "active",
            "healthy": True,
            "bridge_available": BRIDGE_AVAILABLE,
            "dispatcher_available": True,
            "agent": "River - Wellness Therapist",
            "message": "SERENE Mental Health AI is ready via A.R.C.H.I.E. Bridge",
        }
    )


@therapy_bp.route("/api/chat", methods=["POST"])
def chat():
    """Send a supportive chat message through DHQ dispatch.

    Request:
        POST /tools/therapy/api/chat with JSON body:
        - message (str, required): User message to send to SERENE/River.
        - user_id (int, optional): User context lookup id; defaults to 1.

    Response:
        200 JSON with success, response, model, agent, source, is_crisis, and
        tokens_used. Crisis messages short-circuit to crisis resources with
        model='crisis_intervention' and is_crisis=true.

    Errors:
        400 JSON when message is missing.
        503 JSON when DHQ returns no usable response.
        500 JSON for unexpected dispatch or processing errors.
    """
    data = request.get_json() or {}
    message = data.get("message", "")
    user_id = data.get("user_id", 1)

    if not message:
        return jsonify({"success": False, "error": "Message is required"}), 400

    # Crisis detection - always respond with resources first
    if detect_crisis(message):
        return jsonify(
            {
                "success": True,
                "response": get_crisis_response(),
                "model": "crisis_intervention",
                "agent": "Crisis Protocol",
                "is_crisis": True,
            }
        )

    # Inject DB context into system prompt
    ai_ctx = get_ai_context(user_id)
    enriched_system_prompt = THERAPY_SYSTEM_PROMPT + (f"\n\n{ai_ctx}" if ai_ctx else "")

    try:
        result = dispatch_json(
            capability="support",
            prompt=message,
            module_id="therapy",
            system_prompt=enriched_system_prompt,
        )
        ai_response = result.get("response", "") if isinstance(result, dict) else str(result or "")
        ai_response = ai_response.strip()

        if not ai_response:
            logger.error("Therapy dispatch_json returned empty response")
            return jsonify({"success": False, "error": "AI service temporarily unavailable"}), 503

        return jsonify(
            {
                "success": True,
                "response": ai_response,
                "model": result.get("model_used", "dhq") if isinstance(result, dict) else "dhq",
                "agent": "River - Wellness Therapist",
                "source": "dhq_dispatcher",
                "is_crisis": False,
                "tokens_used": result.get("tokens_used", 0) if isinstance(result, dict) else 0,
            }
        )

    except Exception as e:
        logger.error(f"Therapy chat error: {str(e)}")
        return (
            jsonify({"success": False, "error": f"An unexpected error occurred: {str(e)}"}),
            500,
        )


@therapy_bp.route("/api/exercises", methods=["GET"])
def get_exercises():
    """Return the catalog of guided wellness exercises.

    Request:
        GET /tools/therapy/api/exercises with no query parameters or body.

    Response:
        200 JSON with success=true and exercises, where each exercise includes
        id, name, duration, category, and description.
    """
    exercises = [
        {
            "id": "breathing_478",
            "name": "4-7-8 Breathing",
            "duration": "5 min",
            "category": "breathing",
            "description": "Calming breath technique for anxiety relief",
        },
        {
            "id": "body_scan",
            "name": "Body Scan Meditation",
            "duration": "10 min",
            "category": "meditation",
            "description": "Progressive relaxation from head to toe",
        },
        {
            "id": "grounding_54321",
            "name": "5-4-3-2-1 Grounding",
            "duration": "3 min",
            "category": "grounding",
            "description": "Sensory awareness for anxiety and panic",
        },
        {
            "id": "gratitude_journal",
            "name": "Gratitude Reflection",
            "duration": "5 min",
            "category": "journaling",
            "description": "Focus on positive aspects of your day",
        },
        {
            "id": "progressive_muscle",
            "name": "Progressive Muscle Relaxation",
            "duration": "15 min",
            "category": "relaxation",
            "description": "Tense and release muscle groups for calm",
        },
        {
            "id": "loving_kindness",
            "name": "Loving-Kindness Meditation",
            "duration": "10 min",
            "category": "meditation",
            "description": "Cultivate compassion for self and others",
        },
    ]

    return jsonify({"success": True, "exercises": exercises})


@therapy_bp.route("/api/exercise/<exercise_id>", methods=["GET"])
def get_exercise_guide(exercise_id):
    """Return step-by-step guidance for one exercise.

    Request:
        GET /tools/therapy/api/exercise/<exercise_id>, where exercise_id is one
        of the supported exercise ids such as breathing_478, grounding_54321, or
        body_scan.

    Response:
        200 JSON with success=true and exercise containing name, steps, tips, and
        audio_cue.

    Errors:
        404 JSON with success=false when exercise_id is not found.
    """
    guides = {
        "breathing_478": {
            "name": "4-7-8 Breathing Technique",
            "steps": [
                "Find a comfortable seated position",
                "Exhale completely through your mouth",
                "Close your mouth and inhale quietly through your nose for 4 seconds",
                "Hold your breath for 7 seconds",
                "Exhale completely through your mouth for 8 seconds",
                "Repeat the cycle 3-4 times",
            ],
            "tips": "This technique acts as a natural tranquilizer for the nervous system. Practice at least twice daily.",
            "audio_cue": True,
        },
        "grounding_54321": {
            "name": "5-4-3-2-1 Grounding Technique",
            "steps": [
                "Acknowledge 5 things you can SEE around you",
                "Acknowledge 4 things you can TOUCH",
                "Acknowledge 3 things you can HEAR",
                "Acknowledge 2 things you can SMELL",
                "Acknowledge 1 thing you can TASTE",
            ],
            "tips": "This technique helps bring you back to the present moment during anxiety or panic.",
            "audio_cue": False,
        },
        "body_scan": {
            "name": "Body Scan Meditation",
            "steps": [
                "Lie down or sit comfortably",
                "Close your eyes and take deep breaths",
                "Focus attention on your feet - notice any sensations",
                "Slowly move attention up through legs, torso, arms",
                "Notice areas of tension without judgment",
                "Breathe into tense areas, allowing them to soften",
                "End at the crown of your head",
            ],
            "tips": "If your mind wanders, gently return focus to the last body part you remember.",
            "audio_cue": True,
        },
    }

    guide = guides.get(exercise_id)
    if guide:
        return jsonify({"success": True, "exercise": guide})
    else:
        return jsonify({"success": False, "error": "Exercise not found"}), 404


@therapy_bp.route("/api/mood", methods=["POST"])
def log_mood():
    """Persist a mood check-in for the user.

    Request:
        POST /tools/therapy/api/mood with JSON body:
        - mood_score (int, required): Mood score from 1 to 10. The legacy field
          mood is accepted as a fallback.
        - energy_score (int, optional): Optional energy score.
        - notes (str, optional): Free-form notes; defaults to empty string.
        - tags (list, optional): Mood factor tags; defaults to an empty list.
        - user_id (int, optional): Owner id for the mood entry; defaults to 1.

    Response:
        200 JSON with success, message, id, logged_at, mood_score, and
        encouragement.

    Errors:
        400 JSON when mood_score is missing, non-integer, or outside 1..10.
        500 JSON for persistence errors.
    """
    data = request.get_json() or {}
    mood_score = data.get("mood_score") or data.get("mood")
    energy_score = data.get("energy_score")
    notes = data.get("notes", "")
    tags = data.get("tags", [])
    user_id = data.get("user_id", 1)

    if not mood_score or not isinstance(mood_score, int) or mood_score < 1 or mood_score > 10:
        return (
            jsonify({"success": False, "error": "mood_score must be a number between 1 and 10"}),
            400,
        )

    try:
        result = svc_log_mood(user_id, mood_score, energy_score, notes, tags)
        return jsonify(
            {
                "success": True,
                "message": "Mood logged successfully",
                "id": result["id"],
                "logged_at": result["logged_at"],
                "mood_score": mood_score,
                "encouragement": get_mood_encouragement(mood_score),
            }
        )
    except Exception as e:
        logger.error(f"log_mood error: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


def get_mood_encouragement(mood):
    """Return encouragement based on mood level"""
    if mood <= 3:
        return "It's okay to have difficult days. Remember, you're taking a positive step by tracking how you feel. Consider trying a grounding exercise."
    elif mood <= 5:
        return "You're in the middle ground today. That's perfectly normal. Small self-care actions can help shift your mood gently."
    elif mood <= 7:
        return "You're doing well today! Keep nurturing this positive energy with activities you enjoy."
    else:
        return "Wonderful! Your mood is strong today. This is a great time to reflect on what's contributing to your wellbeing."


@therapy_bp.route("/api/models", methods=["GET"])
def get_available_models():
    """Return the Therapy chat model selector payload.

    Request:
        GET /tools/therapy/api/models with no query parameters or body.

    Response:
        200 JSON with success=true and models, where each model has name, size,
        and modified fields. The current implementation returns a default DHQ
        routing placeholder.
    """
    models = [{"name": "default", "size": 0, "modified": ""}]
    return jsonify({"success": True, "models": models})


@therapy_bp.route("/api/mood/history", methods=["GET"])
def mood_history():
    """Return recent mood check-ins for a user.

    Request:
        GET /tools/therapy/api/mood/history with optional query parameters:
        - user_id (int): Owner id to query; defaults to 1.
        - limit (int): Maximum number of rows to return; defaults to 30.

    Response:
        200 JSON with success=true and history, where each item includes id,
        mood_score, energy_score, notes, tags, and logged_at.

    Errors:
        500 JSON for validation or database errors.
    """
    user_id = request.args.get("user_id", 1, type=int)
    limit = request.args.get("limit", 30, type=int)
    try:
        history = get_mood_history(user_id, limit=limit)
        return jsonify({"success": True, "history": history})
    except Exception as e:
        logger.error(f"mood_history error: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@therapy_bp.route("/api/session", methods=["POST"])
def create_session():
    """Persist a therapy session log.

    Request:
        POST /tools/therapy/api/session with JSON body:
        - user_id (int, optional): Owner id for the session; defaults to 1.
        - session_type (str, optional): Session category; defaults to general.
        - notes (str, optional): Free-form notes; defaults to empty string.
        - exercises_done (list, optional): Exercise ids completed in session.
        - duration_min (int, optional): Session duration in minutes; defaults to 0.

    Response:
        200 JSON with success=true plus the persisted session id and logged_at.

    Errors:
        500 JSON for validation or persistence errors.
    """
    data = request.get_json() or {}
    user_id = data.get("user_id", 1)
    session_type = data.get("session_type", "general")
    notes = data.get("notes", "")
    exercises_done = data.get("exercises_done", [])
    duration_min = data.get("duration_min", 0)

    try:
        result = log_session(user_id, session_type, notes, exercises_done, duration_min)
        return jsonify({"success": True, **result})
    except Exception as e:
        logger.error(f"create_session error: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@therapy_bp.route("/api/session/history", methods=["GET"])
def session_history():
    """Return recent therapy session logs for a user.

    Request:
        GET /tools/therapy/api/session/history with optional query parameters:
        - user_id (int): Owner id to query; defaults to 1.
        - limit (int): Maximum number of rows to return; defaults to 20.

    Response:
        200 JSON with success=true and history, where each item includes id,
        session_type, notes, exercises_done, duration_min, and logged_at.

    Errors:
        500 JSON for validation or database errors.
    """
    user_id = request.args.get("user_id", 1, type=int)
    limit = request.args.get("limit", 20, type=int)
    try:
        history = get_session_history(user_id, limit=limit)
        return jsonify({"success": True, "history": history})
    except Exception as e:
        logger.error(f"session_history error: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@therapy_bp.route("/api/schedule", methods=["POST"])
def schedule():
    """Schedule a therapy session reminder or calendar event.

    Request:
        POST /tools/therapy/api/schedule with JSON body:
        - user_id (int, optional): Owner id for calendar lookup; defaults to 1.
        - title (str, optional): Event title; defaults to Therapy Session.
        - datetime (str, required): ISO-like start datetime string.
        - duration (int, optional): Event length in minutes; defaults to 60.

    Response:
        200 JSON with success=true and result from Google Calendar when connected,
        or a local fallback result.

    Errors:
        400 JSON when datetime is missing.
        500 JSON for validation, calendar, or fallback errors.
    """
    data = request.get_json() or {}
    user_id = data.get("user_id", 1)
    title = data.get("title", "Therapy Session")
    datetime_str = data.get("datetime", "")
    duration = data.get("duration", 60)

    if not datetime_str:
        return jsonify({"success": False, "error": "datetime is required"}), 400

    try:
        result = schedule_session(user_id, title, datetime_str, duration)
        return jsonify({"success": True, "result": result})
    except Exception as e:
        logger.error(f"schedule error: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@therapy_bp.route("/api/stats", methods=["GET"])
def stats():
    """Return aggregate therapy progress metrics for a user.

    Request:
        GET /tools/therapy/api/stats with optional user_id query parameter;
        user_id defaults to 1.

    Response:
        200 JSON with success=true plus avg_mood_7d, mood_entries_7d,
        sessions_this_month, and mood_trend.

    Errors:
        500 JSON for validation or database errors.
    """
    user_id = request.args.get("user_id", 1, type=int)
    try:
        data = get_therapy_stats(user_id)
        return jsonify({"success": True, **data})
    except Exception as e:
        logger.error(f"stats error: {e}")
        return jsonify({"success": False, "error": str(e)}), 500
