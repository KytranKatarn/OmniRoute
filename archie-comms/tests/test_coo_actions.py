"""Tools & Actions — cockpit proxy (Slice 4). Server-side proxy to the platform action
endpoints; the INTERNAL_API_KEY never reaches the browser. Curated safe actions, fail-soft."""
import services.coo_actions as ca


def test_run_posts_key(monkeypatch):
    seen = {}

    class _R:
        status_code = 200

        def json(self):
            return {"ok": True, "label": "Platform health", "summary": "green"}

    import requests as rq

    monkeypatch.setattr(
        rq, "post", lambda url, json=None, headers=None, timeout=None: seen.update(url=url, json=json) or _R()
    )
    monkeypatch.setenv("INTERNAL_API_KEY", "k")
    out = ca.run("health")
    assert out["ok"] and seen["json"]["key"] == "health" and seen["url"].endswith("/api/internal/actions/run")


def test_catalog_failsoft(monkeypatch):
    import requests as rq

    def boom(*a, **k):
        raise RuntimeError("down")

    monkeypatch.setattr(rq, "get", boom)
    monkeypatch.setenv("INTERNAL_API_KEY", "k")
    assert ca.catalog() == {"actions": []}
