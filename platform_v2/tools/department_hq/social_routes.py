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

from flask import current_app, jsonify, request
from flask_login import current_user
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

    # ── Social Profiles ──────────────────────────────────────────

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
            return jsonify({"success": True, "id": profile_id, "message": f"Profile added for {platform}"})
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

    @bp.route("/api/signal/overview")
    @admin_required
    def api_signal_overview():
        """S.I.G.N.A.L. status, pending approvals, post stats."""
        from database import get_db_cursor

        try:
            with get_db_cursor() as (_conn, cur):
                cur.execute(
                    """SELECT a.id, a.name, a.shift_state,
                              COALESCE(e.current_mood, 'neutral') AS current_mood,
                              COALESCE(e.stress_level, 0.2) AS stress_level
                       FROM agents a
                       LEFT JOIN agent_emotional_state e ON e.agent_id = a.id
                       WHERE a.name = %s
                       ORDER BY e.timestamp DESC NULLS LAST
                       LIMIT 1""",
                    ("S.I.G.N.A.L.",),
                )
                agent = cur.fetchone()

                cur.execute(
                    "SELECT COUNT(*) AS cnt FROM autonomy_approval_queue WHERE action_type = 'linkedin_post' AND status = 'pending'"
                )
                pending_count = cur.fetchone()["cnt"]

                cur.execute("SELECT COUNT(*) AS total FROM linkedin_post_log WHERE status = 'posted'")
                total_posted = cur.fetchone()["total"]

                cur.execute(
                    "SELECT COUNT(*) AS week FROM linkedin_post_log WHERE status = 'posted' AND posted_at > NOW() - INTERVAL '7 days'"
                )
                week_posted = cur.fetchone()["week"]

                cur.execute(
                    "SELECT COUNT(*) AS cnt FROM linkedin_post_log WHERE post_type = 'personal' AND status = 'posted'"
                )
                personal_count = cur.fetchone()["cnt"]

                cur.execute(
                    "SELECT COUNT(*) AS cnt FROM linkedin_post_log WHERE post_type IN ('company','company_page') AND status = 'posted'"
                )
                company_count = cur.fetchone()["cnt"]

                cur.execute(
                    "SELECT COUNT(*) AS cnt FROM dispatch_pending_queue WHERE capability = 'social_post_draft' AND status IN ('queued','running')"
                )
                queue_depth = cur.fetchone()["cnt"]

                cur.execute(
                    "SELECT MAX(created_at) AS last_run FROM autonomy_loop_log WHERE job_name = 'signal_linkedin_draft'"
                )
                last_run_row = cur.fetchone()
                last_run_at = (
                    last_run_row["last_run"].isoformat() if last_run_row and last_run_row["last_run"] else None
                )

            return jsonify(
                {
                    "agent": dict(agent) if agent else None,
                    "pending_approvals": int(pending_count),
                    "queue_depth": int(queue_depth),
                    "last_run_at": last_run_at,
                    "stats": {
                        "total_posted": int(total_posted),
                        "posted_this_week": int(week_posted),
                        "personal_posts": int(personal_count),
                        "company_posts": int(company_count),
                    },
                }
            )
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @bp.route("/api/signal/post-log")
    @admin_required
    def api_signal_post_log():
        """Recent posts from linkedin_post_log."""
        from database import get_db_cursor

        account = request.args.get("account", "personal")
        limit = min(int(request.args.get("limit", 30)), 100)
        post_type_filter = "personal" if account == "personal" else "company"
        try:
            with get_db_cursor() as (_conn, cur):
                cur.execute(
                    """SELECT id, content, hashtags, post_type, post_url, status,
                              impressions, reactions, comments, shares, posted_at, created_at
                       FROM linkedin_post_log
                       WHERE post_type ILIKE %s
                       ORDER BY posted_at DESC
                       LIMIT %s""",
                    (f"%{post_type_filter}%", limit),
                )
                posts = [dict(r) for r in cur.fetchall()]
            for p in posts:
                for k in ("posted_at", "created_at"):
                    if p.get(k):
                        p[k] = p[k].isoformat()
            return jsonify({"posts": posts, "account": account})
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @bp.route("/api/signal/hashtag-stats")
    @admin_required
    def api_signal_hashtag_stats():
        """Hashtag performance from linkedin_hashtag_stats."""
        from database import get_db_cursor

        limit = min(int(request.args.get("limit", 30)), 100)
        try:
            with get_db_cursor() as (_conn, cur):
                cur.execute(
                    """SELECT hashtag, usage_count, avg_engagement, total_impressions, last_used
                       FROM linkedin_hashtag_stats
                       ORDER BY usage_count DESC, hashtag ASC
                       LIMIT %s""",
                    (limit,),
                )
                tags = [dict(r) for r in cur.fetchall()]
            for t in tags:
                if t.get("last_used"):
                    t["last_used"] = t["last_used"].isoformat()
                if t.get("avg_engagement") is not None:
                    t["avg_engagement"] = float(t["avg_engagement"])
            return jsonify({"hashtags": tags})
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @bp.route("/api/signal/pending-approvals")
    @admin_required
    def api_signal_pending_approvals():
        """Pending linkedin_post items from the approval queue."""
        from database import get_db_cursor

        try:
            with get_db_cursor() as (_conn, cur):
                cur.execute(
                    """SELECT id, action_type, action_data, reason, requested_by, priority, created_at
                       FROM autonomy_approval_queue
                       WHERE action_type = 'linkedin_post' AND status = 'pending'
                       ORDER BY priority DESC, created_at ASC
                       LIMIT 20""",
                )
                rows = [dict(r) for r in cur.fetchall()]
            for r in rows:
                if r.get("created_at"):
                    r["created_at"] = r["created_at"].isoformat()
            return jsonify({"approvals": rows})
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @bp.route("/api/signal/compose", methods=["POST"])
    @admin_required
    def api_signal_compose():
        """UI → S.I.G.N.A.L. announce proxy (avoids exposing API key to browser)."""
        import json as _json
        import os
        import urllib.error
        import urllib.request

        data = request.get_json(silent=True) or {}
        payload = _json.dumps(
            {
                "announcement": (data.get("announcement") or "").strip(),
                "tone": data.get("tone", "professional"),
                "post_type": data.get("post_type", "both"),
                "hashtags": data.get("hashtags", []),
                "priority": int(data.get("priority", 6)),
            }
        ).encode()
        api_key = os.getenv("ARCHIE_API_KEY", "dev-api-key-change-in-production")
        req = urllib.request.Request(
            "http://localhost:3000/api/signal/announce",
            data=payload,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                return jsonify(_json.loads(r.read())), r.status
        except urllib.error.HTTPError as e:
            return jsonify({"error": e.read().decode()}), e.code
        except Exception as e:
            return jsonify({"error": str(e)}), 502

    @bp.route("/api/signal/calendar")
    @admin_required
    def api_signal_calendar():
        """This week's content calendar — 7 days with scheduled slots and queue status."""
        from datetime import date, timedelta

        today = date.today()
        monday = today - timedelta(days=today.weekday())

        # Theme schedule matching signal_linkedin_draft theme_map (0=Mon, 2=Wed, 4=Fri)
        theme_schedule = {
            0: {"theme_name": "Vision & Mission", "accent_color": "#8b5cf6"},
            2: {"theme_name": "Product Spotlight", "accent_color": "#06b6d4"},
            4: {"theme_name": "Building in Public", "accent_color": "#10b981"},
        }

        try:
            with get_db_cursor() as (_conn, cur):
                cur.execute(
                    """SELECT DATE(created_at) as day
                       FROM autonomy_approval_queue
                       WHERE action_type = 'linkedin_post'
                         AND status IN ('pending', 'approved')
                         AND created_at >= %s""",
                    (monday,),
                )
                queued_days = {r["day"] for r in cur.fetchall()}
        except Exception:
            queued_days = set()

        days = []
        for i in range(7):
            d = monday + timedelta(days=i)
            slot_def = theme_schedule.get(i)
            days.append(
                {
                    "date": d.isoformat(),
                    "slots": (
                        [
                            {
                                "theme_name": slot_def["theme_name"],
                                "agent_name": "S.I.G.N.A.L.",
                                "accent_color": slot_def["accent_color"],
                                "auto_generate": True,
                            }
                        ]
                        if slot_def
                        else []
                    ),
                    "queue_status": ["queued"] if d in queued_days else [],
                }
            )

        return jsonify({"days": days})

    @bp.route("/api/signal/themes")
    @admin_required
    def api_signal_themes():
        """Content theme lanes for S.I.G.N.A.L.'s posting strategy."""
        themes = [
            {
                "name": "Vision & Mission",
                "curator_name": "S.I.G.N.A.L.",
                "accent_color": "#8b5cf6",
                "scene_count": 1,
                "music_mood": "Mondays",
            },
            {
                "name": "Product Spotlight",
                "curator_name": "S.I.G.N.A.L.",
                "accent_color": "#06b6d4",
                "scene_count": 1,
                "music_mood": "Wednesdays",
            },
            {
                "name": "Building in Public",
                "curator_name": "S.I.G.N.A.L.",
                "accent_color": "#10b981",
                "scene_count": 1,
                "music_mood": "Fridays",
            },
            {
                "name": "Gov Watch Tender Alert",
                "curator_name": "P.R.O.C.U.R.E.",
                "accent_color": "#f59e0b",
                "scene_count": 0,
                "music_mood": "On demand",
            },
            {
                "name": "KBS Announcement",
                "curator_name": "S.I.G.N.A.L.",
                "accent_color": "#ec4899",
                "scene_count": 0,
                "music_mood": "On demand",
            },
        ]
        return jsonify({"themes": themes})

    @bp.route("/api/signal/run-now", methods=["POST"])
    @admin_required
    def api_signal_run_now():
        """Trigger signal_linkedin_draft job immediately via job service."""
        try:
            svc = current_app.config.get("JOB_SERVICE")
            if not svc:
                return jsonify({"success": False, "error": "Job service unavailable"}), 503
            svc.run_job("signal_linkedin_draft")
            return jsonify({"success": True, "message": "signal_linkedin_draft triggered"})
        except Exception as e:
            return jsonify({"success": False, "error": str(e)}), 500

    @bp.route("/api/signal/pending/<int:approval_id>/approve", methods=["POST"])
    @admin_required
    def api_signal_approve(approval_id):
        """Approve a pending LinkedIn post draft."""
        from database import get_db_cursor

        try:
            with get_db_cursor(commit=True) as (_conn, cur):
                cur.execute(
                    """UPDATE autonomy_approval_queue
                       SET status = 'approved', approved_by = %s, approved_at = NOW(), updated_at = NOW()
                       WHERE id = %s AND action_type = 'linkedin_post' AND status = 'pending'
                       RETURNING id""",
                    (current_user.id, approval_id),
                )
                row = cur.fetchone()
            if not row:
                return jsonify({"success": False, "error": "Not found or already processed"}), 404
            return jsonify({"success": True, "approval_id": approval_id})
        except Exception as e:
            return jsonify({"success": False, "error": str(e)}), 500

    @bp.route("/api/signal/pending/<int:approval_id>/deny", methods=["POST"])
    @admin_required
    def api_signal_deny(approval_id):
        """Deny a pending LinkedIn post draft with reason."""
        from database import get_db_cursor

        data = request.get_json(silent=True) or {}
        reason = (data.get("reason") or "Denied via web UI").strip()
        try:
            with get_db_cursor(commit=True) as (_conn, cur):
                cur.execute(
                    """UPDATE autonomy_approval_queue
                       SET status = 'rejected', approved_by = %s,
                           rejected_reason = %s, updated_at = NOW()
                       WHERE id = %s AND action_type = 'linkedin_post' AND status = 'pending'
                       RETURNING id""",
                    (current_user.id, reason, approval_id),
                )
                row = cur.fetchone()
            if not row:
                return jsonify({"success": False, "error": "Not found or already processed"}), 404
            return jsonify({"success": True, "approval_id": approval_id})
        except Exception as e:
            return jsonify({"success": False, "error": str(e)}), 500
