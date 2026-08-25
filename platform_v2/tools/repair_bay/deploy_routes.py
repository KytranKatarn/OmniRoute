"""Repair Bay — Deploy tab routes.

Thin HTTP layer calling services.proposal_service for deployment data.
Migrated from direct DB queries in Project #103, Phase 2.
"""

import logging
import os
import re

from flask import jsonify, request
from flask_login import login_required

logger = logging.getLogger(__name__)

# Hard violations block deploy_execute; everything else is advisory.
_HARD_RULES = {"ADR-013", "HARDCODED_SECRET"}

_CAP_MAP_CACHE = None

# Deploy-provenance matrix cache (#4777): (monotonic_ts, payload). The drift check
# makes ~9 GitHub-API + /version calls, so serve a ~2-min-cached result to the tab.
_PROVENANCE_CACHE = None


def _capability_map():
    """Lazily load CAPABILITY_DEPARTMENT_MAP from the DHQ dispatcher.

    Returns the dict, or None if it can't be imported (check is skipped then).
    """
    global _CAP_MAP_CACHE
    if _CAP_MAP_CACHE is None:
        try:
            from tools.department_hq.services.department_dispatcher import CAPABILITY_DEPARTMENT_MAP

            _CAP_MAP_CACHE = CAPABILITY_DEPARTMENT_MAP
        except Exception:
            logger.warning("[DeployHealth] CAPABILITY_DEPARTMENT_MAP unavailable — skipping capability audit")
            _CAP_MAP_CACHE = False
    return _CAP_MAP_CACHE or None


def _run_pre_deploy_health_check(file_paths=None):
    """Run a quick pattern compliance check before deployment.

    Returns a dict with 'passed' (bool), 'violations' (list), and 'advisory' (str).
    This is an advisory gate — warns but does not block deployment.
    """
    tools_dir = "/app/tools" if os.path.isdir("/app/tools") else "/mnt/archie_brain/platform_v2/tools"
    violations = []

    # If specific files provided, check only those; otherwise scan all tools
    if file_paths:
        targets = []
        for fp in file_paths:
            full = fp if os.path.isabs(fp) else os.path.join(tools_dir, fp)
            if os.path.isfile(full) and full.endswith(".py"):
                targets.append(full)
    else:
        targets = []
        for root, dirs, files in os.walk(tools_dir):
            dirs[:] = [d for d in dirs if d != "__pycache__"]
            for fname in files:
                if fname.endswith(".py"):
                    targets.append(os.path.join(root, fname))

    for filepath in targets:
        try:
            with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()

            rel_path = filepath.replace(tools_dir + "/", "")

            # ADR-013: No direct Ollama inference calls from modules
            if "call_ollama(" in content and "bridge" not in filepath and "archie_bridge" not in filepath:
                violations.append(
                    {
                        "file": rel_path,
                        "rule": "ADR-013",
                        "message": "Direct Ollama call — must use Bridge dispatcher",
                    }
                )

            # ADR-013: No direct cloud API calls from modules
            if ("call_claude_api(" in content or "call_openai_api(" in content) and "archie_bridge" not in filepath:
                violations.append(
                    {
                        "file": rel_path,
                        "rule": "ADR-013",
                        "message": "Direct cloud API call — must use Bridge dispatcher",
                    }
                )

            # ADR-013-CAP: every dispatch(capability="X") must use a capability
            # registered in CAPABILITY_DEPARTMENT_MAP — otherwise it silently
            # defaults to Engineering & Technology and may misroute. Advisory only.
            for cap in re.findall(
                r"dispatch(?:_json)?\s*\([^)]*?capability\s*=\s*['\"]([^'\"]+)['\"]",
                content,
            ):
                if _capability_map() is not None and cap not in _capability_map():
                    violations.append(
                        {
                            "file": rel_path,
                            "rule": "ADR-013-CAP",
                            "message": (
                                f"dispatch capability '{cap}' not in CAPABILITY_DEPARTMENT_MAP "
                                "— add a mapping or it will default to Engineering & Technology"
                            ),
                        }
                    )

            # Bare except clauses (poor error handling)
            if re.search(r"\bexcept\s*:", content):
                violations.append(
                    {
                        "file": rel_path,
                        "rule": "BARE_EXCEPT",
                        "message": "Bare except clause — catch specific exceptions",
                    }
                )

            # Hardcoded DB passwords
            if (
                re.search(r"password\s*=\s*['\"][^'\"]+['\"]", content)
                and "getenv" not in content[: content.find("password") + 200 if "password" in content else 0]
            ):
                violations.append(
                    {
                        "file": rel_path,
                        "rule": "HARDCODED_SECRET",
                        "message": "Possible hardcoded password — use os.getenv()",
                    }
                )

        except Exception:
            pass

    passed = len(violations) == 0
    advisory = ""
    if not passed:
        advisory = (
            f"Advisory: {len(violations)} pattern violation(s) detected. "
            "Deployment is allowed but review is recommended."
        )

    return {"passed": passed, "violations": violations, "advisory": advisory}


def register_deploy_routes(bp, admin_required):
    """Register deployment-related routes on the repair_bay blueprint."""

    from services import proposal_service

    @bp.route("/api/deploy/history")
    @login_required
    @admin_required
    def deploy_history():
        """Unified deployment history."""
        result = proposal_service.get_deploy_history()
        if not result.get("success"):
            return jsonify(result), 500
        return jsonify(result)

    @bp.route("/api/deploy/ready")
    @login_required
    @admin_required
    def deploy_ready():
        """Proposals ready to deploy (status = tested), with pre-deploy health check."""
        result = proposal_service.get_deploy_ready()
        if not result.get("success"):
            return jsonify(result), 500

        # Run advisory health gate on files referenced by ready proposals
        file_paths = []
        for proposal in result.get("proposals", []):
            fp = proposal.get("file_path") or proposal.get("target_file")
            if fp:
                file_paths.append(fp)

        health = _run_pre_deploy_health_check(file_paths=file_paths if file_paths else None)
        result["health_check"] = health

        return jsonify(result)

    @bp.route("/api/deploy/health-check", methods=["POST"])
    @login_required
    @admin_required
    def deploy_health_check():
        """Run a standalone pre-deploy pattern compliance check.

        Optional JSON body: file_paths (list of files to check).
        Returns violations (advisory, not blocking).
        """
        data = request.get_json(force=True, silent=True) or {}
        file_paths = data.get("file_paths")
        health = _run_pre_deploy_health_check(file_paths=file_paths)
        return jsonify({"success": True, **health})

    @bp.route("/api/deploy/run-batch", methods=["POST"])
    @login_required
    @admin_required
    def deploy_run_batch():
        """Queue all ready_for_review proposals through tiered approval pipeline.

        Optional JSON body:
          risk_filter (list[str]): only queue proposals with these risk levels.
                                   Default: ["low", "medium"]
          limit (int): max proposals to queue per call. Default: 10.

        Returns per-proposal: {id, title, risk_level, approver, queue_id, pending}.
        """
        data = request.get_json(force=True, silent=True) or {}
        risk_filter = set(data.get("risk_filter", ["low", "medium"]))
        limit = min(int(data.get("limit", 10)), 25)

        ready = proposal_service.get_deploy_ready()
        proposals = ready.get("proposals", [])

        results = []
        for p in proposals[:limit]:
            if p.get("risk_level") not in risk_filter:
                results.append(
                    {
                        "id": p["id"],
                        "title": p["title"],
                        "risk_level": p.get("risk_level"),
                        "skipped": True,
                        "reason": "risk_level not in filter",
                    }
                )
                continue
            r = proposal_service.request_tiered_deploy_approval(p["id"])
            results.append(
                {
                    "id": p["id"],
                    "title": p["title"],
                    "risk_level": p.get("risk_level"),
                    "approver": r.get("approver"),
                    "queue_id": r.get("queue_id"),
                    "pending": r.get("pending"),
                    "success": r.get("success"),
                    "message": r.get("message", "")[:80],
                }
            )

        queued = sum(1 for r in results if r.get("pending") and r.get("queue_id"))
        skipped = sum(1 for r in results if r.get("skipped"))
        return jsonify(
            {
                "success": True,
                "total": len(proposals),
                "processed": len(results),
                "queued": queued,
                "skipped": skipped,
                "results": results,
            }
        )

    @bp.route("/api/deploy/queue-status")
    @login_required
    @admin_required
    def deploy_queue_status():
        """Show current dispatch_pending_queue items for deploy_approve_gate callbacks."""
        from database import get_db_cursor

        with get_db_cursor() as (conn, cur):
            cur.execute(
                """
                SELECT id, capability, agent_name, model_needed, status,
                       callback_data->>'proposal_id' as proposal_id,
                       queued_at, completed_at,
                       LEFT(result_response, 120) as verdict
                FROM dispatch_pending_queue
                WHERE callback_type = 'deploy_approve_gate'
                ORDER BY queued_at DESC LIMIT 20
            """
            )
            rows = [dict(r) for r in cur.fetchall()]
        for r in rows:
            if r.get("queued_at"):
                r["queued_at"] = r["queued_at"].isoformat()
            if r.get("completed_at"):
                r["completed_at"] = r["completed_at"].isoformat()
        return jsonify({"success": True, "items": rows, "count": len(rows)})

    @bp.route("/api/deploy/request-approval/<int:proposal_id>", methods=["POST"])
    @login_required
    @admin_required
    def deploy_request_approval(proposal_id):
        """Route a proposal deployment through the org-chart approval chain.

        Risk routing:
          low      → F.O.R.G.E. auto-review → sandbox gate → deploy
          medium   → Department director Telegram → sandbox gate → deploy
          high/critical → A.R.C.H.I.E. Telegram → sandbox gate → deploy

        Sandbox gate = P.R.O.B.E. suite #79 must pass before production deploy.
        """
        result = proposal_service.request_tiered_deploy_approval(proposal_id)
        if not result.get("success") and not result.get("pending"):
            return jsonify(result), 400
        return jsonify(result)

    @bp.route("/api/deploy/approver-info/<int:proposal_id>")
    @login_required
    @admin_required
    def deploy_approver_info(proposal_id):
        """Return the approver routing info for a proposal (no side effects)."""
        from database import get_db_cursor

        with get_db_cursor() as (conn, cur):
            cur.execute(
                "SELECT id, title, category, risk_level FROM improvement_proposals WHERE id = %s",
                (proposal_id,),
            )
            p = cur.fetchone()
        if not p:
            return jsonify({"success": False, "error": "Not found"}), 404
        routing = proposal_service._get_approver(p)
        return jsonify({"success": True, "proposal_id": proposal_id, **routing})

    @bp.route("/api/deploy/execute", methods=["POST"])
    @login_required
    @admin_required
    def deploy_execute():
        """Dispatch a deploy via B.A.S.E. through the Department HQ deploy pipeline.

        JSON body:
          capability   (str) — "deploy_static" | "deploy_vps"
          domain       (str) — domain or VPS container key
          source_path  (str) — local source directory
          changed_files (list[str]) — relative paths of changed files
          verify_url   (str, optional) — URL to verify after deploy
          is_translation (bool, optional) — check for Mock values if True
          container_name (str, optional) — VPS container key (deploy_vps only)
        """
        from services.deploy_service import run_deploy_pipeline

        payload = request.get_json(force=True, silent=True) or {}
        capability = payload.get("capability", "deploy_static")

        if capability not in ("deploy_static", "deploy_vps"):
            return jsonify({"success": False, "error": f"Unknown capability: {capability}"}), 400

        # Pre-deploy compliance gate — BLOCK on hard violations (ADR-013 /
        # hardcoded secrets), advisory for everything else (bare except,
        # unmapped dispatch capabilities).
        changed_files = payload.get("changed_files") or []
        health = _run_pre_deploy_health_check(file_paths=changed_files or None)
        hard = [v for v in health.get("violations", []) if v.get("rule") in _HARD_RULES]
        if hard:
            return (
                jsonify(
                    {
                        "success": False,
                        "domain": payload.get("domain"),
                        "capability": capability,
                        "error": f"Pre-deploy gate blocked: {len(hard)} hard violation(s)",
                        "health_check": health,
                    }
                ),
                422,
            )

        result = run_deploy_pipeline(capability, payload)

        return jsonify(
            {
                "success": result.success,
                "domain": payload.get("domain"),
                "capability": capability,
                "error": result.error if not result.success else None,
                "metadata": result.metadata if result.success else {},
            }
        )

    # ── Website Deploy management ─────────────────────────────────────────────

    WEBSITE_DOMAINS = [
        {
            "domain": "kytranempowerment.com",
            "source": "/mnt/archie_brain/website/kytranempowerment.com",
            "verify_url": "https://kytranempowerment.com",
        },
        {
            "domain": "creed-ai.org",
            "source": "/mnt/archie_brain/website/creed-ai.org",
            "verify_url": "https://creed-ai.org",
        },
    ]

    @bp.route("/api/deploy/hub-state")
    @login_required
    @admin_required
    def deploy_hub_state():
        """The VOLUME-MOUNTED half of deploy provenance (#5867).

        `/api/deploy/provenance` above answers it for image-baked products, where the
        container holds a `COPY .` snapshot. `archie_platform` and `archie_scheduler` are
        the opposite: they bind-mount the tree, so a GitHub merge deploys NOTHING and the
        platform serves whatever branch the host checkout happens to be on.

        Reports branch / behind-main / restarted-since-HEAD / dirty. Fails to `unknown`,
        never to a confident `in_sync` — see services/hub_deploy_state.py.
        """
        try:
            from services.hub_deploy_state import hub_deploy_state

            return jsonify({"success": True, **hub_deploy_state()})
        except Exception as e:  # noqa: BLE001
            logger.error("[deploy/hub-state] failed: %s", e)
            return jsonify({"success": False, "status": "unknown", "detail": str(e)}), 500

    @bp.route("/api/deploy/provenance")
    @login_required
    @admin_required
    def deploy_provenance():
        """Deploy-provenance matrix (#4777): for every image-baked product, its running
        /version baked SHA vs its source-repo head. Reuses scripts/deploy_drift_check.py
        (the SAME logic the daily deploy_drift_monitor job + F.O.R.G.E. Dockerfile guard
        use). Result cached ~2 min (the check makes ~9 GitHub-API + /version calls).
        Fail-safe: any error returns ok=false, never breaks the Ship tab."""
        import sys as _sys
        import time as _time

        global _PROVENANCE_CACHE
        now = _time.monotonic()
        if _PROVENANCE_CACHE and now - _PROVENANCE_CACHE[0] < 120:
            return jsonify(_PROVENANCE_CACHE[1])

        scripts_dir = "/mnt/archie_brain/scripts"
        if scripts_dir not in _sys.path:
            _sys.path.insert(0, scripts_dir)
        try:
            import deploy_drift_check as _ddc

            products = _ddc.check_products()
        except Exception as exc:  # noqa: BLE001 — a check error must not break the tab
            logger.warning("[DeployProvenance] check failed: %s", exc)
            return jsonify({"ok": False, "products": [], "error": str(exc)})

        try:
            from services.time_utils import now_utc

            checked_at = now_utc().isoformat()
        except Exception:  # noqa: BLE001
            checked_at = None
        payload = {
            "ok": True,
            "checked_at": checked_at,
            "products": products,
            "in_sync_count": sum(1 for p in products if p["status"] == "in_sync"),
            "drift_count": sum(1 for p in products if p["status"] == "drift"),
            "fail_open_count": sum(1 for p in products if p["status"] == "fail_open"),
        }
        _PROVENANCE_CACHE = (now, payload)
        return jsonify(payload)

    @bp.route("/api/deploy/website-status")
    @login_required
    @admin_required
    def website_deploy_status():
        """Return last deploy time, status, and pending portrait changes per domain."""
        import os as _os
        from database import get_db_cursor

        rows = []
        with get_db_cursor() as (conn, cur):
            for site in WEBSITE_DOMAINS:
                domain = site["domain"]
                key_ts = f"website_deploy_last_run_{domain}"
                key_st = f"website_deploy_last_status_{domain}"
                cur.execute(
                    "SELECT key, value FROM system_config WHERE key = ANY(%s)",
                    ([key_ts, key_st],),
                )
                cfg = {r["key"]: r["value"] for r in cur.fetchall()}
                last_run = cfg.get(key_ts)
                last_status = cfg.get(key_st, "never")

                # Count portraits updated since last deploy
                pending = 0
                if last_run:
                    cur.execute(
                        "SELECT COUNT(*) as n FROM agent_portraits WHERE updated_at > %s",
                        (last_run,),
                    )
                    pending = (cur.fetchone() or {}).get("n", 0)
                else:
                    cur.execute("SELECT COUNT(*) as n FROM agent_portraits WHERE approved = true")
                    pending = (cur.fetchone() or {}).get("n", 0)

                rows.append(
                    {
                        "domain": domain,
                        "last_run": last_run,
                        "last_status": last_status,
                        "pending_portraits": pending,
                        "source_path": site["source"],
                    }
                )

        return jsonify({"sites": rows})

    @bp.route("/api/deploy/website-trigger", methods=["POST"])
    @login_required
    @admin_required
    def website_deploy_trigger():
        """Trigger an immediate full-site deploy for one or all website domains.

        JSON body: { "domain": "kytranempowerment.com" }  — omit for all sites.
        Runs in a background thread; returns immediately.
        """
        import threading as _threading
        from services.deploy_service import run_deploy_pipeline
        from database import get_db_cursor

        payload = request.get_json(force=True, silent=True) or {}
        target_domain = payload.get("domain")
        sites = [s for s in WEBSITE_DOMAINS if not target_domain or s["domain"] == target_domain]
        if not sites:
            return jsonify({"success": False, "error": "Unknown domain"}), 400

        def _run():
            from database import get_db_cursor as _get_db
            import datetime

            for site in sites:
                domain = site["domain"]
                key_ts = f"website_deploy_last_run_{domain}"
                key_st = f"website_deploy_last_status_{domain}"
                # deploy_static is async: the actual byte push happens later via
                # the Hostinger MCP deploy-website skill. run_deploy_pipeline
                # returns before any bytes land, and a verify here would snapshot
                # PRE-deploy content as false proof — so skip verify_url and
                # record a 'dispatched' status rather than 'success'.
                result = run_deploy_pipeline(
                    "deploy_static",
                    {
                        "domain": domain,
                        "source_path": site["source"],
                        "changed_files": ["assets/portraits/"],
                    },
                )
                status = "dispatched" if result.success else "failed"
                ts = datetime.datetime.now(datetime.timezone.utc).isoformat()
                with _get_db(commit=True) as (conn, cur):
                    for k, v in [(key_ts, ts), (key_st, status)]:
                        cur.execute(
                            """INSERT INTO system_config (key, value, updated_at)
                               VALUES (%s, %s, NOW())
                               ON CONFLICT (key) DO UPDATE SET value=EXCLUDED.value, updated_at=NOW()""",
                            (k, v),
                        )

        t = _threading.Thread(target=_run, daemon=True)
        t.start()
        return jsonify({"success": True, "queued": [s["domain"] for s in sites]})
