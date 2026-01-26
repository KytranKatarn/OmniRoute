"""
Conversation Triage API Routes
Phase 42: Knowledge extraction endpoints
"""

import os
import psycopg2
from flask import Blueprint, request, jsonify
import logging

from .triage_pipeline import TriagePipeline, triage_conversation

logger = logging.getLogger(__name__)

triage_bp = Blueprint('triage', __name__, url_prefix='/api/triage')


def get_db():
    """Get database connection."""
    return psycopg2.connect(
        host=os.getenv('DB_HOST', 'archie_database'),
        port=os.getenv('DB_PORT', '5432'),
        database=os.getenv('DB_NAME', 'archie'),
        user=os.getenv('DB_USER', 'archie'),
        password=os.getenv('DB_PASSWORD', '')
    )


@triage_bp.route('/process', methods=['POST'])
def process_conversation():
    """
    Trigger triage on a conversation.

    POST body:
    {
        "content": "conversation text...",
        "conversation_id": 123  // optional
    }
    """
    try:
        data = request.get_json()
        if not data or 'content' not in data:
            return jsonify({'error': 'content is required'}), 400

        content = data['content']
        conversation_id = data.get('conversation_id')

        db = get_db()
        result = triage_conversation(content, db, conversation_id)

        return jsonify({
            'success': True,
            'result': result
        })

    except Exception as e:
        logger.error(f"Triage error: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@triage_bp.route('/queue', methods=['GET'])
def get_queue():
    """Get pending conversations in triage queue."""
    try:
        db = get_db()
        if not db:
            return jsonify({'error': 'Database not available'}), 500

        cursor = db.cursor()
        cursor.execute("""
            SELECT id, conversation_id, status, priority, primary_topic,
                   conversation_phase, urgency_score, created_at, processed_at
            FROM conversation_triage_queue
            ORDER BY
                CASE status WHEN 'pending' THEN 0 WHEN 'processing' THEN 1 ELSE 2 END,
                priority DESC,
                created_at ASC
            LIMIT 50
        """)

        columns = [desc[0] for desc in cursor.description]
        rows = cursor.fetchall()
        queue = [dict(zip(columns, row)) for row in rows]

        return jsonify({
            'success': True,
            'queue': queue,
            'count': len(queue)
        })

    except Exception as e:
        logger.error(f"Queue error: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@triage_bp.route('/stats', methods=['GET'])
def get_stats():
    """Get triage statistics."""
    try:
        db = get_db()
        if not db:
            return jsonify({'error': 'Database not available'}), 500

        cursor = db.cursor()

        # Queue stats
        cursor.execute("SELECT * FROM triage_stats")
        columns = [desc[0] for desc in cursor.description]
        rows = cursor.fetchall()
        queue_stats = [dict(zip(columns, row)) for row in rows]

        # Extraction stats
        cursor.execute("SELECT * FROM extraction_stats")
        columns = [desc[0] for desc in cursor.description]
        rows = cursor.fetchall()
        extraction_stats = [dict(zip(columns, row)) for row in rows]

        # Recent activity
        cursor.execute("""
            SELECT DATE(created_at) as date, COUNT(*) as count
            FROM conversation_triage_queue
            WHERE created_at > NOW() - INTERVAL '7 days'
            GROUP BY DATE(created_at)
            ORDER BY date DESC
        """)
        daily_activity = cursor.fetchall()

        return jsonify({
            'success': True,
            'queue_stats': queue_stats,
            'extraction_stats': extraction_stats,
            'daily_activity': [{'date': str(d), 'count': c} for d, c in daily_activity]
        })

    except Exception as e:
        logger.error(f"Stats error: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@triage_bp.route('/extract/errors', methods=['GET'])
def get_extracted_errors():
    """Get extracted errors from triage."""
    try:
        db = get_db()
        if not db:
            return jsonify({'error': 'Database not available'}), 500

        limit = request.args.get('limit', 20, type=int)
        offset = request.args.get('offset', 0, type=int)

        cursor = db.cursor()
        cursor.execute("""
            SELECT te.id, te.title, te.content, te.severity, te.confidence_score,
                   te.knowledge_base_id, te.promoted_at, te.created_at,
                   tq.conversation_id, tq.primary_topic
            FROM triage_extractions te
            JOIN conversation_triage_queue tq ON te.triage_id = tq.id
            WHERE te.extraction_type = 'error'
            ORDER BY te.created_at DESC
            LIMIT %s OFFSET %s
        """, (limit, offset))

        columns = [desc[0] for desc in cursor.description]
        rows = cursor.fetchall()
        errors = [dict(zip(columns, row)) for row in rows]

        return jsonify({
            'success': True,
            'errors': errors,
            'count': len(errors)
        })

    except Exception as e:
        logger.error(f"Errors extraction error: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@triage_bp.route('/extract/snippets', methods=['GET'])
def get_extracted_snippets():
    """Get extracted code snippets from triage."""
    try:
        db = get_db()
        if not db:
            return jsonify({'error': 'Database not available'}), 500

        limit = request.args.get('limit', 20, type=int)
        offset = request.args.get('offset', 0, type=int)
        language = request.args.get('language')

        cursor = db.cursor()

        query = """
            SELECT te.id, te.title, te.content, te.language, te.confidence_score,
                   te.knowledge_base_id, te.promoted_at, te.created_at,
                   tq.conversation_id, tq.primary_topic
            FROM triage_extractions te
            JOIN conversation_triage_queue tq ON te.triage_id = tq.id
            WHERE te.extraction_type = 'code_snippet'
        """
        params = []

        if language:
            query += " AND te.language = %s"
            params.append(language)

        query += " ORDER BY te.created_at DESC LIMIT %s OFFSET %s"
        params.extend([limit, offset])

        cursor.execute(query, params)

        columns = [desc[0] for desc in cursor.description]
        rows = cursor.fetchall()
        snippets = [dict(zip(columns, row)) for row in rows]

        return jsonify({
            'success': True,
            'snippets': snippets,
            'count': len(snippets)
        })

    except Exception as e:
        logger.error(f"Snippets extraction error: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@triage_bp.route('/extract/insights', methods=['GET'])
def get_extracted_insights():
    """Get extracted insights from triage."""
    try:
        db = get_db()
        if not db:
            return jsonify({'error': 'Database not available'}), 500

        limit = request.args.get('limit', 20, type=int)
        offset = request.args.get('offset', 0, type=int)

        cursor = db.cursor()
        cursor.execute("""
            SELECT te.id, te.title, te.content, te.confidence_score,
                   te.knowledge_base_id, te.promoted_at, te.created_at,
                   tq.conversation_id, tq.primary_topic
            FROM triage_extractions te
            JOIN conversation_triage_queue tq ON te.triage_id = tq.id
            WHERE te.extraction_type IN ('insight', 'decision', 'todo')
            ORDER BY te.created_at DESC
            LIMIT %s OFFSET %s
        """, (limit, offset))

        columns = [desc[0] for desc in cursor.description]
        rows = cursor.fetchall()
        insights = [dict(zip(columns, row)) for row in rows]

        return jsonify({
            'success': True,
            'insights': insights,
            'count': len(insights)
        })

    except Exception as e:
        logger.error(f"Insights extraction error: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@triage_bp.route('/promote/<int:extraction_id>', methods=['POST'])
def promote_extraction(extraction_id):
    """Promote an extraction to the knowledge base."""
    try:
        db = get_db()
        if not db:
            return jsonify({'error': 'Database not available'}), 500

        data = request.get_json() or {}
        importance = data.get('importance_score', 0.85)

        cursor = db.cursor()

        # Call the promote_extraction function
        cursor.execute("SELECT promote_extraction(%s, %s)", (extraction_id, importance))
        knowledge_id = cursor.fetchone()[0]

        db.commit()

        return jsonify({
            'success': True,
            'knowledge_base_id': knowledge_id,
            'message': f'Extraction {extraction_id} promoted to knowledge base entry {knowledge_id}'
        })

    except Exception as e:
        logger.error(f"Promote error: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@triage_bp.route('/batch', methods=['POST'])
def batch_process():
    """
    Batch process multiple pending conversations.

    POST body:
    {
        "limit": 10  // optional, default 5
    }
    """
    try:
        db = get_db()
        if not db:
            return jsonify({'error': 'Database not available'}), 500

        data = request.get_json() or {}
        limit = min(data.get('limit', 5), 20)  # Max 20 at once

        cursor = db.cursor()

        # Get pending conversations from knowledge_base that aren't yet triaged
        cursor.execute("""
            SELECT kb.id, kb.content
            FROM knowledge_base kb
            WHERE kb.knowledge_type = 'conversation_memory'
            AND NOT EXISTS (
                SELECT 1 FROM conversation_triage_queue tq
                WHERE tq.conversation_id = kb.id
            )
            ORDER BY kb.created_at DESC
            LIMIT %s
        """, (limit,))

        pending = cursor.fetchall()

        if not pending:
            return jsonify({
                'success': True,
                'processed': 0,
                'message': 'No pending conversations to triage'
            })

        pipeline = TriagePipeline(db)
        processed = []

        for conv_id, content in pending:
            try:
                result = pipeline.process(content, conv_id)
                processed.append({
                    'conversation_id': conv_id,
                    'topic': result.classification.primary_topic,
                    'extractions': len(result.errors) + len(result.code_snippets) + len(result.insights)
                })
            except Exception as e:
                logger.error(f"Failed to triage conversation {conv_id}: {e}")

        return jsonify({
            'success': True,
            'processed': len(processed),
            'results': processed
        })

    except Exception as e:
        logger.error(f"Batch error: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500
