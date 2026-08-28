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

# VPS connection — DEFAULT target.
# Watch products + WTF migrated to Citadel/boston-2 (root@100.64.0.10,
# /opt/archie-products/<product>/) in 2026-06; outpost-us no longer hosts any
# products (verified topology: KB #272178). Per-product host/key overrides live
# in VPS_SERVICE_MAP; these are the fallback defaults for unmapped targets.
# Key = the id_ed25519 bind-mounted into the archie_platform/archie_scheduler
# containers at /root/.ssh/id_ed25519 (the SAME key the manual Citadel deploys
# authenticate with) — NOT the unmounted /home/kytran/.ssh/repair_bay_deploy.
VPS_HOST = os.getenv("REPAIR_BAY_VPS_HOST", "root@100.64.0.10")
VPS_KEY = os.getenv("REPAIR_BAY_VPS_KEY", "/root/.ssh/id_ed25519")

# Hostinger API — always full-site deploy (partial deploys destroy public_html)
HOSTINGER_API_KEY = os.getenv("HOSTINGER_API_KEY", "")
HOSTINGER_API_BASE = "https://developers.hostinger.com/api/hosting/v1"

# VPS container service map.
# host/dir/service VERIFIED LIVE against Citadel/boston-2 on 2026-06-17 (#4307):
#   ssh root@100.64.0.10 + `docker compose config --services` per product.
# `host` is per-product so a future move is a one-line change (falls back to
# VPS_HOST when omitted). NOTE: compose SERVICE names are heterogeneous —
# gov uses hyphens (kytran-gov-watch) while market uses underscores
# (kytran_market_api); both differ from their underscore CONTAINER names.
VPS_SERVICE_MAP = {
    "kytran_gov_watch": {
        "host": "root@100.64.0.10",
        "dir": "/opt/archie-products/gov-watch/",
        "service": "kytran-gov-watch",
        "verify_path": "/static/data/translations.json",
    },
    "kytran_watch_api": {
        "host": "root@100.64.0.10",
        "dir": "/opt/archie-products/civic-watch/",
        "service": "watch-api",
        "verify_path": "/data/translations.json",
    },
    "kytran_legal_api": {
        "host": "root@100.64.0.10",
        "dir": "/opt/archie-products/legal-watch/",
        "service": "legal-api",
        "verify_path": "/data/translations.json",
    },
    "kytran_market_api": {
        "host": "root@100.64.0.10",
        "dir": "/opt/archie-products/market-watch/",
        "service": "kytran_market_api",
        "verify_path": "/static/data/translations.json",
    },
    "wtf_consumer": {
        "host": "root@100.64.0.10",
        "dir": "/opt/archie-products/what-the-fact/",
        "service": "wtf-consumer",
        "verify_path": "/static/data/translations.json",
    },
    "wtf_tech": {
        "host": "root@100.64.0.10",
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
    """Return 'auto' if all files are safe static types, else 'approval_required'.

    ⚠️ Feed this REAL FILE PATHS, never directories. A bare directory has no
    suffix, so it can never match AUTO_SAFE_EXTENSIONS and always returns
    'approval_required' — safe, but meaningless: a constant, not a
    classification. The daily website worker passed ``["assets/portraits/",
    "data/"]`` and therefore demanded approval on every run whatever had (or
    had not) changed, while the translation scanner passed real ``.json`` paths
    for the SAME site and auto-deployed. Use ``changed_files_since()`` to build
    the list. Directories are still handled here explicitly — and logged — so
    the behaviour is a decision rather than an accident of Path().suffix
    (audited 2026-07-28).
    """
    for f in changed_files:
        entry = str(f)
        path = Path(entry)
        if entry.endswith("/") or not path.suffix:
            logger.info(
                "[classify_risk] '%s' is a directory, not a file — contents unknown, "
                "requiring approval. Pass real file paths (changed_files_since) for a "
                "meaningful classification.",
                entry,
            )
            return "approval_required"
        if path.suffix.lower() not in AUTO_SAFE_EXTENSIONS:
            return "approval_required"
        name_lower = path.name.lower()
        for pattern in APPROVAL_REQUIRED_PATTERNS:
            if pattern in name_lower:
                return "approval_required"
    return "auto"


def changed_files_since(source_path: str, since_iso: Optional[str], limit: int = 500) -> list[str]:
    """Real file paths under ``source_path`` modified after ``since_iso``.

    Gives classify_risk something it can actually classify. Returns paths
    relative to source_path, sorted. When ``since_iso`` is missing or
    unparseable (a site that has never recorded a push) this returns [] — and
    [] means "nothing measurably changed", NEVER "everything is safe", so
    callers must not treat an empty list as a green light.

    ``limit`` caps the walk so a first run cannot build a 10k-entry approval
    reason; the caller reports when the cap is hit.
    """
    root = Path(source_path)
    if not root.is_dir():
        return []
    try:
        since_dt = datetime.datetime.fromisoformat(str(since_iso).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return []
    if since_dt.tzinfo is None:
        since_dt = since_dt.replace(tzinfo=timezone.utc)
    cutoff = since_dt.timestamp()

    out: list[str] = []
    for p in root.rglob("*"):
        if len(out) >= limit:
            break
        try:
            if p.is_file() and p.stat().st_mtime > cutoff:
                out.append(str(p.relative_to(root)))
        except OSError:
            continue  # vanished mid-walk / unreadable — never fatal
    return sorted(out)


def mark_deploy_pushed(domain: str, artifact: str = "", file_count: int = 0, bytes_pushed: int = 0) -> bool:
    """Record that bytes ACTUALLY reached Hostinger for ``domain``.

    THE ONLY writer of status 'deployed'. Everything upstream may write
    'deploy_pending' (queued for the push) or 'failed'; nothing else may claim
    a completed deploy. Before this existed ``website_deploy_last_status_*``
    could only ever read 'deploy_pending', so a site pushed an hour ago and a
    site stranded for weeks were indistinguishable and the Ship tab showed
    'pending' forever (audited 2026-07-28: both domains sat 'deploy_pending'
    with live content ~2 days stale and 404s on new assets).

    Called by the /deploy-website skill (and the Ship tab deploy action)
    immediately after ``hosting_deployStaticWebsite`` returns success.
    """
    from database import get_db_cursor

    ts = datetime.datetime.now(timezone.utc).isoformat()
    rows = [
        (f"website_deploy_last_status_{domain}", "deployed"),
        (f"website_deploy_last_push_{domain}", ts),
    ]
    if artifact or file_count or bytes_pushed:
        rows.append(
            (
                f"website_deploy_last_artifact_{domain}",
                f"{artifact or 'zip'} files={file_count} bytes={bytes_pushed}",
            )
        )
    try:
        with get_db_cursor(commit=True) as (_, cur):
            for k, v in rows:
                cur.execute(
                    """INSERT INTO system_config (key, value, updated_at)
                       VALUES (%s, %s, NOW())
                       ON CONFLICT (key) DO UPDATE SET value=EXCLUDED.value, updated_at=NOW()""",
                    (k, v),
                )
        logger.info("[DeployStatic] %s marked DEPLOYED (%s, %s files)", domain, artifact, file_count)
        return True
    except Exception as exc:
        logger.error("[DeployStatic] could not mark %s deployed: %s", domain, exc)
        return False


def last_push_iso(domain: str) -> Optional[str]:
    """Timestamp of the last REAL push for ``domain`` (None if never pushed)."""
    from database import get_db_cursor

    try:
        with get_db_cursor() as (_, cur):
            cur.execute("SELECT value FROM system_config WHERE key = %s", (f"website_deploy_last_push_{domain}",))
            row = cur.fetchone()
        if not row:
            return None
        return row["value"] if isinstance(row, dict) else row[0]
    except Exception as exc:
        logger.warning("[DeployStatic] last_push lookup failed for %s: %s", domain, exc)
        return None


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
    # Per-product host/key (fall back to the module defaults). UserKnownHostsFile=
    # /dev/null because the platform/scheduler containers run a read-only rootfs —
    # ssh can't write ~/.ssh/known_hosts, which otherwise emits a noisy warning.
    host = info.get("host") or VPS_HOST
    key = info.get("key") or VPS_KEY
    ssh_opts = [
        "-i",
        key,
        "-o",
        "StrictHostKeyChecking=no",
        "-o",
        "UserKnownHostsFile=/dev/null",
        "-o",
        "BatchMode=yes",
    ]

    # 1. SCP each changed file to its target location on VPS (rsync not in container)
    for rel_path in changed_files:
        src_file = os.path.join(source_dir, rel_path)
        target_subdir = os.path.dirname(os.path.join(target_dir, rel_path))
        # Ensure target directory exists on VPS
        mkdir_cmd = ["ssh"] + ssh_opts + [host, f"mkdir -p {target_subdir}"]
        subprocess.run(mkdir_cmd, capture_output=True, timeout=30)
        scp_cmd = ["scp"] + ssh_opts + [src_file, f"{host}:{target_subdir}/"]
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
    ssh_cmd = ["ssh"] + ssh_opts + [host, rebuild_cmd]
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

    # Step 1 — Risk classification. `approved=True` (set by the website_deploy
    # approval handler after a human taps approve) SKIPS the gate so the re-run
    # actually deploys instead of looping back into another approval request.
    approved = bool(context.get("approved"))
    risk = classify_risk(changed_files)
    if risk == "approval_required" and not approved:
        logger.info(
            "[DeployPipeline] %s requires Telegram approval (risky files: %s)",
            domain,
            changed_files,
        )
        try:
            from ai_bridge.agent_loop import request_approval

            # Dedicated 'website_deploy' action_type (#4344 follow-up). The old
            # 'cloud_throughput_escalation' was tier-1 auto-approved with a no-op
            # deploy handler, so the Telegram prompt was never delivered AND the
            # deploy never ran (it silently auto-approved into nothing). website_deploy
            # defaults to tier-2 (real human approval) and has a handler that
            # re-invokes this pipeline with approved=True. action_data carries the
            # full context so that re-run has everything it needs.
            request_approval(
                action_type="website_deploy",
                action_data={
                    "domain": domain,
                    "capability": capability,
                    "source_path": source_path,
                    "changed_files": changed_files,
                    "verify_url": verify_url,
                    "is_translation": is_translation,
                    "container_name": context.get("container_name", ""),
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
