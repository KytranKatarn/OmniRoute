"""#5317 / ADR-019 phase 2 — llama.cpp as a kill-switched second local provider.

The spike (#5316) proved llama-server on hub CPU: ~2s cold start, 24.2 tok/s
single-stream, x3.73 4-way concurrency scaling, 330MB RAM, OpenAI surface
unmodified. This pilot routes selected (capability, model) pairs through it
from the ONE hub execution chokepoint (_execute_llm), behind platform_settings
that default OFF, with unconditional fallback to Ollama on any failure.

Contract pinned here:
  * should_route() is OFF unless llamacpp:enabled='true' AND the capability is
    in the llamacpp:capabilities allowlist AND the model is served — an empty
    capability allowlist routes NOTHING even when enabled (no accidental
    fleet-wide flip);
  * json_mode is never routed (the pilot covers the plain-text path only);
  * chat() returns the exact call_ollama result shape with provider='llamacpp'
    and node_id=None — node_id MUST stay None or the dispatcher's starship
    provider-tagger would rewrite provider and destroy the telemetry split;
  * options.num_predict maps to max_tokens.
"""

import os
import sys
from unittest.mock import MagicMock

_TREE_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _TREE_ROOT not in sys.path:
    sys.path.insert(0, _TREE_ROOT)

from ai_bridge import llamacpp_client as lc  # noqa: E402


def _settings(monkeypatch, mapping):
    monkeypatch.setattr(lc, "_setting", lambda key, default="": mapping.get(key, default))


class TestShouldRoute:
    def test_off_by_default(self, monkeypatch):
        _settings(monkeypatch, {})
        assert lc.should_route("classify", "qwen2.5:1.5b") is False

    def test_enabled_capability_and_model_match(self, monkeypatch):
        _settings(
            monkeypatch,
            {"llamacpp:enabled": "true", "llamacpp:capabilities": "classify", "llamacpp:models": "qwen2.5:1.5b"},
        )
        assert lc.should_route("classify", "qwen2.5:1.5b") is True

    def test_empty_capability_allowlist_routes_nothing(self, monkeypatch):
        """enabled=true with no capabilities must NOT become a fleet-wide flip."""
        _settings(monkeypatch, {"llamacpp:enabled": "true", "llamacpp:models": "qwen2.5:1.5b"})
        assert lc.should_route("classify", "qwen2.5:1.5b") is False

    def test_unlisted_capability_or_model_not_routed(self, monkeypatch):
        _settings(
            monkeypatch,
            {"llamacpp:enabled": "true", "llamacpp:capabilities": "classify", "llamacpp:models": "qwen2.5:1.5b"},
        )
        assert lc.should_route("research", "qwen2.5:1.5b") is False
        assert lc.should_route("classify", "qwen2.5:7b") is False

    def test_json_mode_never_routed(self, monkeypatch):
        _settings(
            monkeypatch,
            {"llamacpp:enabled": "true", "llamacpp:capabilities": "classify", "llamacpp:models": "qwen2.5:1.5b"},
        )
        assert lc.should_route("classify", "qwen2.5:1.5b", json_mode=True) is False

    def test_settings_error_fails_closed(self, monkeypatch):
        def _boom(key, default=""):
            raise RuntimeError("db down")

        monkeypatch.setattr(lc, "_setting", _boom)
        assert lc.should_route("classify", "qwen2.5:1.5b") is False


class TestChatShape:
    def _stub_post(self, monkeypatch, body):
        captured = {}

        def _post(url, json=None, timeout=None):
            captured["url"] = url
            captured["payload"] = json
            resp = MagicMock()
            resp.json.return_value = body
            resp.raise_for_status.return_value = None
            return resp

        monkeypatch.setattr(lc.requests, "post", _post)
        return captured

    def test_result_matches_call_ollama_contract(self, monkeypatch):
        captured = self._stub_post(
            monkeypatch,
            {
                "choices": [{"message": {"content": "hello"}}],
                "usage": {"prompt_tokens": 12, "completion_tokens": 34},
            },
        )
        out = lc.chat("hi", model="qwen2.5:1.5b", system_prompt="sys", options={"num_predict": 99})
        assert out["success"] is True
        assert out["response"] == "hello"
        assert out["provider"] == "llamacpp"
        assert out["node_id"] is None  # keeps the starship tagger away from provider
        assert out["prompt_tokens"] == 12 and out["completion_tokens"] == 34
        assert captured["url"].endswith("/v1/chat/completions")
        assert captured["payload"]["max_tokens"] == 99
        assert captured["payload"]["messages"][0] == {"role": "system", "content": "sys"}
