"""COO consult — cockpit proxy (Slice 1). Server-side proxy to the platform consult
endpoints; the INTERNAL_API_KEY never reaches the browser. Fail-soft everywhere."""
import services.coo_consult as cc


def test_consult_posts_target_and_prompt(monkeypatch):
    seen = {}

    class _R:
        status_code = 200

        def json(self):
            return {
                "success": True,
                "response": "clean",
                "agent_name": "V.I.G.I.L.",
                "model_used": "qwen2.5:7b",
                "resolved_target": "V.I.G.I.L.",
            }

    import requests as rq

    monkeypatch.setattr(
        rq, "post", lambda url, json=None, headers=None, timeout=None: seen.update(json=json, url=url) or _R()
    )
    monkeypatch.setenv("INTERNAL_API_KEY", "k")
    out = cc.consult("V.I.G.I.L.", "firewall?", 4)
    assert out["agent_name"] == "V.I.G.I.L."
    assert seen["json"]["target"] == "V.I.G.I.L." and seen["json"]["prompt"] == "firewall?"
    assert seen["url"].endswith("/api/internal/coo/consult")


def test_consult_none_on_failure(monkeypatch):
    import requests as rq

    def boom(*a, **k):
        raise RuntimeError("down")

    monkeypatch.setattr(rq, "post", boom)
    monkeypatch.setenv("INTERNAL_API_KEY", "k")
    assert cc.consult("V.I.G.I.L.", "q", 4) is None


def test_list_agents_failsoft(monkeypatch):
    import requests as rq

    def boom(*a, **k):
        raise RuntimeError("down")

    monkeypatch.setattr(rq, "get", boom)
    monkeypatch.setenv("INTERNAL_API_KEY", "k")
    assert cc.list_agents() == {"agents": [], "departments": []}
