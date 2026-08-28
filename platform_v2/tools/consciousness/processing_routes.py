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
from database import _get_db_password
import uuid
import json
import logging
import threading
from datetime import datetime
from flask import Blueprint, jsonify, request
from services.department_coordinator import get_coordinator

logger = logging.getLogger(__name__)

# Create blueprint - no url_prefix since it's registered under consciousness_bp
# Full URL will be: /tools/consciousness/api/processing/*
processing_bp = Blueprint(
    "consciousness_processing",
    __name__,
    url_prefix="/api/processing",
)


@processing_bp.before_request
def _require_admin():
    """Require authentication and admin access for all processing routes."""
    from flask_login import current_user

    if not current_user.is_authenticated:
        return jsonify({"error": "Authentication required"}), 401
    if not getattr(current_user, "is_admin", False):
        return jsonify({"error": "Admin access required"}), 403


# Conversation logs directory
CONVERSATION_LOGS_DIR = "/mnt/archie_brain/conversation_logs"

# --- Server-side processing lock ---
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
        password=_get_db_password(),
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
    conn = None
    cur = None

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
        counts["total"] = counts["conversations"] + counts["github"] + counts["claude_hooks"]

    except Exception as e:
        logger.error(f"Failed to get backlog counts: {e}")
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()

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

    Uses KnowledgeAnalyzer directly for LLM calls (proper model selection,
    no format:json constraint that chokes thinking models like qwen3).
    Bridge job lifecycle is still tracked for the 3D bridge view.
    External calls are logged for HR/welfare tracking.
    """
    from ai_bridge.knowledge_analyzer import get_knowledge_analyzer
    from ai_bridge.embedding_service import generate_embedding
    from ai_bridge.knowledge_cards import save_knowledge_card
    from ai_bridge.relationship_mapper import get_relationship_mapper
    from tools.department_hq.services.department_dispatcher import get_dispatcher

    dispatcher = get_dispatcher()
    analyzer = get_knowledge_analyzer()
    mapper = get_relationship_mapper()
    enforce_local = get_local_only_mode()

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
                metadata["source_ref"] = str(item_id)

                if not content or len(content.strip()) < 100:
                    errors += 1
                    if job_id:
                        dispatcher.update_job_progress(job_id, processed, errors)
                    continue

                # Use analyzer directly — it picks the right model
                # (dolphin3-8k GPU for chat, avoids format:json constraint
                # that produces empty responses with qwen3 thinking models)
                # local_only controlled by consciousness_local_only system_config
                if category == "conversations":
                    result = analyzer.analyze_conversation(content, metadata, job_id=job_id, local_only=enforce_local)
                else:
                    result = analyzer.analyze_code_file(
                        content,
                        filename=title or "unknown",
                        language=metadata.get("language"),
                        job_id=job_id,
                        local_only=enforce_local,
                    )

                if not result.success:
                    logger.warning(f"[Analysis] Analyzer failed for item {item_id}: " f"{result.error}")
                    errors += 1
                    if job_id:
                        dispatcher.update_job_progress(job_id, processed, errors)
                    continue

                total_input_tokens += result.input_tokens
                total_output_tokens += result.output_tokens

                # Log external call for HR/welfare tracking.
                # FIX-3b (KB #270619): pass the REAL token counts so this row carries
                # tokens_used instead of 0. The analyzer runs the LLM outside dispatch(),
                # so this is the ONLY task_execution_log row for the analysis work — and
                # token-based welfare (welfare_load) reads fatigue from tokens. Logging 0
                # made heavy mistral:7b analysis look like idle/free work.
                dispatcher.log_external_call(
                    capability="knowledge_analysis",
                    module_id="consciousness",
                    model_used=analyzer.get_current_model(),
                    duration_ms=result.processing_time_ms,
                    success=True,
                    prompt_tokens=result.input_tokens or 0,
                    completion_tokens=result.output_tokens or 0,
                )

                # Save cards + embeddings
                title_to_id = {}
                for card in result.cards:
                    # Set source_ref from item_id
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
                    dispatcher.update_job_progress(
                        job_id,
                        processed,
                        errors,
                        {"cards_created": cards_created},
                    )

            except Exception as e:
                logger.error(f"Processing item {item_id} failed: {e}")
                errors += 1
                if job_id:
                    dispatcher.update_job_progress(job_id, processed, errors)

        _log_batch_processing(
            batch_id,
            category,
            {
                "batch_id": batch_id,
                "processed": processed,
                "cards_created": cards_created,
                "relationships_created": 0,
                "total_tokens": total_input_tokens + total_output_tokens,
                "errors": errors,
                "log": [],
            },
        )

    except Exception as e:
        logger.error(f"Analysis background job failed: {e}")
    finally:
        if job_id:
            dispatcher.complete_job(job_id)
        logger.info(f"[Analysis] Job #{job_id} finished: " f"{processed} ok, {errors} failed, {cards_created} cards")


@processing_bp.route("/start", methods=["POST"])
def start_processing():
    """Start batch processing via Bridge job system.

    Creates a bridge_job and returns the job_id immediately.
    Work runs in a background thread with progress tracked in Starbase Command.
    """
    try:
        from tools.department_hq.services.department_dispatcher import get_dispatcher

        data = request.get_json() or {}
        category = data.get("category", "conversations")
        batch_size = min(int(data.get("batch_size", 10)), 50)  # Max 50 per batch

        # Generate batch ID
        batch_id = str(uuid.uuid4())

        # Get items to process
        conn = None
        cur = None
        conn = get_db()
        cur = conn.cursor()

        base_sql = """
            SELECT id, title, content, memory_metadata
            FROM knowledge_base
            WHERE {filter_clause}
            AND (ai_analysis IS NULL OR analysis_version = 0)
            AND content IS NOT NULL
            AND LENGTH(content) > 100
            ORDER BY created_at DESC
            LIMIT %s
        """

        if category == "github":
            cur.execute(
                base_sql.format(filter_clause="knowledge_type = %s"),
                ("github_file", batch_size),
            )
        elif category == "claude_hooks":
            cur.execute(
                base_sql.format(filter_clause="source_type = %s"),
                ("claude_hook", batch_size),
            )
        else:
            # Default: conversations
            cur.execute(
                base_sql.format(filter_clause="source_type = %s"),
                ("conversation_log", batch_size),
            )
        items = cur.fetchall()
        if not items:
            return jsonify({"success": True, "message": "No items to process", "processed": 0})

        # ── Create Bridge Job (blocks duplicates) ───────────
        dispatcher = get_dispatcher()
        job_id = dispatcher.create_job(
            job_type="batch_analysis",
            module_source="consciousness",
            description=f"Analyze {len(items)} {category} entries (batch {batch_size})",
            total_steps=len(items),
            capability="knowledge_analysis",
            metadata={"category": category, "batch_id": batch_id, "batch_size": batch_size},
        )

        if not job_id:
            return (
                jsonify(
                    {
                        "success": False,
                        "error": "An analysis job is already running — check Starbase Command for progress",
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
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


def _update_source_analysis(item_id: int, result, batch_id: str):
    """Update source entry with analysis results.

    Items with 0 cards extracted are NOT marked as fully analyzed
    (analysis_version stays 0) so they can be retried in future batches.
    """
    conn = None
    cur = None
    try:
        conn = get_db()
        cur = conn.cursor()

        cards_count = len(result.cards)
        ai_analysis = {
            "cards_extracted": cards_count,
            "relationships_extracted": len(result.relationships),
            "input_tokens": result.input_tokens,
            "output_tokens": result.output_tokens,
            "processing_time_ms": result.processing_time_ms,
            "batch_id": batch_id,
            "analyzed_at": datetime.now().isoformat(),
        }

        # Only mark as fully analyzed (version=1) if cards were extracted.
        # Items with 0 cards keep version=0 so they are retried next batch.
        version = 1 if cards_count > 0 else 0

        cur.execute(
            """
            UPDATE knowledge_base
            SET ai_analysis = %s, analysis_version = %s
            WHERE id = %s
            """,
            (json.dumps(ai_analysis), version, item_id),
        )
        conn.commit()
    except Exception as e:
        logger.error(f"Failed to update source analysis: {e}")
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


def _log_batch_processing(batch_id: str, category: str, results: dict):
    """Log batch processing to knowledge_processing_log"""
    conn = None
    cur = None
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
                        "errors": results["errors"] if isinstance(results["errors"], int) else len(results["errors"]),
                        "log": results["log"][:20],  # Limit log size
                    }
                ),
            ),
        )
        conn.commit()
    except Exception as e:
        logger.error(f"Failed to log batch: {e}")
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


def _run_embedding_job(item_ids_and_data, job_id):
    """Background worker for embedding generation.

    Runs in a separate thread so the HTTP request can return immediately.
    Updates progress via Bridge dispatcher.

    Items are tuples of (id, title, content) for knowledge_base rows,
    or (id, title, content, source) where source is 'decisions' or 'translations'.
    """
    from ai_bridge.embedding_service import generate_embedding, get_embedding_service
    from tools.department_hq.services.department_dispatcher import get_dispatcher

    # Ensure arctic-embed model is loaded before starting batch
    try:
        svc = get_embedding_service()
        health = svc.health_check()
        if health.get("status") != "healthy":
            logger.warning(f"[Embedding] Model not healthy, attempting fleet-wide warmup: {health}")
            # Fleet-aware: warm arctic on EVERY node in the embedding pool
            # (failover), not just the hub. Per-item generation below already
            # fails over via generate_embedding(). (#3525)
            from ai_bridge.embedding_service import warm_all_nodes

            warm_results = warm_all_nodes()
            _ok = sum(1 for v in warm_results.values() if v == "ok")
            logger.info(
                "[Embedding] Fleet warmup complete: %d/%d nodes warm — %s",
                _ok,
                len(warm_results),
                warm_results,
            )
    except Exception as warmup_err:
        logger.warning(f"[Embedding] Model warmup failed: {warmup_err}")

    _UPDATE_SQL = {
        "knowledge_base": """
            UPDATE knowledge_base
            SET embedding = %s, has_embedding = true, embedding_generated_at = NOW()
            WHERE id = %s
        """,
        "decisions": """
            UPDATE project_decisions
            SET embedding = %s, embedding_generated_at = NOW()
            WHERE id = %s
        """,
        "translations": """
            UPDATE translations
            SET embedding = %s, embedding_generated_at = NOW()
            WHERE id = %s
        """,
    }

    dispatcher = get_dispatcher()
    processed = 0
    failed = 0
    conn = None
    cur = None

    try:
        conn = get_db()
        cur = conn.cursor()

        for row in item_ids_and_data:
            item_id, title, content = row[0], row[1], row[2]
            source = row[3] if len(row) > 3 else "knowledge_base"
            try:
                text = f"{title or ''}. {content[:800]}"
                embedding = generate_embedding(text)

                if embedding:
                    cur.execute(_UPDATE_SQL[source], (embedding, item_id))
                    conn.commit()
                    processed += 1
                else:
                    failed += 1

                if job_id:
                    dispatcher.update_job_progress(job_id, processed, failed)

            except Exception as e:
                logger.error(f"Embedding for {source}:{item_id} failed: {e}")
                conn.rollback()
                failed += 1
                if job_id:
                    dispatcher.update_job_progress(job_id, processed, failed)

    except Exception as e:
        logger.error(f"Embedding background job failed: {e}")
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()
        if job_id:
            dispatcher.complete_job(job_id)
        # Log to task_execution_log so embedding is visible in dispatch log
        # and agent welfare (stress/energy) is tracked properly
        try:
            dispatcher.log_external_call(
                capability="embedding",
                module_id="consciousness_embed",
                model_used="arctic-embed-cpu",
                duration_ms=0,
                success=(processed > 0),
            )
        except Exception:
            pass
        logger.info(f"[Embedding] Job #{job_id} finished: {processed} ok, {failed} failed")


@processing_bp.route("/generate-embeddings", methods=["POST"])
def generate_embeddings():
    """Generate embeddings for entries that don't have them.

    Creates a bridge_job and returns the job_id immediately.
    Work runs in a background thread with progress tracked in Starbase Command.
    """
    try:
        from tools.department_hq.services.department_dispatcher import get_dispatcher

        data = request.get_json() or {}
        batch_size = min(int(data.get("batch_size", 50)), 200)

        conn = None
        cur = None
        conn = get_db()
        cur = conn.cursor()

        # Get unembedded items from all intelligence sources
        cur.execute(
            """
            (SELECT id, title, content, 'knowledge_base' AS source
             FROM knowledge_base
             WHERE embedding IS NULL AND content IS NOT NULL AND LENGTH(content) > 50
             ORDER BY created_at DESC LIMIT %s)
            UNION ALL
            (SELECT id, title, decision AS content, 'decisions' AS source
             FROM project_decisions
             WHERE embedding IS NULL
             ORDER BY created_at DESC LIMIT %s)
            UNION ALL
            (SELECT id, key AS title, text AS content, 'translations' AS source
             FROM translations
             WHERE embedding IS NULL
             ORDER BY created_at DESC LIMIT %s)
            """,
            (batch_size, batch_size, batch_size),
        )
        items = cur.fetchall()
        if not items:
            return jsonify({"success": True, "message": "All intelligence embedded", "processed": 0, "total": 0})

        # ── Create Bridge Job (blocks duplicates) ───────────
        dispatcher = get_dispatcher()
        job_id = dispatcher.create_job(
            job_type="batch_embedding",
            module_source="consciousness",
            description=f"Generate embeddings for {len(items)} intelligence entries",
            total_steps=len(items),
            capability="embedding",
            metadata={"batch_size": batch_size, "requested_at": datetime.now().isoformat()},
        )

        if not job_id:
            return (
                jsonify(
                    {
                        "success": False,
                        "error": "An embedding job is already running — check Starbase Command for progress",
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
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


@processing_bp.route("/embedding-coverage", methods=["GET"])
def get_embedding_coverage():
    """Get embedding coverage broken down by source_type"""
    conn = None
    cur = None
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
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


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
    finally:

        cur.close()

        conn.close()


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
    finally:

        cur.close()

        conn.close()


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

    finally:

        cur.close()

        conn.close()


# ── Server-Side Loop Mode ──────────────────────────────────────
# Core loop state management extracted to services/loop_service.py
# _trigger_loop_op stays here because it depends on consciousness job runners.

from services.loop_service import (  # noqa: E402
    VALID_LOOP_OPS,
    _get_backoff_delay,
    _get_retry_state,
    _loop_failures,
    get_server_loops,
    set_server_loop,
    set_trigger_fn as _set_loop_trigger_fn,
)

_LOOP_CONFIG_KEY = "consciousness_server_loops"
_RETRY_CONFIG_KEY = "consciousness_loop_retries"
_LOCAL_ONLY_CONFIG_KEY = "consciousness_local_only"


def get_local_only_mode():
    """Read consciousness_local_only flag from system_config. Default True."""
    conn = None
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute(
            "SELECT value FROM system_config WHERE key = %s",
            (_LOCAL_ONLY_CONFIG_KEY,),
        )
        row = cur.fetchone()
        cur.close()
        if row:
            val = row[0]
            if isinstance(val, bool):
                return val
            if isinstance(val, dict):
                return val.get("enabled", True)
            try:
                parsed = json.loads(val) if isinstance(val, str) else val
                if isinstance(parsed, dict):
                    return parsed.get("enabled", True)
                return bool(parsed)
            except (json.JSONDecodeError, TypeError):
                return True
        return True
    except Exception:
        return True
    finally:
        if conn:
            conn.close()


def set_local_only_mode(enabled):
    """Toggle consciousness_local_only flag in system_config."""
    conn = None
    try:
        conn = get_db()
        cur = conn.cursor()
        payload = json.dumps({"enabled": bool(enabled)})
        cur.execute(
            """
            INSERT INTO system_config (key, value) VALUES (%s, %s::jsonb)
            ON CONFLICT (key) DO UPDATE SET value = %s::jsonb
            """,
            (_LOCAL_ONLY_CONFIG_KEY, payload, payload),
        )
        conn.commit()
        cur.close()
        return bool(enabled)
    finally:
        if conn:
            conn.close()


@processing_bp.route("/local-only-mode", methods=["GET"])
def get_local_only_endpoint():
    """GET the current local-only enforcement mode."""
    return jsonify({"success": True, "local_only": get_local_only_mode()})


@processing_bp.route("/local-only-mode", methods=["PUT"])
def set_local_only_endpoint():
    """PUT to toggle local-only enforcement mode."""
    data = request.get_json(silent=True) or {}
    enabled = data.get("enabled")
    if enabled is None:
        return jsonify({"error": "Missing 'enabled' field"}), 400
    result = set_local_only_mode(enabled)
    logger.info(f"[Consciousness] local_only mode set to {result}")
    return jsonify({"success": True, "local_only": result})


def _trigger_loop_op(op):
    """Trigger the next batch for a loop operation (no Flask context needed)."""
    conn = get_db()
    cur = conn.cursor()

    try:
        from tools.department_hq.services.department_dispatcher import get_dispatcher

        dispatcher = get_dispatcher()

        if op == "analysis":
            cur.execute(
                """
                SELECT id, title, content, memory_metadata
                FROM knowledge_base
                WHERE (ai_analysis IS NULL OR analysis_version = 0)
                AND content IS NOT NULL AND LENGTH(content) > 100
                AND knowledge_type IN (
                    'vault_note', 'mistake_learned', 'conversation_memory',
                    'github_file', 'code_snippet', 'api_endpoint'
                )
                ORDER BY
                    CASE knowledge_type
                        WHEN 'mistake_learned' THEN 1
                        WHEN 'vault_note' THEN 2
                        WHEN 'conversation_memory' THEN 3
                        WHEN 'github_file' THEN 4
                        WHEN 'code_snippet' THEN 5
                        ELSE 6
                    END,
                    importance_score DESC NULLS LAST,
                    created_at DESC
                LIMIT 10
                """
            )
            items = cur.fetchall()
            if not items:
                logger.debug("[ServerLoop] analysis: no items this cycle — will check again next run")
                return

            coordinator = get_coordinator()
            assignment = coordinator.request_agent("knowledge_analysis", "consciousness", priority="normal")
            if assignment.queued:
                logger.info(f"[ServerLoop] analysis: queued — {assignment.reason}")
                return

            batch_id = str(uuid.uuid4())
            job_id = dispatcher.create_job(
                job_type="batch_analysis",
                module_source="consciousness",
                description=f"[auto-loop] Analyze {len(items)} entries",
                total_steps=len(items),
                capability="knowledge_analysis",
                metadata={"category": "conversations", "batch_id": batch_id, "batch_size": 10, "server_loop": True},
            )
            if not job_id:
                coordinator.release_agent(assignment.agent_id)
                logger.info("[ServerLoop] analysis: duplicate job running — will retry after it completes")
                return
            coordinator.model_service.register_job(assignment.model, job_id)
            t = threading.Thread(
                target=_run_analysis_job, args=(list(items), "conversations", batch_id, job_id), daemon=True
            )
            t.start()
            logger.info(
                f"[ServerLoop] analysis: started job #{job_id} with {len(items)} items (agent={assignment.agent_name})"
            )

        elif op == "embedding":
            cur.execute(
                """
                (SELECT id, title, content, 'knowledge_base' AS source
                 FROM knowledge_base
                 WHERE embedding IS NULL AND content IS NOT NULL AND LENGTH(content) > 50
                 ORDER BY created_at DESC LIMIT 200)
                UNION ALL
                (SELECT id, title, decision, 'decisions'
                 FROM project_decisions
                 WHERE embedding IS NULL
                 ORDER BY created_at DESC LIMIT 20)
                UNION ALL
                (SELECT id, key, text, 'translations'
                 FROM translations
                 WHERE embedding IS NULL
                 ORDER BY created_at DESC LIMIT 20)
                """
            )
            items = cur.fetchall()
            if not items:
                logger.debug("[ServerLoop] embedding: no items this cycle — will check again next run")
                return

            coordinator = get_coordinator()
            assignment = coordinator.request_agent("embedding", "consciousness", priority="high")
            if assignment.queued:
                logger.info(f"[ServerLoop] embedding: queued — {assignment.reason}")
                return

            job_id = dispatcher.create_job(
                job_type="batch_embedding",
                module_source="consciousness",
                description=f"[auto-loop] Embed {len(items)} intelligence entries",
                total_steps=len(items),
                capability="embedding",
                metadata={"batch_size": 25, "server_loop": True},
            )
            if not job_id:
                coordinator.release_agent(assignment.agent_id)
                logger.info("[ServerLoop] embedding: duplicate job running")
                return
            coordinator.model_service.register_job(assignment.model, job_id)
            t = threading.Thread(target=_run_embedding_job, args=(list(items), job_id), daemon=True)
            t.start()
            logger.info(
                f"[ServerLoop] embedding: started job #{job_id} with {len(items)} items (agent={assignment.agent_name})"
            )

        elif op == "translate":
            from tools.consciousness.language_routes import _run_translate_bg

            coordinator = get_coordinator()
            assignment = coordinator.request_agent("translate", "consciousness", priority="low")
            if assignment.queued:
                logger.info(f"[ServerLoop] translate: queued — {assignment.reason}")
                return

            languages = ["fr", "es", "pt", "de", "zh", "ar", "he"]
            job_id = dispatcher.create_job(
                job_type="translate_batch",
                module_source="consciousness",
                description="[auto-loop] Translate missing keys",
                total_steps=len(languages),
                capability="translate",
                metadata={"languages": languages, "server_loop": True},
            )
            if not job_id:
                coordinator.release_agent(assignment.agent_id)
                logger.info("[ServerLoop] translate: duplicate job running")
                return
            coordinator.model_service.register_job(assignment.model, job_id)
            t = threading.Thread(
                target=_run_translate_bg,
                args=(languages, None, job_id),
                daemon=True,
            )
            t.start()
            logger.info(f"[ServerLoop] translate: started job #{job_id} (agent={assignment.agent_name})")

    except Exception as e:
        logger.error(f"[ServerLoop] _trigger_loop_op({op}) failed: {e}")
    finally:
        cur.close()
        conn.close()


@processing_bp.route("/knowledge-timeline", methods=["GET"])
def knowledge_timeline():
    """Return hourly intelligence counts for the chart popup.

    Tracks real cumulative growth of knowledge_base entries, translations,
    and decisions — all with their own created_at timelines.
    Returns {t, total, embedded, unembedded, translations, decisions}
    bucketed by hour for the last 48 hours.
    """
    conn = None
    try:
        conn = get_db()
        cur = conn.cursor()

        cur.execute(
            """
            WITH hours AS (
                SELECT generate_series(
                    date_trunc('hour', NOW() - INTERVAL '48 hours'),
                    date_trunc('hour', NOW()),
                    '1 hour'
                ) AS h
            ),
            -- Knowledge base created per hour
            kb_created AS (
                SELECT date_trunc('hour', created_at) AS h, COUNT(*) AS n
                FROM knowledge_base
                WHERE created_at >= NOW() - INTERVAL '48 hours'
                GROUP BY 1
            ),
            -- Knowledge base embedded per hour
            kb_embedded AS (
                SELECT date_trunc('hour', embedding_generated_at) AS h, COUNT(*) AS n
                FROM knowledge_base
                WHERE embedding_generated_at >= NOW() - INTERVAL '48 hours'
                GROUP BY 1
            ),
            -- Translations created per hour
            trans_created AS (
                SELECT date_trunc('hour', created_at) AS h, COUNT(*) AS n
                FROM translations
                WHERE created_at >= NOW() - INTERVAL '48 hours'
                GROUP BY 1
            ),
            -- Decisions created per hour
            dec_created AS (
                SELECT date_trunc('hour', created_at) AS h, COUNT(*) AS n
                FROM project_decisions
                WHERE created_at >= NOW() - INTERVAL '48 hours'
                GROUP BY 1
            ),
            baseline AS (
                SELECT
                    (SELECT COUNT(*) FROM knowledge_base
                     WHERE created_at < NOW() - INTERVAL '48 hours') AS kb_total,
                    (SELECT COUNT(*) FROM knowledge_base
                     WHERE embedding_generated_at IS NOT NULL
                     AND embedding_generated_at < NOW() - INTERVAL '48 hours') AS kb_embedded,
                    (SELECT COUNT(*) FROM translations
                     WHERE created_at < NOW() - INTERVAL '48 hours') AS trans_total,
                    (SELECT COUNT(*) FROM project_decisions
                     WHERE created_at < NOW() - INTERVAL '48 hours') AS dec_total
            )
            SELECT
                hours.h AS t,
                baseline.kb_total + COALESCE(SUM(kb_created.n) OVER (ORDER BY hours.h), 0) AS kb,
                baseline.kb_embedded + COALESCE(SUM(kb_embedded.n) OVER (ORDER BY hours.h), 0) AS embedded,
                baseline.trans_total + COALESCE(SUM(trans_created.n) OVER (ORDER BY hours.h), 0) AS trans,
                baseline.dec_total + COALESCE(SUM(dec_created.n) OVER (ORDER BY hours.h), 0) AS decs
            FROM hours
            CROSS JOIN baseline
            LEFT JOIN kb_created ON kb_created.h = hours.h
            LEFT JOIN kb_embedded ON kb_embedded.h = hours.h
            LEFT JOIN trans_created ON trans_created.h = hours.h
            LEFT JOIN dec_created ON dec_created.h = hours.h
            ORDER BY hours.h
            """
        )
        rows = cur.fetchall()
        cur.close()

        points = []
        for t, kb, emb, trans, decs in rows:
            kb_val = int(kb)
            emb_val = int(emb)
            trans_val = int(trans)
            decs_val = int(decs)
            points.append(
                {
                    "t": t.isoformat(),
                    "total": kb_val + trans_val + decs_val,
                    "kb": kb_val,
                    "embedded": emb_val,
                    "unembedded": kb_val - emb_val,
                    "translations": trans_val,
                    "decisions": decs_val,
                }
            )

        return jsonify({"success": True, "points": points})
    except Exception as e:
        logger.error(f"[KnowledgeTimeline] {e}")
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        if conn:
            conn.close()


# Wire _trigger_loop_op into the shared loop service so retrigger/resume can call it
_set_loop_trigger_fn(_trigger_loop_op)


@processing_bp.route("/server-loop/status", methods=["GET"])
def server_loop_status():
    """Get current server-side loop states with retry info and processing rate."""
    loops = get_server_loops()
    retry_state = _get_retry_state()

    # Build per-operation detail
    ops_detail = {}
    for op in VALID_LOOP_OPS:
        rs = retry_state.get(op, {})
        retry_count = rs.get("count", 0)
        ops_detail[op] = {
            "active": bool(loops.get(op)),
            "retry_count": retry_count,
            "next_delay": _get_backoff_delay(retry_count) if retry_count > 0 else 0,
            "last_success": rs.get("last_success"),
            "last_failure": rs.get("last_failure"),
            "last_error": rs.get("last_error", ""),
        }

    # Processing rate: completed consciousness jobs in the last hour
    rate = {}
    conn = None
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute(
            """
            SELECT job_type, COUNT(*) FROM bridge_jobs
            WHERE module_source = 'consciousness'
              AND status = 'completed'
              AND completed_at >= NOW() - INTERVAL '1 hour'
            GROUP BY job_type
            """
        )
        for row in cur.fetchall():
            # Map job_type back to op key
            jt_map = {
                "batch_analysis": "analysis",
                "batch_embedding": "embedding",
                "translate_batch": "translate",
            }
            op_key = jt_map.get(row[0], row[0])
            rate[op_key] = row[1]
        cur.close()
    except Exception as e:
        logger.error(f"[ServerLoop] Rate query failed: {e}")
    finally:
        if conn:
            conn.close()

    for op in VALID_LOOP_OPS:
        ops_detail[op]["jobs_per_hour"] = rate.get(op, 0)

    return jsonify(
        {
            "success": True,
            "loops": loops,
            "failures": dict(_loop_failures),
            "ops_detail": ops_detail,
        }
    )


@processing_bp.route("/server-loop/toggle", methods=["POST"])
def server_loop_toggle():
    """Toggle a server-side loop. Body: {"op": "analysis", "enabled": true}"""
    data = request.get_json() or {}
    op = data.get("op")
    enabled = data.get("enabled", False)

    if op not in VALID_LOOP_OPS:
        return jsonify({"success": False, "error": f"Invalid op: {op}. Valid: {list(VALID_LOOP_OPS)}"}), 400

    loops = set_server_loop(op, enabled)

    # If enabling, kick off the first batch immediately
    if enabled:

        def _kickoff():
            import time

            time.sleep(2)
            try:
                _trigger_loop_op(op)
            except Exception as e:
                logger.error(f"[ServerLoop] Kickoff {op} failed: {e}")

        t = threading.Thread(target=_kickoff, daemon=True)
        t.start()

    return jsonify({"success": True, "loops": loops, "kicked_off": enabled})
