"""Tests for services.creed_emit per-product tenant routing (#3958)."""

import sys
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services import creed_emit  # noqa: E402


def setup_function(_fn):
    creed_emit.invalidate_cache()
    creed_emit._warned_missing_keys.clear()


def test_env_var_name_normalization():
    assert creed_emit._env_var_for("what-the-fact") == "CREED_INGEST_KEY_WHAT_THE_FACT"
    assert (
        creed_emit._env_var_for("kytran-empowerment")
        == "CREED_INGEST_KEY_KYTRAN_EMPOWERMENT"
    )


def test_resolve_tenant_uses_db_value_and_caches():
    with mock.patch.object(
        creed_emit, "_lookup_tenant", return_value="what-the-fact"
    ) as lk:
        assert creed_emit.resolve_tenant(agent_name="B.I.A.S.") == "what-the-fact"
        assert creed_emit.resolve_tenant(agent_name="B.I.A.S.") == "what-the-fact"
        assert lk.call_count == 1  # second hit served from cache


def test_resolve_tenant_defaults_without_identity():
    assert creed_emit.resolve_tenant() == creed_emit.DEFAULT_TENANT


def test_key_fallback_chain(monkeypatch):
    # 1) product key wins
    monkeypatch.setenv("CREED_INGEST_KEY_GOV_WATCH", "k-gov")
    monkeypatch.setenv("CREED_INGEST_KEY_KYTRAN_EMPOWERMENT", "k-default")
    monkeypatch.setenv("CREED_INGEST_KEY", "k-legacy")
    assert creed_emit.key_for_tenant("gov-watch") == ("k-gov", "gov-watch")
    # 2) missing product key -> default tenant key
    monkeypatch.delenv("CREED_INGEST_KEY_GOV_WATCH")
    assert creed_emit.key_for_tenant("gov-watch") == (
        "k-default",
        creed_emit.DEFAULT_TENANT,
    )
    # 3) nothing but legacy -> legacy (today's behavior, no regression)
    monkeypatch.delenv("CREED_INGEST_KEY_KYTRAN_EMPOWERMENT")
    assert creed_emit.key_for_tenant("gov-watch") == ("k-legacy", "legacy")


def test_emit_event_routes_with_resolved_key(monkeypatch):
    monkeypatch.setenv("CREED_INGEST_KEY_WHAT_THE_FACT", "k-wtf")
    captured = {}

    def fake_post(url, json=None, headers=None, timeout=None):
        captured.update(url=url, json=json, headers=headers)
        return mock.Mock(status_code=201)

    with mock.patch.object(creed_emit, "_lookup_tenant", return_value="what-the-fact"):
        with mock.patch.object(creed_emit.requests, "post", side_effect=fake_post):
            ok = creed_emit.emit_event(
                category="fairness",
                severity="warning",
                description="test",
                agent_name="B.I.A.S.",
                module="NewsPipeline",
            )
    assert ok is True
    assert captured["headers"]["Authorization"] == "Bearer k-wtf"
    assert captured["json"]["metadata"]["routed_tenant"] == "what-the-fact"
    assert captured["json"]["metadata"]["module"] == "NewsPipeline"
    assert captured["url"].endswith("/api/v1/events")


def test_emit_event_skips_without_any_key(monkeypatch):
    for var in list(creed_emit._warned_missing_keys):
        creed_emit._warned_missing_keys.discard(var)
    monkeypatch.delenv("CREED_INGEST_KEY", raising=False)
    monkeypatch.delenv("CREED_INGEST_KEY_KYTRAN_EMPOWERMENT", raising=False)
    with mock.patch.object(
        creed_emit, "_lookup_tenant", return_value="kytran-empowerment"
    ):
        with mock.patch.object(creed_emit.requests, "post") as post:
            assert creed_emit.emit_event("safety", "info", "x", agent_name="A") is False
            post.assert_not_called()


def test_emit_event_never_raises_on_network_error(monkeypatch):
    monkeypatch.setenv("CREED_INGEST_KEY_KYTRAN_EMPOWERMENT", "k")
    with mock.patch.object(
        creed_emit, "_lookup_tenant", return_value="kytran-empowerment"
    ):
        with mock.patch.object(
            creed_emit.requests,
            "post",
            side_effect=creed_emit.requests.ConnectionError("down"),
        ):
            assert creed_emit.emit_event("safety", "info", "x", agent_name="A") is False


def test_auth_header_for_agent(monkeypatch):
    monkeypatch.setenv("CREED_INGEST_KEY_MEDIA_HUB", "k-mh")
    with mock.patch.object(creed_emit, "_lookup_tenant", return_value="media-hub"):
        hdr = creed_emit.auth_header_for_agent(agent_name="M.A.V.E.N.")
    assert hdr == {"Authorization": "Bearer k-mh"}
