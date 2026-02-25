"""
A.R.C.H.I.E. External API
API endpoints for integration with n8n, call handling system, and external services
"""

from flask import Blueprint, request, jsonify
import psycopg2
from psycopg2.extras import RealDictCursor
import os
import json
from datetime import datetime
import time
from .ai_chat import ArchieAI
from .ha_bridge import register_ha_routes

archie_api_bp = Blueprint("archie_api", __name__, url_prefix="/api/archie")
register_ha_routes(archie_api_bp)


def get_db():
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "archie_database"),
        port=os.getenv("DB_PORT", "5432"),
        database=os.getenv("DB_NAME", "archie"),
        user=os.getenv("DB_USER", "archie"),
        password=os.getenv("DB_PASSWORD", ""),
    )


def require_api_key(f):
    """Decorator to require API key authentication"""

    def decorated_function(*args, **kwargs):
        api_key = request.headers.get("Authorization")

        if not api_key:
            return jsonify({"error": "No API key provided"}), 401

        # Remove 'Bearer ' prefix if present
        if api_key.startswith("Bearer "):
            api_key = api_key[7:]

        # Verify API key (for now, check against environment variable)
        valid_key = os.getenv("ARCHIE_API_KEY", "dev-api-key-change-in-production")

        if api_key != valid_key:
            return jsonify({"error": "Invalid API key"}), 401

        return f(*args, **kwargs)

    decorated_function.__name__ = f.__name__
    return decorated_function


@archie_api_bp.route("/health", methods=["GET"])
def health_check():
    """
    Health check endpoint for monitoring
    Returns system status, model availability, and performance metrics
    """
    try:
        conn = get_db()
        cur = conn.cursor()

        # Test database connection
        cur.execute("SELECT 1")
        db_healthy = True

        # Get recent performance metrics
        cur.execute(
            """
            SELECT
                COUNT(*) as total_requests,
                AVG(EXTRACT(EPOCH FROM (created_at - created_at))) as avg_latency
            FROM ai_conversations
            WHERE created_at > NOW() - INTERVAL '5 minutes'
        """
        )
        perf = cur.fetchone()

        # Check AI service availability
        try:
            ai = ArchieAI()
            ai_healthy = True
            models_loaded = [ai.primary_server, ai.secondary_server] if hasattr(ai, "primary_server") else ["ollama"]
        except Exception as e:
            ai_healthy = False
            models_loaded = []

        status = "healthy" if (db_healthy and ai_healthy) else "degraded"

        return (
            jsonify(
                {
                    "status": status,
                    "timestamp": datetime.now().isoformat(),
                    "components": {
                        "database": {"status": "operational" if db_healthy else "error"},
                        "ai_service": {"status": "operational" if ai_healthy else "error"},
                    },
                    "models_loaded": models_loaded,
                    "performance": {
                        "requests_last_5min": perf[0] if perf else 0,
                        "avg_latency_ms": int((perf[1] or 0) * 1000),
                    },
                }
            ),
            200,
        )

    except Exception as e:
        return (
            jsonify(
                {
                    "status": "error",
                    "error": str(e),
                    "timestamp": datetime.now().isoformat(),
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


@archie_api_bp.route("/search", methods=["POST"])
@require_api_key
def knowledge_search():
    """
    Search A.R.C.H.I.E.'s knowledge base

    Request Body:
    {
        "query": "search query text",
        "category": "technical_docs" (optional),
        "context": {...} (optional),
        "limit": 5 (optional),
        "min_confidence": 0.7 (optional)
    }

    Response:
    {
        "results": [...],
        "query_time_ms": 145,
        "total_results": 2
    }
    """
    try:
        data = request.get_json()

        if not data or "query" not in data:
            return jsonify({"success": False, "error": "No query provided"}), 400

        query = data["query"]
        category = data.get("category")
        limit = data.get("limit", 5)
        min_confidence = data.get("min_confidence", 0.7)

        start_time = time.time()

        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Search in long_term_memory for relevant knowledge
        search_query = """
            SELECT
                id,
                content as title,
                content,
                memory_type as category,
                importance_score as confidence,
                source,
                created_at as last_updated
            FROM long_term_memory
            WHERE
                (content ILIKE %s OR tags::text ILIKE %s)
                AND importance_score >= %s
        """

        params = [f"%{query}%", f"%{query}%", min_confidence]

        if category:
            search_query += " AND memory_type = %s"
            params.append(category)

        search_query += " ORDER BY importance_score DESC LIMIT %s"
        params.append(limit)

        cur.execute(search_query, params)
        results = cur.fetchall()

        # Also search in ai_conversations for relevant context
        cur.execute(
            """
            SELECT DISTINCT ON (message)
                id,
                message as title,
                response as content,
                0.8 as confidence,
                'conversation_history' as source,
                created_at as last_updated
            FROM ai_conversations
            WHERE message ILIKE %s OR response ILIKE %s
            ORDER BY message, created_at DESC
            LIMIT %s
        """,
            (f"%{query}%", f"%{query}%", limit),
        )

        conversation_results = cur.fetchall()

        # Combine and format results
        all_results = []

        for r in results:
            all_results.append(
                {
                    "id": str(r["id"]),
                    "title": r["title"][:100] if r["title"] else "Knowledge Entry",
                    "content": r["content"],
                    "confidence": float(r["confidence"]) if r["confidence"] else 0.8,
                    "source": r.get("source", "internal_kb"),
                    "last_updated": (r["last_updated"].isoformat() if r["last_updated"] else None),
                    "category": r.get("category", "general"),
                }
            )

        for r in conversation_results:
            all_results.append(
                {
                    "id": str(r["id"]),
                    "title": r["title"][:100],
                    "content": r["content"],
                    "confidence": 0.75,
                    "source": "conversation_history",
                    "last_updated": (r["last_updated"].isoformat() if r["last_updated"] else None),
                    "category": "support_history",
                }
            )

        # Sort by confidence and limit
        all_results.sort(key=lambda x: x["confidence"], reverse=True)
        all_results = all_results[:limit]

        query_time = int((time.time() - start_time) * 1000)

        return (
            jsonify(
                {
                    "success": True,
                    "results": all_results,
                    "query_time_ms": query_time,
                    "total_results": len(all_results),
                }
            ),
            200,
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


@archie_api_bp.route("/chat", methods=["POST"])
@require_api_key
def chat_inference():
    """
    Conversational inference endpoint

    Request Body:
    {
        "messages": [
            {"role": "user", "content": "message text"}
        ],
        "context": {...} (optional),
        "model": "archie-7b-instruct" (optional),
        "max_tokens": 512 (optional),
        "temperature": 0.7 (optional),
        "stream": false (optional)
    }

    Response:
    {
        "response": "AI response text",
        "confidence": 0.88,
        "model_used": "archie-7b-instruct",
        "generation_time_ms": 1250,
        "tokens_used": 87,
        "sources_referenced": [...]
    }
    """
    try:
        data = request.get_json()

        if not data or "messages" not in data:
            return jsonify({"success": False, "error": "No messages provided"}), 400

        messages = data["messages"]
        context = data.get("context", {})
        max_tokens = data.get("max_tokens", 512)
        temperature = data.get("temperature", 0.7)

        if not messages or len(messages) == 0:
            return jsonify({"success": False, "error": "Messages array is empty"}), 400

        # Get the last user message
        last_message = messages[-1]["content"]

        start_time = time.time()

        # Use ArchieAI for inference
        ai = ArchieAI()
        response_data = ai.chat(last_message, context, messages[:-1] if len(messages) > 1 else [])

        if not response_data["success"]:
            return (
                jsonify(
                    {
                        "success": False,
                        "error": f"AI inference failed: {response_data.get('error', 'Unknown error')}",
                    }
                ),
                503,
            )

        generation_time = int((time.time() - start_time) * 1000)

        return (
            jsonify(
                {
                    "success": True,
                    "response": response_data["response"],
                    "confidence": 0.85,  # Default confidence, can be enhanced later
                    "model_used": response_data.get("model", "unknown"),
                    "generation_time_ms": generation_time,
                    "tokens_used": response_data.get("tokens", 0),
                    "sources_referenced": [],  # Can be enhanced to track sources
                }
            ),
            200,
        )

    except Exception as e:
        import traceback

        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500


@archie_api_bp.route("/learn", methods=["POST"])
@require_api_key
def learning_feedback():
    """
    Submit learning/feedback data to A.R.C.H.I.E.

    Request Body:
    {
        "conversation_id": "uuid",
        "transcript": [...],
        "insights": {...},
        "outcome": "success | escalated | failed",
        "feedback": {...}
    }

    Response:
    {
        "success": true,
        "learning_job_id": "uuid",
        "status": "queued"
    }
    """
    try:
        data = request.get_json()

        if not data:
            return jsonify({"success": False, "error": "No data provided"}), 400

        conversation_id = data.get("conversation_id")
        transcript = data.get("transcript", [])
        insights = data.get("insights", {})
        outcome = data.get("outcome", "unknown")
        feedback = data.get("feedback", {})

        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Store learning data in long_term_memory
        learning_content = {
            "conversation_id": conversation_id,
            "insights": insights,
            "outcome": outcome,
            "feedback": feedback,
        }

        # Calculate importance score based on outcome
        importance_score = 0.5
        if outcome == "success":
            importance_score = 0.8
        elif outcome == "failed":
            importance_score = 0.9  # Learn more from failures

        cur.execute(
            """
            INSERT INTO long_term_memory
            (content, memory_type, importance_score, source, metadata, tags)
            VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING id
        """,
            (
                json.dumps(learning_content),
                "learning_data",
                importance_score,
                "call_system",
                json.dumps(feedback),
                json.dumps(["call_handling", outcome]),
            ),
        )

        learning_id = cur.fetchone()["id"]

        # Store insights as separate memory entries for better retrieval
        if insights:
            for key, value in insights.items():
                if value and (isinstance(value, list) and len(value) > 0):
                    cur.execute(
                        """
                        INSERT INTO long_term_memory
                        (content, memory_type, importance_score, source, tags)
                        VALUES (%s, %s, %s, %s, %s)
                    """,
                        (
                            json.dumps({key: value}),
                            "insight",
                            0.7,
                            "call_system",
                            json.dumps([key, "call_handling"]),
                        ),
                    )

        conn.commit()

        return (
            jsonify(
                {
                    "success": True,
                    "learning_job_id": str(learning_id),
                    "status": "completed",
                    "message": "Learning data stored successfully",
                }
            ),
            202,
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


@archie_api_bp.route("/learn/batch", methods=["POST"])
@require_api_key
def batch_learning():
    """
    Submit batch learning data

    Request Body:
    {
        "conversations": [
            {
                "id": "uuid",
                "transcript": [...],
                "outcome": "resolved",
                "satisfaction": 4.5,
                "insights": {...}
            },
            ...
        ],
        "learning_mode": "incremental"
    }

    Response:
    {
        "job_id": "uuid",
        "conversations_queued": 50,
        "estimated_completion": "ISO8601"
    }
    """
    try:
        data = request.get_json()

        if not data or "conversations" not in data:
            return (
                jsonify({"success": False, "error": "No conversations provided"}),
                400,
            )

        conversations = data["conversations"]
        learning_mode = data.get("learning_mode", "incremental")

        conn = get_db()
        cur = conn.cursor()

        processed_count = 0
        for conv in conversations:
            learning_data = {
                "conversation_id": conv.get("id"),
                "outcome": conv.get("outcome"),
                "satisfaction": conv.get("satisfaction"),
                "insights": conv.get("insights", {}),
            }

            cur.execute(
                """
                INSERT INTO long_term_memory
                (content, memory_type, importance_score, source, tags)
                VALUES (%s, %s, %s, %s, %s)
            """,
                (
                    json.dumps(learning_data),
                    "batch_learning",
                    0.7,
                    "call_system_batch",
                    json.dumps(["batch_learning", learning_mode]),
                ),
            )

            processed_count += 1

        conn.commit()

        # Create a batch learning job record
        job_id = str(datetime.now().timestamp()).replace(".", "")

        return (
            jsonify(
                {
                    "success": True,
                    "job_id": job_id,
                    "conversations_queued": processed_count,
                    "estimated_completion": datetime.now().isoformat(),
                    "status": "completed",
                }
            ),
            202,
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


@archie_api_bp.route("/learn/status/<job_id>", methods=["GET"])
@require_api_key
def learning_status(job_id):
    """
    Check the status of a learning job

    Response:
    {
        "job_id": "uuid",
        "status": "processing",
        "progress_percent": 65,
        "improvements_detected": [...]
    }
    """
    try:
        # For now, return a simple completed status
        # In the future, this could track actual background processing
        return (
            jsonify(
                {
                    "success": True,
                    "job_id": job_id,
                    "status": "completed",
                    "progress_percent": 100,
                    "improvements_detected": ["Learning data processed successfully"],
                }
            ),
            200,
        )

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
