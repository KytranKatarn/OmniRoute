"""Codex promote → Telegram approval → merge + production deploy.

Flow:
  promote_codex_pr(pr) -> request_approval(action_type='codex_promote', tier=2)
    -> Telegram Approve/Deny to Kytran
    -> [on Approve] agent_loop consumer merges the PR (GitHub API) and sets
       execution_result.deploy_pending=true
    -> [host] scripts/agents/codex-prod-deploy.sh sees deploy_pending, does
       git pull main + safe_restart.sh + verify + Telegram "LIVE", clears the flag.

This module only TRIGGERS the approval. The merge happens in the agent_loop
approval consumer; the production deploy happens on the host poller. Nothing
here touches production directly.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def promote_codex_pr(
    pr_number: int,
    title: str | None = None,
    module: str | None = None,
    sandbox_url: str = "https://sandbox.kytranempowerment.com",
    forge_verdict: str | None = None,
) -> dict:
    """Queue a Tier-2 Telegram approval to promote a previewed Codex PR to prod.

    Returns {"success", "approval_id"} or {"success": False, "error"}.
    """
    if not pr_number:
        return {"success": False, "error": "pr_number is required"}
    import re

    # SECURITY: strict module allow-list (layer 1 of 3) — defence-in-depth against
    # injection in the downstream host poller that builds URLs/log strings.
    if module is not None and not re.fullmatch(r"[a-z0-9_-]{1,40}", str(module)):
        return {"success": False, "error": f"invalid module: {module!r}"}
    try:
        from ai_bridge.agent_loop import request_approval
    except Exception as e:  # noqa: BLE001
        return {"success": False, "error": f"cannot import request_approval: {e}"}

    label = title or f"Codex PR #{pr_number}"
    verdict = f" · F.O.R.G.E.: {forge_verdict}" if forge_verdict else ""
    reason = (
        f"Promote {label} to PRODUCTION.{verdict}\n"
        f"Previewed on sandbox: {sandbox_url}\n"
        f"Approve → merge to main + deploy to platform.kytranempowerment.com "
        f"(safe_restart with auto-rollback). Deny → nothing."
    )
    try:
        approval_id = request_approval(
            action_type="codex_promote",
            action_data={
                "pr_number": int(pr_number),
                "title": label,
                "module": module,
                "sandbox_url": sandbox_url,
            },
            reason=reason,
            requested_by="codex_promote",
            tier=2,
            priority=7,
        )
    except Exception as e:  # noqa: BLE001
        logger.error("promote_codex_pr: request_approval failed: %s", e)
        return {"success": False, "error": str(e)}

    logger.info("promote_codex_pr: queued approval #%s for PR #%s", approval_id, pr_number)
    return {"success": True, "approval_id": approval_id, "pr_number": int(pr_number)}
