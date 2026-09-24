"""Flask routes for the DOC medical assistant tool.

This module serves the DOC web UI and API endpoints for health status,
medical-assistant chat, symptom logging and analysis, model metadata, and
user health data. AI responses are routed through the department dispatcher
and must remain educational rather than diagnostic.
"""

from datetime import datetime

from flask import render_template, jsonify, request
from flask_login import login_required, current_user
from . import doc_bp
from tools._user_scope import authenticated_user_id


@doc_bp.before_request
@login_required
def require_login():
    pass


from .services.doc_service import (
    log_symptoms as svc_log_symptoms,
    get_symptom_history,
    add_medication,
    get_medications,
    update_medication,
    get_health_stats,
    schedule_appointment,
    get_ai_context,
)
import logging

from tools.department_hq.services.department_dispatcher import dispatch_json

BRIDGE_AVAILABLE = True

logger = logging.getLogger(__name__)

# Dr. Amara - Medical Advisor agent ID
MEDICAL_AGENT_ID = 36
MEDICATION_UPDATE_FIELDS = frozenset({"dosage", "frequency", "end_date", "active"})
SYMPTOM_DURATION_VALUES = frozenset({"hours", "day", "days", "week", "weeks"})

MEDICAL_DISCLAIMER = (
    "*Remember: This is general information only. Please consult a healthcare professional "
    "for personal medical advice.*"
)
EMERGENCY_APPENDIX = (
    "*Emergency warning: Symptoms such as chest pain, stroke symptoms, or signs of a heart "
    "attack can be life-threatening. If this may be an emergency, call 911 immediately.*"
)
EMERGENCY_KEYWORDS = ("chest pain", "stroke", "heart attack")

# System prompt for medical AI
MEDICAL_SYSTEM_PROMPT = """\
You are DOC, a helpful medical AI assistant. You provide general health information and guidance.

IMPORTANT RULES:
1. Always remind users that you provide information only, not medical advice
2. Recommend consulting a healthcare professional for specific medical concerns
3. Never diagnose conditions - only provide educational information
4. For emergencies, always advise calling emergency services (911)
5. Be empathetic, clear, and thorough in your explanations
6. When discussing medications, always mention consulting a pharmacist or doctor
7. Provide evidence-based information when possible

You can help with:
- General health information and education
- Understanding symptoms (not diagnosing)
- Wellness tips and preventive care
- Medication information (general)
- Nutrition and exercise guidance
- Mental health awareness

Keep responses helpful but concise. Format with bullet points when listing multiple items."""


def _finalize_medical_response(response, source_text=""):
    """Apply mandatory DOC safety language after model generation."""
    finalized = (response or "").strip()
    lower_response = finalized.lower()

    if "consult a healthcare professional" not in lower_response:
        finalized = f"{finalized}\n\n{MEDICAL_DISCLAIMER}" if finalized else MEDICAL_DISCLAIMER
        lower_response = finalized.lower()

    emergency_text = f"{source_text or ''}\n{finalized}".lower()
    if (
        any(keyword in emergency_text for keyword in EMERGENCY_KEYWORDS)
        and EMERGENCY_APPENDIX.lower() not in lower_response
    ):
        finalized = f"{finalized}\n\n{EMERGENCY_APPENDIX}"

    return finalized


def _parse_severity(value):
    try:
        severity = float(value)
    except (TypeError, ValueError):
        return None

    if not 0 <= severity <= 10:
        return None
    return int(severity) if severity.is_integer() else severity


def _parse_iso8601_datetime(value):
    if not isinstance(value, str) or not value.strip():
        raise ValueError("datetime is required")
    return datetime.fromisoformat(value.strip().replace("Z", "+00:00"))


@doc_bp.route("/")
def index():
    """DOC main page"""
    return render_template("tools/doc.html")


@doc_bp.route("/api/status")
def status():
    """API endpoint for module health check"""
    return jsonify(
        {
            "module": "doc",
            "status": "active",
            "healthy": True,
            "bridge_available": BRIDGE_AVAILABLE,
            "dispatcher_available": True,
            "agent": "Dr. Amara - Medical Advisor",
            "message": "DOC Medical AI is operational via A.R.C.H.I.E. Bridge",
        }
    )


@doc_bp.route("/api/chat", methods=["POST"])
def chat():
    """Send message to medical AI via archie_bridge"""
    data = request.get_json() or {}
    message = data.get("message", "")
    user_id = authenticated_user_id(data.get("user_id"))

    if not message:
        return jsonify({"success": False, "error": "Message is required"}), 400

    # Inject DB context into system prompt
    ai_ctx = get_ai_context(user_id)
    enriched_system_prompt = MEDICAL_SYSTEM_PROMPT + (f"\n\n{ai_ctx}" if ai_ctx else "")

    try:
        result = dispatch_json(
            capability="support",
            prompt=message,
            module_id="doc",
            system_prompt=enriched_system_prompt,
            user_id=user_id,
            local_only=True,
        )
        ai_response = result.get("response", "") if isinstance(result, dict) else str(result or "")
        ai_response = ai_response.strip()

        if not ai_response:
            logger.error("DOC dispatch_json returned empty response")
            return jsonify({"success": False, "error": "AI service temporarily unavailable"}), 503

        ai_response = _finalize_medical_response(ai_response, message)

        return jsonify(
            {
                "success": True,
                "response": ai_response,
                "model": result.get("model_used", "dhq") if isinstance(result, dict) else "dhq",
                "agent": "Dr. Amara - Medical Advisor",
                "source": "dhq_dispatcher",
                "tokens_used": result.get("tokens_used", 0) if isinstance(result, dict) else 0,
            }
        )

    except Exception as e:
        logger.error(f"DOC chat error: {str(e)}")
        return (
            jsonify({"success": False, "error": f"An unexpected error occurred: {str(e)}"}),
            500,
        )


@doc_bp.route("/api/symptoms", methods=["POST"])
def analyze_symptoms():
    """Persist symptom log and analyze symptoms (educational purposes only) via archie_bridge"""
    data = request.get_json() or {}
    symptoms = data.get("symptoms", "")
    severity = data.get("severity", 5)
    duration = data.get("duration", "unknown")
    areas = data.get("areas", [])
    notes = data.get("notes", "")
    user_id = authenticated_user_id(data.get("user_id"))

    if not symptoms:
        return (
            jsonify({"success": False, "error": "Symptoms description is required"}),
            400,
        )

    severity = _parse_severity(severity)
    if severity is None:
        return jsonify({"success": False, "error": "Severity must be between 0 and 10"}), 400

    if duration not in SYMPTOM_DURATION_VALUES:
        return jsonify({"success": False, "error": "Invalid duration"}), 400

    if not isinstance(areas, list) or not areas:
        return jsonify({"success": False, "error": "At least one body area is required"}), 400

    # Persist to DB
    try:
        svc_log_symptoms(user_id, symptoms if isinstance(symptoms, list) else [symptoms], severity, notes)
    except Exception as db_err:
        logger.warning(f"symptom persist failed (non-fatal): {db_err}")

    # Build prompt
    prompt = f"""Based on the following symptoms, provide educational information:

Symptoms: {symptoms}
Severity: {severity}/10
Duration: {duration}
Body areas: {', '.join(areas) if areas else 'not specified'}

Please provide:
1. General information about these types of symptoms
2. Common conditions that might have similar symptoms (NOT a diagnosis)
3. When to seek medical attention
4. General self-care tips that might help

Remember to emphasize consulting a healthcare professional."""

    try:
        result = dispatch_json(
            capability="support",
            prompt=prompt,
            module_id="doc",
            system_prompt=MEDICAL_SYSTEM_PROMPT,
            user_id=user_id,
            local_only=True,
        )
        analysis = result.get("response", "") if isinstance(result, dict) else str(result or "")
        analysis = analysis.strip()

        if not analysis:
            return jsonify({"success": False, "error": "Analysis service unavailable"}), 503

        analysis = _finalize_medical_response(analysis, str(symptoms))

        return jsonify(
            {
                "success": True,
                "analysis": analysis,
                "agent": "Dr. Amara - Medical Advisor",
                "source": "dhq_dispatcher",
            }
        )

    except Exception as e:
        logger.error(f"Symptom analysis error: {str(e)}")
        return jsonify({"success": False, "error": "Could not complete analysis"}), 500


@doc_bp.route("/api/models", methods=["GET"])
def get_available_models():
    """Get available AI models via DHQ dispatcher"""
    models = [{"name": "default", "size": 0, "modified": ""}]
    return jsonify({"success": True, "models": models})


@doc_bp.route("/api/symptoms/history", methods=["GET"])
def symptom_history():
    """Return symptom timeline for current user."""
    user_id = authenticated_user_id(request.args.get("user_id"))
    limit = request.args.get("limit", 20, type=int)
    try:
        history = get_symptom_history(user_id, limit=limit)
        return jsonify({"success": True, "history": history})
    except Exception as e:
        logger.error(f"symptom_history error: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@doc_bp.route("/api/medications", methods=["POST"])
def create_medication():
    """Add a new medication record."""
    data = request.get_json() or {}
    user_id = authenticated_user_id(data.get("user_id"))
    name = data.get("name", "")
    dosage = data.get("dosage", "")
    frequency = data.get("frequency", "")
    start_date = data.get("start_date")

    if not name:
        return jsonify({"success": False, "error": "name is required"}), 400

    try:
        result = add_medication(user_id, name, dosage, frequency, start_date)
        return jsonify({"success": True, **result})
    except Exception as e:
        logger.error(f"create_medication error: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@doc_bp.route("/api/medications", methods=["GET"])
def list_medications():
    """List active medications for current user."""
    user_id = authenticated_user_id(request.args.get("user_id"))
    active_only = request.args.get("active_only", "true").lower() != "false"
    try:
        meds = get_medications(user_id, active_only=active_only)
        return jsonify({"success": True, "medications": meds})
    except Exception as e:
        logger.error(f"list_medications error: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@doc_bp.route("/api/medications/<int:med_id>", methods=["PATCH"])
def patch_medication(med_id):
    """Update whitelisted medication fields for the logged-in user."""
    data = request.get_json(silent=True) or {}
    unknown_fields = sorted(set(data) - MEDICATION_UPDATE_FIELDS - {"user_id"})
    if unknown_fields:
        return (
            jsonify({"success": False, "error": f"Invalid field(s): {', '.join(unknown_fields)}"}),
            400,
        )

    requested_user_id = str(data.get("user_id", current_user.id))
    if requested_user_id != str(current_user.id):
        return jsonify({"success": False, "error": "Forbidden"}), 403

    updates = {field: data[field] for field in MEDICATION_UPDATE_FIELDS if field in data}
    if not updates:
        return jsonify({"success": False, "error": "Nothing to update"}), 400

    try:
        result = update_medication(med_id, current_user.id, updates)
        if not result.get("updated"):
            return jsonify({"success": False, "error": "Medication not found"}), 404
        return jsonify({"success": True, **result})
    except Exception as e:
        logger.error(f"patch_medication error: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@doc_bp.route("/api/schedule", methods=["POST"])
def schedule():
    """Schedule a medical appointment via Google Calendar (or local fallback)."""
    data = request.get_json() or {}
    user_id = authenticated_user_id(data.get("user_id"))
    title = data.get("title", "Medical Appointment")
    datetime_str = data.get("datetime", "")
    duration = data.get("duration", 30)

    if not datetime_str:
        return jsonify({"success": False, "error": "datetime is required"}), 400

    try:
        _parse_iso8601_datetime(datetime_str)
    except ValueError:
        return jsonify({"success": False, "error": "datetime must be ISO8601"}), 400

    try:
        result = schedule_appointment(user_id, title, datetime_str, duration)
        return jsonify({"success": True, "result": result})
    except Exception as e:
        logger.error(f"schedule error: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@doc_bp.route("/api/stats", methods=["GET"])
def stats():
    """Return aggregated health stats for current user."""
    user_id = authenticated_user_id(request.args.get("user_id"))
    try:
        data = get_health_stats(user_id)
        return jsonify({"success": True, **data})
    except Exception as e:
        logger.error(f"stats error: {e}")
        return jsonify({"success": False, "error": str(e)}), 500
