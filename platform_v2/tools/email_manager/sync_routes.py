"""Email HQ sync routes — SSE stream for real-time new-mail push (T3279)."""

from __future__ import annotations

import logging

from flask import Response, stream_with_context
from flask_login import current_user

from .access_control import get_visible_mailbox_ids
from .sse_manager import get_sse_manager

logger = logging.getLogger(__name__)


def register_sync_routes(bp, access_required) -> None:
    @bp.route("/api/email/stream")
    @access_required
    def email_sse_stream():
        """SSE endpoint — browser holds one long-lived connection per tab.

        Polls email_push_events (written by IMAP IDLE workers in archie_scheduler)
        every 3 s and emits SSE events.  A ``: heartbeat`` comment is sent every
        30 s to keep the connection alive through proxies.

        Admins receive events for all mailboxes; COLLABORATOR accounts receive
        only events for their department-scoped mailboxes.
        """
        visible = get_visible_mailbox_ids(current_user)
        mgr = get_sse_manager()

        def generate():
            yield ": connected\n\n"
            yield from mgr.generate_stream(mailbox_ids=visible)

        return Response(
            stream_with_context(generate()),
            mimetype="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
                "Connection": "keep-alive",
            },
        )
