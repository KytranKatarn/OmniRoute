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

    # ── LinkedIn persistent trusted session (#3953 / #3948) ──────
    # Thin proxies to the archie_browser_login sidecar (:4281). The owner's
    # one-time login happens via noVNC (:4280); these endpoints just
    # start/stop the headed browser and report session posture for the
    # S.I.G.N.A.L. SESSION sub-tab.
    _LOGIN_SIDECAR = "http://archie_browser_login:4281"
    # Mirrors the sidecar's _ALLOWED_PLATFORMS (#3982 multi-site).
    _BROWSER_PLATFORMS = {"linkedin", "x", "claude", "deepseek"}

    def _sidecar_headers():
        import os as _os

        return {"Authorization": f"Bearer {_os.getenv('INTERNAL_API_KEY', '')}"}

    def _valid_browser_platform(raw) -> str:
        p = (raw or "linkedin").strip().lower()
        return p if p in _BROWSER_PLATFORMS else "linkedin"

    # ── S.I.G.N.A.L. Engagement (likes / proactive comments) — session-authed UI
    #    surface for the approval-gated engagement system. The /api/signal/*
    #    endpoints are API-key-only; the tab is session-authed, so it calls these.
    #    Everything here only PROPOSES — actions fire after a Telegram/tab Approve.
    @bp.route("/api/social/signal/engagement", methods=["GET"])
    @admin_required
    def api_signal_engagement_state():
        from services.signal_engagement_service import engagement_state_by_agent, get_targets
        from services.work_control_service import is_enabled

        return jsonify(
            {
                "targets": get_targets(),
                "monitor_enabled": is_enabled("signal_engagement_monitor", default=False),
                "comments_enabled": is_enabled("signal_engagement_comments", default=False),
                # S7-P1-4b: per-agent voice + daily budget + today's count (drives the UI).
                "agents": engagement_state_by_agent(),
            }
        )

    @bp.route("/api/social/signal/engage", methods=["POST"])
    @admin_required
    def api_signal_engage():
        from services.signal_engagement_service import propose_comment, propose_like

        body = request.get_json(silent=True) or {}
        action = (body.get("action") or "").strip().lower()
        post_url = (body.get("post_url") or "").strip()
        account = (body.get("account") or "personal").strip().lower()
        if not post_url:
            return jsonify({"error": "post_url required"}), 400
        try:
            if action == "like":
                aid = propose_like(post_url, account=account, reaction=(body.get("reaction") or "like"))
            elif action == "comment":
                comment = (body.get("comment") or "").strip()
                if not comment:
                    return jsonify({"error": "comment required for action=comment"}), 400
                aid = propose_comment(post_url, comment, account=account)
            else:
                return jsonify({"error": "action must be 'like' or 'comment'"}), 400
        except ValueError as ve:
            return jsonify({"error": str(ve)}), 400
        except Exception as exc:
            return jsonify({"error": f"engage failed: {exc}"}), 502
        return jsonify({"ok": True, "approval_id": aid, "action": action, "status": "pending_approval"})

    @bp.route("/api/social/signal/targets", methods=["POST"])
    @admin_required
    def api_signal_set_targets():
        from services.signal_engagement_service import get_targets, set_targets

        body = request.get_json(silent=True) or {}
        targets = body.get("targets")
        if not isinstance(targets, list):
            return jsonify({"error": "targets must be a list of LinkedIn profile/company URLs"}), 400
        count = set_targets(targets)
        return jsonify({"ok": True, "count": count, "targets": get_targets()})

    @bp.route("/api/social/signal/agent-config/<account_key>", methods=["POST"])
    @admin_required
    def api_signal_agent_config(account_key):
        """S7-P1-4b: edit a can_engage account's daily_action_budget / voice_key on the
        registry. Body: {daily_action_budget?: int, voice_key?: str}. Column names are
        fixed literals — only the values are user-supplied (parameterized)."""
        from database import get_db_cursor
        from services import signal_accounts

        body = request.get_json(silent=True) or {}
        sets, params = [], []
        if "daily_action_budget" in body:
            try:
                sets.append("daily_action_budget = %s")
                params.append(max(0, int(body["daily_action_budget"])))
            except (TypeError, ValueError):
                return jsonify({"error": "daily_action_budget must be an integer"}), 400
        if "voice_key" in body:
            sets.append("voice_key = %s")
            params.append((body.get("voice_key") or "").strip() or None)
        if not sets:
            return jsonify({"error": "nothing to update (daily_action_budget / voice_key)"}), 400
        params.append(account_key)
        with get_db_cursor(commit=True) as (_conn, cur):
            cur.execute(f"UPDATE agent_platform_accounts SET {', '.join(sets)} WHERE account_key = %s", params)
            updated = cur.rowcount
        if not updated:
            return jsonify({"error": f"no account '{account_key}'"}), 404
        signal_accounts.invalidate()
        return jsonify({"ok": True, "account_key": account_key, "updated": updated})

    @bp.route("/api/social/signal/onboarding", methods=["GET"])
    @admin_required
    def api_signal_onboarding():
        """S7-P6.5b: per-account onboarding state + the next (owner-gated?) step — drives
        the DHQ Accounts panel. Phone contents never leave the server."""
        from services.signal_onboarding_service import is_enabled, onboarding_overview

        return jsonify({"enabled": is_enabled(), "accounts": onboarding_overview()})

    @bp.route("/api/social/signal/onboarding/<account_key>", methods=["POST"])
    @admin_required
    def api_signal_onboarding_transition(account_key):
        """S7-P6.5b: advance an account's onboarding (forward-only). Body: {to_state,
        owner_gate_phone?}. profile_logged_in / company_joined are owner-gated; the one-time
        noVNC login itself is the S.C.O.U.T. session flow. Telegram/UI approval unchanged."""
        from services.signal_onboarding_service import transition

        body = request.get_json(silent=True) or {}
        to_state = (body.get("to_state") or "").strip()
        if not to_state:
            return jsonify({"error": "to_state required"}), 400
        res = transition(account_key, to_state, owner_gate_phone=body.get("owner_gate_phone"), actor="claude")
        return (jsonify(res), 200) if res.get("ok") else (jsonify(res), 400)

    @bp.route("/api/social/signal/engagement-toggle", methods=["POST"])
    @admin_required
    def api_signal_engagement_toggle():
        from services.work_control_service import is_enabled, set_enabled

        body = request.get_json(silent=True) or {}
        flag = (body.get("flag") or "").strip().lower()
        key = {
            "monitor": "signal_engagement_monitor",
            "comments": "signal_engagement_comments",
        }.get(flag)
        if not key:
            return jsonify({"error": "flag must be 'monitor' or 'comments'"}), 400
        set_enabled(key, bool(body.get("enabled")))
        return jsonify({"ok": True, "flag": flag, "enabled": is_enabled(key, default=False)})

    @bp.route("/api/social/linkedin/session-status")
    @admin_required
    def api_linkedin_session_status():
        import requests as _rq

        agent_id = int(request.args.get("agent_id", 342))
        platform = _valid_browser_platform(request.args.get("platform"))
        out = {"success": True, "agent_id": agent_id, "platform": platform}
        try:
            from database import get_db_cursor

            with get_db_cursor(commit=False) as (_c, cur):
                cur.execute(
                    """SELECT status, last_used_at, last_probe_ok, last_failure_reason
                       FROM browser_sessions WHERE agent_id=%s AND platform=%s""",
                    (agent_id, platform),
                )
                row = cur.fetchone()
                out["db_session"] = dict(row) if row else None
        except Exception as exc:
            out["db_session_error"] = str(exc)
        try:
            r = _rq.get(
                f"{_LOGIN_SIDECAR}/status",
                params={"agent_id": agent_id, "platform": platform},
                headers=_sidecar_headers(),
                timeout=5,
            )
            out["login_surface"] = r.json()
        except Exception as exc:
            out["login_surface"] = None
            out["login_surface_error"] = f"sidecar unreachable: {type(exc).__name__}"
        # noVNC password — admin-only surface (same trust boundary as API keys /
        # tenant keys shown elsewhere in this admin UI), so the owner can log in
        # from S.I.G.N.A.L. without SSHing to read .env.
        import os as _os

        out["vnc_password"] = _os.getenv("BROWSER_VNC_PASSWORD") or None
        return jsonify(out)

    @bp.route("/api/social/linkedin/session-login/start", methods=["POST"])
    @admin_required
    def api_linkedin_session_login_start():
        import requests as _rq

        body = request.get_json(silent=True) or {}
        try:
            r = _rq.post(
                f"{_LOGIN_SIDECAR}/start",
                json={
                    "agent_id": int(body.get("agent_id", 342)),
                    "platform": _valid_browser_platform(body.get("platform")),
                },
                headers=_sidecar_headers(),
                timeout=10,
            )
            return jsonify(r.json()), r.status_code
        except Exception as exc:
            return jsonify({"started": False, "error": f"sidecar unreachable: {type(exc).__name__}"}), 502

    @bp.route("/api/social/linkedin/session-login/stop", methods=["POST"])
    @admin_required
    def api_linkedin_session_login_stop():
        import requests as _rq

        try:
            r = _rq.post(f"{_LOGIN_SIDECAR}/stop", headers=_sidecar_headers(), timeout=25)
            return jsonify(r.json()), r.status_code
        except Exception as exc:
            return jsonify({"stopped": False, "error": f"sidecar unreachable: {type(exc).__name__}"}), 502

    @bp.route("/api/social/linkedin/credentials", methods=["POST"])
    @admin_required
    def api_linkedin_credentials():
        """Store LinkedIn login encrypted (AES-GCM, NOT .env) — store-only, no
        login attempt. Answers 'where do I put login info': the encrypted
        browser credential store, surfaced from the Session tab."""
        import os as _os
        import requests as _rq

        body = request.get_json(silent=True) or {}
        username = (body.get("username") or "").strip()
        password = body.get("password") or ""
        agent_id = int(body.get("agent_id", 342))
        if not username or not password:
            return jsonify({"saved": False, "error": "username and password required"}), 400
        try:
            r = _rq.post(
                "http://archie_browser:4242/session/credentials",
                json={
                    "agent_id": agent_id,
                    "platform": _valid_browser_platform(body.get("platform")),
                    "username": username,
                    "password": password,
                },
                headers={"Authorization": f"Bearer {_os.getenv('BROWSER_API_KEY', 'internal')}"},
                timeout=10,
            )
            ok = r.ok and (r.json() or {}).get("stored")
            return jsonify({"saved": bool(ok), **(r.json() if r.content else {})}), (200 if ok else 502)
        except Exception as exc:
            return jsonify({"saved": False, "error": f"browser worker unreachable: {type(exc).__name__}"}), 502

    # ── LinkedIn comment monitor (READ scope, #3964) ─────────────
    @bp.route("/api/social/linkedin/comments")
    @admin_required
    def api_linkedin_comments():
        """List ingested LinkedIn comments (read scope). ?unseen=1 filters."""
        from services import linkedin_comment_monitor as mon

        unseen = request.args.get("unseen") in ("1", "true", "yes")
        limit = min(int(request.args.get("limit", 50)), 200)
        return jsonify({"success": True, "comments": mon.list_recent_comments(limit=limit, unseen_only=unseen)})

    @bp.route("/api/social/linkedin/comments/refresh", methods=["POST"])
    @admin_required
    def api_linkedin_comments_refresh():
        """Trigger a READ-only comment poll. Body: {urls?: [post_url, ...]}.

        Seeds from linkedin_post_log + any explicit urls (e.g. a thread we
        commented on). Posts nothing. Synchronous; small N by design.
        """
        from services import linkedin_comment_monitor as mon

        body = request.get_json(silent=True) or {}
        extra = body.get("urls") or []
        if not isinstance(extra, list):
            return jsonify({"success": False, "error": "urls must be a list"}), 400
        return jsonify({"success": True, **mon.run_comment_monitor(extra_urls=extra)})

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
                    "SELECT COUNT(*) AS cnt FROM linkedin_post_log WHERE post_type ILIKE '%creed%' AND status = 'posted'"
                )
                creed_count = cur.fetchone()["cnt"]

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
                        "creed_posts": int(creed_count),
                    },
                }
            )
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @bp.route("/api/signal/accounts")
    @admin_required
    def api_signal_accounts():
        """Data-driven account roster from the registry (services.signal_accounts,
        migration 440) — drives the S.I.G.N.A.L. account bar instead of hardcoded JS.
        Includes ARCHIE + any supporting agent as data, no code change."""
        try:
            from services import signal_accounts

            out = [
                {
                    "account_key": a["account_key"],
                    "label": a.get("display_label"),
                    "role": a.get("role"),
                    "post_type": a.get("post_type"),
                    "agent_id": a.get("agent_id"),
                    "browser_agent_id": a.get("browser_agent_id"),
                    "company_slug": a.get("company_slug"),
                    "can_post": bool(a.get("can_post")),
                    "can_engage": bool(a.get("can_engage")),
                    "egress_pref": a.get("egress_pref"),
                    "profile_established": bool(a.get("profile_established")),
                }
                for a in signal_accounts.all_accounts()
            ]
            return jsonify({"accounts": out})
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @bp.route("/api/signal/accounts/health")
    @admin_required
    def api_signal_accounts_health():
        """Per-account health for the roster: session status (authed vs logged-out vs the
        #4372 'authed-but-probe-stale' false-negative), last posted, scheduled backlog, and
        pending/failing approvals — so each account shows an honest status dot."""
        from database import get_db_cursor
        from services import signal_accounts

        try:
            out = []
            with get_db_cursor(commit=False) as (_c, cur):
                for a in signal_accounts.all_accounts():
                    ak = a["account_key"]
                    bid = a.get("browser_agent_id")
                    post_types = list(signal_accounts.post_types_for(ak))
                    sess = {}
                    if bid:
                        cur.execute(
                            "SELECT status, last_probe_ok, last_probe_at FROM browser_sessions "
                            "WHERE agent_id = %s AND platform = 'linkedin' LIMIT 1",
                            (bid,),
                        )
                        sess = dict(cur.fetchone() or {})
                    cur.execute(
                        "SELECT MAX(posted_at) AS last FROM linkedin_post_log "
                        "WHERE status = 'posted' AND post_type = ANY(%s)",
                        (post_types,),
                    )
                    last_posted = (cur.fetchone() or {}).get("last")
                    cur.execute(
                        "SELECT status, COUNT(*) AS n FROM autonomy_approval_queue "
                        "WHERE action_type = 'linkedin_post' AND action_data->>'post_type' = ANY(%s) "
                        "AND status IN ('pending', 'failed') GROUP BY status",
                        (post_types,),
                    )
                    counts = {r["status"]: int(r["n"]) for r in cur.fetchall()}
                    cur.execute(
                        "SELECT COUNT(*) AS n FROM agent_content_posts "
                        "WHERE platform = 'linkedin' AND status = 'scheduled' AND post_type = ANY(%s)",
                        (post_types,),
                    )
                    scheduled = int((cur.fetchone() or {}).get("n") or 0)

                    # #5627: measure the OUTPUT, not just the component's self-report.
                    # On 2026-08-15 this dot showed 'healthy' for agent 342 while every
                    # post that day was failing on a login wall — because health was
                    # derived ENTIRELY from browser_sessions, which a precedence bug kept
                    # stamping 'active'. A profile whose recent posts are actually failing
                    # is NOT healthy no matter what its own probe row claims.
                    cur.execute(
                        "SELECT COUNT(*) AS n FROM linkedin_post_log "
                        "WHERE status = 'failed' AND post_type = ANY(%s) "
                        "AND posted_at > NOW() - INTERVAL '24 hours'",
                        (post_types,),
                    )
                    recent_failures = int((cur.fetchone() or {}).get("n") or 0)
                    cur.execute(
                        "SELECT COUNT(*) AS n FROM linkedin_post_log "
                        "WHERE status = 'posted' AND post_type = ANY(%s) "
                        "AND posted_at > NOW() - INTERVAL '24 hours'",
                        (post_types,),
                    )
                    recent_success = int((cur.fetchone() or {}).get("n") or 0)

                    established = bool(a.get("profile_established"))
                    status = sess.get("status")
                    probe_ok = sess.get("last_probe_ok")
                    if not established:
                        health = "not_established"
                    elif status == "stale":
                        health = "logged_out"
                    elif recent_failures and not recent_success:
                        # Self-report says fine, reality says otherwise. Trust reality.
                        health = "posting_failing"
                    elif probe_ok is False:
                        health = "probe_warn"  # authed on disk but probe flaky (#4372 false-negative)
                    elif status == "active":
                        health = "healthy"
                    else:
                        health = "unknown"
                    out.append(
                        {
                            "account_key": ak,
                            "label": a.get("display_label"),
                            "role": a.get("role"),
                            "can_post": bool(a.get("can_post")),
                            "can_engage": bool(a.get("can_engage")),
                            "egress_pref": a.get("egress_pref"),
                            "browser_agent_id": bid,
                            "profile_established": established,
                            "session_status": status,
                            "last_probe_ok": probe_ok,
                            "last_probe_at": (sess["last_probe_at"].isoformat() if sess.get("last_probe_at") else None),
                            "health": health,
                            "last_posted_at": last_posted.isoformat() if last_posted else None,
                            "scheduled": scheduled,
                            "pending_approvals": counts.get("pending", 0),
                            "failing_approvals": counts.get("failed", 0),
                            # #5627 — the OUTPUT signal behind `health`. Surfaced so the tab
                            # can say WHY an account is degraded instead of a bare dot, and
                            # so a 'healthy' claim can be cross-checked against reality.
                            "posts_failed_24h": recent_failures,
                            "posts_succeeded_24h": recent_success,
                        }
                    )
            return jsonify({"accounts": out})
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @bp.route("/api/signal/post-log")
    @admin_required
    def api_signal_post_log():
        """Recent posts from linkedin_post_log."""
        from database import get_db_cursor

        account = request.args.get("account", "personal")
        limit = min(int(request.args.get("limit", 30)), 100)
        if account == "personal":
            post_type_filter = "personal"
        elif account == "terry":
            post_type_filter = "terry"
        elif account == "creed":
            post_type_filter = "creed"
        else:
            post_type_filter = "company"
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
        """Pending linkedin_post items from the approval queue.

        Optional ?account=personal|company|creed filters by post_type in action_data.
        """
        from database import get_db_cursor

        account = request.args.get("account", "").strip().lower()
        try:
            with get_db_cursor() as (_conn, cur):
                if account == "personal":
                    cur.execute(
                        """SELECT id, action_type, action_data, reason, requested_by, priority, created_at
                           FROM autonomy_approval_queue
                           WHERE action_type = 'linkedin_post' AND status = 'pending'
                             AND action_data->>'post_type' = 'personal'
                           ORDER BY priority DESC, created_at ASC LIMIT 20""",
                    )
                elif account == "terry":
                    cur.execute(
                        """SELECT id, action_type, action_data, reason, requested_by, priority, created_at
                           FROM autonomy_approval_queue
                           WHERE action_type = 'linkedin_post' AND status = 'pending'
                             AND action_data->>'post_type' = 'terry'
                           ORDER BY priority DESC, created_at ASC LIMIT 20""",
                    )
                elif account == "company":
                    cur.execute(
                        """SELECT id, action_type, action_data, reason, requested_by, priority, created_at
                           FROM autonomy_approval_queue
                           WHERE action_type = 'linkedin_post' AND status = 'pending'
                             AND action_data->>'post_type' IN ('company', 'company_page')
                           ORDER BY priority DESC, created_at ASC LIMIT 20""",
                    )
                elif account == "creed":
                    cur.execute(
                        """SELECT id, action_type, action_data, reason, requested_by, priority, created_at
                           FROM autonomy_approval_queue
                           WHERE action_type = 'linkedin_post' AND status = 'pending'
                             AND action_data->>'post_type' IN ('creed', 'creed_ai')
                           ORDER BY priority DESC, created_at ASC LIMIT 20""",
                    )
                else:
                    cur.execute(
                        """SELECT id, action_type, action_data, reason, requested_by, priority, created_at
                           FROM autonomy_approval_queue
                           WHERE action_type = 'linkedin_post' AND status = 'pending'
                           ORDER BY priority DESC, created_at ASC LIMIT 20""",
                    )
                rows = [dict(r) for r in cur.fetchall()]
            for r in rows:
                if r.get("created_at"):
                    r["created_at"] = r["created_at"].isoformat()
            return jsonify({"approvals": rows})
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    # ── S.I.G.N.A.L. content calendar Phase 1 (#3989) ────────────
    @bp.route("/api/signal/calendar/backfill", methods=["POST"])
    @admin_required
    def api_signal_calendar_backfill():
        """One-shot: dedup the failed/staged backlog onto per-account
        calendars, 1/day forward. Idempotent; nothing publishes."""
        import logging as _logging

        from services import signal_calendar_service

        try:
            return jsonify({"success": True, **signal_calendar_service.backfill_calendar()})
        except Exception as e:
            _logging.getLogger("platform.signal_calendar").exception("backfill failed")
            return jsonify({"success": False, "error": str(e)}), 500

    @bp.route("/api/signal/calendar/scheduled")
    @admin_required
    def api_signal_calendar_scheduled():
        """Scheduled queue for ?account= (personal|terry|company|creed)."""
        from services import signal_calendar_service

        account = (request.args.get("account") or "personal").strip().lower()
        try:
            return jsonify({"account": account, "posts": signal_calendar_service.get_scheduled(account)})
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @bp.route("/api/signal/calendar/scheduled/<int:post_id>/cancel", methods=["POST"])
    @admin_required
    def api_signal_calendar_cancel(post_id):
        """Cancel one scheduled entry (prune stale backlog content)."""
        from services import signal_calendar_service

        ok = signal_calendar_service.cancel_scheduled(post_id)
        return jsonify({"success": ok}), (200 if ok else 404)

    @bp.route("/api/social/linkedin/comments/draft-replies", methods=["POST"])
    @admin_required
    def api_linkedin_comments_draft_replies():
        """Manually run the reply drafter (#3992) — same path as the 6h job.
        Drafts go to the Tier-2 Telegram approval queue; nothing posts."""
        from services import linkedin_comment_monitor as mon

        try:
            return jsonify({"success": True, **mon.draft_comment_replies()})
        except Exception as e:
            return jsonify({"success": False, "error": str(e)}), 500

    @bp.route("/api/signal/calendar/top-up", methods=["POST"])
    @admin_required
    def api_signal_calendar_topup():
        """Manually run the generation top-up (thin backlogs → fresh drafts
        onto the calendar). Same path as the 10:00 ET job."""
        from services import signal_calendar_service

        try:
            return jsonify({"success": True, **signal_calendar_service.top_up_calendars()})
        except Exception as e:
            return jsonify({"success": False, "error": str(e)}), 500

    @bp.route("/api/signal/calendar/release-now", methods=["POST"])
    @admin_required
    def api_signal_calendar_release_now():
        """Manually run the daily release (due posts → approval queue).
        Same path as the 09:05 ET job; still Telegram-gated downstream."""
        from services import signal_calendar_service

        try:
            return jsonify({"success": True, **signal_calendar_service.release_due_posts()})
        except Exception as e:
            return jsonify({"success": False, "error": str(e)}), 500

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

    @bp.route("/api/signal/run-now", methods=["POST"])
    @admin_required
    def api_signal_run_now():
        """Trigger signal_linkedin_draft job for a specific account (or all).

        Body: {"account": "personal"|"company"|"all"}  (default: "all")
        """
        import threading

        data = request.get_json(silent=True) or {}
        account = data.get("account", "all").strip().lower()
        try:
            from services.agent_jobs import signal_linkedin_draft

            def _run():
                signal_linkedin_draft(account_filter=account)

            threading.Thread(target=_run, daemon=True).start()
            return jsonify({"success": True, "message": f"signal_linkedin_draft triggered for: {account}"})
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
        """Deny a pending LinkedIn post draft.

        If a reason is provided, S.I.G.N.A.L. immediately revises
        the draft and re-queues it for approval (same as Suggest).
        """
        import threading
        from database import get_db_cursor

        data = request.get_json(silent=True) or {}
        reason = (data.get("reason") or "").strip()
        reject_reason = reason or "Denied via web UI"
        try:
            # Load original draft before marking rejected
            original_draft = ""
            action_data = {}
            with get_db_cursor(commit=True) as (_conn, cur):
                cur.execute(
                    """SELECT action_data FROM autonomy_approval_queue
                       WHERE id = %s AND action_type = 'linkedin_post' AND status = 'pending'""",
                    (approval_id,),
                )
                row = cur.fetchone()
                if not row:
                    return jsonify({"success": False, "error": "Not found or already processed"}), 404
                import json as _json

                action_data = (
                    row["action_data"] if isinstance(row["action_data"], dict) else _json.loads(row["action_data"])
                )
                original_draft = action_data.get("content", "")
                cur.execute(
                    """UPDATE autonomy_approval_queue
                       SET status = 'rejected', approved_by = %s,
                           rejected_reason = %s, updated_at = NOW()
                       WHERE id = %s""",
                    (current_user.id, reject_reason, approval_id),
                )

            # If reason given, kick S.I.G.N.A.L. to revise in background
            revising = bool(reason and original_draft)
            if revising:
                _od, _ad, _r = original_draft, action_data, reason

                def _revise():
                    try:
                        from signal_dispatch import redraft_with_suggestion

                        redraft_with_suggestion(_od, _r, _ad)
                    except Exception as _e:
                        import logging

                        logging.getLogger("platform.signal_dispatch").warning("Auto-revise after deny failed: %s", _e)

                threading.Thread(target=_revise, daemon=True).start()

            return jsonify(
                {
                    "success": True,
                    "approval_id": approval_id,
                    "revising": revising,
                    "message": "Denied — S.I.G.N.A.L. is revising based on your feedback." if revising else "Denied.",
                }
            )
        except Exception as e:
            return jsonify({"success": False, "error": str(e)}), 500

    # ── SIGNAL Phase 4 — Retry / Abandon ────────────────────────

    @bp.route("/api/signal/posts/<int:approval_id>/retry", methods=["POST"])
    @admin_required
    def api_signal_retry(approval_id):
        """Retry a failed LinkedIn post: reset status='approved' so the
        autonomy worker re-picks it up and re-fires the skill.

        Defense-in-depth: WHERE clause enforces failure-state check on execution_result
        to prevent re-posting of already-successful posts."""
        from database import get_db_cursor

        try:
            with get_db_cursor(commit=True) as (_conn, cur):
                cur.execute(
                    """UPDATE autonomy_approval_queue
                       SET status = 'approved',
                           execution_result = NULL,
                           executed_at = NULL,
                           updated_at = NOW()
                       WHERE id = %s
                         AND action_type = 'linkedin_post'
                         AND status = 'executed'
                         AND (
                                (execution_result->>'success')::text = 'false'
                             OR (execution_result->'result'->>'success')::text = 'false'
                             OR (execution_result->>'_status') IN ('failed', 'timeout')
                             OR (execution_result->'result'->>'_status') IN ('failed', 'timeout')
                         )
                       RETURNING id""",
                    (approval_id,),
                )
                row = cur.fetchone()
            if not row:
                return jsonify({"success": False, "error": "Not found or not in a failed state"}), 404
            return jsonify({"success": True, "approval_id": approval_id})
        except Exception as e:
            return jsonify({"success": False, "error": str(e)}), 500

    @bp.route("/api/signal/posts/<int:approval_id>/abandon", methods=["POST"])
    @admin_required
    def api_signal_abandon(approval_id):
        """Abandon (Mark Won't Fix) a post: terminal state='abandoned'.
        No worker action — chip displays as 'rejected' grey via classifier mapping."""
        from database import get_db_cursor

        try:
            with get_db_cursor(commit=True) as (_conn, cur):
                cur.execute(
                    """UPDATE autonomy_approval_queue
                       SET status = 'abandoned',
                           updated_at = NOW()
                       WHERE id = %s
                         AND action_type = 'linkedin_post'
                         AND status NOT IN ('abandoned', 'rejected', 'pending')
                       RETURNING id""",
                    (approval_id,),
                )
                row = cur.fetchone()
            if not row:
                return jsonify({"success": False, "error": "Not found or not in an abandonable state"}), 404
            return jsonify({"success": True, "approval_id": approval_id})
        except Exception as e:
            return jsonify({"success": False, "error": str(e)}), 500

    # ── SIGNAL Calendar Live ──────────────────────────────────────

    @bp.route("/api/signal/calendar/live", methods=["GET"])
    @admin_required
    def api_signal_calendar_live():
        """Return the 7-day living-dashboard view for one account.

        Query params:
            account: any registered S.I.G.N.A.L. account_key (required) — data-driven from
            the registry so terry / archie / supporting accounts all work (was hardcoded to
            personal/company/creed, which 400'd terry).
        """
        import logging

        from services import signal_accounts, signal_calendar_live_service

        _logger = logging.getLogger("platform.signal_calendar_live")

        account = (request.args.get("account") or "").strip().lower()
        _valid = set(signal_accounts.account_keys())
        if account not in _valid:
            return (
                jsonify({"error": "account must be one of: " + ", ".join(sorted(_valid))}),
                400,
            )

        try:
            view = signal_calendar_live_service.get_week_view(account=account)
        except Exception:
            _logger.exception("[signal-calendar-live] failed to build view")
            return jsonify({"error": "failed to build calendar view"}), 500

        return jsonify(view), 200
