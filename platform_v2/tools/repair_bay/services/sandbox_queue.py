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
from datetime import datetime
from typing import Dict, Optional, List, Tuple
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


class ProposalQueueManager:
    """
    Enhanced queue manager using proposal_queue table.
    Provides stricter enforcement and better tracking.
    """

    def __init__(self):
        self.db_config = {
            "host": os.getenv("DB_HOST", "archie_database"),
            "database": os.getenv("DB_NAME", "archie"),
            "user": os.getenv("DB_USER", "archie"),
            "password": _get_db_password(),
        }

    def get_db(self):
        return psycopg2.connect(**self.db_config)

    def can_start_processing(self, proposal_id: int) -> Tuple[bool, str]:
        """
        Check if a proposal can start processing.

        Returns:
            Tuple of (can_start: bool, message: str)
        """
        conn = self.get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        try:
            # Check if this proposal is already processing
            cur.execute(
                """
                SELECT id, queue_status
                FROM proposal_queue
                WHERE proposal_id = %s
                AND queue_status IN ('queued', 'processing')
            """,
                (proposal_id,),
            )

            existing = cur.fetchone()
            if existing and existing["queue_status"] == "processing":
                return True, "Already processing"

            # Check if any other proposal is processing
            cur.execute(
                """
                SELECT pq.proposal_id, ip.title
                FROM proposal_queue pq
                JOIN improvement_proposals ip ON ip.id = pq.proposal_id
                WHERE pq.queue_status = 'processing'
                AND pq.proposal_id != %s
                LIMIT 1
            """,
                (proposal_id,),
            )

            active = cur.fetchone()
            if active:
                return (
                    False,
                    f"Queue blocked by Proposal #{active['proposal_id']}: {active['title']}",
                )

            return True, "Ready to process"

        finally:
            cur.close()
            conn.close()

    def add_to_queue(self, proposal_id: int, priority_boost: int = 0) -> Dict:
        """Add a proposal to the processing queue."""
        conn = self.get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        try:
            # Check if already in queue
            cur.execute(
                """
                SELECT id, queue_position, queue_status
                FROM proposal_queue
                WHERE proposal_id = %s
                AND queue_status IN ('queued', 'processing')
            """,
                (proposal_id,),
            )

            existing = cur.fetchone()
            if existing:
                return {
                    "success": True,
                    "already_queued": True,
                    "queue_id": existing["id"],
                    "position": existing["queue_position"],
                    "status": existing["queue_status"],
                }

            # Get next position
            cur.execute(
                """
                SELECT COALESCE(MAX(queue_position), 0) + 1 as next_pos
                FROM proposal_queue
                WHERE queue_status IN ('queued', 'processing')
            """
            )
            next_pos = cur.fetchone()["next_pos"]

            # Add to queue
            cur.execute(
                """
                INSERT INTO proposal_queue (proposal_id, queue_position, priority_boost)
                VALUES (%s, %s, %s)
                RETURNING id, queue_position
            """,
                (proposal_id, next_pos, priority_boost),
            )

            result = cur.fetchone()
            conn.commit()

            logger.info(f"Proposal #{proposal_id} added to queue at position {next_pos}")

            return {
                "success": True,
                "queue_id": result["id"],
                "position": result["queue_position"],
            }

        except Exception as e:
            conn.rollback()
            logger.error(f"Failed to add proposal {proposal_id} to queue: {e}")
            return {"success": False, "error": str(e)}
        finally:
            cur.close()
            conn.close()

    def start_processing(self, proposal_id: int) -> Dict:
        """Mark a proposal as started processing."""
        can_start, message = self.can_start_processing(proposal_id)
        if not can_start:
            return {"success": False, "error": message}

        conn = self.get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        try:
            # Check if already in queue
            cur.execute(
                """
                SELECT id FROM proposal_queue
                WHERE proposal_id = %s AND queue_status = 'queued'
            """,
                (proposal_id,),
            )

            existing = cur.fetchone()

            if existing:
                # Update existing entry
                cur.execute(
                    """
                    UPDATE proposal_queue
                    SET queue_status = 'processing', started_at = NOW()
                    WHERE id = %s
                    RETURNING id
                """,
                    (existing["id"],),
                )
            else:
                # Create new entry directly in processing
                cur.execute(
                    """
                    INSERT INTO proposal_queue
                    (proposal_id, queue_position, queue_status, started_at)
                    VALUES (%s, (SELECT COALESCE(MAX(queue_position), 0) + 1 FROM proposal_queue), 'processing', NOW())
                    RETURNING id
                """,
                    (proposal_id,),
                )

            conn.commit()
            logger.info(f"Proposal #{proposal_id} started processing")
            return {"success": True, "message": "Processing started"}

        except Exception as e:
            conn.rollback()
            logger.error(f"Failed to start processing: {e}")
            return {"success": False, "error": str(e)}
        finally:
            cur.close()
            conn.close()

    def complete_processing(self, proposal_id: int, status: str = "completed") -> Dict:
        """Mark a proposal as done processing."""
        conn = self.get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        try:
            cur.execute(
                """
                UPDATE proposal_queue
                SET queue_status = %s, completed_at = NOW()
                WHERE proposal_id = %s
                AND queue_status = 'processing'
                RETURNING id
            """,
                (status, proposal_id),
            )

            result = cur.fetchone()
            conn.commit()

            if result:
                logger.info(f"Proposal #{proposal_id} completed: {status}")
                return {"success": True}
            return {"success": False, "error": "Not in processing state"}

        except Exception as e:
            conn.rollback()
            return {"success": False, "error": str(e)}
        finally:
            cur.close()
            conn.close()

    def get_full_status(self) -> Dict:
        """Get full queue status including proposal_queue table."""
        conn = self.get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        try:
            # Active processing
            cur.execute(
                """
                SELECT pq.*, ip.title, ip.category, ip.test_retry_count, ip.escalation_status
                FROM proposal_queue pq
                JOIN improvement_proposals ip ON ip.id = pq.proposal_id
                WHERE pq.queue_status = 'processing'
            """
            )
            active = cur.fetchone()

            # Queued items
            cur.execute(
                """
                SELECT pq.*, ip.title, ip.category
                FROM proposal_queue pq
                JOIN improvement_proposals ip ON ip.id = pq.proposal_id
                WHERE pq.queue_status = 'queued'
                ORDER BY (pq.queue_position - pq.priority_boost) ASC
            """
            )
            queued = cur.fetchall()

            return {
                "queue_available": active is None,
                "active_processing": dict(active) if active else None,
                "queued": [dict(q) for q in queued],
                "queued_count": len(queued),
            }

        finally:
            cur.close()
            conn.close()

    def get_position(self, proposal_id: int) -> Dict:
        """Get queue position for a proposal."""
        conn = self.get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        try:
            cur.execute(
                """
                SELECT queue_status, queue_position, queued_at, started_at
                FROM proposal_queue
                WHERE proposal_id = %s
                ORDER BY id DESC
                LIMIT 1
            """,
                (proposal_id,),
            )

            result = cur.fetchone()
            if not result:
                return {"in_queue": False}

            if result["queue_status"] == "processing":
                return {
                    "in_queue": True,
                    "position": 0,
                    "status": "processing",
                    "started_at": (result["started_at"].isoformat() if result["started_at"] else None),
                }
            elif result["queue_status"] == "queued":
                cur.execute(
                    """
                    SELECT COUNT(*) as ahead
                    FROM proposal_queue
                    WHERE queue_status IN ('queued', 'processing')
                    AND (queue_position < %s OR queue_status = 'processing')
                    AND proposal_id != %s
                """,
                    (result["queue_position"], proposal_id),
                )
                ahead = cur.fetchone()["ahead"]

                return {"in_queue": True, "position": ahead + 1, "status": "queued"}
            return {"in_queue": False, "status": result["queue_status"]}

        finally:
            cur.close()
            conn.close()


# Singleton
_proposal_queue_manager = None


def get_proposal_queue_manager() -> ProposalQueueManager:
    """Get singleton ProposalQueueManager"""
    global _proposal_queue_manager
    if _proposal_queue_manager is None:
        _proposal_queue_manager = ProposalQueueManager()
    return _proposal_queue_manager
