"""Tests for core.event_bus — pure Python, no DB needed."""

import pytest

from core.event_bus import EventBus


@pytest.fixture
def bus():
    """Fresh EventBus instance for each test."""
    return EventBus()


# ---------------------------------------------------------------------------
# 1. Emit + consume: handler receives emitted data
# ---------------------------------------------------------------------------


def test_emit_calls_handler(bus):
    received = []

    @bus.on("contact.created")
    def handler(data):
        received.append(data)

    bus.emit("contact.created", {"name": "Jane"}, tenant_id=42)

    assert len(received) == 1
    assert received[0]["name"] == "Jane"
    assert received[0]["_event_type"] == "contact.created"
    assert received[0]["_tenant_id"] == 42


# ---------------------------------------------------------------------------
# 2. Multiple handlers for same event: all fire
# ---------------------------------------------------------------------------


def test_multiple_handlers_all_fire(bus):
    calls = []

    @bus.on("order.placed")
    def handler_a(data):
        calls.append("a")

    @bus.on("order.placed")
    def handler_b(data):
        calls.append("b")

    bus.emit("order.placed", {})

    assert calls == ["a", "b"]


# ---------------------------------------------------------------------------
# 3. No handler for event: doesn't raise
# ---------------------------------------------------------------------------


def test_no_handler_does_not_raise(bus):
    # Should complete silently with no handlers registered
    bus.emit("unknown.event", {"foo": "bar"})


# ---------------------------------------------------------------------------
# 4. Wildcard handler: receives all events (check _event_type field)
# ---------------------------------------------------------------------------


def test_wildcard_receives_all_events(bus):
    seen_types = []

    @bus.on("*")
    def catch_all(data):
        seen_types.append(data["_event_type"])

    bus.emit("contact.created", {})
    bus.emit("invoice.paid", {})
    bus.emit("order.placed", {})

    assert seen_types == ["contact.created", "invoice.paid", "order.placed"]


def test_wildcard_and_specific_both_fire(bus):
    calls = []

    @bus.on("contact.created")
    def specific(data):
        calls.append("specific")

    @bus.on("*")
    def wildcard(data):
        calls.append("wildcard")

    bus.emit("contact.created", {})

    assert "specific" in calls
    assert "wildcard" in calls
    assert len(calls) == 2


# ---------------------------------------------------------------------------
# 5. Handler exception: doesn't break other handlers
# ---------------------------------------------------------------------------


def test_bad_handler_does_not_break_others(bus):
    good_results = []

    @bus.on("contact.created")
    def bad_handler(data):
        raise RuntimeError("boom")

    @bus.on("contact.created")
    def good_handler(data):
        good_results.append(data["name"])

    # Should not raise despite bad_handler failing
    bus.emit("contact.created", {"name": "Alice"})

    assert good_results == ["Alice"]


# ---------------------------------------------------------------------------
# 6. clear(): removes all handlers
# ---------------------------------------------------------------------------


def test_clear_removes_all_handlers(bus):
    calls = []

    @bus.on("contact.created")
    def specific(data):
        calls.append("specific")

    @bus.on("*")
    def wildcard(data):
        calls.append("wildcard")

    bus.clear()
    bus.emit("contact.created", {})

    assert calls == []


def test_clear_clears_wildcard_handlers(bus):
    calls = []

    @bus.on("*")
    def wildcard(data):
        calls.append("wildcard")

    bus.clear()
    bus.emit("anything", {})

    assert calls == []


# ---------------------------------------------------------------------------
# Metadata enrichment
# ---------------------------------------------------------------------------


def test_emit_does_not_mutate_caller_dict(bus):
    """emit() should not modify the original data dict passed by the caller."""

    @bus.on("x")
    def noop(data):
        pass

    original = {"key": "value"}
    bus.emit("x", original)

    assert "_event_type" not in original
    assert "_tenant_id" not in original


def test_tenant_id_none_by_default(bus):
    received = []

    @bus.on("y")
    def handler(data):
        received.append(data)

    bus.emit("y", {})

    assert received[0]["_tenant_id"] is None
