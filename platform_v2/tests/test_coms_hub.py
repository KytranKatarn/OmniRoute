"""COMs/Telegram hub read layer — platform side (Slice 2 of the COO command surface).

Read-only view of the DHQ COMs feed (telegram_message_log) + config + migration, surfaced
in the cockpit COMs tab.
"""

import contextlib


def test_list_messages_builds_filtered_query(monkeypatch):
    import services.coms_hub_service as svc

    seen = {}

    class _Cur:
        def execute(self, q, params=None):
            seen["q"] = q
            seen["params"] = params

        def fetchall(self):
            return [
                {
                    "id": 1,
                    "category": "system",
                    "message": "hi",
                    "source_agent": "V.I.G.I.L.",
                    "status": "sent",
                    "created_at": "2026-07-12",
                }
            ]

    @contextlib.contextmanager
    def _fake_cursor(commit=False):
        yield (None, _Cur())

    monkeypatch.setattr(svc, "_get_cursor", lambda: _fake_cursor)
    rows = svc.list_messages(limit=10, category="system", source_agent="V.I.G.I.L.")
    assert rows[0]["source_agent"] == "V.I.G.I.L."
    assert "telegram_message_log" in seen["q"] and "category = %s" in seen["q"] and "source_agent = %s" in seen["q"]
    assert seen["params"][-1] == 10  # LIMIT is last


def test_config_summary_shape(monkeypatch):
    import services.coms_hub_service as svc

    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "abc123")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "999")
    c = svc.config_summary()
    assert c["bot_token_set"] is True and c["chat_id"] == "999" and isinstance(c["categories"], dict)


def test_config_summary_no_token(monkeypatch):
    import services.coms_hub_service as svc

    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    assert svc.config_summary()["bot_token_set"] is False


def test_overview_combines(monkeypatch):
    import services.coms_hub_service as svc

    monkeypatch.setattr(svc, "list_messages", lambda **k: [{"id": 1}])
    monkeypatch.setattr(svc, "config_summary", lambda: {"bot_token_set": True})
    monkeypatch.setattr(svc, "migration_summary", lambda: {"progress": {"percentage": 50}})
    o = svc.overview()
    assert o["messages"] == [{"id": 1}]
    assert o["config"]["bot_token_set"] and o["migration"]["progress"]["percentage"] == 50


def test_coms_overview_requires_key(client):
    r = client.get("/api/internal/coms/overview")
    assert r.status_code == 401


def test_coms_overview_ok(client, monkeypatch):
    monkeypatch.setenv("INTERNAL_API_KEY", "k")
    import services.coms_hub_service as svc

    monkeypatch.setattr(
        svc,
        "overview",
        lambda **k: {
            "messages": [{"id": 1, "message": "hi"}],
            "config": {"bot_token_set": True},
            "migration": {"progress": {"percentage": 42}},
        },
    )
    r = client.get("/api/internal/coms/overview?limit=5&category=system", headers={"Authorization": "Bearer k"})
    assert r.status_code == 200
    b = r.get_json()
    assert b["success"] and b["messages"][0]["id"] == 1 and b["migration"]["progress"]["percentage"] == 42
