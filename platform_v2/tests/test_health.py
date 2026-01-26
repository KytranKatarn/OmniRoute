"""
Smoke tests for ARCHIE platform health endpoints.
"""


def test_health_endpoint(client):
    """Health endpoint returns 200."""
    response = client.get("/health")
    assert response.status_code == 200


def test_app_exists(app):
    """Flask app initializes."""
    assert app is not None
    assert app.config["TESTING"] is True
