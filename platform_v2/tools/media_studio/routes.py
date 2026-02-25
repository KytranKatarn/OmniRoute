"""Media Studio Module — Image, Video, and Audio generation via AI Bridge.

Routes through the bridge for provider capability discovery, CREATIVE station
assignment, and smart router escalation (free -> paid with Telegram approval).
"""

import json
import logging
from flask import request, jsonify, render_template
from flask_login import login_required, current_user
from . import media_studio_bp

logger = logging.getLogger(__name__)


def get_db():
    """Get raw database connection (caller must close/release)."""
    from database import get_db as _get_db

    return _get_db()


# --- Page Route -----------------------------------------------------------


@media_studio_bp.route("/")
@login_required
def media_studio_page():
    """Render the Media Studio module page."""
    return render_template("tools/media_studio.html")


# --- Capabilities ---------------------------------------------------------


@media_studio_bp.route("/api/capabilities", methods=["GET"])
@login_required
def get_capabilities():
    """Return available media generation capabilities from configured providers."""
    try:
        from ai_bridge.external_providers import get_providers_with_capability

        media_caps = {}
        for cap in ["image_gen", "video_gen", "audio_tts", "audio_music", "vision"]:
            providers = get_providers_with_capability(cap)
            if providers:
                media_caps[cap] = [
                    {
                        "provider_key": p["provider_key"],
                        "display_name": p["display_name"],
                        "is_free_tier": p["is_free_tier"],
                    }
                    for p in providers
                ]

        return jsonify(
            {
                "capabilities": media_caps,
                "supported_types": [k for k in media_caps if media_caps[k]],
            }
        )
    except Exception as e:
        logger.error(f"Failed to load capabilities: {e}")
        return jsonify({"error": str(e)}), 500


# --- Generation -----------------------------------------------------------


@media_studio_bp.route("/api/generate", methods=["POST"])
@login_required
def generate_media_endpoint():
    """Submit a media generation request.

    Body: {type: "image"|"video"|"audio_tts"|"audio_music", prompt: str, params: {}}
    """
    try:
        data = request.get_json()
        if not data:
            return jsonify({"error": "JSON body required"}), 400

        req_type = data.get("type", "image")
        prompt = data.get("prompt", "").strip()
        params = data.get("params", {})

        if not prompt:
            return jsonify({"error": "Prompt is required"}), 400

        if req_type not in ("image", "video", "audio_tts", "audio_music"):
            return jsonify({"error": f"Unsupported type: {req_type}"}), 400

        # Map request type to capability name
        cap_map = {
            "image": "image_gen",
            "video": "video_gen",
            "audio_tts": "audio_tts",
            "audio_music": "audio_music",
        }
        capability = cap_map[req_type]

        # Find provider
        from ai_bridge.external_providers import (
            get_providers_with_capability,
            generate_media as bridge_generate,
        )

        providers = get_providers_with_capability(capability)
        if not providers:
            return jsonify({"error": f"No providers available for {req_type} generation"}), 503

        # Pick first available (sorted by tier_position -- free first)
        provider = providers[0]
        provider_key = provider["provider_key"]
        is_free = provider["is_free_tier"]

        user_id = current_user.id

        # Insert queue entry
        conn = get_db()
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO media_generation_queue
                (request_type, prompt, params, status, provider_key, requested_by)
            VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING id
        """,
            (req_type, prompt, json.dumps(params), "generating", provider_key, user_id),
        )
        queue_id = cur.fetchone()[0]
        conn.commit()

        # For paid providers, check approval
        if not is_free:
            cur.execute("SELECT value FROM system_config WHERE key = 'media_auto_approve_under_usd'")
            row = cur.fetchone()
            auto_threshold = float(row[0]) if row else 0.0
            estimated_cost = 0.04  # Default DALL-E estimate

            if estimated_cost > auto_threshold:
                cur.execute(
                    """
                    UPDATE media_generation_queue SET status = 'awaiting_approval'
                    WHERE id = %s
                """,
                    (queue_id,),
                )
                conn.commit()

                # Request Telegram approval
                try:
                    from ai_bridge.agent_loop import request_approval

                    request_approval(
                        action_type="media_generation",
                        action_data={
                            "queue_id": queue_id,
                            "type": req_type,
                            "prompt": prompt[:200],
                            "provider": provider_key,
                            "estimated_cost": estimated_cost,
                        },
                        reason=f"Media generation ({req_type}) via {provider_key} — est. ${estimated_cost:.4f}",
                        requested_by=f"user:{user_id}",
                        priority=5,
                        tier=2,
                    )
                except Exception as e:
                    logger.error(f"Failed to request approval: {e}")

                cur.close()
                conn.close()
                return jsonify(
                    {
                        "queue_id": queue_id,
                        "status": "awaiting_approval",
                        "message": f"Paid provider ({provider_key}) requires admin approval via Telegram",
                    }
                )

        # Synchronous generation for fast providers
        media_request = {
            "type": req_type,
            "prompt": prompt,
            "params": params,
        }

        # Special case: local TTS
        actual_provider = provider_key
        if req_type == "audio_tts":
            actual_provider = "local_tts"

        result = bridge_generate(actual_provider, media_request)

        if not result.get("success"):
            cur.execute(
                """
                UPDATE media_generation_queue
                SET status = 'failed', error_message = %s, completed_at = NOW()
                WHERE id = %s
            """,
                (result.get("error", "Unknown error"), queue_id),
            )
            conn.commit()
            cur.close()
            conn.close()
            return (
                jsonify(
                    {
                        "queue_id": queue_id,
                        "status": "failed",
                        "error": result.get("error"),
                    }
                ),
                500,
            )

        # Save asset
        meta = result.get("metadata", {})
        cur.execute(
            """
            INSERT INTO media_assets
                (asset_type, prompt, file_path, file_size_bytes, mime_type,
                 provider_key, model_used, cost_usd, generation_params, created_by)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
        """,
            (
                req_type,
                prompt,
                result["file_path"],
                meta.get("file_size_bytes", 0),
                meta.get("mime_type", ""),
                meta.get("provider", provider_key),
                meta.get("model", ""),
                meta.get("cost_usd", 0),
                json.dumps(params),
                user_id,
            ),
        )
        asset_id = cur.fetchone()[0]

        # Update queue
        cur.execute(
            """
            UPDATE media_generation_queue
            SET status = 'completed', result_asset_id = %s, model_used = %s, completed_at = NOW()
            WHERE id = %s
        """,
            (asset_id, meta.get("model", ""), queue_id),
        )
        conn.commit()

        return jsonify(
            {
                "queue_id": queue_id,
                "status": "completed",
                "asset_id": asset_id,
                "file_path": result["file_path"],
                "metadata": meta,
            }
        )

    except Exception as e:
        logger.error(f"Media generation error: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


# --- Queue ----------------------------------------------------------------


@media_studio_bp.route("/api/queue", methods=["GET"])
@login_required
def list_queue():
    """List media generation queue for current user."""
    try:
        user_id = current_user.id
        conn = get_db()
        cur = conn.cursor()
        cur.execute(
            """
            SELECT q.id, q.request_type, q.prompt, q.status, q.provider_key,
                   q.model_used, q.error_message, q.created_at, q.completed_at,
                   q.result_asset_id,
                   a.file_path AS result_file_path
            FROM media_generation_queue q
            LEFT JOIN media_assets a ON q.result_asset_id = a.id
            WHERE q.requested_by = %s
            ORDER BY q.created_at DESC
            LIMIT 50
        """,
            (user_id,),
        )

        columns = [desc[0] for desc in cur.description]
        rows = [dict(zip(columns, row)) for row in cur.fetchall()]

        for row in rows:
            for key in ("created_at", "completed_at"):
                if row.get(key):
                    row[key] = row[key].isoformat()

        return jsonify({"queue": rows})
    except Exception as e:
        logger.error(f"Queue list error: {e}")
        return jsonify({"error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@media_studio_bp.route("/api/queue/<int:queue_id>", methods=["GET"])
@login_required
def get_queue_item(queue_id):
    """Get single queue item status (for polling)."""
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute(
            """
            SELECT q.id, q.request_type, q.prompt, q.status, q.provider_key,
                   q.model_used, q.error_message, q.created_at, q.started_at,
                   q.completed_at, q.result_asset_id,
                   a.file_path AS result_file_path
            FROM media_generation_queue q
            LEFT JOIN media_assets a ON q.result_asset_id = a.id
            WHERE q.id = %s AND q.requested_by = %s
        """,
            (queue_id, current_user.id),
        )

        row = cur.fetchone()
        if not row:
            cur.close()
            conn.close()
            return jsonify({"error": "Not found"}), 404

        columns = [desc[0] for desc in cur.description]
        item = dict(zip(columns, row))

        for key in ("created_at", "completed_at", "started_at"):
            if item.get(key):
                item[key] = item[key].isoformat()

        return jsonify(item)
    except Exception as e:
        logger.error(f"Queue item error: {e}")
        return jsonify({"error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@media_studio_bp.route("/api/queue/<int:queue_id>", methods=["DELETE"])
@login_required
def cancel_queue_item(queue_id):
    """Cancel a pending queue item."""
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute(
            """
            UPDATE media_generation_queue
            SET status = 'cancelled', completed_at = NOW()
            WHERE id = %s AND requested_by = %s AND status IN ('pending', 'awaiting_approval')
            RETURNING id
        """,
            (queue_id, current_user.id),
        )

        row = cur.fetchone()
        conn.commit()

        if not row:
            return jsonify({"error": "Not found or not cancellable"}), 404

        return jsonify({"status": "cancelled", "queue_id": queue_id})
    except Exception as e:
        logger.error(f"Queue cancel error: {e}")
        return jsonify({"error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


# --- Gallery --------------------------------------------------------------


@media_studio_bp.route("/api/gallery", methods=["GET"])
@login_required
def list_gallery():
    """Browse completed media assets."""
    try:
        asset_type = request.args.get("type")
        limit = min(int(request.args.get("limit", 50)), 100)
        offset = int(request.args.get("offset", 0))

        conn = get_db()
        cur = conn.cursor()

        query = """
            SELECT id, asset_type, title, prompt, file_path, file_size_bytes,
                   mime_type, provider_key, model_used, cost_usd, generation_params,
                   is_profile_image, agent_id, created_at
            FROM media_assets
            WHERE created_by = %s AND deleted_at IS NULL
        """
        params_list = [current_user.id]

        if asset_type:
            query += " AND asset_type = %s"
            params_list.append(asset_type)

        query += " ORDER BY created_at DESC LIMIT %s OFFSET %s"
        params_list.extend([limit, offset])

        cur.execute(query, params_list)
        columns = [desc[0] for desc in cur.description]
        rows = [dict(zip(columns, row)) for row in cur.fetchall()]

        for row in rows:
            if row.get("created_at"):
                row["created_at"] = row["created_at"].isoformat()
            if row.get("cost_usd"):
                row["cost_usd"] = float(row["cost_usd"])

        return jsonify({"assets": rows, "count": len(rows)})
    except Exception as e:
        logger.error(f"Gallery list error: {e}")
        return jsonify({"error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@media_studio_bp.route("/api/gallery/<int:asset_id>", methods=["GET"])
@login_required
def get_asset(asset_id):
    """Get single asset details."""
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute(
            """
            SELECT id, asset_type, title, prompt, file_path, file_size_bytes,
                   mime_type, provider_key, model_used, cost_usd, generation_params,
                   is_profile_image, agent_id, created_by, created_at
            FROM media_assets
            WHERE id = %s AND created_by = %s AND deleted_at IS NULL
        """,
            (asset_id, current_user.id),
        )

        row = cur.fetchone()
        if not row:
            cur.close()
            conn.close()
            return jsonify({"error": "Not found"}), 404

        columns = [desc[0] for desc in cur.description]
        asset = dict(zip(columns, row))

        if asset.get("created_at"):
            asset["created_at"] = asset["created_at"].isoformat()
        if asset.get("cost_usd"):
            asset["cost_usd"] = float(asset["cost_usd"])

        return jsonify(asset)
    except Exception as e:
        logger.error(f"Asset get error: {e}")
        return jsonify({"error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@media_studio_bp.route("/api/gallery/<int:asset_id>", methods=["DELETE"])
@login_required
def delete_asset(asset_id):
    """Soft-delete a media asset."""
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute(
            """
            UPDATE media_assets SET deleted_at = NOW()
            WHERE id = %s AND created_by = %s AND deleted_at IS NULL
            RETURNING id
        """,
            (asset_id, current_user.id),
        )

        row = cur.fetchone()
        conn.commit()

        if not row:
            return jsonify({"error": "Not found"}), 404

        return jsonify({"status": "deleted", "asset_id": asset_id})
    except Exception as e:
        logger.error(f"Asset delete error: {e}")
        return jsonify({"error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


# --- Profile Picture ------------------------------------------------------


@media_studio_bp.route("/api/gallery/<int:asset_id>/set-profile", methods=["POST"])
@login_required
def set_profile_image(asset_id):
    """Set a generated image as an agent's profile picture."""
    try:
        data = request.get_json() or {}
        agent_id = data.get("agent_id")

        if not agent_id:
            return jsonify({"error": "agent_id is required"}), 400

        conn = get_db()
        cur = conn.cursor()

        # Get the asset
        cur.execute(
            """
            SELECT file_path, asset_type FROM media_assets
            WHERE id = %s AND created_by = %s AND deleted_at IS NULL
        """,
            (asset_id, current_user.id),
        )

        row = cur.fetchone()
        if not row:
            cur.close()
            conn.close()
            return jsonify({"error": "Asset not found"}), 404

        file_path, asset_type = row
        if asset_type != "image":
            cur.close()
            conn.close()
            return jsonify({"error": "Only images can be set as profile pictures"}), 400

        # Clear previous profile image flag
        cur.execute(
            """
            UPDATE media_assets SET is_profile_image = FALSE
            WHERE agent_id = %s AND is_profile_image = TRUE
        """,
            (agent_id,),
        )

        # Set new profile image
        cur.execute(
            """
            UPDATE media_assets SET is_profile_image = TRUE, agent_id = %s
            WHERE id = %s
        """,
            (agent_id, asset_id),
        )

        # Update agent avatar_url
        cur.execute("UPDATE agents SET avatar_url = %s WHERE id = %s", (file_path, agent_id))

        conn.commit()

        return jsonify(
            {
                "status": "set",
                "agent_id": agent_id,
                "asset_id": asset_id,
                "avatar_url": file_path,
            }
        )
    except Exception as e:
        logger.error(f"Set profile error: {e}")
        return jsonify({"error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


# --- Status / Health ------------------------------------------------------


@media_studio_bp.route("/api/status", methods=["GET"])
@login_required
def media_status():
    """Health check for Media Studio."""
    try:
        from ai_bridge.external_providers import get_providers_with_capability

        image_providers = get_providers_with_capability("image_gen")
        tts_providers = get_providers_with_capability("audio_tts")

        return jsonify(
            {
                "status": "operational" if image_providers else "degraded",
                "image_providers": len(image_providers),
                "tts_providers": len(tts_providers),
                "providers": {
                    "image_gen": [p["provider_key"] for p in image_providers],
                    "audio_tts": [p["provider_key"] for p in tts_providers],
                },
            }
        )
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500
