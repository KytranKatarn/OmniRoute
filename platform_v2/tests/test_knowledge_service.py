"""The route adapter keeps the established KB validation and privacy writer."""

from types import SimpleNamespace
import sys
import pytest
from services.knowledge_service import store_knowledge


def test_adapter_maps_arguments_and_returns_stored_id(monkeypatch):
    calls = []

    async def store(args):
        calls.append(args)
        return {"success": True, "memory_id": 12}

    monkeypatch.setitem(sys.modules, "mcp_server.tools.knowledge", SimpleNamespace(store_memory_handler=store))
    assert store_knowledge("title", "content", "vault_note", "style", ["denied"], 0.9) == 12
    assert calls == [
        {
            "title": "title",
            "content": "content",
            "knowledge_type": "vault_note",
            "category": "style",
            "tags": ["denied"],
            "importance": 0.9,
        }
    ]


def test_adapter_never_reports_a_failed_write_as_success(monkeypatch):
    async def store(args):
        return {"success": False, "error": "privacy rejection"}

    monkeypatch.setitem(sys.modules, "mcp_server.tools.knowledge", SimpleNamespace(store_memory_handler=store))
    with pytest.raises(RuntimeError, match="privacy rejection"):
        store_knowledge("title", "content")
