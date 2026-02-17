"""
A.R.C.H.I.E. Improvement API
HTTP endpoints for the self-improvement system
"""

from flask import Flask, request, jsonify
from flask_cors import CORS
import sys

sys.path.insert(0, "/app/ai_bridge")
from improvement_engine import (
    detect_improvement_opportunities,
    propose_improvement,
    analyze_proposal_with_agents,
    get_recent_proposals,
    run_auto_improvement_detection,
)
from improvement_chat import (
    chat_about_improvements,
    discuss_proposal,
    self_reflection_chat,
)

app = Flask(__name__)
CORS(app)  # Enable CORS for frontend integration


@app.route("/api/improvements/detect", methods=["POST"])
def detect_improvements():
    """
    Run automatic improvement detection

    POST /api/improvements/detect
    {}

    Returns:
        {
            "success": bool,
            "opportunities_detected": int,
            "proposals_created": int,
            "breakdown": Dict,
            "opportunities": List[Dict]
        }
    """
    try:
        summary = run_auto_improvement_detection()
        opportunities = detect_improvement_opportunities()

        return (
            jsonify({"success": True, **summary, "opportunities": opportunities}),
            200,
        )

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/improvements/chat", methods=["POST"])
def improvement_chat():
    """
    Chat about improvements

    POST /api/improvements/chat
    {
        "message": str (required),
        "user_id": int (optional),
        "conversation_id": int (optional),
        "agent": str (optional)
    }

    Returns:
        {
            "success": bool,
            "response": str,
            "conversation_id": int,
            "improvements_detected": List[Dict],
            "proposals_created": List[Dict]
        }
    """
    try:
        data = request.get_json()

        if not data or "message" not in data:
            return (
                jsonify({"success": False, "error": "Missing required field: message"}),
                400,
            )

        result = chat_about_improvements(
            user_message=data["message"],
            user_id=data.get("user_id"),
            conversation_id=data.get("conversation_id"),
            use_specific_agent=data.get("agent"),
        )

        return jsonify(result), 200 if result.get("success") else 500

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/improvements/proposals", methods=["GET"])
def list_proposals():
    """
    Get improvement proposals

    GET /api/improvements/proposals?status=proposed&category=quality&limit=20

    Returns:
        {
            "success": bool,
            "proposals": List[Dict],
            "count": int
        }
    """
    try:
        status = request.args.get("status")
        category = request.args.get("category")
        limit = int(request.args.get("limit", 20))

        proposals = get_recent_proposals(limit=limit, status=status, category=category)

        return (
            jsonify({"success": True, "proposals": proposals, "count": len(proposals)}),
            200,
        )

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/improvements/proposals/<int:proposal_id>", methods=["GET"])
def get_proposal(proposal_id):
    """
    Get specific proposal details

    GET /api/improvements/proposals/123

    Returns:
        {
            "success": bool,
            "proposal": Dict
        }
    """
    try:
        proposals = get_recent_proposals(limit=1000)  # Get all
        proposal = next((p for p in proposals if p["id"] == proposal_id), None)

        if not proposal:
            return jsonify({"success": False, "error": "Proposal not found"}), 404

        return jsonify({"success": True, "proposal": proposal}), 200

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/improvements/proposals", methods=["POST"])
def create_proposal():
    """
    Create new improvement proposal

    POST /api/improvements/proposals
    {
        "title": str (required),
        "description": str (required),
        "category": str (required),
        "priority": str (optional, default: medium),
        "user_id": int (optional)
    }

    Returns:
        {
            "success": bool,
            "proposal": Dict
        }
    """
    try:
        data = request.get_json()

        if not data:
            return jsonify({"success": False, "error": "No JSON data provided"}), 400

        required_fields = ["title", "description", "category"]
        for field in required_fields:
            if field not in data:
                return (
                    jsonify(
                        {"success": False, "error": f"Missing required field: {field}"}
                    ),
                    400,
                )

        proposal = propose_improvement(
            title=data["title"],
            description=data["description"],
            category=data["category"],
            priority=data.get("priority", "medium"),
            proposed_by_user_id=data.get("user_id"),
            auto_detected=False,
        )

        return jsonify({"success": True, "proposal": proposal}), 201

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/improvements/proposals/<int:proposal_id>/analyze", methods=["POST"])
def analyze_proposal(proposal_id):
    """
    Analyze proposal with agents

    POST /api/improvements/proposals/123/analyze
    {}

    Returns:
        {
            "success": bool,
            "analysis": Dict
        }
    """
    try:
        analysis = analyze_proposal_with_agents(proposal_id)

        if "error" in analysis:
            return jsonify({"success": False, "error": analysis["error"]}), 404

        return jsonify({"success": True, "analysis": analysis}), 200

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/improvements/proposals/<int:proposal_id>/discuss", methods=["POST"])
def discuss_proposal_endpoint(proposal_id):
    """
    Discuss specific proposal

    POST /api/improvements/proposals/123/discuss
    {
        "message": str (required),
        "user_id": int (optional)
    }

    Returns:
        {
            "success": bool,
            "response": str,
            "proposal": Dict
        }
    """
    try:
        data = request.get_json()

        if not data or "message" not in data:
            return (
                jsonify({"success": False, "error": "Missing required field: message"}),
                400,
            )

        result = discuss_proposal(
            proposal_id=proposal_id,
            user_message=data["message"],
            user_id=data.get("user_id"),
        )

        return jsonify(result), 200 if result.get("success") else 500

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/improvements/self-reflect", methods=["POST"])
def self_reflect():
    """
    A.R.C.H.I.E. self-reflection

    POST /api/improvements/self-reflect
    {
        "topic": str (optional),
        "user_id": int (optional)
    }

    Returns:
        {
            "success": bool,
            "reflection": str,
            "personality": Dict,
            "opportunities_count": int
        }
    """
    try:
        data = request.get_json() or {}

        result = self_reflection_chat(
            topic=data.get("topic"), user_id=data.get("user_id")
        )

        return jsonify(result), 200 if result.get("success") else 500

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/improvements/health", methods=["GET"])
def health_check():
    """Health check endpoint"""
    return (
        jsonify(
            {
                "status": "healthy",
                "service": "archie_improvement_api",
                "version": "1.0.0",
            }
        ),
        200,
    )


if __name__ == "__main__":
    # Run API server
    print("🚀 Starting A.R.C.H.I.E. Improvement API on port 5002...")
    app.run(host="0.0.0.0", port=5002, debug=True)
