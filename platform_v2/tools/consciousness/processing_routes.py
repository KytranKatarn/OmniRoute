"""
Processing Routes for ARCHIE Consciousness Intelligence

API endpoints for manual batch processing of knowledge extraction.
Handles conversation logs, GitHub files, and Claude Code hooks.

Endpoints:
    GET  /api/processing/status - Overall status and backlog
    GET  /api/processing/backlog - Detailed backlog counts
    POST /api/processing/estimate - Cost estimation for batch
    POST /api/processing/start - Start batch processing
    POST /api/processing/generate-embeddings - Generate missing embeddings
"""

import os
import uuid
import json
import logging
from datetime import datetime
from flask import Blueprint, jsonify, request

logger = logging.getLogger(__name__)

# Create blueprint - no url_prefix since it's registered under consciousness_bp
# Full URL will be: /tools/consciousness/api/processing/*
processing_bp = Blueprint(
    "consciousness_processing",
    __name__,
    url_prefix="/api/processing",
)

# Conversation logs directory
CONVERSATION_LOGS_DIR = "/mnt/archie_brain/conversation_logs"


def get_db():
    """Get database connection"""
    import psycopg2

    return psycopg2.connect(
        host=os.getenv("DB_HOST", "archie_database"),
        database=os.getenv("DB_NAME", "archie"),
        user=os.getenv("DB_USER", "archie"),
        password=os.getenv("DB_PASSWORD", "archiepass"),
    )


@processing_bp.route("/status", methods=["GET"])
def get_processing_status():
    """Get overall processing status"""
    try:
        from ai_bridge.cost_controller import get_daily_cost_status
        from ai_bridge.embedding_service import embedding_health_check
        from ai_bridge.knowledge_analyzer import analyzer_health_check
        from ai_bridge.semantic_search import search_stats
        from ai_bridge.relationship_mapper import graph_stats

        # Get backlog counts
        backlog = _get_backlog_counts()

        # Get service health
        embedding_health = embedding_health_check()
        analyzer_health = analyzer_health_check()

        # Get daily cost status
        cost_status = get_daily_cost_status()

        # Get search stats
        search = search_stats()

        # Get graph stats
        graph = graph_stats()

        return jsonify(
            {
                "success": True,
                "backlog": backlog,
                "services": {
                    "embedding": embedding_health,
                    "analyzer": analyzer_health,
                },
                "cost": cost_status,
                "search": search,
                "graph": graph,
            }
        )
    except Exception as e:
        logger.error(f"Status check failed: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@processing_bp.route("/backlog", methods=["GET"])
def get_backlog():
    """Get detailed backlog counts by category"""
    try:
        backlog = _get_backlog_counts()
        return jsonify({"success": True, **backlog})
    except Exception as e:
        logger.error(f"Backlog check failed: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


def _get_backlog_counts() -> dict:
    """Get counts of unprocessed items by category"""
    counts = {
        "conversations": 0,
        "github": 0,
        "claude_hooks": 0,
        "embeddings_missing": 0,
        "total": 0,
    }

    try:
        conn = get_db()
        cur = conn.cursor()

        # Count conversation logs without AI analysis
        cur.execute(
            """
            SELECT COUNT(*) FROM knowledge_base
            WHERE source_type = 'conversation_log'
            AND (ai_analysis IS NULL OR analysis_version = 0)
            """
        )
        counts["conversations"] = cur.fetchone()[0]

        # Count GitHub files without AI analysis
        cur.execute(
            """
            SELECT COUNT(*) FROM knowledge_base
            WHERE source_type = 'github'
            AND (ai_analysis IS NULL OR analysis_version = 0)
            """
        )
        counts["github"] = cur.fetchone()[0]

        # Count Claude hooks without AI analysis
        cur.execute(
            """
            SELECT COUNT(*) FROM knowledge_base
            WHERE source_type = 'claude_hook'
            AND (ai_analysis IS NULL OR analysis_version = 0)
            """
        )
        counts["claude_hooks"] = cur.fetchone()[0]

        # Count entries missing embeddings
        cur.execute(
            """
            SELECT COUNT(*) FROM knowledge_base
            WHERE embedding IS NULL
            AND content IS NOT NULL
            AND LENGTH(content) > 50
            """
        )
        counts["embeddings_missing"] = cur.fetchone()[0]

        # Also count unprocessed conversation log files
        if os.path.exists(CONVERSATION_LOGS_DIR):
            log_files = [
                f
                for f in os.listdir(CONVERSATION_LOGS_DIR)
                if f.startswith(("snapshot_", "transcript_")) and f.endswith((".json", ".md"))
            ]

            # Check which are already ingested
            cur.execute(
                """
                SELECT COUNT(*) FROM knowledge_base
                WHERE source_type = 'conversation_log'
                """
            )
            ingested_count = cur.fetchone()[0]
            counts["log_files_total"] = len(log_files)
            counts["log_files_pending"] = max(0, len(log_files) - ingested_count)

        cur.close()
        conn.close()

        counts["total"] = counts["conversations"] + counts["github"] + counts["claude_hooks"]

    except Exception as e:
        logger.error(f"Failed to get backlog counts: {e}")

    return counts


@processing_bp.route("/estimate", methods=["POST"])
def estimate_batch():
    """Estimate cost for processing a batch"""
    try:
        from ai_bridge.cost_controller import get_cost_controller

        data = request.get_json() or {}
        category = data.get("category", "conversations")
        batch_size = min(int(data.get("batch_size", 10)), 100)  # Max 100

        controller = get_cost_controller()
        estimate = controller.estimate_batch(batch_size, category)

        return jsonify(
            {
                "success": True,
                "category": category,
                "batch_size": batch_size,
                "estimated_tokens": estimate.estimated_total_tokens,
                "estimated_cost_usd": estimate.estimated_cost_usd,
                "within_daily_limit": estimate.within_daily_limit,
                "would_exceed_by_tokens": estimate.would_exceed_by_tokens,
                "would_exceed_by_usd": estimate.would_exceed_by_usd,
            }
        )
    except Exception as e:
        logger.error(f"Estimate failed: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@processing_bp.route("/start", methods=["POST"])
def start_processing():
    """Start batch processing"""
    try:
        from ai_bridge.cost_controller import get_cost_controller
        from ai_bridge.knowledge_analyzer import get_knowledge_analyzer
        from ai_bridge.embedding_service import generate_embedding
        from ai_bridge.knowledge_cards import save_knowledge_card
        from ai_bridge.relationship_mapper import get_relationship_mapper

        data = request.get_json() or {}
        category = data.get("category", "conversations")
        batch_size = min(int(data.get("batch_size", 10)), 50)  # Max 50 per batch

        # Check cost limits
        controller = get_cost_controller()
        estimate = controller.estimate_batch(batch_size, category)

        if not estimate.within_daily_limit:
            return (
                jsonify(
                    {
                        "success": False,
                        "error": "Would exceed daily limit",
                        "would_exceed_by_tokens": estimate.would_exceed_by_tokens,
                        "would_exceed_by_usd": estimate.would_exceed_by_usd,
                    }
                ),
                400,
            )

        # Generate batch ID
        batch_id = str(uuid.uuid4())

        # Get items to process
        conn = get_db()
        cur = conn.cursor()

        source_type_map = {
            "conversations": "conversation_log",
            "github": "github",
            "claude_hooks": "claude_hook",
        }
        source_type = source_type_map.get(category, "conversation_log")

        cur.execute(
            """
            SELECT id, title, content, memory_metadata
            FROM knowledge_base
            WHERE source_type = %s
            AND (ai_analysis IS NULL OR analysis_version = 0)
            AND content IS NOT NULL
            AND LENGTH(content) > 100
            ORDER BY created_at DESC
            LIMIT %s
            """,
            (source_type, batch_size),
        )
        items = cur.fetchall()
        cur.close()
        conn.close()

        if not items:
            return jsonify({"success": True, "message": "No items to process", "processed": 0})

        # Process items
        analyzer = get_knowledge_analyzer()
        mapper = get_relationship_mapper()
        results = {
            "batch_id": batch_id,
            "processed": 0,
            "cards_created": 0,
            "relationships_created": 0,
            "errors": [],
            "log": [],
        }

        total_input_tokens = 0
        total_output_tokens = 0

        for item_id, title, content, metadata in items:
            try:
                # Parse metadata
                if isinstance(metadata, str):
                    metadata = json.loads(metadata)
                metadata = metadata or {}

                # Add source reference
                metadata["source_id"] = item_id
                metadata["source_type"] = source_type

                # Analyze with Claude
                if category == "conversations":
                    result = analyzer.analyze_conversation(content, metadata)
                else:
                    result = analyzer.analyze_code_file(content, title or "unknown", metadata.get("language"))

                if not result.success:
                    results["errors"].append({"id": item_id, "error": result.error})
                    results["log"].append(f"[{item_id}] Error: {result.error}")
                    continue

                total_input_tokens += result.input_tokens
                total_output_tokens += result.output_tokens

                # Save knowledge cards
                title_to_id = {}
                for card in result.cards:
                    card.source_ref = str(item_id)
                    embedding = generate_embedding(f"{card.title}. {card.summary}")
                    card_id = save_knowledge_card(card, embedding, batch_id)
                    if card_id:
                        results["cards_created"] += 1
                        title_to_id[card.title] = card_id

                # Create relationships
                for card_id in title_to_id.values():
                    rel_stats = mapper.create_relationships_batch(result.relationships, card_id, title_to_id)
                    results["relationships_created"] += rel_stats["created"]

                # Update source entry with analysis
                _update_source_analysis(item_id, result, batch_id)

                results["processed"] += 1
                results["log"].append(
                    f"[{item_id}] {len(result.cards)} cards, " f"{len(result.relationships)} relationships"
                )

            except Exception as e:
                logger.error(f"Processing item {item_id} failed: {e}")
                results["errors"].append({"id": item_id, "error": str(e)})
                results["log"].append(f"[{item_id}] Exception: {str(e)}")

        # Record usage
        if total_input_tokens > 0:
            controller.record_usage(total_input_tokens, total_output_tokens)

        results["total_tokens"] = total_input_tokens + total_output_tokens
        results["success"] = True

        # Log to processing log table
        _log_batch_processing(batch_id, category, results)

        return jsonify(results)

    except Exception as e:
        logger.error(f"Processing failed: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


def _update_source_analysis(item_id: int, result, batch_id: str):
    """Update source entry with analysis results"""
    try:
        conn = get_db()
        cur = conn.cursor()

        ai_analysis = {
            "cards_extracted": len(result.cards),
            "relationships_extracted": len(result.relationships),
            "input_tokens": result.input_tokens,
            "output_tokens": result.output_tokens,
            "processing_time_ms": result.processing_time_ms,
            "batch_id": batch_id,
            "analyzed_at": datetime.now().isoformat(),
        }

        cur.execute(
            """
            UPDATE knowledge_base
            SET ai_analysis = %s, analysis_version = 1
            WHERE id = %s
            """,
            (json.dumps(ai_analysis), item_id),
        )
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        logger.error(f"Failed to update source analysis: {e}")


def _log_batch_processing(batch_id: str, category: str, results: dict):
    """Log batch processing to knowledge_processing_log"""
    try:
        conn = get_db()
        cur = conn.cursor()

        cur.execute(
            """
            INSERT INTO knowledge_processing_log
                (batch_id, source_type, status, cards_created,
                 relationships_created, tokens_used, metadata, completed_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, NOW())
            """,
            (
                batch_id,
                category,
                "completed" if results["processed"] > 0 else "failed",
                results["cards_created"],
                results["relationships_created"],
                results.get("total_tokens", 0),
                json.dumps(
                    {
                        "processed": results["processed"],
                        "errors": len(results["errors"]),
                        "log": results["log"][:20],  # Limit log size
                    }
                ),
            ),
        )
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        logger.error(f"Failed to log batch: {e}")


@processing_bp.route("/generate-embeddings", methods=["POST"])
def generate_embeddings():
    """Generate embeddings for entries that don't have them"""
    try:
        from ai_bridge.embedding_service import generate_embedding

        data = request.get_json() or {}
        batch_size = min(int(data.get("batch_size", 50)), 200)

        conn = get_db()
        cur = conn.cursor()

        # Get entries without embeddings
        cur.execute(
            """
            SELECT id, title, content
            FROM knowledge_base
            WHERE embedding IS NULL
            AND content IS NOT NULL
            AND LENGTH(content) > 50
            ORDER BY created_at DESC
            LIMIT %s
            """,
            (batch_size,),
        )
        items = cur.fetchall()

        results = {"processed": 0, "failed": 0, "total": len(items)}

        for item_id, title, content in items:
            try:
                # Generate embedding from title + content summary
                text = f"{title or ''}. {content[:2000]}"
                embedding = generate_embedding(text)

                if embedding:
                    cur.execute(
                        """
                        UPDATE knowledge_base
                        SET embedding = %s, embedding_generated_at = NOW()
                        WHERE id = %s
                        """,
                        (embedding, item_id),
                    )
                    results["processed"] += 1
                else:
                    results["failed"] += 1

            except Exception as e:
                logger.error(f"Embedding for {item_id} failed: {e}")
                results["failed"] += 1

        conn.commit()
        cur.close()
        conn.close()

        results["success"] = True
        return jsonify(results)

    except Exception as e:
        logger.error(f"Embedding generation failed: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@processing_bp.route("/history", methods=["GET"])
def get_processing_history():
    """Get recent processing history"""
    try:
        limit = min(int(request.args.get("limit", 20)), 100)

        conn = get_db()
        cur = conn.cursor()

        cur.execute(
            """
            SELECT batch_id, source_type, status, cards_created,
                   relationships_created, tokens_used, created_at, completed_at
            FROM knowledge_processing_log
            ORDER BY created_at DESC
            LIMIT %s
            """,
            (limit,),
        )

        rows = cur.fetchall()
        cur.close()
        conn.close()

        history = []
        for row in rows:
            history.append(
                {
                    "batch_id": row[0],
                    "source_type": row[1],
                    "status": row[2],
                    "cards_created": row[3],
                    "relationships_created": row[4],
                    "tokens_used": row[5],
                    "created_at": str(row[6]) if row[6] else None,
                    "completed_at": str(row[7]) if row[7] else None,
                }
            )

        return jsonify({"success": True, "history": history})

    except Exception as e:
        logger.error(f"History fetch failed: {e}")
        return jsonify({"success": False, "error": str(e)}), 500
