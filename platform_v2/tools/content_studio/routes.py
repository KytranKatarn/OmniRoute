"""
A.R.C.H.I.E. CONTENT STUDIO Routes
===================================
AI-powered writing for books, articles, and marketing copy.

Author: A.R.C.H.I.E. Platform
Date: 2026-01-19
"""

import os
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
        password=os.getenv("DB_PASSWORD", ""),
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

        cur.close()
        conn.close()

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
        cur.close()
        conn.close()

        return jsonify({"success": True, "documents": documents})

    except Exception as e:
        logger.warning(f"Documents query failed: {e}")
        return jsonify({"success": True, "documents": []})


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
        cur.close()
        conn.close()

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
        cur.close()
        conn.close()

        if not document:
            return jsonify({"success": False, "error": "Document not found"}), 404

        return jsonify({"success": True, "document": document})

    except Exception as e:
        logger.error(f"Failed to get document: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


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
        cur.close()
        conn.close()

        return jsonify({"success": True, "document": document})

    except Exception as e:
        logger.error(f"Failed to update document: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


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
        cur.close()
        conn.close()

        return jsonify({"success": True, "message": "Document deleted successfully"})

    except Exception as e:
        logger.error(f"Failed to delete document: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


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

        # Fallback response
        return jsonify(
            {
                "success": True,
                "content": f"""<h1>{topic}</h1>

<p>This is a placeholder for AI-generated content about "{topic}".</p>

<p>The AI content generation service is currently being configured. Once active, this will generate a {tone} {content_type} of approximately {target_words} words.</p>

<h2>What to Expect</h2>

<p>When the AI service is fully configured, you'll receive:</p>
<ul>
    <li>Well-structured content matching your specified tone</li>
    <li>Proper formatting with headings and paragraphs</li>
    <li>Integration of your specified keywords</li>
    <li>Content optimized for your target audience</li>
</ul>

<p>Please try again later or contact support if this persists.</p>""",
            }
        )

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


@content_studio_bp.route("/api/documents/<int:doc_id>/export", methods=["POST"])
@login_required
def export_document(doc_id):
    """Export document to specified format"""
    try:
        data = request.get_json()
        export_format = data.get("format", "pdf")

        # Get document
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
        cur.close()
        conn.close()

        if not document:
            return jsonify({"success": False, "error": "Document not found"}), 404

        # Placeholder for export logic
        # In production, this would generate PDF/DOCX/etc.
        return jsonify(
            {
                "success": True,
                "message": f"Document export to {export_format.upper()} initiated",
                "document_title": document["title"],
                "format": export_format,
                "status": "pending",
                "download_url": None,  # Will be populated when export is complete
            }
        )

    except Exception as e:
        logger.error(f"Export failed: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


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
