"""
Background Workflow Runner
Executes workflows in background threads to prevent gunicorn worker timeouts

Author: A.R.C.H.I.E. Self-Improvement System
Date: 2026-01-05
"""

import threading
import time
import traceback
from typing import Dict, Optional
from datetime import datetime


class BackgroundWorkflowRunner:
    """Runs workflows in background threads to prevent blocking web requests"""

    def __init__(self):
        self.active_workflows = {}  # workflow_id -> thread info
        self.workflow_results = {}  # workflow_id -> result dict
        self.lock = threading.Lock()

    def start_workflow(self, proposal_id: int) -> Dict:
        """
        Start workflow in background thread

        Args:
            proposal_id: Proposal ID to process

        Returns:
            {
                'success': True,
                'workflow_id': str,
                'message': str,
                'started_at': str
            }
        """
        workflow_id = f"workflow_{proposal_id}_{int(time.time())}"

        # Check if workflow already running for this proposal
        with self.lock:
            for wf_id, info in self.active_workflows.items():
                if info["proposal_id"] == proposal_id and info["status"] == "running":
                    return {
                        "success": False,
                        "error": f"Workflow already running for proposal #{proposal_id}",
                        "workflow_id": wf_id,
                    }

        # Create and start background thread
        thread = threading.Thread(
            target=self._execute_workflow_thread,
            args=(workflow_id, proposal_id),
            daemon=True,
            name=f"WorkflowThread-{proposal_id}",
        )

        with self.lock:
            self.active_workflows[workflow_id] = {
                "proposal_id": proposal_id,
                "status": "running",
                "started_at": datetime.now().isoformat(),
                "thread": thread,
            }

        thread.start()

        return {
            "success": True,
            "workflow_id": workflow_id,
            "message": f"Workflow started for proposal #{proposal_id}",
            "started_at": self.active_workflows[workflow_id]["started_at"],
        }

    def _execute_workflow_thread(self, workflow_id: str, proposal_id: int):
        """Execute workflow in background thread"""
        try:
            print(
                f"🚀 Background workflow {workflow_id} starting for proposal #{proposal_id}"
            )

            # Import here to avoid circular dependencies
            from workflow_orchestrator import execute_workflow

            # Execute the workflow
            result = execute_workflow(proposal_id)

            # Store result
            with self.lock:
                self.workflow_results[workflow_id] = {
                    **result,
                    "completed_at": datetime.now().isoformat(),
                }

                if workflow_id in self.active_workflows:
                    self.active_workflows[workflow_id]["status"] = "completed"
                    self.active_workflows[workflow_id][
                        "completed_at"
                    ] = datetime.now().isoformat()

            print(f"✅ Background workflow {workflow_id} completed successfully")

        except Exception as e:
            error_msg = f"Workflow error: {str(e)}"
            error_trace = traceback.format_exc()

            print(f"❌ Background workflow {workflow_id} failed: {error_msg}")
            print(error_trace)

            # Store error result
            with self.lock:
                self.workflow_results[workflow_id] = {
                    "success": False,
                    "error": error_msg,
                    "traceback": error_trace,
                    "completed_at": datetime.now().isoformat(),
                }

                if workflow_id in self.active_workflows:
                    self.active_workflows[workflow_id]["status"] = "failed"
                    self.active_workflows[workflow_id]["error"] = error_msg
                    self.active_workflows[workflow_id][
                        "completed_at"
                    ] = datetime.now().isoformat()

    def get_workflow_status(self, workflow_id: str) -> Optional[Dict]:
        """
        Get status of a workflow

        Returns:
            {
                'status': 'running' | 'completed' | 'failed',
                'proposal_id': int,
                'started_at': str,
                'completed_at': str (if done),
                'result': dict (if completed)
            }
        """
        with self.lock:
            if workflow_id not in self.active_workflows:
                return None

            info = self.active_workflows[workflow_id].copy()

            # Add result if available
            if workflow_id in self.workflow_results:
                info["result"] = self.workflow_results[workflow_id]

            # Remove thread object from response
            info.pop("thread", None)

            return info

    def get_proposal_workflow(self, proposal_id: int) -> Optional[Dict]:
        """Get latest workflow for a proposal"""
        with self.lock:
            # Find most recent workflow for this proposal
            matching_workflows = [
                (wf_id, info)
                for wf_id, info in self.active_workflows.items()
                if info["proposal_id"] == proposal_id
            ]

            if not matching_workflows:
                return None

            # Sort by started_at descending
            matching_workflows.sort(key=lambda x: x[1]["started_at"], reverse=True)
            latest_id, latest_info = matching_workflows[0]

            result = latest_info.copy()
            result["workflow_id"] = latest_id

            # Add result if available
            if latest_id in self.workflow_results:
                result["result"] = self.workflow_results[latest_id]

            # Remove thread object
            result.pop("thread", None)

            return result

    def cleanup_old_workflows(self, max_age_hours: int = 24):
        """Remove workflow records older than max_age_hours"""
        cutoff = time.time() - (max_age_hours * 3600)

        with self.lock:
            to_remove = []

            for wf_id, info in self.active_workflows.items():
                started_at = datetime.fromisoformat(info["started_at"])
                if started_at.timestamp() < cutoff:
                    to_remove.append(wf_id)

            for wf_id in to_remove:
                self.active_workflows.pop(wf_id, None)
                self.workflow_results.pop(wf_id, None)

            return len(to_remove)


# Global singleton instance
_runner = None


def get_workflow_runner() -> BackgroundWorkflowRunner:
    """Get global workflow runner instance"""
    global _runner
    if _runner is None:
        _runner = BackgroundWorkflowRunner()
    return _runner


# Convenience functions
def start_workflow_background(proposal_id: int) -> Dict:
    """Start workflow in background"""
    runner = get_workflow_runner()
    return runner.start_workflow(proposal_id)


def get_workflow_status(workflow_id: str) -> Optional[Dict]:
    """Get workflow status"""
    runner = get_workflow_runner()
    return runner.get_workflow_status(workflow_id)


def get_proposal_workflow_status(proposal_id: int) -> Optional[Dict]:
    """Get latest workflow status for a proposal"""
    runner = get_workflow_runner()
    return runner.get_proposal_workflow(proposal_id)
