"""Dev HQ #6624 — the evacuation-classification false-positive guard.

This is real emergency/life-safety content: an evacuation-order layer that
mis-classifies is either a false alarm (crying wolf erodes trust in the next,
real one) or a missed one (silence when there should be a warning). The
research that scoped this task flagged one concrete failure mode: a naive
substring match on "evacuat"/"vacuat" can fire on unrelated text (e.g. a
health-advisory sentence that happens to contain "vacuum"/"vacuuming"). This
test proves the actual regex used in ingest/weather/evacuations.py does not
have that failure mode, in both English and French, and that the event
allowlist gate is doing real work independent of the keyword match.
"""
from ingest.weather.evacuations import (
    _classify_evacuation,
    _EVAC_RE_EN,
    _EVAC_RE_FR,
)


def test_false_positive_vacuum_never_matches():
    text = "Health advisory: residents should avoid vacuuming carpets during the smoke event."
    assert _EVAC_RE_EN.search(text) is None
    assert _EVAC_RE_FR.search(text) is None
    is_evac, matched = _classify_evacuation("Air Quality", text, None)
    assert is_evac is False
    assert matched is None


def test_real_english_evacuation_matches():
    for phrase in [
        "Residents must evacuate immediately.",
        "An evacuation order is in effect for the following area.",
        "All persons are evacuating the affected zone.",
    ]:
        assert _EVAC_RE_EN.search(phrase) is not None, phrase


def test_real_french_evacuation_matches():
    for phrase in [
        "Les résidents doivent évacuer immédiatement.",
        "Un ordre d'évacuation est en vigueur pour le secteur suivant.",
        "Toutes les personnes évacuent la zone touchée.",
    ]:
        assert _EVAC_RE_FR.search(phrase) is not None, phrase


def test_event_allowlist_gates_independently_of_keyword_match():
    # Real evacuation language, but the event type is NOT on the allowlist
    # (e.g. a thunderstorm warning that happens to mention an unrelated
    # evacuation from a past event in its discussion text) -> must NOT match.
    is_evac, matched = _classify_evacuation(
        "Thunderstorm Warning",
        "Residents must evacuate low-lying areas.",
        None,
    )
    assert is_evac is False
    assert matched is None

    # Allowlisted event type, and real evacuation language -> must match.
    is_evac, matched = _classify_evacuation(
        "Wildfire",
        "An evacuation order has been issued for the following communities.",
        None,
    )
    assert is_evac is True
    assert matched is not None


def test_amber_alert_never_matches_even_with_evacuation_word_in_instruction():
    # An AMBER Alert is never on the allowlist, regardless of its text.
    is_evac, matched = _classify_evacuation(
        "AMBER Alert",
        "If seen, call 911. This does not require evacuation of any area.",
        None,
    )
    assert is_evac is False


def test_case_insensitive_and_word_boundary():
    assert _EVAC_RE_EN.search("EVACUATION ORDER") is not None
    assert _EVAC_RE_EN.search("Evacuating now") is not None
    # word boundary: "reevacuate" without a hyphen still starts a real word
    # boundary at 'e' before 'vacuat' is not expected to match — this project
    # accepts that edge case (re-evacuation notices are rare and would still
    # be caught by "evacuation" appearing elsewhere in the same alert text).
    assert _EVAC_RE_EN.search("preevacuation") is None
