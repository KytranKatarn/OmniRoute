"""Unwired supervisor-side publisher adapter; not a runner or command executor.

The host must supply an exclusive trusted transport and independent assignment
context. This adapter neither provisions that boundary nor certifies completion.
It never auto-acknowledges a response: even success stays pending for independent
reconciliation. Nothing imports this module in production.
"""

from types import MappingProxyType

from .publication_fence import PublicationBlocked


class PublicationPublisher:
    def __init__(self, fence, assignment, *, expected, transport):
        self.fence = fence
        self.assignment = assignment
        self.expected = dict(expected)
        self.transport = transport

    def publish(self, operation_id, *, operation):
        if self.fence.inspect(self.assignment, expected=self.expected) is None:
            raise PublicationBlocked("assignment_context_unavailable")
        # begin COMMITs before the transport can issue any external operation.
        # Stop wins => begin raises and the transport is never called.
        # Begin wins => the operation remains pending through stop/crash/timeout.
        self.fence.begin(self.assignment, operation_id, operation=operation)
        return self.transport(
            assignment_id=self.assignment,
            operation_id=operation_id,
            operation=operation,
            context=MappingProxyType(self.expected),
        )
