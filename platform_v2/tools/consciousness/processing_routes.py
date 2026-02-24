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
import threading
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

# --- Server-side processing lock ---
import threading
import time as _time

_processing_lock = threading.Lock()
_active_jobs = {}  # type -> { "session": str, "started": float, "processed": int }

# Lock timeout: if a job hasn't been refreshed in 120s, consider it stale
_LOCK_TIMEOUT = 120


def _cleanup_stale_locks():
    """Remove locks that haven't been refreshed recently"""
    now = _time.time()
    stale = [t for t, j in _active_jobs.items() if now - j.get("heartbeat", j["started"]) > _LOCK_TIMEOUT]
    for t in stale:
        del _active_jobs[t]


@processing_bp.route("/lock/status", methods=["GET"])
def get_lock_status():
    """Check which processing types are currently locked"""
    with _processing_lock:
        _cleanup_stale_locks()
        return jsonify(
            {
                "success": True,
                "active": {
                    t: {
                        "session": j["session"],
                        "processed": j["processed"],
                        "elapsed": round(_time.time() - j["started"]),
                    }
                    for t, j in _active_jobs.items()
                },
            }
        )


@processing_bp.route("/lock/acquire", methods=["POST"])
def acquire_lock():
    """Acquire a processing lock for a type. Returns session_id on success."""
    data = request.get_json() or {}
    proc_type = data.get("type", "")
    if not proc_type:
        return jsonify({"success": False, "error": "type required"}), 400

    with _processing_lock:
        _cleanup_stale_locks()
        if proc_type in _active_jobs:
            existing = _active_jobs[proc_type]
            return (
                jsonify(
                    {
                        "success": False,
                        "error": "busy",
                        "session": existing["session"],
                        "processed": existing["processed"],
                        "elapsed": round(_time.time() - existing["started"]),
                    }
                ),
                409,
            )

        session_id = str(uuid.uuid4())[:8]
        _active_jobs[proc_type] = {
            "session": session_id,
            "started": _time.time(),
            "heartbeat": _time.time(),
            "processed": 0,
        }
        return jsonify({"success": True, "session": session_id})


@processing_bp.route("/lock/heartbeat", methods=["POST"])
def heartbeat_lock():
    """Keep a lock alive + update processed count"""
    data = request.get_json() or {}
    proc_type = data.get("type", "")
    session_id = data.get("session", "")

    with _processing_lock:
        job = _active_jobs.get(proc_type)
        if not job or job["session"] != session_id:
            return jsonify({"success": False, "error": "no matching lock"}), 404
        job["heartbeat"] = _time.time()
        job["processed"] = data.get("processed", job["processed"])
        return jsonify({"success": True})


@processing_bp.route("/lock/release", methods=["POST"])
def release_lock():
    """Release a processing lock"""
    data = request.get_json() or {}
    proc_type = data.get("type", "")
    session_id = data.get("session", "")

    with _processing_lock:
        job = _active_jobs.get(proc_type)
        if job and job["session"] == session_id:
            del _active_jobs[proc_type]
        return jsonify({"success": True})


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
            WHERE knowledge_type = 'github_file'
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

        # Count entries missing embeddings (exclude archived archie_v1)
        cur.execute(
            """
            SELECT COUNT(*) FROM knowledge_base
            WHERE embedding IS NULL
            AND content IS NOT NULL
            AND LENGTH(content) > 50
            AND source_type != 'archie_v1'
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


def _run_analysis_job(items_data, category, batch_id, job_id):
    """Background worker for knowledge analysis.

    Runs in a separate thread so the HTTP request returns immediately.
    """
    from ai_bridge.cost_controller import get_cost_controller
    from ai_bridge.knowledge_analyzer import get_knowledge_analyzer
    from ai_bridge.embedding_service import generate_embedding
    from ai_bridge.knowledge_cards import save_knowledge_card
    from ai_bridge.relationship_mapper import get_relationship_mapper
    from ai_bridge.bridge_dispatcher import get_dispatcher

    dispatcher = get_dispatcher()
    analyzer = get_knowledge_analyzer()
    mapper = get_relationship_mapper()
    controller = get_cost_controller()

    processed = 0
    errors = 0
    cards_created = 0
    total_input_tokens = 0
    total_output_tokens = 0

    try:
        for item_id, title, content, metadata in items_data:
            try:
                if isinstance(metadata, str):
                    metadata = json.loads(metadata)
                metadata = metadata or {}
                metadata["source_id"] = item_id

                if category == "conversations":
                    result = analyzer.analyze_conversation(content, metadata)
                else:
                    result = analyzer.analyze_code_file(content, title or "unknown", metadata.get("language"))

                if not result.success:
                    errors += 1
                    if job_id:
                        dispatcher.update_job_progress(job_id, processed, errors)
                    continue

                total_input_tokens += result.input_tokens
                total_output_tokens += result.output_tokens

                title_to_id = {}
                for card in result.cards:
                    card.source_ref = str(item_id)
                    embedding = generate_embedding(f"{card.title}. {card.summary}")
                    card_id = save_knowledge_card(card, embedding, batch_id)
                    if card_id:
                        cards_created += 1
                        title_to_id[card.title] = card_id

                for card_id in title_to_id.values():
                    mapper.create_relationships_batch(result.relationships, card_id, title_to_id)

                _update_source_analysis(item_id, result, batch_id)
                processed += 1

                if job_id:
                    dispatcher.update_job_progress(job_id, processed, errors, {"cards_created": cards_created})

            except Exception as e:
                logger.error(f"Processing item {item_id} failed: {e}")
                errors += 1
                if job_id:
                    dispatcher.update_job_progress(job_id, processed, errors)

        if total_input_tokens > 0:
            controller.record_usage(total_input_tokens, total_output_tokens)

        _log_batch_processing(
            batch_id,
            category,
            {
                "batch_id": batch_id,
                "processed": processed,
                "cards_created": cards_created,
                "errors": [{"count": errors}],
                "log": [],
            },
        )

    except Exception as e:
        logger.error(f"Analysis background job failed: {e}")
    finally:
        if job_id:
            dispatcher.complete_job(job_id)
        logger.info(f"[Analysis] Job #{job_id} finished: {processed} ok, {errors} failed, {cards_created} cards")


@processing_bp.route("/start", methods=["POST"])
def start_processing():
    """Start batch processing via Bridge job system.

    Creates a bridge_job and returns the job_id immediately.
    Work runs in a background thread with progress tracked in Bridge Command.
    """
    try:
        from ai_bridge.cost_controller import get_cost_controller
        from ai_bridge.knowledge_analyzer import get_knowledge_analyzer
        from ai_bridge.bridge_dispatcher import get_dispatcher

        data = request.get_json() or {}
        category = data.get("category", "conversations")
        batch_size = min(int(data.get("batch_size", 10)), 50)  # Max 50 per batch

        # Warm up Ollama model to avoid cold-start crashes
        analyzer = get_knowledge_analyzer()
        if not analyzer.warmup():
            return (
                jsonify(
                    {
                        "success": False,
                        "error": "Analyzer model failed to warm up. Try again in a few seconds.",
                    }
                ),
                503,
            )

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
            "conversations": "source_type = 'conversation_log'",
            "github": "knowledge_type = 'github_file'",
            "claude_hooks": "source_type = 'claude_hook'",
        }
        type_filter = source_type_map.get(category, "source_type = 'conversation_log'")

        cur.execute(
            f"""
            SELECT id, title, content, memory_metadata
            FROM knowledge_base
            WHERE {type_filter}
            AND (ai_analysis IS NULL OR analysis_version = 0)
            AND content IS NOT NULL
            AND LENGTH(content) > 100
            ORDER BY created_at DESC
            LIMIT %s
            """,
            (batch_size,),
        )
        items = cur.fetchall()
        cur.close()
        conn.close()

        if not items:
            return jsonify({"success": True, "message": "No items to process", "processed": 0})

        # ── Create Bridge Job (blocks duplicates) ───────────
        dispatcher = get_dispatcher()
        job_id = dispatcher.create_job(
            job_type="batch_analysis",
            module_source="consciousness",
            description=f"Analyze {len(items)} {category} entries (batch {batch_size})",
            total_steps=len(items),
            capability="code_analysis",
            metadata={"category": category, "batch_id": batch_id, "batch_size": batch_size},
        )

        if not job_id:
            return (
                jsonify(
                    {
                        "success": False,
                        "error": "An analysis job is already running — check Bridge Command for progress",
                        "duplicate": True,
                    }
                ),
                409,
            )

        # ── Launch background thread ────────────────────────
        thread = threading.Thread(
            target=_run_analysis_job,
            args=(list(items), category, batch_id, job_id),
            daemon=True,
        )
        thread.start()

        return jsonify(
            {
                "success": True,
                "job_id": job_id,
                "batch_id": batch_id,
                "total": len(items),
                "message": f"Analysis job #{job_id} started — {len(items)} {category} entries queued",
            }
        )

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


def _auto_embed_processed_items(item_ids: list) -> dict:
    """Generate embeddings for a list of knowledge_base IDs after processing"""
    results = {"processed": 0, "failed": 0}
    if not item_ids:
        return results

    try:
        from ai_bridge.embedding_service import generate_embedding

        conn = get_db()
        cur = conn.cursor()

        for item_id in item_ids:
            try:
                cur.execute(
                    """
                    SELECT title, content FROM knowledge_base
                    WHERE id = %s AND embedding IS NULL
                    AND content IS NOT NULL AND LENGTH(content) > 50
                    """,
                    (item_id,),
                )
                row = cur.fetchone()
                if not row:
                    continue

                title, content = row
                text = f"{title or ''}. {content[:2000]}"
                embedding = generate_embedding(text)

                if embedding:
                    cur.execute(
                        """
                        UPDATE knowledge_base
                        SET embedding = %s, has_embedding = true, embedding_generated_at = NOW()
                        WHERE id = %s
                        """,
                        (embedding, item_id),
                    )
                    results["processed"] += 1
                else:
                    results["failed"] += 1
            except Exception as e:
                logger.error(f"Auto-embed for {item_id} failed: {e}")
                results["failed"] += 1

        conn.commit()
        cur.close()
        conn.close()
        logger.info(f"Auto-embedded {results['processed']}/{len(item_ids)} items")
    except Exception as e:
        logger.error(f"Auto-embed batch failed: {e}")

    return results


def _run_embedding_job(item_ids_and_data, job_id):
    """Background worker for embedding generation.

    Runs in a separate thread so the HTTP request can return immediately.
    Updates progress via Bridge dispatcher.
    """
    from ai_bridge.embedding_service import generate_embedding
    from ai_bridge.bridge_dispatcher import get_dispatcher

    dispatcher = get_dispatcher()
    processed = 0
    failed = 0

    try:
        conn = get_db()
        cur = conn.cursor()

        for item_id, title, content in item_ids_and_data:
            try:
                text = f"{title or ''}. {content[:2000]}"
                embedding = generate_embedding(text)

                if embedding:
                    cur.execute(
                        """
                        UPDATE knowledge_base
                        SET embedding = %s, has_embedding = true, embedding_generated_at = NOW()
                        WHERE id = %s
                        """,
                        (embedding, item_id),
                    )
                    processed += 1
                else:
                    failed += 1

                if job_id:
                    dispatcher.update_job_progress(job_id, processed, failed)

            except Exception as e:
                logger.error(f"Embedding for {item_id} failed: {e}")
                failed += 1
                if job_id:
                    dispatcher.update_job_progress(job_id, processed, failed)

        conn.commit()
        cur.close()
        conn.close()

    except Exception as e:
        logger.error(f"Embedding background job failed: {e}")
    finally:
        if job_id:
            dispatcher.complete_job(job_id)
        logger.info(f"[Embedding] Job #{job_id} finished: {processed} ok, {failed} failed")


@processing_bp.route("/generate-embeddings", methods=["POST"])
def generate_embeddings():
    """Generate embeddings for entries that don't have them.

    Creates a bridge_job and returns the job_id immediately.
    Work runs in a background thread with progress tracked in Bridge Command.
    """
    try:
        from ai_bridge.bridge_dispatcher import get_dispatcher

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
        cur.close()
        conn.close()

        if not items:
            return jsonify({"success": True, "message": "All entries already embedded", "processed": 0, "total": 0})

        # ── Create Bridge Job (blocks duplicates) ───────────
        dispatcher = get_dispatcher()
        job_id = dispatcher.create_job(
            job_type="batch_embedding",
            module_source="consciousness",
            description=f"Generate embeddings for {len(items)} knowledge entries",
            total_steps=len(items),
            capability="embedding",
            metadata={"batch_size": batch_size, "requested_at": datetime.now().isoformat()},
        )

        if not job_id:
            return (
                jsonify(
                    {
                        "success": False,
                        "error": "An embedding job is already running — check Bridge Command for progress",
                        "duplicate": True,
                    }
                ),
                409,
            )

        # ── Launch background thread ────────────────────────
        thread = threading.Thread(
            target=_run_embedding_job,
            args=(list(items), job_id),
            daemon=True,
        )
        thread.start()

        # Return immediately so frontend can poll Bridge
        return jsonify(
            {
                "success": True,
                "job_id": job_id,
                "total": len(items),
                "message": f"Embedding job #{job_id} started — {len(items)} entries queued",
            }
        )

    except Exception as e:
        logger.error(f"Embedding generation failed: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@processing_bp.route("/embedding-coverage", methods=["GET"])
def get_embedding_coverage():
    """Get embedding coverage broken down by source_type"""
    try:
        conn = get_db()
        cur = conn.cursor()

        cur.execute(
            """
            SELECT COALESCE(NULLIF(source_type, ''), 'uncategorized') as source_type,
                   COUNT(*) as total,
                   COALESCE(SUM(CASE WHEN embedding IS NOT NULL THEN 1 ELSE 0 END), 0) as embedded,
                   COALESCE(SUM(CASE WHEN ai_analysis IS NOT NULL THEN 1 ELSE 0 END), 0) as analyzed
            FROM knowledge_base
            GROUP BY COALESCE(NULLIF(source_type, ''), 'uncategorized')
            ORDER BY total DESC
            """
        )
        rows = cur.fetchall()

        types = []
        total_all = 0
        embedded_all = 0
        analyzed_all = 0
        for row in rows:
            types.append(
                {
                    "source_type": row[0],
                    "total": row[1],
                    "embedded": row[2],
                    "analyzed": row[3],
                }
            )
            # Exclude archived legacy entries from global coverage metrics
            if row[0] != "archie_v1":
                total_all += row[1]
                embedded_all += row[2]
                analyzed_all += row[3]

        cur.close()
        conn.close()

        return jsonify(
            {
                "success": True,
                "types": types,
                "totals": {
                    "total": total_all,
                    "embedded": embedded_all,
                    "analyzed": analyzed_all,
                },
            }
        )
    except Exception as e:
        logger.error(f"Embedding coverage failed: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@processing_bp.route("/job-status/<int:job_id>", methods=["GET"])
def get_job_status(job_id):
    """Get live status of a bridge job by ID.

    Returns the job's agent, progress counters, status, and metadata
    so the frontend can render a progress bar.
    """
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute(
            """
            SELECT bj.id, bj.job_type, bj.description,
                   bj.total_steps, bj.completed_steps, bj.failed_steps,
                   bj.status, bj.agent_name, bj.metadata,
                   bj.created_at, bj.updated_at, bj.completed_at,
                   COALESCE(
                       NULLIF(CONCAT_WS(' ', a.first_name, a.last_name), ''),
                       a.name,
                       bj.agent_name
                   ) as agent_display
            FROM bridge_jobs bj
            LEFT JOIN agents a ON a.name = bj.agent_name AND a.status = 'active'
            WHERE bj.id = %s
            """,
            (job_id,),
        )
        row = cur.fetchone()
        cur.close()
        conn.close()

        if not row:
            return jsonify({"success": False, "error": "Job not found"}), 404

        return jsonify(
            {
                "success": True,
                "job": {
                    "id": row[0],
                    "job_type": row[1],
                    "description": row[2],
                    "total_steps": row[3],
                    "completed_steps": row[4] or 0,
                    "failed_steps": row[5] or 0,
                    "status": row[6],
                    "agent_name": row[7],
                    "metadata": row[8] if isinstance(row[8], dict) else json.loads(row[8] or "{}"),
                    "created_at": row[9].isoformat() if row[9] else None,
                    "updated_at": row[10].isoformat() if row[10] else None,
                    "completed_at": row[11].isoformat() if row[11] else None,
                    "agent_display": row[12],
                },
            }
        )
    except Exception as e:
        logger.error(f"Job status lookup failed: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@processing_bp.route("/active-jobs", methods=["GET"])
def get_active_jobs():
    """Return any currently running bridge jobs from the consciousness module.

    The frontend uses this to:
    - Show live status of in-progress work (agent name, progress bar)
    - Disable action buttons so users can't double-trigger jobs
    """
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute(
            """
            SELECT bj.id, bj.job_type, bj.description,
                   bj.total_steps, bj.completed_steps, bj.failed_steps,
                   bj.status, bj.agent_name, bj.metadata,
                   bj.created_at, bj.updated_at,
                   COALESCE(
                       NULLIF(CONCAT_WS(' ', a.first_name, a.last_name), ''),
                       a.name,
                       bj.agent_name
                   ) as agent_display
            FROM bridge_jobs bj
            LEFT JOIN agents a ON a.name = bj.agent_name AND a.status = 'active'
            WHERE bj.module_source = 'consciousness'
              AND bj.status IN ('pending', 'running')
            ORDER BY bj.created_at DESC
            """,
        )
        rows = cur.fetchall()
        cur.close()
        conn.close()

        jobs = []
        for row in rows:
            jobs.append(
                {
                    "id": row[0],
                    "job_type": row[1],
                    "description": row[2],
                    "total_steps": row[3],
                    "completed_steps": row[4] or 0,
                    "failed_steps": row[5] or 0,
                    "status": row[6],
                    "agent_name": row[7],
                    "metadata": row[8] if isinstance(row[8], dict) else json.loads(row[8] or "{}"),
                    "created_at": row[9].isoformat() if row[9] else None,
                    "updated_at": row[10].isoformat() if row[10] else None,
                    "agent_display": row[11],
                }
            )

        return jsonify({"success": True, "jobs": jobs})
    except Exception as e:
        logger.error(f"Active jobs lookup failed: {e}")
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
