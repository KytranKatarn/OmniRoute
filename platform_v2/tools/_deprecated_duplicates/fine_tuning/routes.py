"""
AI Model Fine-tuning Routes
Phase 46: Custom AI model training interface

Features:
- Dataset management (upload, preview, validate)
- Base model selection (Ollama models)
- Training job configuration and monitoring
- Fine-tuned model management
- Evaluation and benchmarking
"""

import os
import json
import logging
from datetime import datetime
from flask import render_template, jsonify, request
from flask_login import login_required, current_user
import psycopg2
from psycopg2.extras import RealDictCursor
from . import fine_tuning_bp

logger = logging.getLogger(__name__)


def get_db_connection():
    """Get database connection"""
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "localhost"),
        port=os.getenv("DB_PORT", "5432"),
        database=os.getenv("DB_NAME", "archie"),
        user=os.getenv("DB_USER", "archie"),
        password=os.getenv("DB_PASSWORD", ""),
    )


# =============================================================================
# MAIN PAGE
# =============================================================================


@fine_tuning_bp.route("/")
@login_required
def index():
    """Fine-tuning main page"""
    return render_template("tools/fine_tuning.html")


@fine_tuning_bp.route("/api/status")
@login_required
def status():
    """API endpoint for module health check"""
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM ft_base_models WHERE is_available = TRUE")
        model_count = cur.fetchone()[0]
        cur.close()
        conn.close()

        return jsonify(
            {
                "module": "fine_tuning",
                "status": "active",
                "healthy": True,
                "available_models": model_count,
                "message": "AI Fine-tuning module operational",
            }
        )
    except Exception as e:
        return jsonify(
            {
                "module": "fine_tuning",
                "status": "error",
                "healthy": False,
                "message": str(e),
            }
        )


# =============================================================================
# DASHBOARD STATS
# =============================================================================


@fine_tuning_bp.route("/api/stats")
@login_required
def get_stats():
    """Get user's fine-tuning statistics"""
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute(
            """
            SELECT * FROM v_ft_user_stats WHERE user_id = %s
        """,
            (current_user.id,),
        )
        stats = cur.fetchone()

        # Get active jobs
        cur.execute(
            """
            SELECT COUNT(*) FROM ft_training_jobs
            WHERE user_id = %s AND status IN ('queued', 'preparing', 'training')
        """,
            (current_user.id,),
        )
        active_jobs = cur.fetchone()["count"]

        cur.close()
        conn.close()

        return jsonify(
            {
                "success": True,
                "stats": {
                    "total_datasets": stats["total_datasets"] if stats else 0,
                    "total_jobs": stats["total_jobs"] if stats else 0,
                    "completed_jobs": stats["completed_jobs"] if stats else 0,
                    "active_jobs": active_jobs,
                    "total_models": stats["total_models"] if stats else 0,
                    "deployed_models": stats["deployed_models"] if stats else 0,
                },
            }
        )
    except Exception as e:
        logger.error(f"Failed to get stats: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


# =============================================================================
# BASE MODELS
# =============================================================================


@fine_tuning_bp.route("/api/base-models")
@login_required
def get_base_models():
    """Get available base models for fine-tuning"""
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute(
            """
            SELECT * FROM ft_base_models
            WHERE is_available = TRUE AND supports_fine_tuning = TRUE
            ORDER BY provider, parameters
        """
        )
        models = cur.fetchall()

        cur.close()
        conn.close()

        return jsonify({"success": True, "models": models})
    except Exception as e:
        logger.error(f"Failed to get base models: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


# =============================================================================
# DATASETS
# =============================================================================


@fine_tuning_bp.route("/api/datasets")
@login_required
def get_datasets():
    """Get user's datasets"""
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute(
            """
            SELECT id, name, description, dataset_type, source_type,
                   total_samples, train_samples, validation_samples,
                   status, size_bytes, created_at, updated_at
            FROM ft_datasets
            WHERE user_id = %s
            ORDER BY created_at DESC
        """,
            (current_user.id,),
        )
        datasets = cur.fetchall()

        cur.close()
        conn.close()

        return jsonify({"success": True, "datasets": datasets})
    except Exception as e:
        logger.error(f"Failed to get datasets: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@fine_tuning_bp.route("/api/datasets", methods=["POST"])
@login_required
def create_dataset():
    """Create a new dataset"""
    try:
        data = request.get_json() or {}
        name = data.get("name", "").strip()
        description = data.get("description", "")
        dataset_type = data.get("type", "conversation")

        if not name:
            return jsonify({"success": False, "error": "Dataset name is required"}), 400

        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute(
            """
            INSERT INTO ft_datasets (user_id, name, description, dataset_type, status)
            VALUES (%s, %s, %s, %s, 'pending')
            RETURNING id, name, description, dataset_type, status, created_at
        """,
            (current_user.id, name, description, dataset_type),
        )

        dataset = cur.fetchone()
        conn.commit()
        cur.close()
        conn.close()

        return jsonify(
            {
                "success": True,
                "dataset": dataset,
                "message": "Dataset created successfully",
            }
        )
    except psycopg2.errors.UniqueViolation:
        return (
            jsonify({"success": False, "error": "Dataset with this name already exists"}),
            400,
        )
    except Exception as e:
        logger.error(f"Failed to create dataset: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@fine_tuning_bp.route("/api/datasets/<int:dataset_id>")
@login_required
def get_dataset(dataset_id):
    """Get dataset details"""
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute(
            """
            SELECT * FROM ft_datasets
            WHERE id = %s AND user_id = %s
        """,
            (dataset_id, current_user.id),
        )
        dataset = cur.fetchone()

        cur.close()
        conn.close()

        if not dataset:
            return jsonify({"success": False, "error": "Dataset not found"}), 404

        return jsonify({"success": True, "dataset": dataset})
    except Exception as e:
        logger.error(f"Failed to get dataset: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@fine_tuning_bp.route("/api/datasets/<int:dataset_id>/upload", methods=["POST"])
@login_required
def upload_dataset_data(dataset_id):
    """Upload data to a dataset (JSONL format)"""
    try:
        data = request.get_json() or {}
        samples = data.get("samples", [])

        if not samples:
            return jsonify({"success": False, "error": "No samples provided"}), 400

        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Verify ownership
        cur.execute(
            "SELECT id FROM ft_datasets WHERE id = %s AND user_id = %s",
            (dataset_id, current_user.id),
        )
        if not cur.fetchone():
            cur.close()
            conn.close()
            return jsonify({"success": False, "error": "Dataset not found"}), 404

        # Update dataset with samples
        total = len(samples)
        train_count = int(total * 0.8)
        val_count = int(total * 0.1)
        test_count = total - train_count - val_count

        cur.execute(
            """
            UPDATE ft_datasets
            SET total_samples = %s, train_samples = %s, validation_samples = %s,
                test_samples = %s, sample_data = %s, status = 'ready', updated_at = NOW()
            WHERE id = %s
            RETURNING id, total_samples, status
        """,
            (
                total,
                train_count,
                val_count,
                test_count,
                json.dumps(samples[:5]),
                dataset_id,
            ),
        )

        result = cur.fetchone()
        conn.commit()
        cur.close()
        conn.close()

        return jsonify(
            {
                "success": True,
                "dataset": result,
                "message": f"Uploaded {total} samples successfully",
            }
        )
    except Exception as e:
        logger.error(f"Failed to upload dataset data: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@fine_tuning_bp.route("/api/datasets/<int:dataset_id>", methods=["DELETE"])
@login_required
def delete_dataset(dataset_id):
    """Delete a dataset"""
    try:
        conn = get_db_connection()
        cur = conn.cursor()

        cur.execute(
            """
            DELETE FROM ft_datasets
            WHERE id = %s AND user_id = %s
            RETURNING id
        """,
            (dataset_id, current_user.id),
        )

        deleted = cur.fetchone()
        conn.commit()
        cur.close()
        conn.close()

        if not deleted:
            return jsonify({"success": False, "error": "Dataset not found"}), 404

        return jsonify({"success": True, "message": "Dataset deleted successfully"})
    except Exception as e:
        logger.error(f"Failed to delete dataset: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


# =============================================================================
# TRAINING JOBS
# =============================================================================


@fine_tuning_bp.route("/api/jobs")
@login_required
def get_jobs():
    """Get user's training jobs"""
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute(
            """
            SELECT j.*, m.model_name as base_model_name, d.name as dataset_name
            FROM ft_training_jobs j
            LEFT JOIN ft_base_models m ON j.base_model_id = m.id
            LEFT JOIN ft_datasets d ON j.dataset_id = d.id
            WHERE j.user_id = %s
            ORDER BY j.created_at DESC
        """,
            (current_user.id,),
        )
        jobs = cur.fetchall()

        cur.close()
        conn.close()

        return jsonify({"success": True, "jobs": jobs})
    except Exception as e:
        logger.error(f"Failed to get jobs: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@fine_tuning_bp.route("/api/jobs", methods=["POST"])
@login_required
def create_job():
    """Create a new training job"""
    try:
        data = request.get_json() or {}

        job_name = data.get("name", "").strip()
        base_model_id = data.get("base_model_id")
        dataset_id = data.get("dataset_id")
        training_method = data.get("training_method", "lora")
        epochs = data.get("epochs", 3)
        batch_size = data.get("batch_size", 4)
        learning_rate = data.get("learning_rate", 2e-5)

        if not job_name:
            return jsonify({"success": False, "error": "Job name is required"}), 400
        if not base_model_id:
            return jsonify({"success": False, "error": "Base model is required"}), 400
        if not dataset_id:
            return jsonify({"success": False, "error": "Dataset is required"}), 400

        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Verify dataset ownership and readiness
        cur.execute(
            """
            SELECT id, total_samples FROM ft_datasets
            WHERE id = %s AND user_id = %s AND status = 'ready'
        """,
            (dataset_id, current_user.id),
        )
        dataset = cur.fetchone()
        if not dataset:
            cur.close()
            conn.close()
            return (
                jsonify({"success": False, "error": "Dataset not found or not ready"}),
                400,
            )

        # Calculate total steps
        total_steps = (dataset["total_samples"] // batch_size) * epochs

        cur.execute(
            """
            INSERT INTO ft_training_jobs
            (user_id, job_name, base_model_id, dataset_id, training_method,
             epochs, batch_size, learning_rate, total_steps, status)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 'queued')
            RETURNING id, job_name, status, created_at
        """,
            (
                current_user.id,
                job_name,
                base_model_id,
                dataset_id,
                training_method,
                epochs,
                batch_size,
                learning_rate,
                total_steps,
            ),
        )

        job = cur.fetchone()
        conn.commit()
        cur.close()
        conn.close()

        return jsonify({"success": True, "job": job, "message": "Training job created and queued"})
    except Exception as e:
        logger.error(f"Failed to create job: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@fine_tuning_bp.route("/api/jobs/<int:job_id>")
@login_required
def get_job(job_id):
    """Get job details"""
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute(
            """
            SELECT j.*, m.model_name as base_model_name, m.model_id as base_model_id_str,
                   d.name as dataset_name, d.total_samples
            FROM ft_training_jobs j
            LEFT JOIN ft_base_models m ON j.base_model_id = m.id
            LEFT JOIN ft_datasets d ON j.dataset_id = d.id
            WHERE j.id = %s AND j.user_id = %s
        """,
            (job_id, current_user.id),
        )
        job = cur.fetchone()

        cur.close()
        conn.close()

        if not job:
            return jsonify({"success": False, "error": "Job not found"}), 404

        return jsonify({"success": True, "job": job})
    except Exception as e:
        logger.error(f"Failed to get job: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@fine_tuning_bp.route("/api/jobs/<int:job_id>/start", methods=["POST"])
@login_required
def start_job(job_id):
    """Start a queued training job"""
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute(
            """
            UPDATE ft_training_jobs
            SET status = 'preparing', started_at = NOW(), updated_at = NOW()
            WHERE id = %s AND user_id = %s AND status = 'queued'
            RETURNING id, status
        """,
            (job_id, current_user.id),
        )

        job = cur.fetchone()
        conn.commit()
        cur.close()
        conn.close()

        if not job:
            return (
                jsonify({"success": False, "error": "Job not found or already started"}),
                404,
            )

        # TODO: Trigger actual training process via background worker

        return jsonify({"success": True, "job": job, "message": "Training job started"})
    except Exception as e:
        logger.error(f"Failed to start job: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@fine_tuning_bp.route("/api/jobs/<int:job_id>/cancel", methods=["POST"])
@login_required
def cancel_job(job_id):
    """Cancel a running training job"""
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute(
            """
            UPDATE ft_training_jobs
            SET status = 'cancelled', updated_at = NOW()
            WHERE id = %s AND user_id = %s AND status IN ('queued', 'preparing', 'training')
            RETURNING id, status
        """,
            (job_id, current_user.id),
        )

        job = cur.fetchone()
        conn.commit()
        cur.close()
        conn.close()

        if not job:
            return (
                jsonify({"success": False, "error": "Job not found or cannot be cancelled"}),
                404,
            )

        return jsonify({"success": True, "job": job, "message": "Training job cancelled"})
    except Exception as e:
        logger.error(f"Failed to cancel job: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


# =============================================================================
# FINE-TUNED MODELS
# =============================================================================


@fine_tuning_bp.route("/api/models")
@login_required
def get_models():
    """Get user's fine-tuned models"""
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute(
            """
            SELECT m.*, b.model_name as base_model_name, j.job_name as training_job_name
            FROM ft_models m
            LEFT JOIN ft_base_models b ON m.base_model_id = b.id
            LEFT JOIN ft_training_jobs j ON m.training_job_id = j.id
            WHERE m.user_id = %s
            ORDER BY m.created_at DESC
        """,
            (current_user.id,),
        )
        models = cur.fetchall()

        cur.close()
        conn.close()

        return jsonify({"success": True, "models": models})
    except Exception as e:
        logger.error(f"Failed to get models: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@fine_tuning_bp.route("/api/models/<int:model_id>")
@login_required
def get_model(model_id):
    """Get model details"""
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute(
            """
            SELECT m.*, b.model_name as base_model_name, j.job_name as training_job_name
            FROM ft_models m
            LEFT JOIN ft_base_models b ON m.base_model_id = b.id
            LEFT JOIN ft_training_jobs j ON m.training_job_id = j.id
            WHERE m.id = %s AND m.user_id = %s
        """,
            (model_id, current_user.id),
        )
        model = cur.fetchone()

        cur.close()
        conn.close()

        if not model:
            return jsonify({"success": False, "error": "Model not found"}), 404

        return jsonify({"success": True, "model": model})
    except Exception as e:
        logger.error(f"Failed to get model: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@fine_tuning_bp.route("/api/models/<int:model_id>/deploy", methods=["POST"])
@login_required
def deploy_model(model_id):
    """Deploy a fine-tuned model to Ollama"""
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute(
            """
            UPDATE ft_models
            SET is_deployed = TRUE, status = 'deployed', updated_at = NOW()
            WHERE id = %s AND user_id = %s AND status = 'ready'
            RETURNING id, model_name, model_id as ollama_model_id
        """,
            (model_id, current_user.id),
        )

        model = cur.fetchone()
        conn.commit()
        cur.close()
        conn.close()

        if not model:
            return (
                jsonify({"success": False, "error": "Model not found or not ready"}),
                404,
            )

        # TODO: Actually load model into Ollama

        return jsonify(
            {
                "success": True,
                "model": model,
                "message": f"Model {model['model_name']} deployed successfully",
            }
        )
    except Exception as e:
        logger.error(f"Failed to deploy model: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@fine_tuning_bp.route("/api/models/<int:model_id>", methods=["DELETE"])
@login_required
def delete_model(model_id):
    """Delete a fine-tuned model"""
    try:
        conn = get_db_connection()
        cur = conn.cursor()

        cur.execute(
            """
            DELETE FROM ft_models
            WHERE id = %s AND user_id = %s
            RETURNING id
        """,
            (model_id, current_user.id),
        )

        deleted = cur.fetchone()
        conn.commit()
        cur.close()
        conn.close()

        if not deleted:
            return jsonify({"success": False, "error": "Model not found"}), 404

        return jsonify({"success": True, "message": "Model deleted successfully"})
    except Exception as e:
        logger.error(f"Failed to delete model: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


# =============================================================================
# MODEL TESTING
# =============================================================================


@fine_tuning_bp.route("/api/models/<int:model_id>/test", methods=["POST"])
@login_required
def test_model(model_id):
    """Test a fine-tuned model with a prompt"""
    try:
        data = request.get_json() or {}
        prompt = data.get("prompt", "").strip()

        if not prompt:
            return jsonify({"success": False, "error": "Prompt is required"}), 400

        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute(
            """
            SELECT model_id, model_name, is_deployed
            FROM ft_models
            WHERE id = %s AND user_id = %s
        """,
            (model_id, current_user.id),
        )
        model = cur.fetchone()

        cur.close()
        conn.close()

        if not model:
            return jsonify({"success": False, "error": "Model not found"}), 404

        # TODO: Actually call the model via Ollama API
        # For now, return a demo response
        demo_response = f"[Demo] Response from {model['model_name']} to: {prompt[:50]}..."

        return jsonify(
            {
                "success": True,
                "response": demo_response,
                "model": model["model_name"],
                "note": "Demo response - real inference coming soon",
            }
        )
    except Exception as e:
        logger.error(f"Failed to test model: {e}")
        return jsonify({"success": False, "error": str(e)}), 500
