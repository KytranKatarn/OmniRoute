"""In-process pub/sub event bus for inter-plugin communication."""

import logging
from collections import defaultdict

logger = logging.getLogger(__name__)


class EventBus:
    """In-process pub/sub event bus for inter-plugin communication.

    Usage:
        bus = EventBus()

        @bus.on("contact.created")
        def handle_contact(data):
            print(data["name"])

        bus.emit("contact.created", {"name": "Jane"}, tenant_id=1)
    """

    def __init__(self):
        self._handlers = defaultdict(list)
        self._wildcard_handlers = []

    def on(self, event_type: str):
        """Decorator to register a handler for an event type.

        Use ``"*"`` to register a wildcard handler that receives all events.
        """

        def decorator(fn):
            if event_type == "*":
                self._wildcard_handlers.append(fn)
            else:
                self._handlers[event_type].append(fn)
            return fn

        return decorator

    def emit(self, event_type: str, data: dict, tenant_id=None) -> None:
        """Emit an event to all registered handlers.

        Enriches *data* in-place with ``_event_type`` and ``_tenant_id``.
        Handler exceptions are caught and logged so one bad handler never
        prevents others from receiving the event.
        """
        data = dict(data)  # copy — don't mutate caller's dict
        data["_event_type"] = event_type
        data["_tenant_id"] = tenant_id

        handlers = list(self._handlers.get(event_type, [])) + list(self._wildcard_handlers)

        for handler in handlers:
            try:
                handler(data)
            except Exception:
                logger.exception(
                    "Event handler %s raised an exception for event %r",
                    getattr(handler, "__name__", repr(handler)),
                    event_type,
                )

    def clear(self) -> None:
        """Remove all registered handlers (useful for test isolation)."""
        self._handlers.clear()
        self._wildcard_handlers.clear()


# Module-level singleton
event_bus = EventBus()
