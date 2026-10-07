"""Department HQ social routes: signal monitor routes."""

from flask import jsonify, request


def register_signal_monitor_routes(bp, admin_required):
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
                            "last_posted_at": (last_posted.isoformat() if last_posted else None),
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
