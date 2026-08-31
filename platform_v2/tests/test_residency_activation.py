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
    # `found_tier`, not `tier` — see test_found_tier_is_the_tier_FOUND below.
    assert r["requested"][0]["found_tier"] == "gpu"
    assert r["requested"][0]["ready"] is True


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


# ── bounded warm-up (the 174.6s serial version blocked three jobs) ──────────
def test_a_slow_warm_up_does_not_block_past_the_deadline(wired, monkeypatch):
    """The reason this exists: serial warming took 174.6s and was about to be
    called at the top of three scheduled backlog jobs."""
    import time

    monkeypatch.setattr(ra, "_WARM_DEADLINE_S", 1)
    monkeypatch.setattr(ra, "_record_active", lambda n, t: None)

    class _Slow:
        def ensure_model_ready(self, *a):
            time.sleep(30)  # far past the wall
            return {"ready": True, "tier": "gpu"}

    monkeypatch.setattr("services.model_service.get_model_service", lambda: _Slow())
    t0 = time.time()
    r = ra.activate(dry_run=False)
    elapsed = time.time() - t0
    assert elapsed < 15, f"caller was held {elapsed:.1f}s despite a 1s deadline"
    assert r["ok"] is True


def test_a_timed_out_warm_up_is_not_reported_as_a_failure(wired, monkeypatch):
    """The deadline does not cancel the load — Ollama keeps warming and the
    model lands resident shortly after. Calling that 'failed' would be wrong."""
    import time

    monkeypatch.setattr(ra, "_WARM_DEADLINE_S", 1)
    monkeypatch.setattr(ra, "_record_active", lambda n, t: None)

    class _Slow:
        def ensure_model_ready(self, *a):
            time.sleep(30)
            return {"ready": True, "tier": "gpu"}

    monkeypatch.setattr("services.model_service.get_model_service", lambda: _Slow())
    e = ra.activate(dry_run=False)["requested"][0]
    assert e.get("timed_out") is True
    assert "load continues" in (e.get("note") or "")


def test_found_tier_is_the_tier_FOUND_not_the_tier_achieved(wired, monkeypatch):
    """model_service's warm-boot SUCCESS path hardcodes
    {"ready": True, "tier": "cold"} — so ready=True with 'cold' means "it WAS
    cold, we loaded it, it is now resident". The field was called `tier`, which
    read as an outcome and misled me into reporting a success as a failure.
    """
    monkeypatch.setattr(ra, "_record_active", lambda n, t: None)

    class _Booted:
        def ensure_model_ready(self, *a):
            return {"ready": True, "tier": "cold", "warm_boot_ms": 22775}

    monkeypatch.setattr("services.model_service.get_model_service", lambda: _Booted())
    e = ra.activate(dry_run=False)["requested"][0]
    assert e["ready"] is True, "a warm-booted model is READY"
    assert e["found_tier"] == "cold", "and it was FOUND cold — that is not a failure"
    assert "tier" not in e, "the ambiguous key must be gone, not merely aliased"


# ── warm_for_backlog: the scheduled caller (#6217) ─────────────────────────
@pytest.fixture
def backlog(monkeypatch):
    """Armed by default; individual tests disarm one gate at a time."""
    import services.residency_profiles as rp

    settings = {ra._BACKLOG_ENABLED_KEY: "true"}
    monkeypatch.setattr(rp, "_read_setting", lambda k: settings.get(k))
    monkeypatch.setattr(ra, "status", lambda: {"active": False})
    monkeypatch.setattr(rp, "all_profiles", lambda: {"default": {}, "aux": {}})
    return settings


def test_warm_for_backlog_is_OFF_unless_explicitly_armed(backlog, monkeypatch):
    """This ships inert. An unset flag must not warm anything — the setting is
    the owner's decision, and 'absent' is not 'yes'."""
    monkeypatch.setattr(ra, "activate", lambda *a, **k: pytest.fail("must not activate"))
    for value in (None, "", "false", "1", "yes", "off"):
        backlog[ra._BACKLOG_ENABLED_KEY] = value
        r = ra.warm_for_backlog()
        assert r["warmed"] is False, f"{value!r} armed the warm-up"
    backlog[ra._BACKLOG_ENABLED_KEY] = "true"
    monkeypatch.setattr(ra, "activate", lambda *a, **k: {"requested": [{"model": "m"}]})
    assert ra.warm_for_backlog()["warmed"] is True, "'true' must arm it"


def test_case_and_whitespace_in_the_flag_still_arm_it(backlog, monkeypatch):
    """Deliberately forgiving. A trailing space or a capital in a hand-typed
    platform_settings row is a typo, not a different intent — and a flag that
    silently ignores 'TRUE ' is a support ticket, not a safety feature."""
    monkeypatch.setattr(ra, "activate", lambda *a, **k: {"requested": [{"model": "m"}]})
    for value in ("TRUE ", " true", "True"):
        backlog[ra._BACKLOG_ENABLED_KEY] = value
        assert ra.warm_for_backlog()["warmed"] is True, f"{value!r} should arm it"


def test_an_active_profile_is_not_re_warmed(backlog, monkeypatch):
    """The throttle. Three producers call this; only the first should act."""
    monkeypatch.setattr(ra, "status", lambda: {"active": True, "profile": "news", "seconds_remaining": 900})
    monkeypatch.setattr(ra, "activate", lambda *a, **k: pytest.fail("re-warmed a live profile"))
    r = ra.warm_for_backlog()
    assert r["warmed"] is False and r["reason"] == "already active"


def test_a_lapsed_profile_IS_re_warmed(backlog, monkeypatch):
    """...and the throttle must actually expire, or one warm-up is all we ever get."""
    monkeypatch.setattr(ra, "status", lambda: {"active": False, "lapsed": True})
    monkeypatch.setattr(ra, "activate", lambda *a, **k: {"requested": [{"model": "m"}]})
    assert ra.warm_for_backlog()["warmed"] is True


def test_a_fully_refused_activation_is_NOT_reported_as_warmed(backlog, monkeypatch):
    """activate() writes the TTL even when every model was refused by the
    capacity/presence gates, so status() will read `active` for the whole
    window. That is deliberate upstream — the refusals are structural — but it
    means `active` says "we asked", not "it is warm". Reporting that as a
    successful warm-up would put a false success in the job log."""
    monkeypatch.setattr(
        ra,
        "activate",
        lambda *a, **k: {"ok": True, "requested": [], "refused": [{"reason": "capacity gate"}]},
    )
    r = ra.warm_for_backlog()
    assert r["warmed"] is False
    assert r["reason"] == "nothing requestable"
    assert r["result"]["refused"], "the refusals must survive to the caller"


def test_warm_for_backlog_never_raises_into_the_drain(backlog, monkeypatch):
    """A backlog cycle that cannot warm must still drain. This is the whole
    reason the call is safe to put at the top of three scheduled jobs."""
    monkeypatch.setattr(ra, "activate", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    r = ra.warm_for_backlog("wtf_factcheck_backlog")
    assert r["warmed"] is False and "boom" in r["reason"]


def test_a_broken_settings_read_disarms_rather_than_raising(monkeypatch):
    import services.residency_profiles as rp

    monkeypatch.setattr(rp, "_read_setting", lambda k: (_ for _ in ()).throw(RuntimeError("db down")))
    assert ra.warm_for_backlog()["warmed"] is False


def test_profile_and_ttl_are_configurable_with_sane_defaults(backlog, monkeypatch):
    seen = {}

    def _cap(name, ttl_minutes=None, dry_run=True):
        seen.update(name=name, ttl=ttl_minutes, dry_run=dry_run)
        return {"requested": [{"model": "m"}]}

    monkeypatch.setattr(ra, "activate", _cap)
    ra.warm_for_backlog()
    assert seen["name"] == ra._BACKLOG_DEFAULT_PROFILE
    assert seen["ttl"] == ra._DEFAULT_TTL_MIN
    assert seen["dry_run"] is False, "the scheduled caller must actually warm"

    backlog[ra._BACKLOG_PROFILE_KEY] = "aux"
    backlog[ra._BACKLOG_TTL_KEY] = "30"
    ra.warm_for_backlog()
    assert seen["name"] == "aux" and seen["ttl"] == 30


def test_a_garbage_ttl_setting_falls_back_instead_of_raising(backlog, monkeypatch):
    backlog[ra._BACKLOG_TTL_KEY] = "not-a-number"
    seen = {}
    monkeypatch.setattr(
        ra, "activate", lambda n, ttl_minutes=None, dry_run=True: seen.update(ttl=ttl_minutes) or {"requested": [1]}
    )
    ra.warm_for_backlog()
    assert seen["ttl"] == ra._DEFAULT_TTL_MIN


def test_all_three_wtf_backlog_producers_call_the_warm_up():
    """STRUCTURAL PIN. tools/department_hq/jobs.py has no test that EXECUTES it
    (the same gap the K.I.N. tab work hit), so a call site added there is
    otherwise unverifiable and can be dropped by a future edit without any test
    going red. Grepping the source is the honest substitute — same approach as
    tests/test_merge_state_ui.py.

    All THREE must call it: they share one agent pool, and warming in front of
    only one leaves the other two paying the cold-load cost anyway.
    """
    import pathlib

    src = (pathlib.Path(__file__).resolve().parents[1] / "tools/department_hq/jobs.py").read_text()
    for job in ("wtf_factcheck_backlog", "wtf_bias_backlog", "wtf_geo_backlog"):
        assert (
            f"warm_for_backlog('{job}')" in src or f'warm_for_backlog("{job}")' in src
        ), f"{job} no longer warms its residency profile"


def test_the_default_profile_must_actually_EXIST():
    """The bug this pins: _BACKLOG_DEFAULT_PROFILE was 'news', a profile that is
    planned but not written. activate() answers "declares no nodes", which the
    wrapper reported as `nothing requestable` — identical to "every model was
    refused". The feature would have been silently off while looking like it ran.
    """
    import services.residency_profiles as rp

    assert ra._BACKLOG_DEFAULT_PROFILE in rp.all_profiles(), (
        f"default profile {ra._BACKLOG_DEFAULT_PROFILE!r} does not exist; " f"known: {sorted(rp.all_profiles())}"
    )


def test_a_typo_in_the_profile_setting_degrades_loudly_instead_of_silently_off(backlog, monkeypatch):
    """A hand-typed settings row will eventually contain a typo. Warming is an
    optimisation, so the safe failure is 'warn and warm the known-good profile',
    not 'quietly stop warming and report a plausible-looking refusal'."""
    seen = {}
    monkeypatch.setattr(
        ra, "activate", lambda n, ttl_minutes=None, dry_run=True: seen.update(name=n) or {"requested": [1]}
    )
    backlog[ra._BACKLOG_PROFILE_KEY] = "newz"
    r = ra.warm_for_backlog()
    assert r["warmed"] is True
    assert seen["name"] == ra._BACKLOG_DEFAULT_PROFILE, "a typo must fall back, not warm nothing"


def test_if_even_the_default_is_missing_it_says_so_rather_than_pretending(backlog, monkeypatch):
    import services.residency_profiles as rp

    monkeypatch.setattr(rp, "all_profiles", lambda: {})
    monkeypatch.setattr(ra, "activate", lambda *a, **k: pytest.fail("must not activate a missing profile"))
    r = ra.warm_for_backlog()
    assert r["warmed"] is False and r["reason"].startswith("unknown profile:")
