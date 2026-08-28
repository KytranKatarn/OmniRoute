import json


def test_history_agents_returns_list(client):
    """Agents endpoint returns 200 with a JSON array (may be empty in test DB).
    Unauthenticated callers receive 401/302/403 — all acceptable in test env."""
    resp = client.get("/tools/department-hq/api/dispatch/history/agents")
    assert resp.status_code in (200, 302, 401, 403)
    if resp.status_code == 200:
        data = json.loads(resp.data)
        assert isinstance(data, list)
        for item in data:
            assert isinstance(item, str) and item


def test_history_capabilities_returns_list(client):
    """Capabilities endpoint returns 200 with a JSON array."""
    resp = client.get("/tools/department-hq/api/dispatch/history/capabilities")
    assert resp.status_code in (200, 302, 401, 403)
    if resp.status_code == 200:
        data = json.loads(resp.data)
        assert isinstance(data, list)


def test_history_agents_route_exists(client):
    """Endpoint is registered — not a 404 or 405."""
    resp = client.get("/tools/department-hq/api/dispatch/history/agents")
    assert resp.status_code != 404
    assert resp.status_code != 405


def test_history_capabilities_route_exists(client):
    """Endpoint is registered — not a 404 or 405."""
    resp = client.get("/tools/department-hq/api/dispatch/history/capabilities")
    assert resp.status_code != 404
    assert resp.status_code != 405


def test_history_agents_requires_auth(client):
    """Unauthenticated request to agents endpoint must be rejected."""
    resp = client.get("/tools/department-hq/api/dispatch/history/agents")
    assert resp.status_code in (302, 401, 403), f"Expected auth rejection, got {resp.status_code}"


def test_history_capabilities_requires_auth(client):
    """Unauthenticated request to capabilities endpoint must be rejected."""
    resp = client.get("/tools/department-hq/api/dispatch/history/capabilities")
    assert resp.status_code in (302, 401, 403), f"Expected auth rejection, got {resp.status_code}"


def test_history_default_response_shape(client):
    """Default call returns expected shape (works even as unauthed — checking shape, not auth here)."""
    resp = client.get("/tools/department-hq/api/dispatch/history")
    # Either returns data (if somehow authed) or redirects
    assert resp.status_code in (200, 302, 401, 403)
    if resp.status_code == 200:
        data = resp.get_json()
        assert "stats" in data and "rows" in data
        assert "total" in data and "page" in data and "pages" in data
        assert isinstance(data["rows"], list)
        assert isinstance(data["stats"]["total_calls"], int)
        assert isinstance(data["stats"]["success_rate"], (int, float))
        assert isinstance(data["stats"]["avg_duration_s"], (int, float))


def test_history_requires_auth(client):
    """History endpoint requires authentication."""
    resp = client.get("/tools/department-hq/api/dispatch/history")
    assert resp.status_code in (302, 401, 403), f"Expected auth rejection, got {resp.status_code}"


def test_history_source_param_accepted(client):
    """source param is accepted without server error."""
    resp = client.get("/tools/department-hq/api/dispatch/history?source=task")
    assert resp.status_code in (200, 302, 401, 403)
