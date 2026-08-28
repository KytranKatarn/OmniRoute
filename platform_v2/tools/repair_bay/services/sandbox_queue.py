"""
Sandbox Queue Manager
Ensures only ONE proposal can use the sandbox at a time
Others wait in queue until current proposal completes and deploys

Enhanced with proposal_queue table for:
- Explicit queue position tracking
- Processing state management
- Priority boost system
- Test retry loop integration
"""

import psycopg2
from psycopg2.extras import RealDictCursor
from typing import Dict, Optional, List
import os
from database import _get_db_password
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def _fire_post_deploy_hooks(
    proposal_id: int,
    title: str,
    category: str,
    module_name: str,
    proposal_source: str,
) -> None:
    """Post-deploy feedback loop: docs updater + C.O.D.E.X. + Telegram.

    Fires asynchronously in a daemon thread — never blocks release_sandbox().
    """
    import threading

    def _run():
        # 1. Sandbox docs updater — writes to knowledge_base
        try:
            from tools.repair_bay.services.sandbox_docs_updater import SandboxDocsUpdater

            SandboxDocsUpdater().on_deployment_success(
                proposal_id=proposal_id,
                module_id=module_name or category or "platform",
                title=title,
                description=f"Deployed fix for {module_name or 'platform'}: {title}",
                category=category or "code_quality",
            )
        except Exception as e:
            logger.warning("sandbox_docs_updater failed (non-fatal): %s", e)

        # 2. C.O.D.E.X. dispatch — update KB docs for the changed module
        if module_name:
            try:
                from tools.department_hq.services.department_dispatcher import dispatch

                dispatch(
                    capability="documentation",
                    prompt=(
                        f"A code fix was deployed for module '{module_name}': \"{title}\". "
                        f"Update the knowledge base with a brief vault_note documenting what was fixed, "
                        f"when it was deployed, and which module was affected."
                    ),
                    context={
                        "proposal_id": proposal_id,
                        "module": module_name,
                        "source": proposal_source,
                    },
                )
            except Exception as e:
                logger.warning("C.O.D.E.X. post-deploy dispatch failed (non-fatal): %s", e)

        # 3. Telegram notification via A.R.C.H.I.E.
        try:
            from services.telegram_service import send_info

            source_label = f" (from {proposal_source})" if proposal_source != "manual" else ""
            send_info(
                f"✅ *Repair Bay deployed*{source_label}\n"
                f"Proposal #{proposal_id}: _{title}_\n"
                f"Module: `{module_name or 'platform'}`"
            )
        except Exception as e:
            logger.warning("Telegram post-deploy notify failed (non-fatal): %s", e)

    t = threading.Thread(target=_run, daemon=True)
    t.start()


def _is_deploy_paused_for_perf() -> bool:
    """Return True iff system_config.deploy_paused_perf is set to 'true'.

    Set by the post-deploy perf gate (proposal_service._evaluate_perf_gate)
    when a non-critical regression hits the 2-of-3 pattern. Cleared via
    /api/qa/regressions/<id>/clear or by ops setting the row to 'false'.

    Fail-open: any DB / lookup error returns False so a pause-flag bug
    can never wedge the entire deploy pipeline.
    """
    try:
        from database import get_db_cursor

        with get_db_cursor() as (conn, cur):
            cur.execute("SELECT value FROM system_config WHERE key = 'deploy_paused_perf'")
            row = cur.fetchone()
        if not row:
            return False
        # get_db_cursor returns RealDictCursor by default; tolerate both shapes
        value = row["value"] if isinstance(row, dict) else row[0]
        return str(value).lower() == "true"
    except Exception as _exc:  # noqa: BLE001 — fail open
        logger.warning("deploy_paused_perf check failed: %s", _exc)
        return False


class SandboxQueue:
    """Manages the proposal queue for sandbox testing"""

    def __init__(self):
        self.db_config = {
            "host": os.getenv("DB_HOST", "archie_database"),
            "database": os.getenv("DB_NAME", "archie"),
            "user": os.getenv("DB_USER", "archie"),
            "password": _get_db_password(),
        }

    def get_db(self):
        """Get database connection"""
        return psycopg2.connect(**self.db_config)

    def get_current_sandbox_proposal(self) -> Optional[Dict]:
        """
        Get the proposal currently using the sandbox

        Returns:
            Dict with proposal info if sandbox is in use, None otherwise
        """
        conn = self.get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Check if there's an active sandbox
        cur.execute(
            """
            SELECT
                si.id as sandbox_id,
                si.proposal_id,
                si.status as sandbox_status,
                si.created_at as sandbox_created_at,
                ip.title,
                ip.status as proposal_status,
                ip.category,
                ip.priority,
                ip.approved_at
            FROM sandbox_instances si
            JOIN improvement_proposals ip ON si.proposal_id = ip.id
            WHERE si.destroyed_at IS NULL
            AND si.status IN ('ready', 'testing', 'tested', 'applying_changes')
            ORDER BY si.created_at DESC
            LIMIT 1
        """
        )

        result = cur.fetchone()
        cur.close()
        conn.close()

        return dict(result) if result else None

    def get_queue(self) -> List[Dict]:
        """
        Get all proposals waiting in queue for sandbox

        Returns:
            List of proposals in queue (approved but not yet in sandbox).
            Returns [] when system_config.deploy_paused_perf='true' so no
            new claims fire while we're awaiting human review of a perf
            regression. Fails open (continues query) on lookup error.
        """
        if _is_deploy_paused_for_perf():
            return []

        conn = self.get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Get approved proposals that aren't in sandbox yet
        cur.execute(
            """
            SELECT
                id,
                title,
                category,
                priority,
                approved_at,
                team_size,
                EXTRACT(EPOCH FROM (NOW() - approved_at))/3600 as hours_waiting
            FROM improvement_proposals
            WHERE status = 'approved'
            AND id NOT IN (
                SELECT proposal_id
                FROM sandbox_instances
                WHERE destroyed_at IS NULL
                AND status IN ('ready', 'testing', 'tested', 'applying_changes')
            )
            ORDER BY
                CASE priority
                    WHEN 'critical' THEN 1
                    WHEN 'high' THEN 2
                    WHEN 'medium' THEN 3
                    WHEN 'low' THEN 4
                    ELSE 5
                END,
                approved_at ASC
        """
        )

        results = cur.fetchall()
        cur.close()
        conn.close()

        return [dict(row) for row in results]

    def can_use_sandbox(self, proposal_id: int) -> Dict:
        """
        Check if a proposal can use the sandbox

        Returns:
            {
                'can_use': bool,
                'reason': str,
                'current_proposal': dict or None,
                'queue_position': int or None
            }
        """
        # Perf gate — refuse direct claims when deploys paused for perf review
        if _is_deploy_paused_for_perf():
            return {
                "can_use": False,
                "reason": "Deploys paused — awaiting human review of a perf regression",
                "current_proposal": None,
                "queue_position": None,
            }

        current = self.get_current_sandbox_proposal()

        # If no sandbox in use, this proposal can use it
        if not current:
            return {
                "can_use": True,
                "reason": "Sandbox is available",
                "current_proposal": None,
                "queue_position": 0,
            }

        # If this IS the current proposal, it's already using sandbox
        if current["proposal_id"] == proposal_id:
            return {
                "can_use": True,
                "reason": "This proposal is currently using the sandbox",
                "current_proposal": current,
                "queue_position": 0,
            }

        # Otherwise, check queue position
        queue = self.get_queue()
        position = None
        for idx, queued_proposal in enumerate(queue):
            if queued_proposal["id"] == proposal_id:
                position = idx + 1
                break

        return {
            "can_use": False,
            "reason": f"Sandbox is in use by Proposal #{current['proposal_id']}",
            "current_proposal": current,
            "queue_position": position,
        }

    def release_sandbox(self, proposal_id: int) -> Dict:
        """
        Release the sandbox after proposal is deployed
        This allows the next proposal in queue to use it

        Returns:
            {
                'success': bool,
                'message': str,
                'next_proposal': dict or None
            }
        """
        conn = self.get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Mark sandbox as destroyed
        cur.execute(
            """
            UPDATE sandbox_instances
            SET status = 'destroyed', destroyed_at = NOW()
            WHERE proposal_id = %s
            AND destroyed_at IS NULL
        """,
            (proposal_id,),
        )

        # Update proposal status to deployed
        cur.execute(
            """
            UPDATE improvement_proposals
            SET
                status = 'deployed',
                deployed_at = NOW()
            WHERE id = %s
        """,
            (proposal_id,),
        )

        # Fetch proposal details for post-deploy hooks before closing
        cur.execute(
            "SELECT title, category, module_name, proposal_source, proposed_by "
            "FROM improvement_proposals WHERE id = %s",
            (proposal_id,),
        )
        _prop = cur.fetchone() or {}

        conn.commit()
        cur.close()
        conn.close()

        # Post-deploy feedback loop — fire-and-forget (never block the release)
        _fire_post_deploy_hooks(
            proposal_id=proposal_id,
            title=_prop.get("title", f"Proposal #{proposal_id}"),
            category=_prop.get("category", ""),
            module_name=_prop.get("module_name", ""),
            proposal_source=_prop.get("proposal_source", "manual"),
        )

        # Get next proposal in queue
        queue = self.get_queue()
        next_proposal = queue[0] if queue else None

        return {
            "success": True,
            "message": f"Sandbox released from Proposal #{proposal_id}",
            "next_proposal": next_proposal,
        }

    def get_queue_status(self) -> Dict:
        """
        Get complete queue status

        Returns:
            {
                'sandbox_in_use': bool,
                'current_proposal': dict or None,
                'queue_length': int,
                'queue': list of proposals
            }
        """
        current = self.get_current_sandbox_proposal()
        queue = self.get_queue()

        return {
            "sandbox_in_use": current is not None,
            "current_proposal": current,
            "queue_length": len(queue),
            "queue": queue,
        }


# Convenience functions
def get_sandbox_queue():
    """Get SandboxQueue instance"""
    return SandboxQueue()


def can_proposal_use_sandbox(proposal_id: int) -> Dict:
    """Quick check if proposal can use sandbox"""
    queue = SandboxQueue()
    return queue.can_use_sandbox(proposal_id)


def get_queue_status() -> Dict:
    """Quick get queue status"""
    queue = SandboxQueue()
    return queue.get_queue_status()


# ProposalQueueManager + get_proposal_queue_manager REMOVED (#5344, 2026-08-17):
# they were the ONLY consumer of the dropped `proposal_queue` table (migration 471)
# and their sole caller lived in _deprecated/admin_deprecated_20260113. The live
# sandbox path is SandboxQueue above, which never touched that table.
