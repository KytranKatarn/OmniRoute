"""COMs hub — cockpit proxy (Slice 2). Server-side proxy to the platform COMs read
endpoint; the INTERNAL_API_KEY never reaches the browser. Read-only, fail-soft."""
import services.coms_hub as ch


def test_overview_proxies_with_filters(monkeypatch):
    seen = {}

    class _R:
        status_code = 200

        def json(self):
            return {
                "success": True,
                "messages": [{"id": 1}],
                "config": {"bot_token_set": True},
                "migration": {"progress": {"percentage": 10}},
            }

    import requests as rq

    monkeypatch.setattr(
        rq, "get", lambda url, headers=None, params=None, timeout=None: seen.update(url=url, params=params) or _R()
    )
    monkeypatch.setenv("INTERNAL_API_KEY", "k")
    out = ch.overview(limit=5, category="system")
    assert out["messages"][0]["id"] == 1
    assert seen["url"].endswith("/api/internal/coms/overview")
    assert seen["params"]["limit"] == 5 and seen["params"]["category"] == "system"


def test_overview_failsoft(monkeypatch):
    import requests as rq

    def boom(*a, **k):
        raise RuntimeError("down")

    monkeypatch.setattr(rq, "get", boom)
    monkeypatch.setenv("INTERNAL_API_KEY", "k")
    assert ch.overview() == {"messages": [], "config": {}, "migration": {}}
