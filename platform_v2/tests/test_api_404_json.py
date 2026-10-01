"""An unknown /api/* path must answer JSON, not an HTML redirect.

Found while wiring V.I.G.I.L.'s heartbeat through archie_mcp_gateway: the gateway
proxies GET /api/internal/infra/heartbeat to the hub, and a caller that mistypes a
path got `302 -> /dashboard` with an HTML body. The gateway's JSON parse then died on
the first byte and surfaced `JSONDecodeError` — so a typo in a URL path was
indistinguishable from the hub being down. The real 404 was never visible.

(500) and the generic Exception handler both branch on request.path.startswith("/api/");
errorhandler(404) did not, so it was the only API-shaped failure that answered HTML.

Runs in-container (needs /app/app.py):
    docker exec -i archie_platform python3 -m pytest tests/test_api_404_json.py -q
"""

import json

ALLOWED_HOST = "localhost"  # keeps the AdGuard block-page branch out of the way


def test_unknown_api_path_is_json_404_not_html_redirect(client):
    """The whole point: a machine caller gets a parseable, honest miss."""
    resp = client.get("/api/internal/no_such_endpoint_xyz", headers={"Host": ALLOWED_HOST})

    assert resp.status_code == 404
    assert resp.mimetype == "application/json", "a 404 on /api/ answered non-JSON"
    body = json.loads(resp.data)
    assert body["error"] == "not_found"
    assert body["path"] == "/api/internal/no_such_endpoint_xyz"


def test_unknown_api_path_is_json_even_under_tools_prefix(client):
    """The bug was not scoped to /api/internal — every /api/* shape was affected."""
    resp = client.get("/api/no_such_module/thing", headers={"Host": ALLOWED_HOST})

    assert resp.status_code == 404
    assert json.loads(resp.data)["error"] == "not_found"


def test_unknown_browser_page_still_redirects(client):
    """Humans keep the flash-and-send-them-to-dashboard behaviour."""
    resp = client.get("/definitely-not-a-page", headers={"Host": ALLOWED_HOST})

    assert resp.status_code == 302, "a browser 404 stopped redirecting"
    assert resp.headers["Location"].endswith("/dashboard")


def test_blocked_host_still_gets_the_adguard_page_even_on_api(client):
    """Ordering guard.

    The AdGuard branch must keep winning for a blocked domain, or a typo from a
    blocked network silently becomes a 200 block page instead of a 404. This is the
    reason the JSON check sits *after* the host check and not before it.
    """
    resp = client.get("/api/no_such_module/thing", headers={"Host": "ads.example.invalid"})

    assert resp.status_code == 200
    assert b"block" in resp.data.lower()
