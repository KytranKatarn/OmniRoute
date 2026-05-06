"""
DOC Routes - Medical AI Assistant
Phase 7: Standalone Apps - Uses archie_bridge for local-first AI with team agents
Updated: 2026-01-21 - Now uses Dr. Amara (Medical Advisor) via archie_bridge
"""

from flask import render_template, jsonify, request
from flask_login import login_required, current_user
from . import doc_bp


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
import sys
import logging

# Add ai_bridge to path for archie_bridge import
sys.path.insert(0, "/mnt/archie_brain/ai_bridge")
try:
    from archie_bridge import archie_bridge

    BRIDGE_AVAILABLE = True
except ImportError:
    BRIDGE_AVAILABLE = False

try:
    from ai_bridge.bridge_dispatcher import get_dispatcher

    _dispatcher = get_dispatcher()
except Exception:
    _dispatcher = None

logger = logging.getLogger(__name__)

# Dr. Amara - Medical Advisor agent ID
MEDICAL_AGENT_ID = 36

# Bridge dispatcher for fallback LLM calls
from bridge_dispatcher import dispatch as bridge_dispatch

# System prompt for medical AI
MEDICAL_SYSTEM_PROMPT = """You are DOC, a helpful medical AI assistant. You provide general health information and guidance.

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
            "dispatcher_available": _dispatcher is not None,
            "agent": ("Dr. Amara - Medical Advisor" if BRIDGE_AVAILABLE else "Bridge Dispatcher"),
            "message": (
                "DOC Medical AI is operational via A.R.C.H.I.E. Bridge"
                if BRIDGE_AVAILABLE
                else "DOC Medical AI is operational (bridge dispatch fallback)"
            ),
        }
    )


@doc_bp.route("/api/chat", methods=["POST"])
def chat():
    """Send message to medical AI via archie_bridge"""
    data = request.get_json() or {}
    message = data.get("message", "")
    user_id = data.get("user_id", 1)  # Default to admin user

    if not message:
        return jsonify({"success": False, "error": "Message is required"}), 400

    # Inject DB context into system prompt
    ai_ctx = get_ai_context(user_id)
    enriched_system_prompt = MEDICAL_SYSTEM_PROMPT + (f"\n\n{ai_ctx}" if ai_ctx else "")

    try:
        if BRIDGE_AVAILABLE:
            # Use archie_bridge with Dr. Amara (Medical Advisor)
            result = archie_bridge(
                prompt=message,
                user_id=user_id,
                agent_id=MEDICAL_AGENT_ID,
                system_prompt=enriched_system_prompt,
                enable_memory=True,
                try_local_first=True,  # Check knowledge base first
                task_type="medical_consultation",
            )

            if _dispatcher:
                try:
                    _dispatcher.log_external_call(
                        capability="conversation",
                        module_id="doc",
                        model_used=result.get("model_used", ""),
                        success=bool(result.get("response")),
                    )
                except Exception:
                    pass

            if result.get("success"):
                ai_response = result.get("response", "").strip()

                # Add disclaimer if not present
                if "consult" not in ai_response.lower() and "healthcare" not in ai_response.lower():
                    ai_response += "\n\n*Remember: This is general information only. Please consult a healthcare professional for personal medical advice.*"

                return jsonify(
                    {
                        "success": True,
                        "response": ai_response,
                        "model": result.get("model_used", "archie_bridge"),
                        "agent": "Dr. Amara - Medical Advisor",
                        "source": result.get("source", "ai_bridge"),
                        "tokens_used": result.get("tokens_used", 0),
                    }
                )
            else:
                logger.warning(f"archie_bridge returned error, falling back to direct Ollama")
                # Fall through to direct Ollama call

        # Fallback: Bridge dispatcher
        model = data.get("model") or ""
        result = bridge_dispatch(
            capability="chat",
            prompt=f"{MEDICAL_SYSTEM_PROMPT}\n\nUser: {message}\n\nDOC:",
            model=model,
            module_id="doc",
            timeout=60,
        )

        if result and result.success:
            ai_response = (result.response or "").strip()

            # Add disclaimer if not present
            if "consult" not in ai_response.lower() and "healthcare" not in ai_response.lower():
                ai_response += "\n\n*Remember: This is general information only. Please consult a healthcare professional for personal medical advice.*"

            return jsonify(
                {
                    "success": True,
                    "response": ai_response,
                    "model": "bridge_dispatch",
                    "agent": "Bridge Dispatcher (fallback)",
                    "source": "bridge_dispatch",
                }
            )
        else:
            logger.error("Bridge dispatch failed for DOC chat fallback")
            return (
                jsonify({"success": False, "error": "AI service temporarily unavailable"}),
                503,
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
    user_id = data.get("user_id", 1)

    # Persist to DB
    try:
        svc_log_symptoms(user_id, symptoms if isinstance(symptoms, list) else [symptoms], severity, notes)
    except Exception as db_err:
        logger.warning(f"symptom persist failed (non-fatal): {db_err}")

    if not symptoms:
        return (
            jsonify({"success": False, "error": "Symptoms description is required"}),
            400,
        )

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
        if BRIDGE_AVAILABLE:
            # Use archie_bridge with Dr. Amara
            result = archie_bridge(
                prompt=prompt,
                user_id=user_id,
                agent_id=MEDICAL_AGENT_ID,
                system_prompt=MEDICAL_SYSTEM_PROMPT,
                enable_memory=True,
                try_local_first=True,
                task_type="symptom_analysis",
            )

            if result.get("success"):
                return jsonify(
                    {
                        "success": True,
                        "analysis": result.get("response", "").strip(),
                        "agent": "Dr. Amara - Medical Advisor",
                        "source": result.get("source", "ai_bridge"),
                    }
                )

        # Fallback: Bridge dispatcher
        result = bridge_dispatch(
            capability="chat",
            prompt=f"{MEDICAL_SYSTEM_PROMPT}\n\n{prompt}\n\nDOC:",
            module_id="doc",
            timeout=90,
        )

        if result and result.success:
            return jsonify(
                {
                    "success": True,
                    "analysis": (result.response or "").strip(),
                    "agent": "Bridge Dispatcher (fallback)",
                    "source": "bridge_dispatch",
                }
            )
        else:
            return (
                jsonify({"success": False, "error": "Analysis service unavailable"}),
                503,
            )

    except Exception as e:
        logger.error(f"Symptom analysis error: {str(e)}")
        return jsonify({"success": False, "error": "Could not complete analysis"}), 500


@doc_bp.route("/api/models", methods=["GET"])
def get_available_models():
    """Get available AI models via BridgeDispatcher"""
    # Models come from the bridge dispatcher
    models = []
    if _dispatcher:
        try:
            status = _dispatcher.get_dispatch_status()
            seen = set()
            for station_info in status.get("stations", {}).values():
                for agent in station_info.get("agents", []):
                    m = agent.get("model", "")
                    if m and m not in seen:
                        models.append({"name": m, "size": 0, "modified": ""})
                        seen.add(m)
        except Exception:
            pass
    if not models:
        models = [{"name": "default", "size": 0, "modified": ""}]
    return jsonify({"success": True, "models": models})


@doc_bp.route("/api/symptoms/history", methods=["GET"])
def symptom_history():
    """Return symptom timeline for current user."""
    user_id = request.args.get("user_id", 1, type=int)
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
    user_id = data.get("user_id", 1)
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
    user_id = request.args.get("user_id", 1, type=int)
    active_only = request.args.get("active_only", "true").lower() != "false"
    try:
        meds = get_medications(user_id, active_only=active_only)
        return jsonify({"success": True, "medications": meds})
    except Exception as e:
        logger.error(f"list_medications error: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@doc_bp.route("/api/schedule", methods=["POST"])
def schedule():
    """Schedule a medical appointment via Google Calendar (or local fallback)."""
    data = request.get_json() or {}
    user_id = data.get("user_id", 1)
    title = data.get("title", "Medical Appointment")
    datetime_str = data.get("datetime", "")
    duration = data.get("duration", 30)

    if not datetime_str:
        return jsonify({"success": False, "error": "datetime is required"}), 400

    try:
        result = schedule_appointment(user_id, title, datetime_str, duration)
        return jsonify({"success": True, "result": result})
    except Exception as e:
        logger.error(f"schedule error: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@doc_bp.route("/api/stats", methods=["GET"])
def stats():
    """Return aggregated health stats for current user."""
    user_id = request.args.get("user_id", 1, type=int)
    try:
        data = get_health_stats(user_id)
        return jsonify({"success": True, **data})
    except Exception as e:
        logger.error(f"stats error: {e}")
        return jsonify({"success": False, "error": str(e)}), 500
