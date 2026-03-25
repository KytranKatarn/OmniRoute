"""
A.R.C.H.I.E. CONTENT STUDIO Routes
===================================
AI-powered writing for books, articles, and marketing copy.

Author: A.R.C.H.I.E. Platform
Date: 2026-01-19
"""

import os
from database import _get_db_password
import logging
import time
from datetime import datetime
from flask import render_template, jsonify, request
from flask_login import login_required, current_user
import psycopg2
from psycopg2.extras import RealDictCursor
from . import content_studio_bp

logger = logging.getLogger(__name__)

# Import archie_bridge for AI routing with contractor approval and task logging
try:
    from archie_bridge import archie_bridge
    from ai_bridge.archie_bridge import log_task_execution

    BRIDGE_AVAILABLE = True
except ImportError:
    BRIDGE_AVAILABLE = False
    logger.warning("archie_bridge not available, using fallback")


# Database connection helper
def get_db_connection():
    """Get database connection"""
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "localhost"),
        port=os.getenv("DB_PORT", "5432"),
        database=os.getenv("DB_NAME", "archie"),
        user=os.getenv("DB_USER", "archie"),
        password=_get_db_password(),
    )


# ============================================================================
# MAIN PAGE
# ============================================================================


@content_studio_bp.route("/")
@login_required
def index():
    """Render the Content Studio page"""
    return render_template("tools/content_studio.html")


# ============================================================================
# HEALTH CHECK
# ============================================================================


@content_studio_bp.route("/api/status")
def status():
    """Health check endpoint"""
    return jsonify(
        {
            "module": "content_studio",
            "status": "healthy",
            "healthy": True,
            "message": "Content Studio operational",
        }
    )


# ============================================================================
# STATS API
# ============================================================================


@content_studio_bp.route("/api/stats")
@login_required
def get_stats():
    """Get Content Studio statistics"""
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Get document counts
        cur.execute(
            """
            SELECT
                COUNT(*) as total_documents,
                COUNT(*) FILTER (WHERE status = 'published') as published,
                COALESCE(SUM(word_count), 0) as total_words
            FROM content_documents
            WHERE user_id = %s OR %s = TRUE
        """,
            (
                current_user.id,
                current_user.is_admin if hasattr(current_user, "is_admin") else False,
            ),
        )
        stats = cur.fetchone() or {
            "total_documents": 0,
            "published": 0,
            "total_words": 0,
        }

        return jsonify(
            {
                "success": True,
                "total_documents": stats["total_documents"],
                "published": stats["published"],
                "total_words": int(stats["total_words"]),
            }
        )

    except Exception as e:
        logger.warning(f"Stats query failed (tables may not exist yet): {e}")
        return jsonify({"success": True, "total_documents": 0, "published": 0, "total_words": 0})
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


# ============================================================================
# DOCUMENTS CRUD API
# ============================================================================


@content_studio_bp.route("/api/documents")
@login_required
def get_documents():
    """Get all documents for current user"""
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute(
            """
            SELECT id, title, doc_type, status, word_count,
                   LEFT(content, 200) as excerpt,
                   created_at, updated_at
            FROM content_documents
            WHERE user_id = %s OR %s = TRUE
            ORDER BY updated_at DESC
        """,
            (
                current_user.id,
                current_user.is_admin if hasattr(current_user, "is_admin") else False,
            ),
        )

        documents = cur.fetchall()

        return jsonify({"success": True, "documents": documents})

    except Exception as e:
        logger.warning(f"Documents query failed: {e}")
        return jsonify({"success": True, "documents": []})
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@content_studio_bp.route("/api/documents", methods=["POST"])
@login_required
def create_document():
    """Create a new document"""
    try:
        data = request.get_json()
        title = data.get("title", "Untitled Document")
        doc_type = data.get("doc_type", "article")
        content = data.get("content", "")
        description = data.get("description", "")

        # Calculate word count
        word_count = len(content.split()) if content else 0

        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute(
            """
            INSERT INTO content_documents
            (user_id, title, doc_type, content, description, word_count, status, created_at, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, 'draft', NOW(), NOW())
            RETURNING id, title, doc_type, status, word_count, created_at
        """,
            (current_user.id, title, doc_type, content, description, word_count),
        )

        document = cur.fetchone()
        conn.commit()

        return jsonify(
            {
                "success": True,
                "document": document,
                "message": f'Document "{title}" created successfully',
            }
        )

    except Exception as e:
        logger.error(f"Failed to create document: {e}")
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@content_studio_bp.route("/api/documents/<int:doc_id>")
@login_required
def get_document(doc_id):
    """Get a specific document"""
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute(
            """
            SELECT * FROM content_documents
            WHERE id = %s AND (user_id = %s OR %s = TRUE)
        """,
            (
                doc_id,
                current_user.id,
                current_user.is_admin if hasattr(current_user, "is_admin") else False,
            ),
        )

        document = cur.fetchone()

        if not document:
            return jsonify({"success": False, "error": "Document not found"}), 404

        return jsonify({"success": True, "document": document})

    except Exception as e:
        logger.error(f"Failed to get document: {e}")
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@content_studio_bp.route("/api/documents/<int:doc_id>", methods=["PUT"])
@login_required
def update_document(doc_id):
    """Update a document"""
    try:
        data = request.get_json()
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Build update query dynamically
        updates = []
        values = []
        for field in ["title", "content", "status", "doc_type", "description"]:
            if field in data:
                updates.append(f"{field} = %s")
                values.append(data[field])

        # Recalculate word count if content changed
        if "content" in data:
            word_count = len(data["content"].split()) if data["content"] else 0
            updates.append("word_count = %s")
            values.append(word_count)

        if not updates:
            return jsonify({"success": False, "error": "No fields to update"}), 400

        updates.append("updated_at = NOW()")
        values.extend([doc_id, current_user.id])

        cur.execute(
            f"""
            UPDATE content_documents
            SET {', '.join(updates)}
            WHERE id = %s AND user_id = %s
            RETURNING *
        """,
            values,
        )

        document = cur.fetchone()
        conn.commit()

        return jsonify({"success": True, "document": document})

    except Exception as e:
        logger.error(f"Failed to update document: {e}")
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@content_studio_bp.route("/api/documents/<int:doc_id>", methods=["DELETE"])
@login_required
def delete_document(doc_id):
    """Delete a document"""
    try:
        conn = get_db_connection()
        cur = conn.cursor()

        cur.execute(
            """
            DELETE FROM content_documents
            WHERE id = %s AND user_id = %s
        """,
            (doc_id, current_user.id),
        )

        conn.commit()

        return jsonify({"success": True, "message": "Document deleted successfully"})

    except Exception as e:
        logger.error(f"Failed to delete document: {e}")
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


# ============================================================================
# AI GENERATION API
# ============================================================================


@content_studio_bp.route("/api/ai/generate", methods=["POST"])
@login_required
def ai_generate():
    """Generate content with AI"""
    try:
        data = request.get_json()
        content_type = data.get("type", "article")
        topic = data.get("topic", "")
        tone = data.get("tone", "professional")
        length = data.get("length", "medium")
        keywords = data.get("keywords", "")

        if not topic:
            return jsonify({"success": False, "error": "Topic is required"}), 400

        # Build prompt
        length_words = {"short": 300, "medium": 600, "long": 1000, "extended": 2000}
        target_words = length_words.get(length, 600)

        prompt = f"""Write a {tone} {content_type} about: {topic}

Target length: approximately {target_words} words
Tone: {tone}
{"Keywords to include: " + keywords if keywords else ""}

Please write engaging, well-structured content that is ready to publish."""

        # Call archie_bridge directly for proper routing and logging
        start_time = time.time()
        if BRIDGE_AVAILABLE:
            try:
                result = archie_bridge(
                    prompt=prompt,
                    system_prompt="You are a professional content writer. Create high-quality, engaging content.",
                    task_type="content_generation",
                    user_id=current_user.id,
                    try_local_first=True,
                    use_smart_routing=True,
                    context={
                        "module": "content_studio",
                        "action": "generate",
                        "content_type": content_type,
                        "tone": tone,
                    },
                )
                duration_ms = int((time.time() - start_time) * 1000)

                if result.get("success"):
                    # Log task execution for HR/IAAE tracking
                    try:
                        log_task_execution(
                            agent_id=result.get("agent_id"),
                            task_type="content_generation",
                            module_source="content_studio",
                            model_used=result.get("model_used", "unknown"),
                            provider=result.get("provider", "ollama"),
                            tokens_used=result.get("tokens_used", 0),
                            cost=result.get("cost", 0),
                            duration_ms=duration_ms,
                            success=True,
                            user_id=current_user.id,
                        )
                    except Exception as log_err:
                        logger.warning(f"Failed to log task execution: {log_err}")

                    return jsonify(
                        {
                            "success": True,
                            "content": result.get("response", result.get("content", "")),
                        }
                    )
                else:
                    logger.warning(f"AI bridge returned error: {result.get('error')}")
            except Exception as ai_error:
                logger.warning(f"archie_bridge call failed: {ai_error}")

        # Fallback: Bridge unavailable
        return jsonify({"success": False, "error": "AI Bridge unavailable"}), 503

    except Exception as e:
        logger.error(f"AI generation failed: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@content_studio_bp.route("/api/ai/suggest", methods=["POST"])
@login_required
def ai_suggest():
    """Get AI suggestions for selected text"""
    try:
        data = request.get_json()
        text = data.get("text", "")

        if not text:
            return jsonify({"success": False, "error": "No text provided"}), 400

        prompt = f"""Provide suggestions to improve this text:

"{text}"

Offer:
1. Alternative phrasings
2. Grammar/style improvements
3. Ways to make it more engaging"""

        # Call archie_bridge directly for proper routing and logging
        start_time = time.time()
        if BRIDGE_AVAILABLE:
            try:
                result = archie_bridge(
                    prompt=prompt,
                    system_prompt="You are an expert editor. Provide concise, helpful suggestions.",
                    task_type="content_editing",
                    user_id=current_user.id,
                    try_local_first=True,
                    use_smart_routing=True,
                    context={"module": "content_studio", "action": "suggest"},
                )
                duration_ms = int((time.time() - start_time) * 1000)

                if result.get("success"):
                    # Log task execution
                    try:
                        log_task_execution(
                            agent_id=result.get("agent_id"),
                            task_type="content_editing",
                            module_source="content_studio",
                            model_used=result.get("model_used", "unknown"),
                            provider=result.get("provider", "ollama"),
                            tokens_used=result.get("tokens_used", 0),
                            cost=result.get("cost", 0),
                            duration_ms=duration_ms,
                            success=True,
                            user_id=current_user.id,
                        )
                    except Exception as log_err:
                        logger.warning(f"Failed to log task execution: {log_err}")

                    return jsonify(
                        {
                            "success": True,
                            "suggestion": result.get(
                                "response",
                                result.get("content", "No suggestions available"),
                            ),
                        }
                    )
            except Exception as ai_error:
                logger.warning(f"archie_bridge suggestion call failed: {ai_error}")

        return jsonify(
            {
                "success": True,
                "suggestion": "AI suggestions are being configured. Try again later.",
            }
        )

    except Exception as e:
        logger.error(f"AI suggestion failed: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


# ============================================================================
# EXPORT API
# ============================================================================


@content_studio_bp.route("/api/documents/<int:doc_id>/export", methods=["GET", "POST"])
@login_required
def export_document(doc_id):
    """Export document as Markdown or HTML based on ?format= param"""
    from flask import make_response

    export_format = request.args.get("format") or ((request.get_json(silent=True) or {}).get("format", "markdown"))
    export_format = export_format.lower()

    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(
            """
            SELECT * FROM content_documents
            WHERE id = %s AND (user_id = %s OR %s = TRUE)
            """,
            (
                doc_id,
                current_user.id,
                current_user.is_admin if hasattr(current_user, "is_admin") else False,
            ),
        )
        document = cur.fetchone()

        if not document:
            return jsonify({"success": False, "error": "Document not found"}), 404

        title = document.get("title", "document")
        content = document.get("content") or ""
        safe_title = "".join(c if c.isalnum() or c in " _-" else "_" for c in title)[:80]

        if export_format == "html":
            # Wrap markdown content in minimal HTML
            html_body = content.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            html_out = (
                f"<!DOCTYPE html><html><head><meta charset='utf-8'>"
                f"<title>{title}</title></head><body>"
                f"<h1>{title}</h1><pre style='white-space:pre-wrap'>{html_body}</pre>"
                f"</body></html>"
            )
            resp = make_response(html_out)
            resp.headers["Content-Type"] = "text/html; charset=utf-8"
            resp.headers["Content-Disposition"] = f'attachment; filename="{safe_title}.html"'
            return resp
        else:
            # Default: Markdown
            md_out = f"# {title}\n\n{content}"
            resp = make_response(md_out)
            resp.headers["Content-Type"] = "text/markdown; charset=utf-8"
            resp.headers["Content-Disposition"] = f'attachment; filename="{safe_title}.md"'
            return resp

    except Exception as e:
        logger.error(f"Export failed: {e}")
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


# ============================================================================
# TEMPLATES API
# ============================================================================


@content_studio_bp.route("/api/templates")
@login_required
def get_templates():
    """Get available content templates"""
    templates = [
        {
            "id": 1,
            "name": "Blog Post",
            "desc": "Engaging blog article template",
            "type": "blog",
        },
        {
            "id": 2,
            "name": "Press Release",
            "desc": "Professional PR announcement",
            "type": "article",
        },
        {
            "id": 3,
            "name": "Book Chapter",
            "desc": "Novel chapter with structure",
            "type": "book",
        },
        {
            "id": 4,
            "name": "Product Description",
            "desc": "E-commerce product copy",
            "type": "copy",
        },
        {
            "id": 5,
            "name": "Email Newsletter",
            "desc": "Marketing email template",
            "type": "copy",
        },
        {
            "id": 6,
            "name": "Landing Page",
            "desc": "Conversion-focused copy",
            "type": "copy",
        },
        {
            "id": 7,
            "name": "Social Media Pack",
            "desc": "Multi-platform posts",
            "type": "copy",
        },
        {
            "id": 8,
            "name": "Technical Article",
            "desc": "How-to guide template",
            "type": "article",
        },
        {
            "id": 9,
            "name": "Case Study",
            "desc": "Business success story",
            "type": "article",
        },
        {
            "id": 10,
            "name": "Script/Screenplay",
            "desc": "Video/film script format",
            "type": "script",
        },
        {
            "id": 11,
            "name": "Research Paper",
            "desc": "Academic paper structure",
            "type": "article",
        },
        {
            "id": 12,
            "name": "White Paper",
            "desc": "In-depth industry report",
            "type": "article",
        },
    ]

    return jsonify({"success": True, "templates": templates})


# ============================================================================
# AI WRITING PIPELINE
# ============================================================================

from .services import writing_service  # noqa: E402


@content_studio_bp.route("/api/ai/write", methods=["POST"])
@login_required
def start_writing_pipeline():
    """Start a 5-stage AI writing pipeline session"""
    try:
        data = request.get_json() or {}
        description = data.get("description", "").strip()
        if not description:
            return jsonify({"success": False, "error": "description is required"}), 400

        result = writing_service.start_writing(
            user_id=current_user.id,
            description=description,
            content_type=data.get("content_type", "article"),
            tone=data.get("tone", "professional"),
            template=data.get("template"),
        )
        return jsonify({"success": True, **result})
    except Exception as e:
        logger.error(f"Writing pipeline start failed: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@content_studio_bp.route("/api/ai/write/<int:session_id>", methods=["GET"])
@login_required
def get_writing_status(session_id):
    """Get writing pipeline session status"""
    try:
        session = writing_service.get_writing_status(session_id)
        if not session:
            return jsonify({"success": False, "error": "Session not found"}), 404
        if session["user_id"] != current_user.id:
            return jsonify({"success": False, "error": "Forbidden"}), 403
        return jsonify({"success": True, "session": session})
    except Exception as e:
        logger.error(f"Writing status fetch failed: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@content_studio_bp.route("/api/ai/write/<int:session_id>/approve", methods=["POST"])
@login_required
def approve_writing_checkpoint(session_id):
    """Approve a checkpoint stage and advance the writing pipeline"""
    try:
        session = writing_service.get_writing_status(session_id)
        if not session:
            return jsonify({"success": False, "error": "Session not found"}), 404
        if session["user_id"] != current_user.id:
            return jsonify({"success": False, "error": "Forbidden"}), 403

        result = writing_service.approve_checkpoint(session_id, current_user.id)
        return jsonify(result)
    except Exception as e:
        logger.error(f"Writing checkpoint approval failed: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@content_studio_bp.route("/api/ai/write/<int:session_id>/apply", methods=["POST"])
@login_required
def apply_writing_result(session_id):
    """Publish the final writing session output to a content document"""
    try:
        session = writing_service.get_writing_status(session_id)
        if not session:
            return jsonify({"success": False, "error": "Session not found"}), 404
        if session["user_id"] != current_user.id:
            return jsonify({"success": False, "error": "Forbidden"}), 403

        result = writing_service.apply_writing_result(session_id)
        return jsonify(result)
    except Exception as e:
        logger.error(f"Writing apply failed: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@content_studio_bp.route("/api/ai/assist", methods=["POST"])
@login_required
def ai_assist_inline():
    """Inline AI editor actions: expand, rewrite, summarize, change_tone"""
    try:
        data = request.get_json() or {}
        text = data.get("text", "").strip()
        action = data.get("action", "rewrite")
        context = data.get("context") or {}

        if not text:
            return jsonify({"success": False, "error": "text is required"}), 400

        result = writing_service.ai_assist(text, action, context)
        return jsonify(result)
    except Exception as e:
        logger.error(f"AI assist failed: {e}")
        return jsonify({"success": False, "error": str(e)}), 500
