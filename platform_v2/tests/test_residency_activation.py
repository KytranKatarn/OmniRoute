"""Warm-residency ACTIVATION (step 3 of the warmboot spec).

This is the first step in the warmboot work that can change anything at runtime,
so the tests are weighted toward what it must REFUSE rather than what it does.

Run: docker exec archie_platform python3 -m pytest /app/tests/test_residency_activation.py -q
"""

import pytest

from services import residency_activation as ra

HUB = "archie-starbase"
NODE = {
    "node_id": HUB,
    "node_name": "Archie Starbase",
    "hostname": "192.168.1.200",
    "status": "online",
    "gpu_available": True,
    "gpu_vram_gb": 12,
    "ram_gb": 128,
    "extra_capabilities": {},
}


@pytest.fixture
def wired(monkeypatch):
    """One node, one declared model, both gates open unless a test closes one."""
    monkeypatch.setattr(ra, "_node_rows", lambda: {HUB: dict(NODE)})
    import services.residency_profiles as rp

    monkeypatch.setattr(rp, "nodes_for", lambda name=None: {HUB: {"expect_resident": ["qwen2.5:7b"]}})
    monkeypatch.setattr(rp, "active_name", lambda: "default")
    import services.fleet_resource_router as frr

    monkeypatch.setattr(frr, "can_node_run_model", lambda n, m: True)
    monkeypatch.setattr(frr, "node_has_model", lambda n, m: True)
    return monkeypatch


# ── the default that protects the fleet ────────────────────────────────────
def test_dry_run_is_the_default(wired):
    """The first runtime-affecting step in this feature must not be something
    you get by accident."""
    r = ra.activate()
    assert r["dry_run"] is True
    assert all(e.get("would_request") for e in r["requested"])


def test_dry_run_loads_nothing(wired, monkeypatch):
    called = []
    monkeypatch.setattr(
        "services.model_service.get_model_service",
        lambda: (_ for _ in ()).throw(AssertionError("must not be called")),
    )
    r = ra.activate(dry_run=True)
    assert r["ok"] and not called


# ── the gates: what it must REFUSE ─────────────────────────────────────────
def test_capacity_gate_refuses_before_asking(wired, monkeypatch):
    """Never queue a load the drain would refuse anyway — the #5809 waste."""
    import services.fleet_resource_router as frr

    monkeypatch.setattr(frr, "can_node_run_model", lambda n, m: False)
    r = ra.activate(dry_run=True)
    assert not r["requested"]
    assert r["refused"] and "capacity gate" in r["refused"][0]["reason"]


def test_presence_gate_refuses_a_model_not_pulled_on_the_node(wired, monkeypatch):
    """CAPACITY IS NOT PRESENCE (#5862).

    Measured live on this fleet, the two predicates DISAGREE on real nodes:
        Citadel     qwen2.5:7b  capacity=False presence=True
        Outpost-US  qwen2.5:7b  capacity=False presence=True
    and #5863 recorded the reverse costing 16 runs / 0 ok / MODEL_NOT_FOUND.
    Asking a node to warm a model it does not have is a PULL, not a warm-up.
    """
    import services.fleet_resource_router as frr

    monkeypatch.setattr(frr, "node_has_model", lambda n, m: False)
    r = ra.activate(dry_run=True)
    assert not r["requested"], "activation asked for a model the node does not have"
    assert r["refused"] and "presence gate" in r["refused"][0]["reason"]


def test_both_gates_must_pass_not_either(wired, monkeypatch):
    """A model that passes capacity but fails presence must still be refused —
    otherwise the second gate is decorative."""
    import services.fleet_resource_router as frr

    monkeypatch.setattr(frr, "can_node_run_model", lambda n, m: True)
    monkeypatch.setattr(frr, "node_has_model", lambda n, m: False)
    assert not ra.activate(dry_run=True)["requested"]


def test_an_offline_node_is_skipped_not_failed(wired, monkeypatch):
    """A profile may legitimately name a node that is currently down."""
    monkeypatch.setattr(ra, "_node_rows", lambda: {})
    r = ra.activate(dry_run=True)
    assert r["ok"] is True
    assert r["skipped"] and r["skipped"][0]["reason"] == "not online"


# ── TTL ────────────────────────────────────────────────────────────────────
def test_ttl_is_clamped_to_a_maximum(wired):
    """Beyond the cap it is not an activation, it is a config change — and a
    permanent reservation for one workload is how the others starve."""
    r = ra.activate(ttl_minutes=100000, dry_run=True)
    assert r["ttl_minutes"] == ra._MAX_TTL_MIN


def test_ttl_has_a_floor(wired):
    r = ra.activate(ttl_minutes=0, dry_run=True)
    assert r["ttl_minutes"] >= 1


def test_a_dry_run_does_not_record_an_active_profile(wired, monkeypatch):
    recorded = []
    monkeypatch.setattr(ra, "_record_active", lambda n, t: recorded.append((n, t)))
    ra.activate(dry_run=True)
    assert not recorded, "a dry run must not claim the fleet"


def test_a_real_activation_records_the_profile(wired, monkeypatch):
    recorded = []
    monkeypatch.setattr(ra, "_record_active", lambda n, t: recorded.append((n, t)))

    class _Svc:
        def ensure_model_ready(self, agent, model, host):
            return {"ready": True, "tier": "gpu", "warm_boot_ms": 12}

    monkeypatch.setattr("services.model_service.get_model_service", lambda: _Svc())
    r = ra.activate(dry_run=False)
    assert recorded and recorded[0][0] == "default"
    assert r["requested"][0]["tier"] == "gpu"


# ── never raises ───────────────────────────────────────────────────────────
def test_a_loader_failure_is_reported_not_raised(wired, monkeypatch):
    class _Svc:
        def ensure_model_ready(self, *a):
            raise RuntimeError("ollama unreachable")

    monkeypatch.setattr("services.model_service.get_model_service", lambda: _Svc())
    monkeypatch.setattr(ra, "_record_active", lambda n, t: None)
    r = ra.activate(dry_run=False)
    assert r["requested"][0]["ready"] is False
    assert r["errors"]


def test_an_empty_profile_is_reported_not_silently_successful(monkeypatch):
    """A profile that declares nothing must not read as 'activated'."""
    import services.residency_profiles as rp

    monkeypatch.setattr(rp, "nodes_for", lambda name=None: {})
    monkeypatch.setattr(rp, "active_name", lambda: "default")
    r = ra.activate(dry_run=True)
    assert r["ok"] is False and r["errors"]


def test_target_host_is_none_for_a_node_with_no_hostname():
    """ensure_model_ready treats None as the hub. A blank hostname must not
    silently redirect a node's warm-up onto the hub."""
    assert ra._target_host({"hostname": ""}) is None
    assert ra._target_host(None) is None
    assert ra._target_host({"hostname": "192.168.1.246"})["port"] == 11434


def test_status_distinguishes_never_activated_from_lapsed(monkeypatch):
    import services.residency_profiles as rp
    import time as _t

    monkeypatch.setattr(rp, "source", lambda: "fallback")
    monkeypatch.setattr(rp, "_read_setting", lambda k: "news" if k == ra._ACTIVE_KEY else str(int(_t.time()) - 5))
    s = ra.status()
    assert s["profile"] == "news"
    assert (
        s["active"] is False and s["lapsed"] is True
    ), "an operator must tell 'never activated' from 'activated and lapsed'"
