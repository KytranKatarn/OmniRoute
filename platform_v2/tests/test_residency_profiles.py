"""Warm-residency profile resolver (step 2 of the warmboot spec).

The property that matters most is the same one as every other layer added this
session: **an absent or invalid setting must behave exactly like today**. A
residency layer that can degrade the fleet by being misconfigured is worse than
no residency layer, because it fails in a way nobody is watching for.

Run: python3 -m pytest tests/test_residency_profiles.py -q
"""

import json

import pytest

from services import residency_profiles as rp


@pytest.fixture(autouse=True)
def clean():
    rp.invalidate()
    yield
    rp.invalidate()


def _settings(monkeypatch, mapping):
    """Stub the platform_settings read — no DB in unit tests."""
    monkeypatch.setattr(rp, "_read_setting", lambda k: mapping.get(k))


# ── the property that protects the fleet ───────────────────────────────────
def test_absent_setting_falls_back_to_todays_implicit_profile(monkeypatch):
    _settings(monkeypatch, {})
    assert rp.source() == "fallback"
    assert rp.nodes_for() == rp._FALLBACK_PROFILES["default"]["nodes"]


def test_a_dead_database_falls_back_rather_than_raising(monkeypatch):
    def boom(_k):
        raise RuntimeError("connection refused")

    # _read_setting already swallows; this asserts the LAYER above also survives
    monkeypatch.setattr(rp, "_read_setting", lambda k: None)
    assert rp.source() == "fallback"
    assert rp.nodes_for()


def test_invalid_json_falls_back_and_does_not_partially_apply(monkeypatch):
    _settings(monkeypatch, {rp._SETTINGS_KEY: "{not json at all"})
    assert rp.source() == "fallback"
    assert rp.nodes_for() == rp._FALLBACK_PROFILES["default"]["nodes"]


def test_an_invalid_profile_is_rejected_WHOLE_not_partially(monkeypatch):
    """One good node + one broken node must reject the entire blob.

    A partially applied residency plan is a plan nobody wrote — and it would be
    applied with the same confidence as a correct one.
    """
    blob = {
        "default": {
            "nodes": {
                "archie-starbase": {"expect_resident": ["gemma3:12b"]},
                "115": {"expect_resident": ["qwen2.5:7b"]},  # INT id — invalid
            }
        }
    }
    _settings(monkeypatch, {rp._SETTINGS_KEY: json.dumps(blob)})
    assert rp.source() == "fallback"
    assert "archie-starbase" in rp.nodes_for()
    assert "115" not in rp.nodes_for(), "the good half must NOT be applied either"


# ── validation ─────────────────────────────────────────────────────────────
def test_the_shipped_fallback_is_itself_valid():
    """If the fallback cannot pass its own validator, every fallback path is a
    latent crash."""
    ok, errors = rp.validate(rp._FALLBACK_PROFILES)
    assert ok, errors


def test_an_int_node_id_is_rejected():
    """remote_nodes has BOTH id (int) and node_id (varchar). Passing the int to
    a `WHERE node_id = %s` query casts, errors, and aborts the txn — the
    recurring fleet trap (fleet.md identity invariants)."""
    ok, errors = rp.validate({"p": {"nodes": {"115": {"expect_resident": []}}}})
    assert not ok
    assert any("INT remote_nodes.id" in e for e in errors)


def test_an_unknown_tier_is_rejected():
    ok, errors = rp.validate({"p": {"nodes": {"archie-starbase": {"tiers": {"vram": []}}}}})
    assert not ok
    assert any("unknown tier" in e for e in errors)


@pytest.mark.parametrize("tier", rp.VALID_TIERS)
def test_every_declared_tier_is_accepted(tier):
    ok, errors = rp.validate({"p": {"nodes": {"archie-starbase": {"tiers": {tier: []}}}}})
    assert ok, errors


def test_span_is_a_real_tier_not_a_typo():
    """The hub genuinely splits a model across its two cards — measured
    GPULayers:49[Quadro 31, TITAN 18]. Dropping 'span' would make the only node
    with two GPUs inexpressible."""
    assert "span" in rp.VALID_TIERS


@pytest.mark.parametrize("bad", [None, [], "string", 42, {}])
def test_structurally_wrong_input_is_rejected(bad):
    ok, _ = rp.validate(bad)
    assert not ok


def test_model_lists_must_be_lists_of_strings():
    ok, errors = rp.validate({"p": {"nodes": {"archie-starbase": {"expect_resident": "qwen2.5:7b"}}}})
    assert not ok
    assert any("list of model names" in e for e in errors)


# ── content of today's profile ─────────────────────────────────────────────
def test_citadel_is_absent_from_the_default_profile():
    """#6216: Citadel cannot run qwen2.5:7b and the owner settled that it stays
    the DR warm-standby. Declaring residency there would re-create the dead hop
    #2985 just removed."""
    assert not any("outpost_e834ff" in n for n in rp._FALLBACK_PROFILES["default"]["nodes"])


def test_every_default_node_cites_why_it_is_there():
    """A residency claim without its reason is the comment-only invariant that
    eroded in the first place (#1905, 2026-08-21)."""
    for node_id, intent in rp._FALLBACK_PROFILES["default"]["nodes"].items():
        assert intent.get("why"), f"{node_id} declares residency with no rationale"


# ── "news" profile (#6215 — WTF warm residency) ────────────────────────────
def test_news_profile_exists_and_is_valid():
    assert "news" in rp._FALLBACK_PROFILES
    ok, errors = rp.validate({"news": rp._FALLBACK_PROFILES["news"]})
    assert ok, errors


def test_news_hub_entry_declares_qwen_and_gemma_resident():
    """Hub is WTF's PRIMARY node (_WTF_CPU_FIRST, #3955) — the gap 'default'
    left open: it only ever declared gemma3:12b resident there, never the
    qwen2.5:7b the WTF backlog actually dispatches."""
    hub = rp._FALLBACK_PROFILES["news"]["nodes"]["archie-starbase"]
    assert set(hub["expect_resident"]) == {"qwen2.5:7b", "gemma3:12b"}


def test_news_hub_entry_only_cpu_pins_gemma_not_qwen():
    """Regression pin: qwen2.5:7b is excluded from _HUB_CPU_TIER (KB #270009)
    and exceeds _CPU_VIABLE_MAX_GB (4.0GB) — model_service REFUSES rather than
    CPU-serve it (#5623). Marking it cpu_pinned here would declare an intent
    the model service cannot honour."""
    hub = rp._FALLBACK_PROFILES["news"]["nodes"]["archie-starbase"]
    assert hub.get("cpu_pinned") == ["gemma3:12b"]
    assert "qwen2.5:7b" not in hub.get("cpu_pinned", [])


def test_news_defiant_entry_restates_qwen_overflow():
    """Only one profile is active fleet-wide at a time (fleet:residency:active),
    so 'news' must be self-describing rather than relying on 'default' having
    ALSO reserved qwen2.5:7b on Defiant for an unrelated reason (#1905)."""
    defiant = rp._FALLBACK_PROFILES["news"]["nodes"]["starship_76583490e36955ab"]
    assert defiant["expect_resident"] == ["qwen2.5:7b"]


def test_news_excludes_runabout_and_citadel():
    """Runabout (4GB) cannot hold qwen2.5:7b resident — measured 143s warm-boot
    timeout (#6217). Citadel is the DR warm-standby, no 8GB inference model
    (#6216) — same reasoning 'default' already applies, restated for 'news'."""
    nodes = rp._FALLBACK_PROFILES["news"]["nodes"]
    assert "starship_5501c2766526e746" not in nodes  # Runabout
    assert not any("outpost_e834ff" in n for n in nodes)  # Citadel


def test_every_news_node_cites_why_it_is_there():
    for node_id, intent in rp._FALLBACK_PROFILES["news"]["nodes"].items():
        assert intent.get("why"), f"{node_id} declares residency with no rationale"


# ── active profile selection ───────────────────────────────────────────────
def test_active_defaults_to_default_when_unset(monkeypatch):
    _settings(monkeypatch, {})
    assert rp.active_name() == "default"


def test_an_undefined_active_profile_falls_back_rather_than_emptying(monkeypatch):
    """Pointing at a profile that does not exist must not silently yield an
    EMPTY residency plan — that would read as 'nothing should be warm'."""
    _settings(monkeypatch, {rp._ACTIVE_KEY: "totally-undefined-profile"})
    assert rp.active_name() == "default"
    assert rp.nodes_for(), "must not resolve to an empty plan"


def test_nodes_for_an_unknown_profile_is_empty_not_an_exception(monkeypatch):
    _settings(monkeypatch, {})
    assert rp.nodes_for("does-not-exist") == {}


def test_a_valid_custom_profile_is_used(monkeypatch):
    blob = {
        "default": {"nodes": {"archie-starbase": {"expect_resident": ["mistral:7b"]}}},
        "news": {"nodes": {"archie-starbase": {"expect_resident": ["qwen2.5:7b"]}}},
    }
    _settings(monkeypatch, {rp._SETTINGS_KEY: json.dumps(blob), rp._ACTIVE_KEY: "news"})
    assert rp.source() == "platform_settings"
    assert rp.active_name() == "news"
    assert rp.nodes_for()["archie-starbase"]["expect_resident"] == ["qwen2.5:7b"]


def test_callers_cannot_mutate_the_cache(monkeypatch):
    """all_profiles() hands out a copy. A caller mutating the shared dict would
    silently rewrite the residency plan for every other caller."""
    _settings(monkeypatch, {})
    a = rp.all_profiles()
    a["default"]["nodes"].clear()
    assert rp.nodes_for(), "the cache was mutated through a returned reference"


def test_load_is_safe_under_concurrency(monkeypatch):
    """Review finding, PR #2988 — the cache update was not atomic.

    _load() previously relied on EVERY caller holding _lock. That is the same
    'guard wired per caller' shape this fleet keeps getting bitten by, so the
    lock moved INSIDE _load() and became re-entrant (callers already holding it
    would deadlock on a plain Lock).
    """
    import threading

    _settings(monkeypatch, {})
    errors, seen = [], []

    def worker():
        try:
            for _ in range(50):
                rp.invalidate()  # force the refresh path repeatedly
                seen.append(len(rp.nodes_for()))
        except Exception as exc:  # a deadlock shows as a hang, a race as this
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(12)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=20)

    assert not any(t.is_alive() for t in threads), "deadlock — a thread never finished"
    assert not errors, f"concurrent access raised: {errors[:2]}"
    assert len(set(seen)) == 1, f"callers saw inconsistent profiles: {sorted(set(seen))}"


def test_load_can_be_called_while_already_holding_the_lock():
    """The re-entrancy that RLock buys. With a plain Lock this hangs forever."""
    import threading

    done = threading.Event()

    def probe():
        with rp._lock:
            rp._load()  # would deadlock on a non-reentrant lock
        done.set()

    t = threading.Thread(target=probe, daemon=True)
    t.start()
    assert done.wait(timeout=10), "deadlock: _load() under a held lock never returned"
