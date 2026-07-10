"""Chronicle rename (Slice 01/09, 2026-07-10) — mailbox_story -> Chronicle.

Verifies: the new /tools/chronicle prefix is live, the old /tools/mailbox-story
path 307-redirects to it (preserving method/body), and the module_registry
entry is rebranded while keeping id="mailbox_story" (blueprint_import/health
tracking unchanged) per docs/superpowers/plans/2026-07-10-chronicle-implementation-plan.md.

Uses the `client` fixture from conftest.py (loads app.py via importlib to avoid
the /app/__init__.py package-shadowing trap — see conftest.py:_load_flask_app).
"""


def test_new_chronicle_route_serves(client):
    # status endpoint is unauthenticated (module registry health-pings it);
    # route existing is what matters here — must not 404.
    r = client.get("/tools/chronicle/api/status")
    assert r.status_code != 404, "new /tools/chronicle prefix must be registered"


def test_old_mailbox_story_path_redirects(client):
    r = client.get("/tools/mailbox-story/api/status", follow_redirects=False)
    assert r.status_code in (307, 308), f"old path must 307-redirect, got {r.status_code}"
    assert "/tools/chronicle/api/status" in r.headers.get("Location", "")


def test_registry_rebranded():
    from module_registry import MODULES

    m = next(x for x in MODULES if getattr(x, "id", None) == "mailbox_story")
    assert m.name == "Chronicle"
    assert m.route == "/tools/chronicle"
