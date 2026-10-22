"""Media Hub API routes."""

from . import media_hub_bp
from .routes_shared import *  # noqa: F401,F403

@media_hub_bp.route("/api/settings/services", methods=["POST"])
@media_hub_admin_required
def api_add_service():
    """Add or update a service configuration"""
    data = request.get_json() or {}

    service_type = data.get("service_type")
    name = data.get("name")
    host = data.get("host", MEDIA_HOST)
    port = data.get("port")
    use_ssl = data.get("use_ssl", False)
    api_key = data.get("api_key")
    is_primary = data.get("is_primary", False)
    is_enabled = data.get("is_enabled", True)
    config_path = data.get("config_path")

    if not service_type or not port:
        return (
            jsonify({"success": False, "error": "service_type and port are required"}),
            400,
        )

    try:
        # Encrypt API key if provided
        api_key_encrypted = encrypt_api_key(api_key) if api_key else None

        with get_db_cursor(cursor_factory=None, commit=True) as (conn, cur):
            # Check if service exists
            cur.execute(
                "SELECT id FROM media_hub_services WHERE service_type = %s AND host = %s AND port = %s",
                (service_type, host, port),
            )
            existing = cur.fetchone()

            if existing:
                # Update existing
                cur.execute(
                    """
                    UPDATE media_hub_services SET
                        name = COALESCE(%s, name),
                        use_ssl = %s,
                        api_key_encrypted = COALESCE(%s, api_key_encrypted),
                        is_primary = %s,
                        is_enabled = %s,
                        config_path = COALESCE(%s, config_path),
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = %s
                """,
                    (
                        name,
                        use_ssl,
                        api_key_encrypted,
                        is_primary,
                        is_enabled,
                        config_path,
                        existing[0],
                    ),
                )
                service_id = existing[0]
            else:
                # Insert new
                cur.execute(
                    """
                    INSERT INTO media_hub_services
                    (service_type, name, host, port, use_ssl, api_key_encrypted, is_primary, is_enabled, config_path)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING id
                """,
                    (
                        service_type,
                        name or service_type.title(),
                        host,
                        port,
                        use_ssl,
                        api_key_encrypted,
                        is_primary,
                        is_enabled,
                        config_path,
                    ),
                )
                service_id = cur.fetchone()[0]

            return jsonify(
                {
                    "success": True,
                    "service_id": service_id,
                    "message": f"{service_type} configuration saved",
                }
            )
    except Exception as e:
        logger.error(f"Error saving service: {e}")
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass

@media_hub_bp.route("/api/settings/discover", methods=["POST"])
@media_hub_admin_required
def api_discover_services():
    """Auto-discover API keys from config files"""
    try:
        discovered = discover_all_api_keys()
        saved_count = 0

        with get_db_cursor(cursor_factory=None, commit=True) as (conn, cur):
            for service_type, info in discovered.items():
                if info["found"] and info["api_key"]:
                    # Encrypt the discovered API key
                    api_key_encrypted = encrypt_api_key(info["api_key"])

                    # Update or insert
                    cur.execute(
                        """
                        INSERT INTO media_hub_services
                        (service_type, name, host, port, use_ssl, api_key_encrypted, config_path)
                        VALUES (%s, %s, %s, %s, FALSE, %s, %s)
                        ON CONFLICT (service_type, host, port) DO UPDATE SET
                            api_key_encrypted = EXCLUDED.api_key_encrypted,
                            config_path = EXCLUDED.config_path,
                            updated_at = CURRENT_TIMESTAMP
                    """,
                        (
                            service_type,
                            service_type.title(),
                            MEDIA_HOST,
                            info["port"],
                            api_key_encrypted,
                            info["config_path"],
                        ),
                    )
                    saved_count += 1

        # Build response without exposing actual keys
        results = {}
        for service_type, info in discovered.items():
            results[service_type] = {
                "found": info["found"],
                "config_path": info["config_path"],
                "port": info["port"],
                "note": info.get("note"),
            }

        return jsonify(
            {
                "success": True,
                "discovered": results,
                "saved_count": saved_count,
                "message": f"Discovered and saved {saved_count} API keys",
            }
        )
    except Exception as e:
        logger.error(f"Error discovering services: {e}")
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500

@media_hub_bp.route("/api/settings/test/<int:service_id>", methods=["POST"])
@media_hub_admin_required
def api_test_service(service_id):
    """Test connection to a specific service"""
    try:
        # Read service config
        with get_db_cursor(cursor_factory=None, commit=False) as (conn, cur):
            cur.execute(
                """
                SELECT service_type, host, port, use_ssl, api_key_encrypted
                FROM media_hub_services WHERE id = %s
            """,
                (service_id,),
            )
            row = cur.fetchone()

        if not row:
            return jsonify({"success": False, "error": "Service not found"}), 404

        service_type, host, port, use_ssl, api_key_encrypted = row
        api_key = decrypt_api_key(api_key_encrypted) if api_key_encrypted else None

        if not api_key:
            return jsonify({"success": False, "error": "No API key configured"})

        # Test connection — prefer probe() for a real error message
        client = get_service_client(service_type, host, port, api_key, use_ssl)
        if hasattr(client, "probe"):
            is_healthy, health_message = client.probe()
        else:
            is_healthy = client.test_connection()
            health_message = "Connection successful" if is_healthy else "Connection failed"

        # Update health status in database
        with get_db_cursor(cursor_factory=None, commit=True) as (conn, cur):
            cur.execute(
                """
                UPDATE media_hub_services SET
                    health_status = %s,
                    health_message = %s,
                    last_health_check = CURRENT_TIMESTAMP
                WHERE id = %s
            """,
                (
                    "healthy" if is_healthy else "unhealthy",
                    health_message,
                    service_id,
                ),
            )

        return jsonify(
            {
                "success": True,
                "healthy": is_healthy,
                "message": ("Connection successful" if is_healthy else "Connection failed"),
            }
        )
    except Exception as e:
        logger.error(f"Error testing service: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

@media_hub_bp.route("/api/settings/services/<int:service_id>", methods=["DELETE"])
@media_hub_admin_required
def api_delete_service(service_id):
    """Delete a service configuration"""
    try:
        with get_db_cursor(cursor_factory=None, commit=True) as (conn, cur):
            cur.execute(
                "DELETE FROM media_hub_services WHERE id = %s RETURNING service_type",
                (service_id,),
            )
            deleted = cur.fetchone()

            if deleted:
                return jsonify({"success": True, "message": f"{deleted[0]} deleted"})
            else:
                return jsonify({"success": False, "error": "Service not found"}), 404
    except Exception as e:
        logger.error(f"Error deleting service: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

@media_hub_bp.route("/api/settings/set-primary/<int:service_id>", methods=["POST"])
@media_hub_admin_required
def api_set_primary_server(service_id):
    """Set a service as the primary media server"""
    try:
        with get_db_cursor(cursor_factory=None, commit=True) as (conn, cur):
            # Get service type
            cur.execute("SELECT service_type FROM media_hub_services WHERE id = %s", (service_id,))
            row = cur.fetchone()
            if not row:
                return jsonify({"success": False, "error": "Service not found"}), 404

            service_type = row[0]
            if service_type not in ("plex", "jellyfin"):
                return (
                    jsonify({"success": False, "error": "Only Plex or Jellyfin can be primary"}),
                    400,
                )

            # Unset all other primaries for media servers
            cur.execute(
                """
                UPDATE media_hub_services SET is_primary = FALSE
                WHERE service_type IN ('plex', 'jellyfin')
            """
            )

            # Set this one as primary
            cur.execute(
                "UPDATE media_hub_services SET is_primary = TRUE WHERE id = %s",
                (service_id,),
            )

            return jsonify({"success": True, "message": f"{service_type} set as primary media server"})
    except Exception as e:
        logger.error(f"Error setting primary: {e}")
        return jsonify({"success": False, "error": str(e)}), 500
