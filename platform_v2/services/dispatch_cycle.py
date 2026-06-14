"""Pure decision logic for scheduled jobs that dispatch ONE capability and must
tolerate the cold-model QUEUE path (``DispatchResult.queued``).

A cold model does not run inline — ``dispatch()`` returns
``DispatchResult(success=False, queued=True, queue_id=N)`` and the
``model_dispatch_worker`` finishes the task moments later, writing the result
back onto the ``dispatch_pending_queue`` row. The naive ``success else failed``
check therefore records a FALSE failure for a task that is actually in progress
(KB: ``feedback_never-bypass-dhq-for-warmup`` — "queue returning not-ready =
queue working, not a failure").

``classify_dispatch_cycle`` maps a dispatch result (plus the final
``dispatch_pending_queue`` row, when the caller polled it to a terminal state)
to an :class:`CycleOutcome` for ``AgentLoop._log_cycle``. It also surfaces the
real failure reason instead of swallowing it (previously ``error_message`` was
left NULL — #4151).

PURE — no DB, no I/O. The polling that produces ``queue_final`` lives in the
caller (``AgentLoop._poll_pending_queue``).
"""

from typing import Any, Optional

# dispatch_pending_queue terminal statuses (see services/model_dispatch_service.py).
QUEUE_DONE = "done"
QUEUE_FAILURE_STATES = ("failed", "expired")
QUEUE_TERMINAL_STATES = (QUEUE_DONE,) + QUEUE_FAILURE_STATES


class CycleOutcome:
    """The four values ``AgentLoop._log_cycle`` needs for one dispatch cycle."""

    __slots__ = ("items_processed", "items_failed", "error_message", "response")

    def __init__(self, items_processed, items_failed, error_message, response):
        self.items_processed = items_processed
        self.items_failed = items_failed
        self.error_message = error_message
        self.response = response

    def as_tuple(self):
        return (self.items_processed, self.items_failed, self.error_message, self.response)

    def __eq__(self, other):
        return isinstance(other, CycleOutcome) and self.as_tuple() == other.as_tuple()

    def __repr__(self):
        return (
            f"CycleOutcome(processed={self.items_processed}, failed={self.items_failed}, "
            f"error={self.error_message!r}, response={self.response!r})"
        )


def _trim(text, limit=500):
    if not text:
        return ""
    return str(text)[:limit]


def classify_dispatch_cycle(result: Any, queue_final: Optional[dict] = None) -> CycleOutcome:
    """Map a ``DispatchResult`` (+ optional terminal queue row) to a CycleOutcome.

    Args:
        result: the ``DispatchResult`` from ``dispatch()`` (``None`` is tolerated
            and treated as an immediate failure).
        queue_final: dict-like with keys ``status`` / ``result_response`` /
            ``error`` — the terminal ``dispatch_pending_queue`` row when a queued
            task was polled to completion; ``None`` when the task was queued but
            still non-terminal at the caller's poll timeout (treated as
            in-progress, NOT a failure).
    """
    # 1. Synchronous completion — a warm model executed inline.
    if getattr(result, "success", False):
        return CycleOutcome(1, 0, None, _trim(getattr(result, "response", "")))

    # 2. Queued — a cold model was deferred to dispatch_pending_queue.
    if getattr(result, "queued", False):
        queue_id = getattr(result, "queue_id", None)
        if queue_final is None:
            # Still queued/running at the poll timeout — the worker will finish
            # it. Not a failure: the job kicked off and handed work to the queue.
            return CycleOutcome(
                1,
                0,
                None,
                f"queued (id={queue_id}) — handed to dispatch_pending_queue, still in progress at poll timeout",
            )
        status = (queue_final.get("status") or "").lower()
        if status == QUEUE_DONE:
            return CycleOutcome(1, 0, None, _trim(queue_final.get("result_response")))
        if status in QUEUE_FAILURE_STATES:
            reason = queue_final.get("error") or status
            return CycleOutcome(0, 1, _trim(f"queued task {status}: {reason}"), None)
        # A non-terminal status was handed in (caller contract violation) — treat
        # as in-progress rather than inventing a failure.
        return CycleOutcome(1, 0, None, f"queued (id={queue_id}) — non-terminal status {status!r}")

    # 3. Immediate, non-queued failure — no skilled agent, welfare block, or a
    #    dispatch-layer error. Surface the reason (no longer swallowed → NULL).
    err = getattr(result, "error", None) or "dispatch returned success=False"
    return CycleOutcome(0, 1, _trim(err), None)
