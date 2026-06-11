# platform_v2/tools/department_hq/scout_routes.py
"""DHQ Scout tab — mirrors social_routes.py (S.I.G.N.A.L.) pattern."""
import json
import logging
import urllib.request

from flask import jsonify, request

logger = logging.getLogger(__name__)

_SCRAPER_BASE = "http://archie_scraper:4243"


def _scraper_post(path: str, body: dict) -> dict:
    payload = json.dumps(body).encode()
    req = urllib.request.Request(f"{_SCRAPER_BASE}{path}", data=payload)
    req.add_header("Content-Type", "application/json")
    try:
        r = urllib.request.urlopen(req, timeout=10)
        return json.loads(r.read())
    except Exception as exc:
        return {"error": str(exc)}


def _scraper_get(path: str) -> dict:
    try:
        r = urllib.request.urlopen(f"{_SCRAPER_BASE}{path}", timeout=5)
        return json.loads(r.read())
    except Exception as exc:
        return {"error": str(exc)}


def register_scout_routes(bp, admin_required):

    @bp.route("/api/scout/overview")
    @admin_required
    def api_scout_overview():
        from database import get_db_cursor

        pool = _scraper_get("/pool/status")
        with get_db_cursor() as (conn, cur):
            cur.execute("SELECT status, COUNT(*) AS cnt FROM scout_jobs GROUP BY status")
            counts = {r["status"]: r["cnt"] for r in cur.fetchall()}
            cur.execute(
                """SELECT id, job_type, target_url, status, created_at, findings
                   FROM scout_jobs ORDER BY created_at DESC LIMIT 5"""
            )
            recent = [dict(r) for r in cur.fetchall()]
        return jsonify({"pool": pool, "job_counts": counts, "recent_jobs": recent})

    @bp.route("/api/scout/jobs")
    @admin_required
    def api_scout_jobs():
        from database import get_db_cursor

        status_filter = request.args.get("status")
        job_type_filter = request.args.get("job_type")
        limit = min(int(request.args.get("limit") or 50), 200)
        clauses, params = [], []
        if status_filter:
            clauses.append("status = %s")
            params.append(status_filter)
        if job_type_filter:
            clauses.append("job_type = %s")
            params.append(job_type_filter)
        base_sql = """SELECT id, job_type, target_url, status, egress_tier,
                             created_at, completed_at, requested_by, findings, auto_approve
                      FROM scout_jobs"""
        if clauses:
            base_sql += " WHERE " + " AND ".join(clauses)
        base_sql += " ORDER BY created_at DESC LIMIT %s"
        with get_db_cursor() as (conn, cur):
            cur.execute(base_sql, params + [limit])
            jobs = [dict(r) for r in cur.fetchall()]
        return jsonify({"jobs": jobs, "total": len(jobs)})

    @bp.route("/api/scout/jobs/<int:job_id>")
    @admin_required
    def api_scout_job_detail(job_id):
        from database import get_db_cursor

        with get_db_cursor() as (conn, cur):
            cur.execute("SELECT * FROM scout_jobs WHERE id = %s", (job_id,))
            row = cur.fetchone()
        if not row:
            return jsonify({"error": "not found"}), 404
        return jsonify(dict(row))

    @bp.route("/api/scout/jobs/<int:job_id>/approve", methods=["POST"])
    @admin_required
    def api_scout_approve(job_id):
        from database import get_db_cursor

        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                """UPDATE scout_jobs
                   SET status = 'approved', reviewed_at = NOW(), reviewed_by = 'admin'
                   WHERE id = %s AND status = 'needs_review'
                   RETURNING id""",
                (job_id,),
            )
            updated = cur.fetchone()
        if not updated:
            return jsonify({"error": "not found or not in needs_review state"}), 400
        return jsonify({"success": True, "job_id": job_id, "status": "approved"})

    @bp.route("/api/scout/jobs/<int:job_id>/reject", methods=["POST"])
    @admin_required
    def api_scout_reject(job_id):
        from database import get_db_cursor

        data = request.get_json(silent=True) or {}
        note = (data.get("note") or "")[:500]
        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                """UPDATE scout_jobs
                   SET status = 'rejected', reviewed_at = NOW(),
                       reviewed_by = 'admin', error_log = %s
                   WHERE id = %s AND status = 'needs_review'
                   RETURNING id""",
                (f"Rejected: {note}", job_id),
            )
            updated = cur.fetchone()
        if not updated:
            return jsonify({"error": "not found or not in needs_review state"}), 400
        return jsonify({"success": True, "job_id": job_id, "status": "rejected"})

    @bp.route("/api/scout/run-now", methods=["POST"])
    @admin_required
    def api_scout_run_now():
        data = request.get_json(silent=True) or {}
        job_type = (data.get("job_type") or "procurement_sync").strip()
        target_url = data.get("target_url") or "https://canadabuys.canada.ca/en/tender-opportunities"
        result = _scraper_post(
            "/jobs",
            {
                "job_type": job_type,
                "target_url": target_url,
                "params": data.get("params") or {},
                "requested_by": "dhq_manual",
            },
        )
        return jsonify(result)

    @bp.route("/api/scout/pool")
    @admin_required
    def api_scout_pool():
        return jsonify(_scraper_get("/pool/status"))

    # ── Session vault (#3708 v1) — unified view of the auth fabric ──
    # Cookie sessions (encrypted storage_state in browser_sessions) + the
    # persistent device-trust profiles (login sidecar). Metadata only —
    # cookie/state contents never leave the server. KSO-assisted capture +
    # per-platform egress tiers are the task's phase 2.
    @bp.route("/api/scout/sessions")
    @admin_required
    def api_scout_sessions():
        import os as _os

        import requests as _rq
        from database import get_db_cursor
        from services.browser_profile_service import WARM_PROFILES

        out = {"cookie_sessions": [], "profiles": []}
        try:
            with get_db_cursor(commit=False) as (_c, cur):
                cur.execute(
                    """SELECT bs.id, bs.agent_id, a.name AS agent_name, bs.platform,
                              bs.status, bs.last_used_at, bs.last_probe_at,
                              bs.last_probe_ok, bs.last_failure_reason,
                              bs.egress_pref,
                              octet_length(bs.encrypted_state) AS state_bytes,
                              bs.updated_at
                       FROM browser_sessions bs
                       LEFT JOIN agents a ON a.id = bs.agent_id
                       ORDER BY bs.updated_at DESC"""
                )
                for r in cur.fetchall():
                    d = dict(r)
                    for k in ("last_used_at", "last_probe_at", "updated_at"):
                        if d.get(k):
                            d[k] = d[k].isoformat()
                    out["cookie_sessions"].append(d)
        except Exception as exc:
            out["cookie_sessions_error"] = str(exc)

        hdrs = {"Authorization": f"Bearer {_os.getenv('INTERNAL_API_KEY', '')}"}
        try:
            # #4006: enumerate REAL profile dirs from the sidecar instead of
            # the hardcoded WARM_PROFILES registry.
            pr = _rq.get("http://archie_browser_login:4281/profiles", headers=hdrs, timeout=5)
            for p in (pr.json() or {}).get("profiles") or []:
                out["profiles"].append(
                    {
                        "agent_id": p.get("agent_id"),
                        "platform": p.get("platform"),
                        "profile_established": bool(p.get("established")),
                    }
                )
        except Exception:
            # Fallback (old sidecar image / sidecar down): probe the known
            # registry pairs via /status so the subtab never blanks.
            for aid, plat in WARM_PROFILES:
                row = {"agent_id": aid, "platform": plat, "profile_established": None}
                try:
                    pr = _rq.get(
                        "http://archie_browser_login:4281/status",
                        params={"agent_id": aid, "platform": plat},
                        headers=hdrs,
                        timeout=5,
                    )
                    row["profile_established"] = bool((pr.json() or {}).get("profile_established"))
                except Exception:
                    row["error"] = "sidecar unreachable"
                out["profiles"].append(row)
        return jsonify(out)

    @bp.route("/api/scout/sessions/probe", methods=["POST"])
    @admin_required
    def api_scout_sessions_probe():
        """Manually run the cookie-session health probe (same path as the 4h
        job). READ-probes active sessions; stale ones flip status."""
        from services.browser_profile_service import run_session_health_probe

        try:
            return jsonify({"success": True, "results": run_session_health_probe()})
        except Exception as exc:
            return jsonify({"success": False, "error": str(exc)}), 500

    @bp.route("/api/scout/egress-nodes")
    @admin_required
    def api_scout_egress_nodes():
        """#4007 — catalog of egress endpoints (hub + online CPU outposts).
        `egress_ready` nodes are selectable; the rest list as 'proxy not
        deployed'."""
        from services import egress_catalog_service

        try:
            return jsonify({"success": True, "nodes": egress_catalog_service.list_egress_nodes()})
        except Exception as exc:
            return jsonify({"success": False, "error": str(exc)}), 500

    @bp.route("/api/scout/sessions/<int:agent_id>/<platform>/egress", methods=["POST"])
    @admin_required
    def api_scout_session_set_egress(agent_id, platform):
        """#4007 — set a session's browse-from-country preference. Value must be
        'hub'/'auto' or a currently egress-ready node_name."""
        from services import browser_session_service, egress_catalog_service

        pref = (request.get_json(silent=True) or {}).get("egress_pref")
        if not egress_catalog_service.is_valid_egress(pref):
            return jsonify({"success": False, "error": "unknown or not-egress-ready node"}), 400
        try:
            ok = browser_session_service.set_session_egress(agent_id, platform, pref)
            if not ok:
                return jsonify({"success": False, "error": "no such session"}), 404
            return jsonify({"success": True})
        except Exception as exc:
            return jsonify({"success": False, "error": str(exc)}), 500

    @bp.route("/api/scout/sessions/<int:agent_id>/<platform>/expire", methods=["POST"])
    @admin_required
    def api_scout_session_expire(agent_id, platform):
        """Vault 'expire' verb — mark a cookie session stale so no skill
        trusts it until re-imported."""
        from services import browser_session_service

        try:
            browser_session_service.mark_stale(agent_id, platform, "expired via S.C.O.U.T. session vault")
            return jsonify({"success": True})
        except Exception as exc:
            return jsonify({"success": False, "error": str(exc)}), 500

    # ── #4006 phase 2a — platform registry + generic login capture ──
    # Interactive login capture for ANY registry platform (not just the
    # S.I.G.N.A.L. LinkedIn lane in social_routes.py, which stays untouched).
    # Flow: pick/add platform → /login/start spawns the headed browser →
    # owner logs in via noVNC (:4280, LAN/mesh only) → /login/stop → the
    # sidecar exports storage_state into browser_sessions (vault + 4h probe).
    _LOGIN_SIDECAR = "http://archie_browser_login:4281"

    def _scout_sidecar_headers():
        import os as _os

        return {"Authorization": f"Bearer {_os.getenv('INTERNAL_API_KEY', '')}"}

    @bp.route("/api/scout/platforms")
    @admin_required
    def api_scout_platforms():
        from services import browser_platform_service

        try:
            return jsonify({"success": True, "platforms": browser_platform_service.list_platforms()})
        except Exception as exc:
            return jsonify({"success": False, "error": str(exc)}), 500

    @bp.route("/api/scout/platforms", methods=["POST"])
    @admin_required
    def api_scout_platforms_add():
        from services import browser_platform_service

        j = request.get_json(silent=True) or {}
        try:
            p = browser_platform_service.add_platform(
                platform=j.get("platform") or "",
                display_name=j.get("display_name") or "",
                allowed_hosts=j.get("allowed_hosts") or [],
                login_url=(j.get("login_url") or "").strip() or None,
                probe_url=(j.get("probe_url") or "").strip() or None,
            )
            return jsonify({"success": True, "platform": p})
        except ValueError as exc:
            return jsonify({"success": False, "error": str(exc)}), 400
        except Exception:
            return jsonify({"success": False, "error": "add failed"}), 500

    @bp.route("/api/scout/sessions/login/start", methods=["POST"])
    @admin_required
    def api_scout_login_start():
        import requests as _rq

        from services import browser_platform_service

        j = request.get_json(silent=True) or {}
        try:
            agent_id = int(j.get("agent_id") or 0)
        except (TypeError, ValueError):
            agent_id = 0
        if agent_id <= 0:
            return jsonify({"started": False, "error": "valid agent_id required"}), 400
        platform = (j.get("platform") or "").strip().lower()
        reg = browser_platform_service.get_platform(platform)
        if not reg or not reg.get("enabled"):
            return jsonify({"started": False, "error": "unknown or disabled platform"}), 400
        if not reg.get("login_url"):
            return (
                jsonify({"started": False, "error": "platform is cookie-import only (no login_url)"}),
                400,
            )
        try:
            r = _rq.post(
                f"{_LOGIN_SIDECAR}/start",
                json={
                    "agent_id": agent_id,
                    "platform": platform,
                    "login_url": reg["login_url"],
                    "allowed_hosts": reg.get("allowed_hosts") or [],
                },
                headers=_scout_sidecar_headers(),
                timeout=10,
            )
            return jsonify(r.json()), r.status_code
        except Exception as exc:
            return jsonify({"started": False, "error": f"sidecar unreachable: {type(exc).__name__}"}), 502

    @bp.route("/api/scout/sessions/login/stop", methods=["POST"])
    @admin_required
    def api_scout_login_stop():
        import requests as _rq

        try:
            # 25s > the sidecar's 20s SIGTERM→SIGKILL window.
            r = _rq.post(f"{_LOGIN_SIDECAR}/stop", headers=_scout_sidecar_headers(), timeout=25)
            return jsonify(r.json()), r.status_code
        except Exception as exc:
            return jsonify({"stopped": False, "error": f"sidecar unreachable: {type(exc).__name__}"}), 502

    @bp.route("/api/scout/sessions/login/status")
    @admin_required
    def api_scout_login_status():
        import os as _os

        import requests as _rq

        out = {"success": True}
        try:
            params = {}
            if request.args.get("agent_id"):
                params["agent_id"] = int(request.args["agent_id"])
            if request.args.get("platform"):
                params["platform"] = request.args["platform"].strip().lower()
            r = _rq.get(f"{_LOGIN_SIDECAR}/status", params=params, headers=_scout_sidecar_headers(), timeout=5)
            out["login_surface"] = r.json()
        except Exception as exc:
            out["login_surface"] = None
            out["login_surface_error"] = f"sidecar unreachable: {type(exc).__name__}"
        # Admin-only surface — same trust boundary as social_routes
        # session-status (owner reads the VNC password here instead of .env).
        out["vnc_password"] = _os.getenv("BROWSER_VNC_PASSWORD") or None
        return jsonify(out)

    @bp.route("/api/scout/cli-dispatch", methods=["POST"])
    def api_scout_cli_dispatch():
        """Key-authenticated job submission for Claude Code /scout skill."""
        from os import getenv

        key = request.headers.get("X-Scout-Key", "")
        expected = getenv("CLUSTER_PROXY_KEY", "")
        if not expected or key != expected:
            return jsonify({"error": "Unauthorized"}), 401

        data = request.get_json(silent=True) or {}
        job_type = (data.get("job_type") or "").strip()
        target_url = (data.get("target_url") or "").strip()
        if not job_type or not target_url:
            return jsonify({"error": "job_type and target_url required"}), 400

        result = _scraper_post(
            "/jobs",
            {
                "job_type": job_type,
                "target_url": target_url,
                "params": data.get("params") or {},
                "requested_by": "claude_cli",
            },
        )
        return jsonify(result)

    @bp.route("/api/scout/cli-status/<int:job_id>")
    def api_scout_cli_status(job_id):
        """Key-authenticated job status for Claude Code /scout skill."""
        from os import getenv

        key = request.headers.get("X-Scout-Key", "")
        expected = getenv("CLUSTER_PROXY_KEY", "")
        if not expected or key != expected:
            return jsonify({"error": "Unauthorized"}), 401

        from database import get_db_cursor

        with get_db_cursor() as (conn, cur):
            cur.execute(
                """SELECT id, job_type, target_url, status, findings,
                          screenshots, data, created_at, completed_at
                   FROM scout_jobs WHERE id = %s""",
                (job_id,),
            )
            row = cur.fetchone()
        if not row:
            return jsonify({"error": "not found"}), 404
        return jsonify(dict(row))
