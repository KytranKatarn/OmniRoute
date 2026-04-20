"""Unit tests for services.ollama_availability.is_model_available."""

from __future__ import annotations

import pytest
from unittest import mock


@pytest.fixture(autouse=True)
def _path():
    import sys

    if "/app" not in sys.path:
        sys.path.insert(0, "/app")


def test_is_model_available_true_when_present():
    from services.ollama_availability import is_model_available

    fake_response = mock.Mock(
        status_code=200,
        json=lambda: {"models": [{"name": "mistral:7b"}, {"name": "llama3:8b"}]},
    )
    with mock.patch("services.ollama_availability.requests.get", return_value=fake_response):
        ok, msg = is_model_available("mistral:7b")
    assert ok is True


def test_is_model_available_false_when_missing():
    from services.ollama_availability import is_model_available

    fake_response = mock.Mock(
        status_code=200,
        json=lambda: {"models": [{"name": "llama3:8b"}]},
    )
    with mock.patch("services.ollama_availability.requests.get", return_value=fake_response):
        ok, msg = is_model_available("mistral:7b")
    assert ok is False
    assert "mistral:7b" in msg


def test_is_model_available_false_on_timeout():
    from services.ollama_availability import is_model_available
    import requests

    with mock.patch(
        "services.ollama_availability.requests.get",
        side_effect=requests.Timeout("timed out"),
    ):
        ok, msg = is_model_available("anything:1b")
    assert ok is False
    assert "timeout" in msg.lower() or "unreachable" in msg.lower()


def test_is_model_available_false_on_connection_error():
    from services.ollama_availability import is_model_available
    import requests

    with mock.patch(
        "services.ollama_availability.requests.get",
        side_effect=requests.ConnectionError("boom"),
    ):
        ok, msg = is_model_available("anything:1b")
    assert ok is False


def test_cloud_suffix_skips_local_probe():
    """Cloud models always return ok without HTTP."""
    from services.ollama_availability import is_model_available

    with mock.patch("services.ollama_availability.requests.get") as m:
        ok, msg = is_model_available("gpt-4o:cloud")
    assert ok is True
    assert m.called is False
