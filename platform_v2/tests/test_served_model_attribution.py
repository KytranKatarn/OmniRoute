"""#6653 Phase 3 — task_execution_log.model_used records the model that actually
SERVED a contractor call, never an auto-router id like "auto/coding".

OmniRoute's whole value is quota-aware auto-fallback, so the served model differs
from the requested one. Before this, the served model was discarded at THREE
layers (external_providers._call_openai_compatible, dispatcher._dispatch_to_contractor,
and the request_work result builder) and a default_model of "auto" would have logged
the literal string "auto" into the accounting spine (ADR-034).

Runs in-container:
    docker exec -i archie_platform python3 -m pytest tests/test_served_model_attribution.py -q
"""

import re
import sys
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve()
sys.path.insert(0, str(_HERE.parents[1]))  # /app (platform_v2); ai_bridge is already importable in-container

from ai_bridge import external_providers as ep  # noqa: E402

_DISPATCHER_SRC = _HERE.parents[1] / "tools" / "department_hq" / "services" / "department_dispatcher.py"


# --- external_providers helpers -------------------------------------------------


@pytest.mark.parametrize("mid", ["auto", "auto/coding", "auto/coding:free", "AUTO/fast"])
def test_auto_router_ids_are_recognised(mid):
    assert ep.is_auto_router(mid) is True


@pytest.mark.parametrize("mid", ["gpt-4o-mini", "deepseek/deepseek-chat", "autopilot-x", "", None])
def test_concrete_ids_are_not_auto_routers(mid):
    assert ep.is_auto_router(mid) is False


def test_served_model_comes_from_the_response_body():
    model, resolved = ep.resolve_served_model({"model": "deepseek/deepseek-chat"}, "auto/coding")
    assert (model, resolved) == ("deepseek/deepseek-chat", True)


def test_body_echoing_an_auto_id_falls_back_to_requested_and_is_flagged():
    model, resolved = ep.resolve_served_model({"model": "auto/coding"}, "auto/coding")
    assert model == "auto/coding" and resolved is False


def test_missing_body_model_with_concrete_request_is_resolved():
    model, resolved = ep.resolve_served_model({}, "gpt-4o-mini")
    assert (model, resolved) == ("gpt-4o-mini", True)


def test_missing_body_model_with_auto_request_is_unresolved():
    model, resolved = ep.resolve_served_model({}, "auto")
    assert model == "auto" and resolved is False


# --- _call_openai_compatible threads the served model through --------------------


class _Resp:
    def __init__(self, body, headers=None, status=200):
        self._body, self.headers, self.status_code = body, headers or {}, status
        self.text = ""

    def raise_for_status(self):
        pass

    def json(self):
        return self._body


def _neutralise(monkeypatch, served):
    monkeypatch.setattr(
        ep, "_get_provider_config", lambda p: {"base_url": "http://omniroute:20128/v1", "default_model": "auto/coding"}
    )
    monkeypatch.setattr(ep, "_get_api_key", lambda p: "k")
    monkeypatch.setattr(ep, "_check_budget", lambda p: True)
    monkeypatch.setattr(ep, "check_weekly_budget", lambda p: True)
    # DS9 Phase 3: the group normally reads the snapshots table — pin it to a
    # settled allow so these white-box tests stay hermetic (no DB dependency).
    monkeypatch.setattr(ep, "_omniroute_quota_gate", lambda model, base_url: {"allow": True, "reason": "ok"})
    monkeypatch.setattr(ep, "_update_cost", lambda *a, **k: None)
    logged = {}
    monkeypatch.setattr(ep, "_log_usage", lambda prov, model, *a, **k: logged.update({"model": model}))
    monkeypatch.setattr(ep, "_calculate_cost", lambda model, *a, **k: (logged.update({"cost_model": model}), 0.0)[1])
    body = {
        "model": served,
        "choices": [{"message": {"content": "ok"}}],
        "usage": {"prompt_tokens": 3, "completion_tokens": 2},
    }
    monkeypatch.setattr(
        ep.requests, "post", lambda *a, **k: _Resp(body, {"X-OmniRoute-Decision": "strategy=lkgp provider=deepseek"})
    )
    return logged


def test_call_openai_compatible_returns_the_served_model_not_the_requested(monkeypatch):
    logged = _neutralise(monkeypatch, served="deepseek/deepseek-chat")
    r = ep._call_openai_compatible("omniroute", "hi", model="auto/coding")
    assert r["success"] is True
    assert r["model"] == "deepseek/deepseek-chat"
    assert r["requested_model"] == "auto/coding"
    assert r["served_model_resolved"] is True
    assert r["routing_decision"] == "strategy=lkgp provider=deepseek"
    assert logged["model"] == "deepseek/deepseek-chat"  # usage ledger keyed by the served model
    assert logged["cost_model"] == "deepseek/deepseek-chat"


def test_call_openai_compatible_never_reports_auto_as_resolved(monkeypatch):
    _neutralise(monkeypatch, served="auto/coding")
    r = ep._call_openai_compatible("omniroute", "hi", model="auto/coding")
    assert r["served_model_resolved"] is False
    assert r["model"] == "auto/coding"  # the requested id, flagged — never silently "resolved"


# --- dispatcher: served_or_requested + the three call sites ----------------------


def test_served_or_requested_prefers_the_served_model():
    from tools.department_hq.services.department_dispatcher import served_or_requested

    assert served_or_requested({"model": "deepseek/deepseek-chat"}, "auto/coding") == "deepseek/deepseek-chat"


def test_served_or_requested_falls_back_when_served_is_an_auto_router_or_missing():
    from tools.department_hq.services.department_dispatcher import served_or_requested

    assert served_or_requested({"model": "auto/coding"}, "auto/coding") == "auto/coding"
    assert served_or_requested({}, "qwen2.5:7b") == "qwen2.5:7b"
    assert served_or_requested(None, "qwen2.5:7b") == "qwen2.5:7b"


def test_every_model_used_site_on_the_contractor_and_hub_paths_uses_the_helper():
    src = _DISPATCHER_SRC.read_text(encoding="utf-8")
    # _dispatch_to_contractor: both branches
    assert len(re.findall(r"model_used=served_or_requested\((llm_result|result), model or provider_key\)", src)) == 2
    # request_work success builder (the explicit model_override / A-B lane path)
    assert re.search(r"model_used=served_or_requested\(llm_result, model\)", src) is not None
    # the old literal forms must be gone from those sites
    assert "model_used=model or provider_key," not in src


def test_dispatch_to_contractor_records_the_served_model(monkeypatch):
    from tools.department_hq.services import department_dispatcher as dd

    disp = dd.DepartmentDispatcher()
    monkeypatch.setattr(disp, "_cloud_capability_allowed", lambda cap: True)
    monkeypatch.setattr(disp, "_cloud_budget_ok", lambda *a, **k: True)
    monkeypatch.setattr(
        ep,
        "call_external",
        lambda **kw: {
            "success": True,
            "response": "ok",
            "model": "deepseek/deepseek-chat",
            "requested_model": "auto/coding",
            "served_model_resolved": True,
            "routing_decision": "provider=deepseek",
            "provider": "omniroute",
            "prompt_tokens": 3,
            "completion_tokens": 2,
        },
    )
    contractor = {
        "provider_key": "omniroute",
        "display_name": "OmniRoute",
        "default_model": "auto/coding",
        "is_cloud_proxy": False,
        "tier_position": 9,
        "creed_compliance_tier": 2,
    }
    res = disp._dispatch_to_contractor(contractor, "write a fizzbuzz", "code", "cloud_code_lane")
    assert res is not None and res.success
    assert res.model_used == "deepseek/deepseek-chat"
    assert res.provider == "contractor:omniroute"
    assert res.metadata["served_model_resolved"] is True
    assert res.metadata["routing_decision"] == "provider=deepseek"


# ── #6670: a contractor row is self-describing ───────────────────────────────


def test_both_contractor_metadata_dicts_stamp_is_cloud():
    """A task_execution_log row from a contractor must say so ITSELF, rather than
    depending on the provider-name allowlist in services/token_provenance.py to infer
    it. Measured motivation: failed cloud-code attempts landed with provider='ollama',
    which that allowlist classifies as LOCAL.

    BOTH branches of _dispatch_to_contractor carry it — the cloud-proxy branch
    (is_cloud_proxy=True) and the standard OpenAI-compatible branch
    (is_cloud_proxy=False). is_cloud_proxy says WHICH branch served it; is_cloud says
    it was cloud either way, so asserting only one branch would miss the other.
    """
    src = (
        Path(__file__).resolve().parents[1] / "tools" / "department_hq" / "services" / "department_dispatcher.py"
    ).read_text(encoding="utf-8")

    for proxy_flag in ('"is_cloud_proxy": True,', '"is_cloud_proxy": False,'):
        idx = src.index(proxy_flag)
        window = src[idx : idx + 220]
        assert '"is_cloud": True' in window, (
            f"the contractor metadata dict containing {proxy_flag.strip()} must also "
            f'carry "is_cloud": True — a contractor row has to be self-describing'
        )


# ── DS9 Phase 3: the OmniRoute quota gate is consumed at the gateway call site ─


def test_gate_ignores_non_omniroute_providers(monkeypatch):
    monkeypatch.setattr(
        ep, "_get_provider_config", lambda p: {"base_url": "https://api.openai.com/v1", "default_model": "gpt-4o-mini"}
    )
    monkeypatch.setattr(ep, "_get_api_key", lambda p: "k")
    monkeypatch.setattr(ep, "_check_budget", lambda p: True)
    monkeypatch.setattr(ep, "check_weekly_budget", lambda p: True)
    r = ep._call_openai_compatible("openai", "hi", model="gpt-4o-mini")
    assert r["success"] is False  # no API key path actually fires a POST; proves the gate didn't pre-empt
    assert "quota" not in (r.get("error") or "").lower()


def test_gate_refuses_exhausted_upstream_before_the_post(monkeypatch):
    _neutralise(monkeypatch, served="deepseek/deepseek-chat")
    monkeypatch.setattr(
        ep, "_omniroute_quota_gate", lambda model, base_url: {"allow": False, "reason": "upstream opencode exhausted", "status": "exhausted"}
    )
    r = ep._call_openai_compatible("omniroute", "hi", model="auto/coding")
    assert r["success"] is False
    assert "quota" in (r.get("error") or "").lower()
    assert r.get("quota_status", {}).get("status") == "exhausted"


def test_gate_degraded_warns_but_sends(monkeypatch):
    _neutralise(monkeypatch, served="deepseek/deepseek-chat")
    monkeypatch.setattr(
        ep, "_omniroute_quota_gate", lambda model, base_url: {"allow": True, "status": "degraded", "reason": "degraded"}
    )
    r = ep._call_openai_compatible("omniroute", "hi", model="auto/coding")
    assert r["success"] is True  # degraded warns, never blocks
    assert r["model"] == "deepseek/deepseek-chat"
