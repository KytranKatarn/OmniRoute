"""The ensemble must not average an ABSENCE into a measurement.

`bias.score_bias()` writes a real row with score = 0.0 when it matched no
trigger terms. The old guard was `if tier1_score is None`, so that 0.0 was not
None and was blended at full 50% weight — halving every real ML lean toward
centre.

Measured over the 120,918 articles carrying both scores: 84,809 had a no-signal
heuristic row, and 41,203 of those (48.6%) sit in the wrong band. 34,732 are
published "center" while the ML score says center-right.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from ingest.bias_v2_backlog_worker import blend_ensemble  # noqa: E402


# ── the bug ───────────────────────────────────────────────────────────────────

def test_no_signal_heuristic_is_excluded_not_averaged():
    """The exact live case: v1 measured nothing, v2 says -0.256."""
    assert blend_ensemble(-0.256, 0.0, False) == pytest.approx(-0.256)


def test_the_old_behaviour_would_have_halved_it():
    """Documents what was published: -0.128, which bands as 'center'."""
    old = round(0.5 * 0.0 + 0.5 * -0.256, 3)
    assert old == pytest.approx(-0.128)
    assert blend_ensemble(-0.256, 0.0, False) != pytest.approx(old)


@pytest.mark.parametrize("v2", [-0.9, -0.5, -0.256, -0.16, 0.3, 0.7, 0.95])
def test_a_no_signal_row_never_moves_the_score(v2):
    assert blend_ensemble(v2, 0.0, False) == pytest.approx(float(v2))


# ── the heuristic still counts when it MEASURED something ─────────────────────

def test_a_real_heuristic_reading_is_still_blended():
    assert blend_ensemble(-0.256, -0.6, True) == pytest.approx(-0.428)


def test_a_genuine_centrist_heuristic_reading_still_pulls_toward_centre():
    """signal_detected=True with score 0.0 is a real finding: 'we looked, it is
    centrist'. That one SHOULD dilute — the fix must not discard it."""
    assert blend_ensemble(-0.4, 0.0, True) == pytest.approx(-0.2)


def test_missing_heuristic_row_uses_the_ml_score_alone():
    assert blend_ensemble(-0.256, None, None) == pytest.approx(-0.256)
    assert blend_ensemble(-0.256, None, True) == pytest.approx(-0.256)


# ── the NULL case must not be over-filtered ───────────────────────────────────

def test_null_signal_column_is_trusted_not_discarded():
    """A pre-migration-063 row has signal_detected NULL — unknown, not absent.

    Treating unknown as absent would silently throw away every heuristic reading
    written before the column existed. Only an explicit False is excluded.
    """
    assert blend_ensemble(-0.4, -0.6, None) == pytest.approx(-0.5)


# ── shape ─────────────────────────────────────────────────────────────────────

def test_result_is_rounded_to_three_places_when_blending():
    assert blend_ensemble(-0.3333, -0.1111, True) == pytest.approx(-0.222)


def test_accepts_numeric_strings_from_the_db_layer():
    """psycopg2 can hand back Decimal/str for NUMERIC columns."""
    assert blend_ensemble(-0.256, "0.0", False) == pytest.approx(-0.256)
    assert blend_ensemble(-0.4, "-0.6", True) == pytest.approx(-0.5)
