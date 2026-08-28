"""
Workflow Server-Sent Events (SSE) Manager
Provides real-time updates for workflow execution progress

Purpose:
- Stream workflow status updates to frontend
- Replace polling with push-based notifications
- Show live progress as commits are processed
- Update UI instantly when stages complete

Author: A.R.C.H.I.E. Platform
Date: 2026-01-06
"""

import json
import logging

logger = logging.getLogger(__name__)
import queue
import threading
from typing import Dict
from datetime import datetime
from collections import defaultdict


class WorkflowSSEManager:
    """Manages SSE connections and workflow status broadcasts"""

    def __init__(self):
        # Store active SSE connections per proposal_id
        self.connections = defaultdict(list)  # proposal_id -> [queue1, queue2, ...]
        self.lock = threading.Lock()

    def register_client(self, proposal_id: int) -> queue.Queue:
        """
        Register a new SSE client for workflow updates

        Args:
            proposal_id: Improvement proposal ID to subscribe to

        Returns:
            Queue that will receive SSE messages
        """
        message_queue = queue.Queue(maxsize=50)

        with self.lock:
            self.connections[proposal_id].append(message_queue)
            print(f"[SSE] Client registered for proposal #{proposal_id} ({len(self.connections[proposal_id])} total)")

        # Send initial connection message
        self._send_message(
            message_queue,
            {
                "type": "connected",
                "proposal_id": proposal_id,
                "timestamp": datetime.now().isoformat(),
                "message": f"Connected to proposal #{proposal_id} updates",
            },
        )

        return message_queue

    def unregister_client(self, proposal_id: int, message_queue: queue.Queue):
        """
        Unregister an SSE client

        Args:
            proposal_id: Proposal ID
            message_queue: Queue to remove
        """
        with self.lock:
            if proposal_id in self.connections:
                if message_queue in self.connections[proposal_id]:
                    self.connections[proposal_id].remove(message_queue)
                    logger.info(f"[SSE] Client unregistered from proposal #{proposal_id}")

                # Clean up empty connection lists
                if not self.connections[proposal_id]:
                    del self.connections[proposal_id]

    def broadcast_workflow_event(self, proposal_id: int, event_type: str, data: Dict):
        """
        Broadcast a workflow event to all connected clients

        Args:
            proposal_id: Proposal ID
            event_type: Event type (workflow_started, stage_complete, error, etc.)
            data: Event data dictionary
        """
        with self.lock:
            queues = self.connections.get(proposal_id, [])

            if not queues:
                print(f"[SSE] No clients connected for proposal #{proposal_id}")
                return

            print(f"[SSE] Broadcasting {event_type} to {len(queues)} client(s) for proposal #{proposal_id}")

            message = {
                "type": event_type,
                "proposal_id": proposal_id,
                "timestamp": datetime.now().isoformat(),
                **data,
            }

            # Send to all connected clients
            for message_queue in queues[:]:  # Copy list to avoid modification during iteration
                self._send_message(message_queue, message)

    def _send_message(self, message_queue: queue.Queue, message: Dict):
        """Send a message to a client queue"""
        try:
            message_queue.put_nowait(message)
        except queue.Full:
            print("[SSE] Warning: Client queue full, dropping message")

    def notify_workflow_started(self, proposal_id: int, workflow_id: str, commit_hash: str):
        """Notify that workflow has started"""
        self.broadcast_workflow_event(
            proposal_id,
            "workflow_started",
            {
                "workflow_id": workflow_id,
                "commit_hash": commit_hash,
                "message": f"Workflow started for commit {commit_hash[:8]}",
                "stage": "initialization",
            },
        )

    def notify_stage_started(
        self,
        proposal_id: int,
        workflow_id: str,
        stage_name: str,
        stage_description: str = None,
    ):
        """Notify that a workflow stage has started"""
        self.broadcast_workflow_event(
            proposal_id,
            "stage_started",
            {
                "workflow_id": workflow_id,
                "stage": stage_name,
                "description": stage_description or stage_name,
                "message": f"Starting: {stage_description or stage_name}",
            },
        )

    def notify_stage_progress(
        self,
        proposal_id: int,
        workflow_id: str,
        stage_name: str,
        progress: int,
        message: str = None,
    ):
        """Notify about progress within a stage"""
        self.broadcast_workflow_event(
            proposal_id,
            "stage_progress",
            {
                "workflow_id": workflow_id,
                "stage": stage_name,
                "progress": progress,  # 0-100
                "message": message,
            },
        )

    def notify_stage_complete(
        self,
        proposal_id: int,
        workflow_id: str,
        stage_name: str,
        success: bool = True,
        message: str = None,
    ):
        """Notify that a stage has completed"""
        self.broadcast_workflow_event(
            proposal_id,
            "stage_complete",
            {
                "workflow_id": workflow_id,
                "stage": stage_name,
                "success": success,
                "message": message or (f"{stage_name} completed" if success else f"{stage_name} failed"),
            },
        )

    def notify_workflow_complete(
        self,
        proposal_id: int,
        workflow_id: str,
        success: bool = True,
        message: str = None,
        metadata: Dict = None,
    ):
        """Notify that entire workflow has completed"""
        self.broadcast_workflow_event(
            proposal_id,
            "workflow_complete",
            {
                "workflow_id": workflow_id,
                "success": success,
                "message": message or ("Workflow completed successfully" if success else "Workflow failed"),
                "metadata": metadata or {},
            },
        )

    def notify_error(self, proposal_id: int, workflow_id: str, error_message: str, stage: str = None):
        """Notify about an error"""
        self.broadcast_workflow_event(
            proposal_id,
            "error",
            {
                "workflow_id": workflow_id,
                "stage": stage,
                "error": error_message,
                "message": f"Error: {error_message}",
            },
        )

    def notify_log_message(self, proposal_id: int, workflow_id: str, log_level: str, message: str):
        """Send a log message"""
        self.broadcast_workflow_event(
            proposal_id,
            "log",
            {
                "workflow_id": workflow_id,
                "level": log_level,  # info, warning, error, debug
                "message": message,
            },
        )

    def generate_sse_stream(self, message_queue: queue.Queue):
        """
        Generate SSE formatted messages from a queue

        This is a generator function for Flask SSE responses

        Yields:
            SSE formatted strings
        """
        try:
            while True:
                # Wait for message with timeout
                try:
                    message = message_queue.get(timeout=30)

                    # Format as SSE
                    if message:
                        sse_data = f"data: {json.dumps(message)}\n\n"
                        yield sse_data

                except queue.Empty:
                    # Send keepalive ping
                    keepalive = {
                        "type": "ping",
                        "timestamp": datetime.now().isoformat(),
                    }
                    yield f"data: {json.dumps(keepalive)}\n\n"

        except GeneratorExit:
            # Client disconnected
            print("[SSE] Client disconnected")


# Global SSE manager instance
_sse_manager = None


def get_sse_manager() -> WorkflowSSEManager:
    """Get or create the global SSE manager"""
    global _sse_manager

    if _sse_manager is None:
        _sse_manager = WorkflowSSEManager()

    return _sse_manager


# Convenience functions
def notify_workflow_event(proposal_id: int, event_type: str, **kwargs):
    """Notify about a workflow event"""
    manager = get_sse_manager()
    manager.broadcast_workflow_event(proposal_id, event_type, kwargs)
