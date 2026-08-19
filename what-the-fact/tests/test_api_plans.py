"""Guards for API-key plans and key handling (tasks #2138 / #2140).

STDLIB-ONLY imports by path, for the reason `rate_policy` itself records: a guard
that pulls in Flask reports `s` (skipped) on a machine without it while the suite
still prints "passed" (KB #290497). Credential handling is precisely the code
that must not be silently untested.

THE CENTRAL INVARIANT — a plan upgrade can never give a caller LESS.
That is easy to break by hand and impossible to see in review: "5 per hour" for
anonymous versus "50 per day" for a paid key reads as generous and is actually a
58% cut. So the windows are asserted IDENTICAL across plans and the limits
NON-DECREASING, rather than trusted.
"""

import importlib.util
import pathlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]


def _load(name, rel):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)          # stdlib-only: this can never skip
    return mod


rp = _load("_rate_policy", "consumer/rate_policy.py")
ak = _load("_api_key_policy", "consumer/api_key_policy.py")


# ── plan ladder ───────────────────────────────────────────────────────────────

def test_every_plan_covers_every_tier():
    """A tier missing from one plan silently falls back to anonymous limits —
    which looks like a downgrade bug to the user and is invisible in review."""
    tiers = set(rp.PLANS[rp.DEFAULT_PLAN])
    for plan, table in rp.PLANS.items():
        assert set(table) == tiers, f"plan '{plan}' tier set differs: {set(table) ^ tiers}"


@pytest.mark.parametrize("tier", sorted(rp.PLANS["anonymous"]))
def test_windows_are_identical_across_plans(tier):
    """Comparability. Different windows per plan make 'more generous' unprovable."""
    windows = {plan: rp.limits_for(tier, plan)[1] for plan in rp.PLAN_ORDER}
    assert len(set(windows.values())) == 1, f"{tier} windows differ across plans: {windows}"


@pytest.mark.parametrize("tier", sorted(rp.PLANS["anonymous"]))
def test_limits_never_decrease_as_plan_escalates(tier):
    """THE invariant. Upgrading must never take capability away."""
    limits = [rp.limits_for(tier, plan)[0] for plan in rp.PLAN_ORDER]
    assert limits == sorted(limits), f"{tier} limits not monotonic across {rp.PLAN_ORDER}: {limits}"
    assert limits[0] < limits[-1], f"{tier}: paid is no better than anonymous ({limits})"


def test_anonymous_plan_is_unchanged_from_the_pre_key_policy():
    """No existing public caller may be newly throttled by introducing keys.
    POLICY is the pre-#2138 table and is the reference."""
    for tier, expected in rp.POLICY.items():
        assert rp.limits_for(tier, "anonymous") == expected, f"{tier} anonymous limit changed"


def test_score_tier_preserves_the_long_standing_five_per_day():
    """tech/routes.py has shipped 5/day/IP on /api/v1/score for a long time.
    Keys may raise it; introducing plans must not lower it."""
    assert rp.limits_for("score", "anonymous") == (5, 86400)


def test_unknown_plan_falls_back_to_least_privilege():
    for bogus in ("", "admin", "PAID", "enterprise", None):
        assert rp.limits_for("default", bogus) == rp.PLANS["anonymous"]["default"]


def test_higher_plan_picks_the_better_and_unknown_names_do_not_escalate():
    assert rp.higher_plan("anonymous", "paid") == "paid"
    assert rp.higher_plan("paid", "keyed") == "paid"
    assert rp.higher_plan("keyed", "keyed") == "keyed"
    # a typo must not outrank a real plan
    assert rp.higher_plan("superuser", "keyed") == "keyed"
    assert rp.higher_plan("keyed", "superuser") == "keyed"


def test_plan_for_resolution():
    assert rp.plan_for(False, False) == "anonymous"
    assert rp.plan_for(True, False) == "keyed"
    assert rp.plan_for(False, True) == "paid"
    assert rp.plan_for(True, True) == "paid"


# ── prune window: the trap ────────────────────────────────────────────────────

def test_longest_window_spans_plans_not_just_policy():
    """Pruning on a SHORTER window refills a LONGER budget. POLICY tops out at
    3600s while `score` runs on 86400s, so a POLICY-only max would hand an abuser
    a fresh 5-per-day allowance every hour."""
    policy_only = max(w for _, w in rp.POLICY.values())
    assert rp.longest_window() >= policy_only
    every_window = [w for t in rp.PLANS.values() for _, w in t.values()]
    assert rp.longest_window() == max(max(every_window), policy_only)
    assert rp.longest_window() > policy_only, "the score tier should exceed POLICY's max"


def test_score_path_classifies_to_its_own_tier():
    assert rp.classify("/api/v1/score") == "score"
    assert rp.classify("/api/v1/articles") == "default"


# ── key handling ──────────────────────────────────────────────────────────────

def test_generated_key_roundtrips_and_the_secret_is_not_the_hash():
    full, prefix, key_hash = ak.generate_key()
    parsed = ak.parse_key(full)
    assert parsed is not None
    assert parsed[0] == prefix
    assert ak.verify_secret(parsed[1], key_hash)
    # the stored hash must not be the secret, or storage is plaintext by another name
    assert parsed[1] not in key_hash
    assert key_hash != parsed[1]


def test_keys_are_unique_across_many_generations():
    seen = {ak.generate_key()[1] for _ in range(500)}
    assert len(seen) == 500, "prefix collisions — entropy or slicing is wrong"


def test_wrong_secret_is_rejected():
    _full, _prefix, key_hash = ak.generate_key()
    other_full, _p2, _h2 = ak.generate_key()
    assert ak.verify_secret(ak.parse_key(other_full)[1], key_hash) is False
    assert ak.verify_secret("", key_hash) is False
    assert ak.verify_secret("x", key_hash) is False


@pytest.mark.parametrize(
    "junk",
    [
        None, "", "   ", "x", "wtf_short_abc",
        "evil_aaaaaaaaaaaa_bbbb",           # wrong namespace
        "wtf_aaaaaaaaaaaa",                 # no secret
        "wtf_aaaaaaaaaaaa_bad!chars",       # charset
        "wtf_" + "a" * 12 + "_" + "b" * 500,  # absurd length
        "wtf_" + "a" * 11 + "_bbbb",        # prefix one char short
        "wtf_aaaaaaaaaaaa_bbbb_extra",      # too many segments
    ],
)
def test_malformed_keys_are_refused_before_any_db_query(junk):
    assert ak.parse_key(junk) is None


def test_redact_never_echoes_the_secret():
    full, prefix, _h = ak.generate_key()
    secret = ak.parse_key(full)[1]
    out = ak.redact(full)
    assert prefix in out
    assert secret not in out
    assert ak.redact("garbage") == "<invalid key>"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
