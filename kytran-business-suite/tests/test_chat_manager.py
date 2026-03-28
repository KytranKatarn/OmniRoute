"""Tests for chat manager -- conversation lifecycle with mocked DB."""

from unittest.mock import MagicMock, call, patch

import pytest


@pytest.fixture
def mock_db():
    """Mock database context manager."""
    mock_cur = MagicMock()
    mock_conn = MagicMock()

    ctx = MagicMock()
    ctx.__enter__ = MagicMock(return_value=(mock_conn, mock_cur))
    ctx.__exit__ = MagicMock(return_value=False)

    return ctx, mock_conn, mock_cur


def test_start_conversation(mock_db):
    from core.chat_manager import ChatManager

    ctx, mock_conn, mock_cur = mock_db

    # First fetchone returns conversation, second is for system message INSERT
    mock_cur.fetchone.return_value = {
        "id": 1,
        "visitor_name": "Jane",
        "visitor_email": "jane@test.com",
        "customer_id": None,
        "status": "active",
        "channel": "widget",
        "created_at": "2026-03-28T10:00:00",
    }

    with (
        patch("core.chat_manager.get_db_cursor", return_value=ctx),
        patch("core.chat_manager.set_tenant_search_path"),
        patch("core.chat_manager.event_bus") as mock_bus,
    ):
        manager = ChatManager()
        conv = manager.start_conversation(
            tenant_id=1, visitor_name="Jane", visitor_email="jane@test.com"
        )

    assert conv["id"] == 1
    assert conv["status"] == "active"
    assert conv["visitor_name"] == "Jane"
    mock_bus.emit.assert_called_once()


def test_add_message(mock_db):
    from core.chat_manager import ChatManager

    ctx, mock_conn, mock_cur = mock_db

    # First call: conversation lookup, second: message insert
    mock_cur.fetchone.side_effect = [
        {"id": 1, "status": "active"},
        {
            "id": 10,
            "conversation_id": 1,
            "sender_type": "visitor",
            "sender_name": "Jane",
            "content": "Hello!",
            "created_at": "2026-03-28T10:01:00",
        },
    ]

    with (
        patch("core.chat_manager.get_db_cursor", return_value=ctx),
        patch("core.chat_manager.set_tenant_search_path"),
    ):
        manager = ChatManager()
        msg = manager.add_message(
            tenant_id=1,
            conversation_id=1,
            sender_type="visitor",
            content="Hello!",
            sender_name="Jane",
        )

    assert msg["id"] == 10
    assert msg["content"] == "Hello!"
    assert msg["sender_type"] == "visitor"


def test_add_message_closed_conversation(mock_db):
    from core.chat_manager import ChatManager

    ctx, mock_conn, mock_cur = mock_db
    mock_cur.fetchone.return_value = {"id": 1, "status": "closed"}

    with (
        patch("core.chat_manager.get_db_cursor", return_value=ctx),
        patch("core.chat_manager.set_tenant_search_path"),
    ):
        manager = ChatManager()
        with pytest.raises(ValueError, match="closed"):
            manager.add_message(
                tenant_id=1,
                conversation_id=1,
                sender_type="visitor",
                content="Hello!",
            )


def test_add_message_not_found(mock_db):
    from core.chat_manager import ChatManager

    ctx, mock_conn, mock_cur = mock_db
    mock_cur.fetchone.return_value = None

    with (
        patch("core.chat_manager.get_db_cursor", return_value=ctx),
        patch("core.chat_manager.set_tenant_search_path"),
    ):
        manager = ChatManager()
        with pytest.raises(ValueError, match="not found"):
            manager.add_message(
                tenant_id=1,
                conversation_id=999,
                sender_type="visitor",
                content="Hello!",
            )


def test_get_messages(mock_db):
    from core.chat_manager import ChatManager

    ctx, mock_conn, mock_cur = mock_db
    mock_cur.fetchall.return_value = [
        {
            "id": 1,
            "conversation_id": 1,
            "sender_type": "system",
            "sender_name": "System",
            "content": "Welcome!",
            "created_at": "2026-03-28T10:00:00",
        },
        {
            "id": 2,
            "conversation_id": 1,
            "sender_type": "visitor",
            "sender_name": "Jane",
            "content": "Hi!",
            "created_at": "2026-03-28T10:01:00",
        },
    ]

    with (
        patch("core.chat_manager.get_db_cursor", return_value=ctx),
        patch("core.chat_manager.set_tenant_search_path"),
    ):
        manager = ChatManager()
        messages = manager.get_messages(tenant_id=1, conversation_id=1)

    assert len(messages) == 2
    assert messages[0]["sender_type"] == "system"
    assert messages[1]["content"] == "Hi!"


def test_get_messages_since(mock_db):
    from core.chat_manager import ChatManager

    ctx, mock_conn, mock_cur = mock_db
    mock_cur.fetchall.return_value = [
        {
            "id": 3,
            "conversation_id": 1,
            "sender_type": "agent",
            "sender_name": "Support",
            "content": "How can I help?",
            "created_at": "2026-03-28T10:02:00",
        },
    ]

    with (
        patch("core.chat_manager.get_db_cursor", return_value=ctx),
        patch("core.chat_manager.set_tenant_search_path"),
    ):
        manager = ChatManager()
        messages = manager.get_messages(
            tenant_id=1, conversation_id=1, since="2026-03-28T10:01:00"
        )

    assert len(messages) == 1
    # Verify the query used the since parameter
    query_call = mock_cur.execute.call_args
    assert "created_at > %s" in str(query_call)


def test_close_conversation(mock_db):
    from core.chat_manager import ChatManager

    ctx, mock_conn, mock_cur = mock_db
    mock_cur.fetchone.return_value = {
        "id": 1,
        "status": "closed",
        "closed_at": "2026-03-28T11:00:00",
    }

    with (
        patch("core.chat_manager.get_db_cursor", return_value=ctx),
        patch("core.chat_manager.set_tenant_search_path"),
        patch("core.chat_manager.event_bus") as mock_bus,
    ):
        manager = ChatManager()
        result = manager.close_conversation(tenant_id=1, conversation_id=1)

    assert result["status"] == "closed"
    mock_bus.emit.assert_called_once()


def test_close_already_closed(mock_db):
    from core.chat_manager import ChatManager

    ctx, mock_conn, mock_cur = mock_db
    mock_cur.fetchone.return_value = None  # UPDATE returns nothing

    with (
        patch("core.chat_manager.get_db_cursor", return_value=ctx),
        patch("core.chat_manager.set_tenant_search_path"),
    ):
        manager = ChatManager()
        with pytest.raises(ValueError, match="not found or already closed"):
            manager.close_conversation(tenant_id=1, conversation_id=1)


def test_get_active_conversations(mock_db):
    from core.chat_manager import ChatManager

    ctx, mock_conn, mock_cur = mock_db
    mock_cur.fetchall.return_value = [
        {
            "id": 1,
            "visitor_name": "Jane",
            "visitor_email": None,
            "customer_id": None,
            "status": "active",
            "created_at": "2026-03-28T10:00:00",
            "last_message": "Hello!",
            "message_count": 3,
        },
    ]

    with (
        patch("core.chat_manager.get_db_cursor", return_value=ctx),
        patch("core.chat_manager.set_tenant_search_path"),
    ):
        manager = ChatManager()
        convs = manager.get_active_conversations(tenant_id=1)

    assert len(convs) == 1
    assert convs[0]["visitor_name"] == "Jane"
    assert convs[0]["message_count"] == 3
