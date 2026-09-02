"""Guards for the declared-vs-actual model drift observer (#383 slice 4).

The defining test is `test_catches_the_6276_shape`. The equally important one is
`test_a_model_outside_a_minimal_warm_set_is_NOT_a_finding` — the first version of
this module warned on any dispatched model absent from the warm set and produced
22 warnings across 40 live capabilities, burying the single real one. A check
that cries wolf 21 times out of 22 is worse than no check.
"""

from __future__ import annotations

from services.calibration_drift import MIN_DISPATCHES, derive_drift, summarize


def _cap(capability, agent, model, count=50):
    return {"capability": capability, "agent": agent, "model": model, "dispatch_count": count}


# The real shape of the live `default` profile: one node reserves capacity for a
# capability, the others just declare a warm set.
_PROFILE = {
    "USS-246": {"reserved_for": "code_review", "expect_resident": ["qwen2.5:7b"]},
    "USS-245": {"expect_resident": ["llama3.2:3b"]},
    "hub": {"expect_resident": ["gemma3:12b"], "cpu_pinned": ["gemma3:12b"]},
}
_RESIDENT = {"USS-246": ["qwen2.5:7b"], "USS-245": ["llama3.2:3b"], "hub": ["gemma3:12b"]}


# --------------------------------------------------------------------------
# The finding this module exists for
# --------------------------------------------------------------------------


def test_catches_the_6276_shape():
    """USS-246 reserves for code_review and warms qwen2.5:7b; code_review
    actually dispatches P.R.O.B.E. on qwen2.5-coder:7b."""
    f = derive_drift([_cap("code_review", "P.R.O.B.E.", "qwen2.5-coder:7b", 120)], _PROFILE, _RESIDENT)
    mm = [x for x in f if x["kind"] == "reservation_mismatch"]
    assert len(mm) == 1
    assert mm[0]["capability"] == "code_review"
    assert mm[0]["model"] == "qwen2.5-coder:7b"
    assert mm[0]["promised"] == ["qwen2.5:7b"]
    assert mm[0]["node"] == "USS-246"
    assert mm[0]["severity"] == "warning"


def test_reservation_honoured_produces_no_mismatch():
    f = derive_drift([_cap("code_review", "F.O.R.G.E.", "qwen2.5:7b", 120)], _PROFILE, _RESIDENT)
    assert not [x for x in f if x["kind"] == "reservation_mismatch"]


def test_a_model_outside_a_minimal_warm_set_is_NOT_a_finding():
    """THE noise test. bias_quick legitimately runs qwen2.5:1.5b, which no node
    declares — because the profile is a MINIMAL warm set, not an allowlist. The
    first design warned here and drowned the real signal 21:1."""
    f = derive_drift([_cap("bias_quick", "B.I.A.S.", "qwen2.5:1.5b", 2751)], _PROFILE, _RESIDENT)
    assert not [x for x in f if x["severity"] == "warning"]


def test_unreserved_node_never_raises_a_mismatch():
    """hub declares gemma3:12b but reserves nothing, so a capability running
    something else there is a placement choice, not a broken promise."""
    f = derive_drift([_cap("translate", "R.O.S.E.T.T.A.", "mistral:7b", 900)], _PROFILE, _RESIDENT)
    assert not [x for x in f if x["kind"] == "reservation_mismatch"]


# --------------------------------------------------------------------------
# Demand gating — the K.I.N. 104-phantom-gaps lesson
# --------------------------------------------------------------------------


def test_reserved_capability_with_no_traffic_is_not_a_finding():
    assert not derive_drift([], _PROFILE, _RESIDENT) or not [
        x for x in derive_drift([], _PROFILE, _RESIDENT) if x["severity"] == "warning"
    ]


def test_below_threshold_traffic_is_ignored():
    f = derive_drift(
        [_cap("code_review", "P.R.O.B.E.", "qwen2.5-coder:7b", MIN_DISPATCHES - 1)],
        _PROFILE,
        _RESIDENT,
    )
    assert not [x for x in f if x["kind"] == "reservation_mismatch"]


def test_at_threshold_traffic_is_reported():
    f = derive_drift(
        [_cap("code_review", "P.R.O.B.E.", "qwen2.5-coder:7b", MIN_DISPATCHES)],
        _PROFILE,
        _RESIDENT,
    )
    assert [x for x in f if x["kind"] == "reservation_mismatch"]


def test_highest_volume_offender_is_the_one_reported():
    f = derive_drift(
        [
            _cap("code_review", "P.R.O.B.E.", "qwen2.5-coder:7b", 30),
            _cap("code_review", "OTHER", "phi4:14b", 400),
        ],
        _PROFILE,
        _RESIDENT,
    )
    mm = [x for x in f if x["kind"] == "reservation_mismatch"][0]
    assert mm["model"] == "phi4:14b" and mm["dispatch_count"] == 400


def test_a_promised_model_among_several_actuals_does_not_mask_the_offender():
    f = derive_drift(
        [
            _cap("code_review", "F.O.R.G.E.", "qwen2.5:7b", 500),  # honoured
            _cap("code_review", "P.R.O.B.E.", "qwen2.5-coder:7b", 120),  # not
        ],
        _PROFILE,
        _RESIDENT,
    )
    mm = [x for x in f if x["kind"] == "reservation_mismatch"]
    assert len(mm) == 1 and mm[0]["model"] == "qwen2.5-coder:7b"


# --------------------------------------------------------------------------
# declared-but-absent — observation, never an alarm
# --------------------------------------------------------------------------


def test_declared_not_resident_is_an_observation():
    f = derive_drift([], _PROFILE, {"USS-246": ["qwen2.5:7b"], "USS-245": [], "hub": []})
    obs = [x for x in f if x["kind"] == "declared_not_resident"]
    assert obs and all(x["severity"] == "observation" for x in obs)
    assert {x["model"] for x in obs} == {"llama3.2:3b", "gemma3:12b"}


def test_cpu_pinned_models_count_as_declared():
    f = derive_drift([], {"hub": {"cpu_pinned": ["gemma3:12b"]}}, {"hub": ["gemma3:12b"]})
    assert not f


# --------------------------------------------------------------------------
# Robustness
# --------------------------------------------------------------------------


def test_malformed_input_is_skipped_not_fatal():
    f = derive_drift(
        [
            None,
            {},
            "nonsense",
            {"capability": "code_review"},
            _cap("code_review", "P.R.O.B.E.", "qwen2.5-coder:7b", 99),
        ],
        {"USS-246": {"reserved_for": "code_review", "expect_resident": ["qwen2.5:7b"]}, "bad": "not-a-dict"},
        _RESIDENT,
    )
    assert [x for x in f if x["kind"] == "reservation_mismatch"]


def test_empty_everything_is_clean_not_crash():
    assert derive_drift([], {}, {}) == []
    assert derive_drift(None, None, None) == []


def test_summarize_all_clear_and_mismatch():
    assert "none" in summarize([])
    s = summarize(derive_drift([_cap("code_review", "P.R.O.B.E.", "qwen2.5-coder:7b", 120)], _PROFILE, _RESIDENT))
    assert "MISMATCH" in s and "qwen2.5-coder:7b" in s


def test_a_model_declared_twice_on_a_node_is_reported_once():
    """The hub lists gemma3:12b in BOTH expect_resident and cpu_pinned. Without
    deduping, one absence reports as two problems and inflates any count built
    on these findings."""
    f = derive_drift([], {"hub": {"expect_resident": ["gemma3:12b"], "cpu_pinned": ["gemma3:12b"]}}, {})
    absent = [x for x in f if x["kind"] == "declared_not_resident"]
    assert len(absent) == 1
