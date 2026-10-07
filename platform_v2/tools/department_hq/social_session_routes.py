"""Department HQ social routes: social session routes."""

from flask import jsonify, request


def register_social_session_routes(bp, admin_required):
    # one-time login happens via noVNC (:4280); these endpoints just
    # start/stop the headed browser and report session posture for the
    # S.I.G.N.A.L. SESSION sub-tab.
    _LOGIN_SIDECAR = "http://archie_browser_login:4281"
    # Mirrors the sidecar's _ALLOWED_PLATFORMS (#3982 multi-site).
    _BROWSER_PLATFORMS = {"linkedin", "x", "claude", "deepseek"}

    def _sidecar_headers():
        import os as _os

        return {
            "Authorization": f"Bearer {(_os.getenv('BROWSER_LOGIN_API_KEY') or _os.getenv('INTERNAL_API_KEY', ''))}"
        }

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
        from services.signal_engagement_service import (
            engagement_state_by_agent,
            get_targets,
        )
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
                    return (
                        jsonify({"error": "comment required for action=comment"}),
                        400,
                    )
                aid = propose_comment(post_url, comment, account=account)
            else:
                return jsonify({"error": "action must be 'like' or 'comment'"}), 400
        except ValueError as ve:
            return jsonify({"error": str(ve)}), 400
        except Exception as exc:
            return jsonify({"error": f"engage failed: {exc}"}), 502
        return jsonify(
            {
                "ok": True,
                "approval_id": aid,
                "action": action,
                "status": "pending_approval",
            }
        )

    @bp.route("/api/social/signal/targets", methods=["POST"])
    @admin_required
    def api_signal_set_targets():
        from services.signal_engagement_service import get_targets, set_targets

        body = request.get_json(silent=True) or {}
        targets = body.get("targets")
        if not isinstance(targets, list):
            return (
                jsonify({"error": "targets must be a list of LinkedIn profile/company URLs"}),
                400,
            )
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
            return (
                jsonify({"error": "nothing to update (daily_action_budget / voice_key)"}),
                400,
            )
        params.append(account_key)
        with get_db_cursor(commit=True) as (_conn, cur):
            # Keep all three supported updates literal; bind values and the account key.
            if len(sets) == 2:
                cur.execute(
                    "UPDATE agent_platform_accounts SET daily_action_budget = %s, voice_key = %s WHERE account_key = %s",
                    params,
                )
            elif "daily_action_budget" in body:
                cur.execute(
                    "UPDATE agent_platform_accounts SET daily_action_budget = %s WHERE account_key = %s",
                    params,
                )
            else:
                cur.execute(
                    "UPDATE agent_platform_accounts SET voice_key = %s WHERE account_key = %s",
                    params,
                )
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
        noVNC login itself is the S.C.O.U.T. session flow. Telegram/UI approval unchanged.
        """
        from services.signal_onboarding_service import transition

        body = request.get_json(silent=True) or {}
        to_state = (body.get("to_state") or "").strip()
        if not to_state:
            return jsonify({"error": "to_state required"}), 400
        res = transition(
            account_key,
            to_state,
            owner_gate_phone=body.get("owner_gate_phone"),
            actor="claude",
        )
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

        # WHICH LOGIN IS THIS, AND WHAT DOES IT TAKE DOWN? (#5627 follow-up)
        #
        # The panel used to show only an agent id and a status dot, so "342 is stale"
        # gave the owner no way to know that (a) the account to log in as is
        # kytranempowerment@gmail.com and (b) THREE S.I.G.N.A.L. accounts post through
        # that one profile — Kytran Katarn, Kytran Empowerment Inc. and Creed-AI. That
        # is why a single dead profile paused three accounts and read as "four broken
        # accounts". Both facts are already in the DB; they were simply never surfaced.
        #
        # ⚠️ USERNAME ONLY. `password_encrypted` is never selected, never returned.
        # `auto_relogin_armed` is a boolean so the panel can say "armed" without the
        # secret ever leaving the server.
        try:
            from database import get_db_cursor

            with get_db_cursor(commit=False) as (_c, cur):
                cur.execute(
                    """SELECT username,
                              (password_encrypted IS NOT NULL AND password_encrypted <> '') AS armed
                         FROM agent_browser_sessions
                        WHERE agent_id = %s AND platform = %s""",
                    (agent_id, platform),
                )
                crow = cur.fetchone()
                if crow:
                    crow = dict(crow)
                    out["stored_login"] = crow.get("username") or None
                    out["auto_relogin_armed"] = bool(crow.get("armed"))
                else:
                    out["stored_login"] = None
                    out["auto_relogin_armed"] = False

                # Which S.I.G.N.A.L. accounts ride this profile — the blast radius.
                cur.execute(
                    """SELECT account_key, display_label, can_post
                         FROM agent_platform_accounts
                        WHERE platform = %s AND browser_agent_id = %s
                        ORDER BY account_key""",
                    (platform, agent_id),
                )
                out["serves_accounts"] = [dict(r) for r in cur.fetchall()]
        except Exception as exc:
            # Never let the new context break a panel that worked before it existed.
            out["identity_error"] = f"identity lookup failed ({type(exc).__name__})"
            out.setdefault("stored_login", None)
            out.setdefault("auto_relogin_armed", None)
            out.setdefault("serves_accounts", [])

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
            return (
                jsonify(
                    {
                        "started": False,
                        "error": f"sidecar unreachable: {type(exc).__name__}",
                    }
                ),
                502,
            )

    @bp.route("/api/social/linkedin/session-login/stop", methods=["POST"])
    @admin_required
    def api_linkedin_session_login_stop():
        import requests as _rq

        try:
            r = _rq.post(f"{_LOGIN_SIDECAR}/stop", headers=_sidecar_headers(), timeout=25)
            return jsonify(r.json()), r.status_code
        except Exception as exc:
            return (
                jsonify(
                    {
                        "stopped": False,
                        "error": f"sidecar unreachable: {type(exc).__name__}",
                    }
                ),
                502,
            )

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
            return (
                jsonify({"saved": False, "error": "username and password required"}),
                400,
            )
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
            return (
                jsonify(
                    {
                        "saved": False,
                        "error": f"browser worker unreachable: {type(exc).__name__}",
                    }
                ),
                502,
            )

    # ── LinkedIn comment monitor (READ scope, #3964) ─────────────
    @bp.route("/api/social/linkedin/comments")
    @admin_required
    def api_linkedin_comments():
        """List ingested LinkedIn comments (read scope). ?unseen=1 filters."""
        from services import linkedin_comment_monitor as mon

        unseen = request.args.get("unseen") in ("1", "true", "yes")
        limit = min(int(request.args.get("limit", 50)), 200)
        return jsonify(
            {
                "success": True,
                "comments": mon.list_recent_comments(limit=limit, unseen_only=unseen),
            }
        )

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
