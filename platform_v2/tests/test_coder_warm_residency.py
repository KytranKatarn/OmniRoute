"""Demand-driven coder warmth is a SEPARATE axis from the residency profile (#6703).

Owner ask 2026-09-11: "if there is a coder request keep it warm for next hours".

THE BUG THIS FEATURE HAD TO AVOID, and why most of these tests exist:
`warm_for_backlog()` routes through `activate()`, which writes ONE profile name into
ONE settings key with ONE expiry — and it refuses outright when `status()['active']`
is set. The WTF backlog re-arms that slot every few minutes, so a coder caller wired
through the profile system would have returned "already active" essentially always,
warming NOTHING while logging plausibly. Same shape as the 'news'-profile-that-did-
not-exist bug (KB #300145): armed-looking and inert.

So the load-bearing property under test is NON-COLLISION: coder warmth must never
read or write the profile slot, in either direction.

The second load-bearing property is that coder warmth REFUSES rather than falling
back to "any node with capacity". can_node_run_model() says True for the hub, but
the active profile already puts qwen2.5:7b on that same 12GB card — stacking a
second 7B there is the measured 2026-08-15 failure (VRAM budget 0.0GB, fact_check
89% failure on 240s timeouts). The fallback IS the incident.

No DB: pytest forces the empty archie_test database, so a test that reached Postgres
would assert against zero rows and pass vacuously (KB: pytest live data is VACUOUS).
Every seam is replaced.
"""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

ra = pytest.importorskip("services.residency_activation")


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------


@pytest.fixture
def settings(monkeypatch):
    """A fake platform_settings the module reads through, plus a record of writes."""
    store = {}
    written = []

    from services import residency_profiles as rp

    monkeypatch.setattr(rp, "_read_setting", lambda k: store.get(k))

    def _claim(reason, ttl_minutes):
        written.append((reason, ttl_minutes))
        store[ra._CODER_ACTIVE_KEY] = reason
        import time as _t

        store[ra._CODER_EXPIRES_KEY] = str(int(_t.time()) + int(ttl_minutes) * 60)

    monkeypatch.setattr(ra, "_record_coder_claim", _claim)
    store["_writes"] = written
    return store


def _node(node_id="starship_246", name="Starship - Defiant - USS-246"):
    return {"node_id": node_id, "node_name": name, "gpu_available": True, "gpu_vram_gb": 8.0, "ram_gb": 32.0}


@pytest.fixture
def fleet(monkeypatch):
    """One online node that passes both gates, and a warm loop that records calls."""
    warmed = []
    monkeypatch.setattr(ra, "_node_rows", lambda: {"starship_246": _node()})
    monkeypatch.setattr(ra, "_target_host", lambda n: {"host": "x"})
    monkeypatch.setattr(ra, "_warm_all", lambda pending, report: warmed.extend(m for _e, m, _h, _n in pending))
    return warmed


# --------------------------------------------------------------------------
# THE property: coder warmth and the profile slot are independent
# --------------------------------------------------------------------------


class TestItDoesNotCollideWithTheProfileSlot:
    def test_an_active_profile_does_not_block_coder_warmth(self, settings, fleet, monkeypatch):
        """THE regression this feature exists to avoid.

        'news' being active (which it is, in production, almost always) must not
        make coder warmth a no-op. If this ever fails, the coder path has been
        re-routed through activate() and the feature is inert again.
        """
        settings[ra._CODER_ENABLED_KEY] = "true"
        settings[ra._ACTIVE_KEY] = "news"  # the profile slot is TAKEN
        import time as _t

        settings[ra._EXPIRES_KEY] = str(int(_t.time()) + 3600)

        monkeypatch.setattr(ra, "coder_models", lambda: ("qwen2.5-coder:7b",))
        monkeypatch.setattr(ra, "coder_target_nodes", lambda: {"starship_246": "reserved for code_review"})

        res = ra.warm_for_coder("test", block=True)
        assert res.get("warmed") is True, f"an active profile blocked coder warmth: {res}"
        assert "qwen2.5-coder:7b" in fleet

    def test_coder_warmth_never_writes_the_profile_slot(self, settings, fleet, monkeypatch):
        """The inverse direction: warming for a coder must not hijack the fleet's
        residency profile, which would evict the WTF backlog's warm set."""
        settings[ra._CODER_ENABLED_KEY] = "true"
        monkeypatch.setattr(ra, "coder_models", lambda: ("qwen2.5-coder:7b",))
        monkeypatch.setattr(ra, "coder_target_nodes", lambda: {"starship_246": "why"})

        ra.warm_for_coder("test", block=True)
        assert ra._ACTIVE_KEY not in settings, "coder warmth wrote the PROFILE slot"
        assert ra._EXPIRES_KEY not in settings

    def test_the_two_axes_use_different_keys(self):
        """Cheap, but it is the whole design in one assertion."""
        assert ra._CODER_ACTIVE_KEY != ra._ACTIVE_KEY
        assert ra._CODER_EXPIRES_KEY != ra._EXPIRES_KEY


# --------------------------------------------------------------------------
# It ships INERT
# --------------------------------------------------------------------------


class TestItShipsInert:
    def test_disabled_by_default(self, settings, fleet):
        res = ra.warm_for_coder("test", block=True)
        assert res == {"warmed": False, "reason": "disabled"}
        assert fleet == [], "warmed something while disabled"

    @pytest.mark.parametrize("val", ["false", "0", "", "TRUE-ish", "yes"])
    def test_only_the_literal_true_arms_it(self, settings, fleet, val):
        """'yes' is deliberately NOT enough — the existing warmboot keys use the
        same literal-'true' rule and a second spelling here would be a trap."""
        settings[ra._CODER_ENABLED_KEY] = val
        assert ra.warm_for_coder("test", block=True)["warmed"] is False
        assert fleet == []


# --------------------------------------------------------------------------
# The TTL is the throttle
# --------------------------------------------------------------------------


class TestTheTtlThrottles:
    def test_a_live_claim_refuses_a_second_warm(self, settings, fleet, monkeypatch):
        """archie_platform runs --workers 4; an in-memory timer would warm 4x
        (KB #282671). The claim is DB-backed precisely so it is shared."""
        import time as _t

        settings[ra._CODER_ENABLED_KEY] = "true"
        settings[ra._CODER_ACTIVE_KEY] = "someone_else"
        settings[ra._CODER_EXPIRES_KEY] = str(int(_t.time()) + 600)

        res = ra.warm_for_coder("test", block=True)
        assert res["warmed"] is False
        assert res["reason"] == "already warm"
        assert fleet == []

    def test_a_lapsed_claim_allows_warming_again(self, settings, fleet, monkeypatch):
        import time as _t

        settings[ra._CODER_ENABLED_KEY] = "true"
        settings[ra._CODER_ACTIVE_KEY] = "old"
        settings[ra._CODER_EXPIRES_KEY] = str(int(_t.time()) - 1)  # lapsed
        monkeypatch.setattr(ra, "coder_models", lambda: ("qwen2.5-coder:7b",))
        monkeypatch.setattr(ra, "coder_target_nodes", lambda: {"starship_246": "why"})

        assert ra.warm_for_coder("test", block=True)["warmed"] is True

    def test_the_short_lease_is_taken_before_warming_then_extended(self, settings, fleet, monkeypatch):
        """Two writes: a 5-minute claim BEFORE the warm (so concurrent workers do
        not all warm), extended to the full TTL only once a warm was requested.
        A single up-front full-TTL write would leave the feature inert for hours
        after one transient failure."""
        settings[ra._CODER_ENABLED_KEY] = "true"
        settings[ra._CODER_TTL_KEY] = "180"
        monkeypatch.setattr(ra, "coder_models", lambda: ("qwen2.5-coder:7b",))
        monkeypatch.setattr(ra, "coder_target_nodes", lambda: {"starship_246": "why"})

        ra.warm_for_coder("test", block=True)
        ttls = [ttl for _r, ttl in settings["_writes"]]
        assert ttls == [ra._CODER_CLAIM_MIN, 180], f"expected short-lease-then-extend, got {ttls}"

    def test_a_run_that_warms_nothing_keeps_only_the_short_lease(self, settings, fleet, monkeypatch):
        """Every node offline -> retry in 5 minutes, not in 3 hours."""
        settings[ra._CODER_ENABLED_KEY] = "true"
        monkeypatch.setattr(ra, "coder_models", lambda: ("qwen2.5-coder:7b",))
        monkeypatch.setattr(ra, "coder_target_nodes", lambda: {"ghost_node": "why"})
        monkeypatch.setattr(ra, "_node_rows", lambda: {})  # nothing online

        res = ra.warm_for_coder("test", block=True)
        assert res["warmed"] is False
        assert [ttl for _r, ttl in settings["_writes"]] == [ra._CODER_CLAIM_MIN]

    def test_ttl_is_clamped_to_the_module_maximum(self, settings, fleet, monkeypatch):
        settings[ra._CODER_ENABLED_KEY] = "true"
        settings[ra._CODER_TTL_KEY] = "99999"
        monkeypatch.setattr(ra, "coder_models", lambda: ("qwen2.5-coder:7b",))
        monkeypatch.setattr(ra, "coder_target_nodes", lambda: {"starship_246": "why"})

        ra.warm_for_coder("test", block=True)
        assert max(ttl for _r, ttl in settings["_writes"]) == ra._MAX_TTL_MIN

    @pytest.mark.parametrize("junk", ["abc", "", "12.5"])
    def test_a_junk_ttl_falls_back_to_the_default(self, settings, fleet, monkeypatch, junk):
        settings[ra._CODER_ENABLED_KEY] = "true"
        settings[ra._CODER_TTL_KEY] = junk
        monkeypatch.setattr(ra, "coder_models", lambda: ("qwen2.5-coder:7b",))
        monkeypatch.setattr(ra, "coder_target_nodes", lambda: {"starship_246": "why"})

        ra.warm_for_coder("test", block=True)
        assert max(ttl for _r, ttl in settings["_writes"]) == ra._CODER_DEFAULT_TTL_MIN


# --------------------------------------------------------------------------
# Targets: derived from a declaration, never from capacity alone
# --------------------------------------------------------------------------


class TestItRefusesRatherThanTargetingTheHub:
    def test_no_code_review_reservation_means_no_targets(self, monkeypatch):
        """The safety property. can_node_run_model() is True for the hub, so a
        capacity-based fallback would put a second 7B on the card that already
        holds qwen2.5:7b. Returning {} is the correct, deliberate refusal."""
        from services import residency_profiles as rp

        monkeypatch.setattr(rp, "_read_setting", lambda k: None)
        monkeypatch.setattr(rp, "active_name", lambda: "default")
        monkeypatch.setattr(rp, "nodes_for", lambda n: {"archie-starbase": {"expect_resident": ["gemma3:12b"]}})

        assert ra.coder_target_nodes() == {}

    def test_it_says_WHY_it_refused_distinctly(self, settings, fleet, monkeypatch):
        """'declares no nodes' and 'everything was refused' are different faults
        with the same symptom. Conflating them is KB #300145."""
        settings[ra._CODER_ENABLED_KEY] = "true"
        monkeypatch.setattr(ra, "coder_models", lambda: ("qwen2.5-coder:7b",))
        monkeypatch.setattr(ra, "coder_target_nodes", lambda: {})

        res = ra.warm_for_coder("test", block=True)
        assert res["warmed"] is False
        assert "code_review" in res["reason"] and "hub" in res["reason"], res["reason"]

    def test_it_targets_the_node_reserved_for_code_review(self, monkeypatch):
        from services import residency_profiles as rp

        monkeypatch.setattr(rp, "_read_setting", lambda k: None)
        monkeypatch.setattr(rp, "active_name", lambda: "news")
        monkeypatch.setattr(
            rp,
            "nodes_for",
            lambda n: {
                "archie-starbase": {"expect_resident": ["qwen2.5:7b"]},
                "starship_246": {"reserved_for": "code_review", "reserved_vram_gb": 8.0},
            },
        )
        targets = ra.coder_target_nodes()
        assert list(targets) == ["starship_246"]
        assert "code_review" in targets["starship_246"]

    def test_an_explicit_override_wins(self, monkeypatch):
        from services import residency_profiles as rp

        monkeypatch.setattr(rp, "_read_setting", lambda k: "node_a, node_b" if k == ra._CODER_NODES_KEY else None)
        assert sorted(ra.coder_target_nodes()) == ["node_a", "node_b"]


# --------------------------------------------------------------------------
# One source of truth for the model list
# --------------------------------------------------------------------------


class TestTheModelListIsNotDuplicated:
    def test_models_come_from_FAMILY_WARM_MODELS(self):
        """AUX POWER (#6081) already pins these. A second hardcoded list here is
        how the pin and the warm-up silently diverge."""
        from services.fleet_dispatch_profile import FAMILY_WARM_MODELS

        assert ra.coder_models() == tuple(FAMILY_WARM_MODELS["repair_bay"])

    def test_the_family_name_actually_resolves(self):
        """A NAME in a constant is a REFERENCE — assert it resolves. _BACKLOG_
        DEFAULT_PROFILE once shipped as 'news', a profile that did not exist, and
        the result was indistinguishable from 'everything was refused'."""
        from services.fleet_dispatch_profile import FAMILY_WARM_MODELS

        assert ra._CODER_FAMILY in FAMILY_WARM_MODELS
        assert ra.coder_models(), "the coder family resolved to an EMPTY model list"


# --------------------------------------------------------------------------
# It never raises into the caller
# --------------------------------------------------------------------------


class TestItNeverRaises:
    def test_a_settings_failure_returns_a_reason(self, monkeypatch):
        from services import residency_profiles as rp

        def boom(_k):
            raise RuntimeError("db down")

        monkeypatch.setattr(rp, "_read_setting", boom)
        res = ra.warm_for_coder("test", block=True)
        assert res["warmed"] is False and "error" in res["reason"]

    def test_a_warm_failure_is_reported_not_raised(self, settings, monkeypatch):
        settings[ra._CODER_ENABLED_KEY] = "true"
        monkeypatch.setattr(ra, "coder_models", lambda: ("qwen2.5-coder:7b",))
        monkeypatch.setattr(ra, "coder_target_nodes", lambda: {"starship_246": "why"})
        monkeypatch.setattr(ra, "_node_rows", lambda: {"starship_246": _node()})
        monkeypatch.setattr(ra, "_target_host", lambda n: {"host": "x"})

        def boom(pending, report):
            raise RuntimeError("ollama exploded")

        monkeypatch.setattr(ra, "_warm_all", boom)
        res = ra.warm_for_coder("test", block=True)
        assert res["warmed"] is False and res["ok"] is False

    def test_the_non_blocking_path_hands_off_to_a_thread(self, settings, fleet, monkeypatch):
        """block=False is the dispatch-path default and MUST NOT inherit
        _warm_all's 45s wall — that would add up to 45s to the first coder
        request in every TTL window.

        ⚠️ threading.Thread is REPLACED rather than allowed to run. A real thread
        here outlives monkeypatch teardown, and the restored `_warm_all` /
        `_node_rows` would then fire a genuine multi-minute model load against
        the LIVE fleet from a unit test. Assert the hand-off, never perform it.
        """
        settings[ra._CODER_ENABLED_KEY] = "true"
        monkeypatch.setattr(ra, "coder_models", lambda: ("qwen2.5-coder:7b",))
        monkeypatch.setattr(ra, "coder_target_nodes", lambda: {"starship_246": "why"})

        spawned = {}

        class _FakeThread:
            def __init__(self, target=None, args=(), name=None, daemon=None):
                spawned.update(target=target, args=args, name=name, daemon=daemon)

            def start(self):
                spawned["started"] = True

        import threading

        monkeypatch.setattr(threading, "Thread", _FakeThread)

        res = ra.warm_for_coder("test", block=False)
        assert res.get("scheduled") is True
        assert spawned.get("started") is True, "never started the worker"
        assert spawned["target"] is ra._warm_coder_now
        assert spawned["daemon"] is True, "a non-daemon thread would hold the worker on shutdown"
        assert fleet == [], "the non-blocking path warmed inline"


# --------------------------------------------------------------------------
# status reporting is honest
# --------------------------------------------------------------------------


class TestCoderStatusIsHonest:
    def test_never_claimed_reads_inactive(self, settings):
        st = ra.coder_status()
        assert st["active"] is False and st["claimed_by"] is None

    def test_a_lapsed_claim_still_names_who_claimed_it(self, settings):
        """'never warmed' and 'warmed and lapsed' are different operational states."""
        import time as _t

        settings[ra._CODER_ACTIVE_KEY] = "coder_lane"
        settings[ra._CODER_EXPIRES_KEY] = str(int(_t.time()) - 5)
        st = ra.coder_status()
        assert st["active"] is False
        assert st["lapsed"] is True
        assert st["claimed_by"] == "coder_lane"
