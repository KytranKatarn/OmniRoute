"""Key figures are VERBATIM article sentences — never a summary, never furniture.

Every string this returns is rendered on the public article page as a quoted
fact. On a fact-checking site a fabricated or mis-attributed number is the worst
defect available, so the extractor quotes spans and never generates text.

Every rejection case below was observed in LIVE output, not invented.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from ingest.content_kind import extract_key_figures  # noqa: E402


def _body(sentence, times=4):
    """extract_key_figures needs >=200 chars; repeat to clear the floor."""
    return (sentence + " ") * times


# ── navigation furniture must never be quoted as a fact ───────────────────────

def test_recommendation_rail_is_not_a_key_figure():
    """Observed live: a rail glued to the body by a pre-#3029 capture. It has a
    currency figure and scans as a sentence, so grounding alone passed it."""
    rail = ("MORE ON POLITICS MORE VIDEOS Doug Ford's symbolic Lake Ontario "
            "sign cost $25k: Premier's office Ontario city says")
    assert extract_key_figures(_body(rail)) == []


@pytest.mark.parametrize("furniture", [
    "READ MORE Ontario budget hits $12 billion in new spending",
    "MOST POPULAR The deal is worth $4.2 million to the city",
    "3 hours ago The province committed $80 million to housing",
    "5 min read The fund grew by 12 percent last year",
])
def test_furniture_markers_are_rejected(furniture):
    assert extract_key_figures(_body(furniture)) == []


# ── real reporting must survive ───────────────────────────────────────────────

def test_a_real_quantified_sentence_is_kept():
    s = ("He estimates, based on publicly available figures, that the Department "
         "of Health spent around $32,000 per month on his care.")
    assert s in extract_key_figures(_body(s))


def test_acronyms_in_prose_are_not_mistaken_for_a_shouted_header():
    """The shouted-run rule must not eat ordinary sentences naming CBC, CTV, RCMP."""
    s = "The CBC and CTV both reported that 19 percent of respondents disagreed."
    assert s in extract_key_figures(_body(s))


def test_returns_verbatim_spans_only():
    s = "The city granted 88 permits, a 19 percent increase over last year."
    out = extract_key_figures(_body(s))
    assert out and all(f in _body(s) for f in out), "every figure must be a copied span"


# ── absence is honest ─────────────────────────────────────────────────────────

def test_short_or_missing_body_yields_nothing():
    assert extract_key_figures(None) == []
    assert extract_key_figures("") == []
    assert extract_key_figures("Too short to judge.") == []


def test_prose_without_figures_yields_nothing():
    s = ("The perfumer described the coastline and the way the wind carries salt "
         "inland, shaping what she wanted the blend to evoke for a visitor.")
    assert extract_key_figures(_body(s)) == []


# ── the traps that produced junk before ───────────────────────────────────────

def test_a_bare_year_is_not_a_figure():
    s = "She referred to her bestselling 2019 novel during the interview segment."
    assert extract_key_figures(_body(s)) == []


def test_a_dateline_is_not_a_figure():
    """Abbreviation-aware splitting: 'Sept.' must not end the sentence."""
    s = ("VANCOUVER, British Columbia, Sept. 01, 2026 (GLOBE NEWSWIRE) -- "
         "AVRICORE HEALTH INC. announced results today.")
    assert extract_key_figures(_body(s)) == []


def test_limit_is_respected():
    s = "The program served 1,240 patients across 61 clinics in 12 regions."
    assert len(extract_key_figures(_body(s, 30), limit=3)) <= 3
