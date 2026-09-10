"""archie_comms must send the Claude-proxy shared secret on every proxy POST.

`scripts/claude_proxy.py` now gates POST on `X-Claude-Proxy-Token` (matched against
CLAUDE_PROXY_TOKEN with hmac.compare_digest) because a POST there runs
`claude -p --dangerously-skip-permissions` as the host user. A caller that does not send
the header gets a 401 and Claude collaboration silently stops working, so this is pinned
here as well as on the proxy side.

Functional, not a grep: `_send_via_proxy` is driven with a fake `urlopen` and the real
`urllib.request.Request` it built is inspected.
"""

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from collaboration import claude_bridge  # noqa: E402

TOKEN = "comms-proxy-token-for-tests"


class _FakeResponse:
    def __init__(self, payload):
        self._payload = json.dumps(payload).encode()

    def read(self):
        return self._payload


def _capture_request(monkeypatch):
    """Patch urlopen so the built Request is captured and no socket is opened."""
    captured = {}

    def _fake_urlopen(req, timeout=None):
        captured["request"] = req
        return _FakeResponse({"success": True, "response": "hi"})

    monkeypatch.setattr(claude_bridge, "urlopen", _fake_urlopen)
    return captured


def test_proxy_post_carries_the_token_header(monkeypatch):
    monkeypatch.setenv("CLAUDE_PROXY_TOKEN", TOKEN)
    captured = _capture_request(monkeypatch)

    bridge = claude_bridge.ClaudeBridge()
    result = bridge._send_via_proxy("hello", "sys")

    assert result == "hi"
    req = captured["request"]
    # urllib capitalises header names, so ask it rather than indexing the dict.
    assert req.get_header("X-claude-proxy-token") == TOKEN
    assert req.get_header("Content-type") == "application/json"


def test_token_is_read_at_call_time_not_import_time(monkeypatch):
    """A rotated secret must take effect on restart without a code change."""
    monkeypatch.setenv("CLAUDE_PROXY_TOKEN", "first-value")
    assert claude_bridge._proxy_headers()["X-Claude-Proxy-Token"] == "first-value"

    monkeypatch.setenv("CLAUDE_PROXY_TOKEN", "second-value")
    assert claude_bridge._proxy_headers()["X-Claude-Proxy-Token"] == "second-value"


def test_no_header_when_the_token_is_unconfigured(monkeypatch):
    """Sending an empty token would be meaningless — the proxy refuses either way."""
    monkeypatch.delenv("CLAUDE_PROXY_TOKEN", raising=False)
    headers = claude_bridge._proxy_headers()
    assert "X-Claude-Proxy-Token" not in headers
    assert headers["Content-Type"] == "application/json"


def test_health_check_get_sends_no_token(monkeypatch):
    """GET is deliberately open on the proxy; the probe must not depend on the secret."""
    monkeypatch.setenv("CLAUDE_PROXY_TOKEN", TOKEN)
    monkeypatch.setattr(claude_bridge, "ANTHROPIC_API_KEY", "")
    captured = _capture_request(monkeypatch)

    def _fake_urlopen(req, timeout=None):
        captured["request"] = req
        return _FakeResponse({"status": "ok"})

    monkeypatch.setattr(claude_bridge, "urlopen", _fake_urlopen)

    result = claude_bridge.ClaudeBridge().health_check()

    assert result["status"] == "healthy"
    assert captured["request"].get_method() == "GET"
    assert captured["request"].get_header("X-claude-proxy-token") is None
