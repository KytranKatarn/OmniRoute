"""
C.O.D.E.X. Gate Service — auto-documentation after every deploy.
Non-blocking soft gate: always approves, documents in background via delegation.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def document_deploy(
    module: str,
    git_commit: str | None,
    changes_summary: str,
    proposal_id: int | None = None,
    pr_number: int | None = None,
) -> dict[str, Any]:
    """
    C.O.D.E.X. post-deploy documentation. Non-blocking — always succeeds.
    Delegates documentation task to C.O.D.E.X. via Department HQ.

    Returns:
        {success: bool, blocks_deploy: False, kb_entry_id: int|None}
    """
    try:
        from services.delegation_service import delegate_task

        delegate_task(
            capability="documentation",
            reason=f"Auto-doc: module={module} commit={git_commit} proposal={proposal_id}",
            args={
                "module": module,
                "git_commit": git_commit,
                "changes_summary": changes_summary,
                "proposal_id": proposal_id,
                "pr_number": pr_number,
            },
            delegation_source="automation",
        )
        logger.info("C.O.D.E.X. documentation task delegated for module=%s", module)
    except Exception as e:
        # Non-blocking — log but never fail the deploy
        logger.warning("C.O.D.E.X. documentation delegation failed (suppressed): %s", e)

    return {"success": True, "blocks_deploy": False, "kb_entry_id": None}
