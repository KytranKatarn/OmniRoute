"""deploy_service.py — Autonomous deploy pipeline for B.A.S.E. (agent_id=139).

Capabilities:
  deploy_static — full-site zip upload to Hostinger API (always replaces public_html)
  deploy_vps    — SSH rsync changed files + docker compose rebuild on VPS

Pipeline per deploy:
  1. classify_risk(changed_files) → 'auto' | 'approval_required'
  2. snapshot_current(domain, verify_url) → backup KB id
  3. execute deploy
  4. verify_deploy(verify_url, is_translation)
  5. On failure: retry once → restore snapshot → Telegram alert + Repair Bay proposal
"""

from __future__ import annotations

import datetime
import logging
import os
import subprocess
import time
import zipfile
from dataclasses import dataclass, field
from datetime import timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger("agent_loop")

# File extensions that are safe to auto-deploy without Telegram approval
AUTO_SAFE_EXTENSIONS = frozenset(
    [".json", ".js", ".css", ".html", ".svg", ".ico", ".txt", ".xml", ".webp", ".png", ".jpg"]
)

# File names/patterns that always require Telegram approval before deploy
APPROVAL_REQUIRED_PATTERNS = frozenset(["dockerfile", "docker-compose", ".py", ".sql", ".sh", ".env"])

RETRY_DELAY_SECONDS = 120
VERIFY_WAIT_SECONDS = 8

# VPS connection
VPS_HOST = os.getenv("REPAIR_BAY_VPS_HOST", "kytran@76.13.107.109")
VPS_KEY = os.getenv("REPAIR_BAY_VPS_KEY", "/home/kytran/.ssh/repair_bay_deploy")

# Hostinger API — always full-site deploy (partial deploys destroy public_html)
HOSTINGER_API_KEY = os.getenv("HOSTINGER_API_KEY", "")
HOSTINGER_API_BASE = "https://developers.hostinger.com/api/hosting/v1"

# VPS container service map
VPS_SERVICE_MAP = {
    "kytran_gov_watch": {
        "dir": "/opt/archie-products/gov-watch/",
        "service": "kytran-gov-watch",
        "verify_path": "/static/data/translations.json",
    },
    "kytran_watch_api": {
        "dir": "/opt/archie-products/civic-watch/",
        "service": "watch-api",
        "verify_path": "/data/translations.json",
    },
    "kytran_legal_api": {
        "dir": "/opt/archie-products/legal-watch/",
        "service": "legal-api",
        "verify_path": "/data/translations.json",
    },
    "kytran_market_api": {
        "dir": "/opt/kytran-market-watch/",
        "service": None,
        "verify_path": "/static/data/translations.json",
    },
    "wtf_consumer": {
        "dir": "/opt/archie-products/what-the-fact/",
        "service": "wtf-consumer",
        "verify_path": "/static/data/translations.json",
    },
    "wtf_tech": {
        "dir": "/opt/archie-products/what-the-fact/",
        "service": "wtf-tech",
        "verify_path": "/static/data/translations.json",
    },
}

# Static site source paths
STATIC_SITE_MAP = {
    "kytranempowerment.com": "/mnt/archie_brain/website/kytranempowerment.com",
    "creed-ai.org": "/mnt/archie_brain/website/creed-ai.org",
}


@dataclass
class DeployResult:
    success: bool
    domain: str
    capability: str
    http_status: Optional[int] = None
    error: Optional[str] = None
    backup_id: Optional[int] = None
    retried: bool = False
    rolled_back: bool = False
    metadata: dict = field(default_factory=dict)


def classify_risk(changed_files: list[str]) -> str:
    """Return 'auto' if all files are safe static types, else 'approval_required'."""
    for f in changed_files:
        name_lower = Path(f).name.lower()
        suffix_lower = Path(f).suffix.lower()
        if suffix_lower not in AUTO_SAFE_EXTENSIONS:
            return "approval_required"
        for pattern in APPROVAL_REQUIRED_PATTERNS:
            if pattern in name_lower:
                return "approval_required"
    return "auto"


def _deploy_static_hostinger(domain: str, source_path: str) -> bool:
    """Mark a Hostinger static site deploy as pending.

    Hostinger shared hosting has no REST API deploy endpoint — the only
    working mechanism is the MCP tool mcp__hostinger-api__hosting_deployStaticWebsite,
    which runs via Claude (Anthropic infrastructure), not from inside the
    Docker container.

    This function marks the domain as deploy_pending in system_config.
    The actual upload is handled by:
      1. The /deploy-website Claude skill (manual or scheduled via /schedule)
      2. The Repair Bay → Ship → Website tab "Deploy" button (which prompts
         Claude to run the skill)

    Never call this expecting an immediate Hostinger push — it won't happen.
    """
    from database import get_db_cursor
    import datetime

    key_st = f"website_deploy_last_status_{domain}"
    key_ts = f"website_deploy_last_run_{domain}"
    ts = datetime.datetime.now(timezone.utc).isoformat()

    with get_db_cursor(commit=True) as (_, cur):
        for k, v in [(key_ts, ts), (key_st, "deploy_pending")]:
            cur.execute(
                """INSERT INTO system_config (key, value, updated_at)
                   VALUES (%s, %s, NOW())
                   ON CONFLICT (key) DO UPDATE SET value=EXCLUDED.value, updated_at=NOW()""",
                (k, v),
            )

    logger.info(
        "[DeployStatic] %s marked deploy_pending — run /deploy-website skill or use "
        "Repair Bay → Ship → Website tab to push to Hostinger via MCP.",
        domain,
    )
    # Return True so the pipeline continues (verify, etc.) — the actual deploy
    # is async and handled by Claude via the deploy-website skill.
    return True


def _deploy_vps(container_name: str, changed_files: list[str], source_dir: str) -> bool:
    """Rsync changed files to VPS then rebuild the container. Returns True on success."""
    info = VPS_SERVICE_MAP.get(container_name)
    if not info:
        raise ValueError(f"Unknown VPS container: {container_name}. Add to VPS_SERVICE_MAP.")

    target_dir = info["dir"]
    service = info["service"]
    ssh_opts = ["-i", VPS_KEY, "-o", "StrictHostKeyChecking=no", "-o", "BatchMode=yes"]

    # 1. SCP each changed file to its target location on VPS (rsync not in container)
    for rel_path in changed_files:
        src_file = os.path.join(source_dir, rel_path)
        target_subdir = os.path.dirname(os.path.join(target_dir, rel_path))
        # Ensure target directory exists on VPS
        mkdir_cmd = ["ssh"] + ssh_opts + [VPS_HOST, f"mkdir -p {target_subdir}"]
        subprocess.run(mkdir_cmd, capture_output=True, timeout=30)
        scp_cmd = [
            "scp",
            "-i",
            VPS_KEY,
            "-o",
            "StrictHostKeyChecking=no",
            "-o",
            "BatchMode=yes",
            src_file,
            f"{VPS_HOST}:{target_subdir}/",
        ]
        result = subprocess.run(scp_cmd, capture_output=True, timeout=60)
        if result.returncode != 0:
            logger.error("[DeployVPS] scp failed for %s: %s", rel_path, result.stderr.decode())
            return False

    # 2. Docker compose rebuild on VPS via SSH
    rebuild_cmd = (
        f"cd {target_dir} && docker compose up -d --build --no-deps {service}"
        if service
        else f"cd {target_dir} && docker compose up -d --build"
    )
    ssh_cmd = ["ssh"] + ssh_opts + [VPS_HOST, rebuild_cmd]
    result = subprocess.run(ssh_cmd, capture_output=True, timeout=180)
    if result.returncode != 0:
        logger.error("[DeployVPS] docker rebuild failed for %s: %s", container_name, result.stderr.decode())
        return False

    logger.info("[DeployVPS] %s rebuilt OK", container_name)
    return True


def _http_get_status(url: str) -> int:
    """Return HTTP status code for url, or 0 on connection error."""
    try:
        import urllib.request

        resp = urllib.request.urlopen(url, timeout=10)
        return resp.status
    except Exception:
        return 0


def _count_mock_values(translations_url: str) -> int:
    """Fetch translations.json and count Mock* values. Returns 0 if unreachable."""
    try:
        import json as _json
        import urllib.request

        resp = urllib.request.urlopen(translations_url, timeout=10)
        data = _json.loads(resp.read())
        count = 0
        for _lang, keys in data.items():
            if isinstance(keys, dict):
                count += sum(1 for v in keys.values() if str(v).startswith("Mock"))
        return count
    except Exception:
        return 0


def verify_deploy(verify_url: str, is_translation: bool) -> bool:
    """Return True if deploy succeeded: HTTP 200 + 0 Mock values (if translation)."""
    status = _http_get_status(verify_url)
    if status != 200:
        logger.warning("[DeployVerify] HTTP %d for %s", status, verify_url)
        return False
    if is_translation:
        mocks = _count_mock_values(verify_url)
        if mocks > 0:
            logger.warning("[DeployVerify] %d Mock values at %s", mocks, verify_url)
            return False
    return True


def snapshot_current(domain: str, verify_url: str) -> Optional[int]:
    """Fetch current live translations.json and store as KB vault_note pre-deploy snapshot."""
    try:
        import urllib.request

        resp = urllib.request.urlopen(verify_url, timeout=10)
        content = resp.read().decode()
        from database import get_db_cursor

        with get_db_cursor(commit=True) as (_conn, cur):
            cur.execute(
                """INSERT INTO knowledge_base
                   (memory_type, title, content, category, tags, importance_score, created_at)
                   VALUES ('vault_note', %s, %s, 'deploy-snapshot',
                           ARRAY['deploy-snapshot', 'pre-deploy', %s], 0.5, NOW())
                   RETURNING id""",
                (
                    f"Pre-deploy snapshot: {domain}",
                    content,
                    domain.replace(".", "_"),
                ),
            )
            kb_id = cur.fetchone()["id"]
            logger.info("[DeploySnapshot] Stored pre-deploy snapshot kb_id=%d for %s", kb_id, domain)
            return kb_id
    except Exception:
        logger.exception("[DeploySnapshot] Failed to snapshot %s", domain)
        return None


def restore_snapshot(backup_kb_id: int, source_path: str, filename: str) -> bool:
    """Restore file from KB snapshot to source_path/filename."""
    try:
        from database import get_db_cursor

        with get_db_cursor() as (_conn, cur):
            cur.execute("SELECT content FROM knowledge_base WHERE id = %s", (backup_kb_id,))
            row = cur.fetchone()
        if not row:
            logger.error("[DeployRestore] Snapshot kb_id=%d not found", backup_kb_id)
            return False
        dest = os.path.join(source_path, filename)
        with open(dest, "w") as f:
            f.write(row["content"])
        logger.info("[DeployRestore] Restored from kb_id=%d to %s", backup_kb_id, dest)
        return True
    except Exception:
        logger.exception("[DeployRestore] Failed to restore kb_id=%d", backup_kb_id)
        return False


def _alert_and_propose(domain: str, capability: str, error: str) -> None:
    """Send Telegram alert and create Repair Bay proposal for failed deploy."""
    try:
        from services.telegram_service import send_system

        send_system(
            f"Deploy failed: {domain}\n"
            f"Capability: {capability}\n"
            f"Error: {error}\n"
            f"Repair Bay proposal created."
        )
    except Exception:
        logger.warning("[DeployPipeline] Telegram alert failed for %s", domain)

    try:
        from database import get_db_cursor

        with get_db_cursor(commit=True) as (_conn, cur):
            cur.execute(
                """INSERT INTO improvement_proposals
                   (title, description, category, priority, status)
                   VALUES (%s, %s, 'deploy_failure', 'high', 'proposed')""",
                (
                    f"Deploy failed: {domain}",
                    f"Capability {capability} failed for {domain}. Error: {error}",
                ),
            )
    except Exception:
        logger.warning("[DeployPipeline] Failed to create proposal for %s", domain)


def run_deploy_pipeline(capability: str, context: dict) -> DeployResult:
    """Execute full deploy pipeline: classify → snapshot → execute → verify → retry/rollback.

    context keys:
      domain        (str)       — domain name or VPS container name
      source_path   (str)       — local source directory
      changed_files (list[str]) — relative paths of changed files (used for risk + VPS rsync)
      verify_url    (str)       — URL to verify after deploy (empty = skip verify)
      is_translation (bool)     — if True, also check for Mock values (default False)
      container_name (str)      — VPS container key in VPS_SERVICE_MAP (deploy_vps only)
    """
    domain = context.get("domain", "unknown")
    source_path = context.get("source_path", "")
    changed_files = context.get("changed_files", [])
    verify_url = context.get("verify_url", "")
    is_translation = context.get("is_translation", False)

    result = DeployResult(success=False, domain=domain, capability=capability)

    # Step 1 — Risk classification
    risk = classify_risk(changed_files)
    if risk == "approval_required":
        logger.info(
            "[DeployPipeline] %s requires Telegram approval (risky files: %s)",
            domain,
            changed_files,
        )
        try:
            from ai_bridge.agent_loop import request_approval

            request_approval(
                action_type="cloud_throughput_escalation",
                action_data={
                    "domain": domain,
                    "changed_files": changed_files,
                    "capability": capability,
                },
                reason=f"Deploy to {domain} includes non-static files ({changed_files}). Approve?",
                requested_by="deploy_service",
                tier=2,
            )
        except Exception:
            logger.exception("[DeployPipeline] Approval request failed for %s", domain)
        result.error = "Pending Telegram approval"
        return result

    # Step 2 — Pre-deploy snapshot
    if verify_url:
        result.backup_id = snapshot_current(domain, verify_url)

    # Step 3 — Execute
    def _execute() -> bool:
        if capability == "deploy_static":
            return _deploy_static_hostinger(domain, source_path)
        elif capability == "deploy_vps":
            container = context.get("container_name", domain)
            return _deploy_vps(container, changed_files, source_path)
        else:
            raise ValueError(f"Unknown deploy capability: {capability}")

    try:
        ok = _execute()
    except Exception as e:
        ok = False
        result.error = str(e)
        logger.exception("[DeployPipeline] Execute failed for %s", domain)

    # deploy_static is ASYNC: the container only marks the domain deploy_pending in
    # system_config — the real Hostinger push runs via Claude's hosting_deployStaticWebsite
    # MCP tool (Anthropic infra), never from inside this container. Running verify/retry on
    # a push that did not happen here ALWAYS fails → 120s retry sleep + _alert_and_propose
    # LLM dispatch, which blows past the delegate_task worker's 360s timeout and wedges the
    # single-instance worker for ALL delegations (task #3577, KB #269948). Short-circuit:
    # return as soon as the pending mark lands. The actual push + live verify is the
    # /deploy-website skill's job.
    if capability == "deploy_static":
        result.success = ok
        if ok:
            result.metadata["status"] = "deploy_pending"
            result.metadata["note"] = (
                "Marked deploy_pending only — the live Hostinger push must be run by "
                "Claude via the /deploy-website skill (hosting_deployStaticWebsite). "
                "No bytes were pushed by this pipeline."
            )
            logger.info(
                "[DeployPipeline] %s deploy_static -> deploy_pending (async; skipping "
                "in-container verify/retry — push is handled by the deploy-website skill)",
                domain,
            )
        else:
            result.error = result.error or "Failed to mark deploy_pending"
        return result

    # Step 4 — Verify
    if ok and verify_url:
        time.sleep(VERIFY_WAIT_SECONDS)
        ok = verify_deploy(verify_url, is_translation)
        if not ok:
            result.error = "Verification failed (HTTP or Mock values)"

    # Step 5 — Retry once on failure
    if not ok and not result.retried:
        logger.info("[DeployPipeline] Retrying %s in %ds...", domain, RETRY_DELAY_SECONDS)
        time.sleep(RETRY_DELAY_SECONDS)
        result.retried = True
        try:
            ok = _execute()
        except Exception as e:
            ok = False
            result.error = str(e)
        if ok and verify_url:
            time.sleep(VERIFY_WAIT_SECONDS)
            ok = verify_deploy(verify_url, is_translation)

    # Step 6 — On double failure: restore + alert
    if not ok:
        if result.backup_id and changed_files and changed_files[0].endswith(".json"):
            restore_snapshot(result.backup_id, source_path, changed_files[0])
            result.rolled_back = True
        _alert_and_propose(domain, capability, result.error or "Unknown error")
        return result

    result.success = True
    result.metadata["backed_up_kb_id"] = result.backup_id
    logger.info("[DeployPipeline] %s deployed successfully via %s", domain, capability)
    return result
