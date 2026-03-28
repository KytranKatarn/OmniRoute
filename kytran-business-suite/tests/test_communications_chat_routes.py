"""Tests for chat route logic -- start, message, poll, close.

These test the ChatManager (already tested) and route helper functions.
Full HTTP route tests require DB+auth, so we test logic at the unit level.
"""

from unittest.mock import MagicMock, patch

import pytest


def test_chat_manager_start_creates_conversation():
    """Verify ChatManager.start_conversation returns correct shape."""
    from core.chat_manager import ChatManager

    ctx = MagicMock()
    mock_cur = MagicMock()
    ctx.__enter__ = MagicMock(return_value=(MagicMock(), mock_cur))
    ctx.__exit__ = MagicMock(return_value=False)

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
        patch("core.chat_manager.event_bus"),
    ):
        mgr = ChatManager()
        conv = mgr.start_conversation(
            tenant_id=1, visitor_name="Jane", visitor_email="jane@test.com"
        )

    assert conv["id"] == 1
    assert conv["status"] == "active"
    assert conv["visitor_name"] == "Jane"


def test_chat_manager_add_message_returns_message():
    from core.chat_manager import ChatManager

    ctx = MagicMock()
    mock_cur = MagicMock()
    ctx.__enter__ = MagicMock(return_value=(MagicMock(), mock_cur))
    ctx.__exit__ = MagicMock(return_value=False)

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
        mgr = ChatManager()
        msg = mgr.add_message(
            tenant_id=1,
            conversation_id=1,
            sender_type="visitor",
            content="Hello!",
            sender_name="Jane",
        )

    assert msg["id"] == 10
    assert msg["content"] == "Hello!"


def test_chat_manager_rejects_message_to_closed():
    from core.chat_manager import ChatManager

    ctx = MagicMock()
    mock_cur = MagicMock()
    ctx.__enter__ = MagicMock(return_value=(MagicMock(), mock_cur))
    ctx.__exit__ = MagicMock(return_value=False)
    mock_cur.fetchone.return_value = {"id": 1, "status": "closed"}

    with (
        patch("core.chat_manager.get_db_cursor", return_value=ctx),
        patch("core.chat_manager.set_tenant_search_path"),
    ):
        mgr = ChatManager()
        with pytest.raises(ValueError, match="closed"):
            mgr.add_message(
                tenant_id=1,
                conversation_id=1,
                sender_type="visitor",
                content="Hi",
            )


def test_chat_manager_get_messages_returns_list():
    from core.chat_manager import ChatManager

    ctx = MagicMock()
    mock_cur = MagicMock()
    ctx.__enter__ = MagicMock(return_value=(MagicMock(), mock_cur))
    ctx.__exit__ = MagicMock(return_value=False)
    mock_cur.fetchall.return_value = [
        {
            "id": 1,
            "conversation_id": 1,
            "sender_type": "system",
            "sender_name": "System",
            "content": "Welcome!",
            "created_at": "2026-03-28T10:00:00",
        },
    ]

    with (
        patch("core.chat_manager.get_db_cursor", return_value=ctx),
        patch("core.chat_manager.set_tenant_search_path"),
    ):
        mgr = ChatManager()
        msgs = mgr.get_messages(tenant_id=1, conversation_id=1)

    assert len(msgs) == 1
    assert msgs[0]["sender_type"] == "system"


def test_chat_manager_close_emits_event():
    from core.chat_manager import ChatManager

    ctx = MagicMock()
    mock_cur = MagicMock()
    ctx.__enter__ = MagicMock(return_value=(MagicMock(), mock_cur))
    ctx.__exit__ = MagicMock(return_value=False)
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
        mgr = ChatManager()
        result = mgr.close_conversation(tenant_id=1, conversation_id=1)

    assert result["status"] == "closed"
    mock_bus.emit.assert_called_once()


def test_chat_routes_module_imports():
    """Verify chat_routes module can be imported without errors."""
    from plugins.kbs_communications.chat_routes import register_chat_routes

    assert callable(register_chat_routes)


def test_sms_routes_module_imports():
    """Verify sms_routes module can be imported without errors."""
    from plugins.kbs_communications.sms_routes import register_sms_routes

    assert callable(register_sms_routes)


def test_campaign_routes_module_imports():
    """Verify campaign_routes module can be imported without errors."""
    from plugins.kbs_communications.campaign_routes import register_campaign_routes

    assert callable(register_campaign_routes)
