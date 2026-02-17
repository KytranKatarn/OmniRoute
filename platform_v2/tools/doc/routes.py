"""
DOC Routes - Medical AI Assistant
Phase 7: Standalone Apps - Uses archie_bridge for local-first AI with team agents
Updated: 2026-01-21 - Now uses Dr. Amara (Medical Advisor) via archie_bridge
"""

from flask import render_template, jsonify, request
from . import doc_bp
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

# Fallback Ollama endpoint (if bridge unavailable)
OLLAMA_URL = "http://localhost:11434"

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
    import requests as req

    # Check Ollama connection (fallback)
    ollama_healthy = False
    try:
        response = req.get(f"{OLLAMA_URL}/api/tags", timeout=5)
        ollama_healthy = response.status_code == 200
    except:
        pass

    return jsonify(
        {
            "module": "doc",
            "status": "active",
            "healthy": True,
            "bridge_available": BRIDGE_AVAILABLE,
            "ollama_connected": ollama_healthy,
            "agent": ("Dr. Amara - Medical Advisor" if BRIDGE_AVAILABLE else "Direct Ollama"),
            "message": (
                "DOC Medical AI is operational via A.R.C.H.I.E. Bridge"
                if BRIDGE_AVAILABLE
                else "DOC Medical AI is operational (fallback mode)"
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

    try:
        if BRIDGE_AVAILABLE:
            # Use archie_bridge with Dr. Amara (Medical Advisor)
            result = archie_bridge(
                prompt=message,
                user_id=user_id,
                agent_id=MEDICAL_AGENT_ID,
                system_prompt=MEDICAL_SYSTEM_PROMPT,
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

        # Fallback: Direct Ollama call
        import requests as req

        _default_model = _dispatcher.get_model_for_capability("conversation") if _dispatcher else ""
        model = data.get("model") or _default_model
        response = req.post(
            f"{OLLAMA_URL}/api/generate",
            json={
                "model": model,
                "prompt": f"{MEDICAL_SYSTEM_PROMPT}\n\nUser: {message}\n\nDOC:",
                "stream": False,
                "options": {"temperature": 0.7, "num_predict": 1000},
            },
            timeout=60,
        )

        if response.status_code == 200:
            result = response.json()
            ai_response = result.get("response", "").strip()

            # Add disclaimer if not present
            if "consult" not in ai_response.lower() and "healthcare" not in ai_response.lower():
                ai_response += "\n\n*Remember: This is general information only. Please consult a healthcare professional for personal medical advice.*"

            return jsonify(
                {
                    "success": True,
                    "response": ai_response,
                    "model": model,
                    "agent": "Direct Ollama (fallback)",
                    "source": "ollama_direct",
                }
            )
        else:
            logger.error(f"Ollama error: {response.status_code}")
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
    """Analyze symptoms (educational purposes only) via archie_bridge"""
    data = request.get_json() or {}
    symptoms = data.get("symptoms", "")
    severity = data.get("severity", 5)
    duration = data.get("duration", "unknown")
    areas = data.get("areas", [])
    user_id = data.get("user_id", 1)

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

        # Fallback: Direct Ollama call
        import requests as req

        _default_model = _dispatcher.get_model_for_capability("conversation") if _dispatcher else ""
        _fallback_model = _default_model or "dolphin3-8k:latest"
        response = req.post(
            f"{OLLAMA_URL}/api/generate",
            json={
                "model": _fallback_model,
                "prompt": f"{MEDICAL_SYSTEM_PROMPT}\n\n{prompt}\n\nDOC:",
                "stream": False,
                "options": {"temperature": 0.5, "num_predict": 1500},
            },
            timeout=90,
        )

        if response.status_code == 200:
            result = response.json()
            if _dispatcher:
                try:
                    _dispatcher.log_external_call(
                        capability="conversation",
                        module_id="doc",
                        model_used=_fallback_model,
                        success=True,
                    )
                except Exception:
                    pass
            return jsonify(
                {
                    "success": True,
                    "analysis": result.get("response", "").strip(),
                    "agent": "Direct Ollama (fallback)",
                    "source": "ollama_direct",
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
