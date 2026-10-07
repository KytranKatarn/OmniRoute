"""
Department HQ -- Agent Social Presence routes

Endpoints:
  GET    /api/agent/<id>/social-profiles           -- List social profiles
  POST   /api/agent/<id>/social-profiles           -- Add/update profile
  DELETE /api/agent/<id>/social-profiles/<platform> -- Remove profile
  GET    /api/agent/<id>/writing-voice              -- Get writing voice
  POST   /api/agent/<id>/writing-voice              -- Update writing voice
  GET    /api/agent/<id>/posts                      -- List posts
  POST   /api/agent/<id>/posts/generate             -- Generate post content
  POST   /api/agent/<id>/posts                      -- Create post
  POST   /api/posts/<id>/publish                    -- Publish a post
  GET    /api/social/feed                           -- All recent posts
  GET    /api/social/stats                          -- Social presence stats
"""

from flask import jsonify, request
from flask_login import current_user  # noqa: F401 - preserve existing module import
from services.agent_service import get_agent
from services.agent_social_service import (
    get_social_profiles,
    add_social_profile,
    remove_social_profile,
    get_writing_voice,
    update_writing_voice,
    get_posts,
    create_post,
    publish_post,
    generate_post_content,
)

VALID_PLATFORMS = (
    "twitter",
    "linkedin",
    "instagram",
    "bluesky",
    "mastodon",
    "threads",
    "github",
    "website",
)

VALID_TONES = (
    "professional",
    "casual",
    "witty",
    "academic",
    "inspirational",
    "technical",
    "friendly",
    "authoritative",
)


def register_social_routes(bp, admin_required):
    """Register agent social presence routes on the blueprint."""

    # ── LinkedIn persistent trusted session (#3953 / #3948) ──────
    # Thin proxies to the archie_browser_login sidecar (:4281). The owner's
    from .social_session_routes import register_social_session_routes
    from .signal_monitor_routes import register_signal_monitor_routes
    from .signal_action_routes import register_signal_action_routes

    register_social_session_routes(bp, admin_required)

    @bp.route("/api/agent/<int:agent_id>/social-profiles")
    @admin_required
    def api_agent_social_profiles(agent_id):
        """List social profiles for an agent."""
        try:
            agent = get_agent(agent_id)
            if not agent:
                return jsonify({"error": "Agent not found"}), 404
            profiles = get_social_profiles(agent_id)
            return jsonify({"agent_id": agent_id, "profiles": profiles})
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @bp.route("/api/agent/<int:agent_id>/social-profiles", methods=["POST"])
    @admin_required
    def api_agent_add_social_profile(agent_id):
        """Add or update a social media profile."""
        data = request.get_json(silent=True) or {}
        platform = (data.get("platform") or "").strip().lower()
        handle = (data.get("handle") or "").strip()
        profile_url = (data.get("profile_url") or "").strip()

        if not platform:
            return jsonify({"error": "platform is required"}), 400
        if platform not in VALID_PLATFORMS:
            return (
                jsonify({"error": f"Invalid platform. Valid: {', '.join(VALID_PLATFORMS)}"}),
                400,
            )
        if not handle:
            return jsonify({"error": "handle is required"}), 400

        try:
            agent = get_agent(agent_id)
            if not agent:
                return jsonify({"error": "Agent not found"}), 404

            profile_id = add_social_profile(agent_id, platform, handle, profile_url)
            return jsonify(
                {
                    "success": True,
                    "id": profile_id,
                    "message": f"Profile added for {platform}",
                }
            )
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @bp.route("/api/agent/<int:agent_id>/social-profiles/<platform>", methods=["DELETE"])
    @admin_required
    def api_agent_remove_social_profile(agent_id, platform):
        """Remove a social media profile."""
        try:
            agent = get_agent(agent_id)
            if not agent:
                return jsonify({"error": "Agent not found"}), 404
            remove_social_profile(agent_id, platform.lower())
            return jsonify({"success": True, "message": f"Removed {platform} profile"})
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    # ── Writing Voice ────────────────────────────────────────────

    @bp.route("/api/agent/<int:agent_id>/writing-voice")
    @admin_required
    def api_agent_writing_voice(agent_id):
        """Get agent's writing voice settings."""
        try:
            agent = get_agent(agent_id)
            if not agent:
                return jsonify({"error": "Agent not found"}), 404
            voice = get_writing_voice(agent_id)
            return jsonify({"agent_id": agent_id, "voice": voice})
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @bp.route("/api/agent/<int:agent_id>/writing-voice", methods=["POST"])
    @admin_required
    def api_agent_update_writing_voice(agent_id):
        """Update agent's writing voice."""
        data = request.get_json(silent=True) or {}
        tone = data.get("tone")
        style = data.get("style")
        topics = data.get("topics")

        if tone and tone not in VALID_TONES:
            return (
                jsonify({"error": f"Invalid tone. Valid: {', '.join(VALID_TONES)}"}),
                400,
            )
        if topics is not None and not isinstance(topics, list):
            return jsonify({"error": "topics must be an array"}), 400

        try:
            agent = get_agent(agent_id)
            if not agent:
                return jsonify({"error": "Agent not found"}), 404

            update_writing_voice(agent_id, tone=tone, style=style, topics=topics)
            return jsonify({"success": True, "message": "Writing voice updated"})
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    # ── Posts ────────────────────────────────────────────────────

    @bp.route("/api/agent/<int:agent_id>/posts")
    @admin_required
    def api_agent_posts(agent_id):
        """List posts for an agent."""
        try:
            agent = get_agent(agent_id)
            if not agent:
                return jsonify({"error": "Agent not found"}), 404
            status_filter = request.args.get("status")
            posts = get_posts(agent_id=agent_id, status=status_filter)
            return jsonify({"agent_id": agent_id, "posts": posts})
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @bp.route("/api/agent/<int:agent_id>/posts/generate", methods=["POST"])
    @admin_required
    def api_agent_generate_post(agent_id):
        """Generate post content in the agent's voice (returns text, does not save)."""
        data = request.get_json(silent=True) or {}
        topic = (data.get("topic") or "").strip()

        try:
            agent = get_agent(agent_id)
            if not agent:
                return jsonify({"error": "Agent not found"}), 404

            content = generate_post_content(agent_id, topic=topic or None)
            if not content:
                return (
                    jsonify({"error": "Generation failed or returned empty"}),
                    502,
                )
            return jsonify({"content": content})
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @bp.route("/api/agent/<int:agent_id>/posts", methods=["POST"])
    @admin_required
    def api_agent_create_post(agent_id):
        """Create a content post (draft by default)."""
        data = request.get_json(silent=True) or {}
        content = (data.get("content") or "").strip()
        platform = (data.get("platform") or "").strip().lower() or None
        post_type = data.get("post_type", "update")

        if not content:
            return jsonify({"error": "content is required"}), 400

        try:
            agent = get_agent(agent_id)
            if not agent:
                return jsonify({"error": "Agent not found"}), 404

            post_id = create_post(agent_id, content, platform=platform, post_type=post_type)
            return jsonify({"success": True, "id": post_id, "message": "Post created as draft"})
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @bp.route("/api/posts/<int:post_id>/publish", methods=["POST"])
    @admin_required
    def api_publish_post(post_id):
        """Publish a post."""
        try:
            publish_post(post_id)
            return jsonify({"success": True, "message": "Post published"})
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    # ── Social Feed & Stats ──────────────────────────────────────

    @bp.route("/api/social/feed")
    @admin_required
    def api_social_feed():
        """All recent posts across agents."""
        try:
            limit = min(int(request.args.get("limit", 50)), 200)
            status_filter = request.args.get("status")
            posts = get_posts(status=status_filter, limit=limit)
            return jsonify({"posts": posts})
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @bp.route("/api/social/stats")
    @admin_required
    def api_social_stats():
        """Social presence stats -- agents with profiles, posts this week."""
        try:
            from database import get_db_cursor

            with get_db_cursor() as (conn, cur):
                cur.execute("SELECT COUNT(DISTINCT agent_id) AS agents_with_profiles FROM agent_social_profiles")
                agents_with_profiles = cur.fetchone()["agents_with_profiles"]

                cur.execute(
                    """SELECT COUNT(*) AS total_profiles,
                              COUNT(DISTINCT platform) AS platforms_used
                       FROM agent_social_profiles"""
                )
                profile_row = cur.fetchone()

                cur.execute(
                    """SELECT COUNT(*) AS posts_this_week
                       FROM agent_content_posts
                       WHERE created_at > NOW() - INTERVAL '7 days'"""
                )
                posts_week = cur.fetchone()["posts_this_week"]

                cur.execute(
                    """SELECT COUNT(*) AS published
                       FROM agent_content_posts
                       WHERE status = 'published'"""
                )
                published = cur.fetchone()["published"]

            return jsonify(
                {
                    "agents_with_profiles": agents_with_profiles,
                    "total_profiles": profile_row["total_profiles"],
                    "platforms_used": profile_row["platforms_used"],
                    "posts_this_week": posts_week,
                    "total_published": published,
                }
            )
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    # ── S.I.G.N.A.L. Command Center ──────────────────────────────

    register_signal_monitor_routes(bp, admin_required)
    register_signal_action_routes(bp, admin_required)
