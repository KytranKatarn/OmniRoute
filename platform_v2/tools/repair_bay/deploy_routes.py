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
                result = run_deploy_pipeline(
                    "deploy_static",
                    {
                        "domain": domain,
                        "source_path": site["source"],
                        "verify_url": site["verify_url"],
                        "changed_files": ["assets/portraits/"],
                    },
                )
                status = "success" if result.success else "failed"
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
