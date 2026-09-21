"""#6029's prose gate could not see a unicode bullet behind a diff marker (#6817 part 2a).

`_UNICODE_BULLET_RE` is matched on the RAW evidence, deliberately, so the `^[+-]\\s?` strip in
`_evidence_is_prose_not_code` cannot eat a markdown bullet. But its anchor was `^\\s*`, and
evidence is quoted FROM A DIFF — so it arrives as `+⚠️ **prose**`, the anchor hits the `+`, and
the bullet is never reached. The regex handled `⚠️ prose` and missed `+⚠️ prose`, which is the
only shape that actually occurs.

MEASURED: PR #3406 — a 4-line `.md`-only regeneration of the capability index — blocked with
`[WARNING] Potential false positives in review coverage reporting` whose Evidence was
`+⚠️ **The note distinguishes two causes with OPPOSITE remedies**`: a markdown SENTENCE
describing `coverage_dropped_paths()`, reviewed as that function. `_evidence_is_prose_not_code`
returned False on it. Verbatim from `forge_reviews.summary`, pr3406 att1.

This is the general fix for "prose reviewed as code" — and it is strictly better than the
alternative #6817 floated (skip review for `.md`-only diffs), for two reasons:
  * skipping would REDUCE safety on `.claude/rules/*.md`, which are INSTRUCTIONS to agents and
    have a documented history of carrying false claims (the phantom `backups` table, the
    non-existent `sc-live` classes, a Beacon IP pointing at a decommissioned host);
  * only 4 of ~100 recent PRs were `.md`-only, while a MIXED code+docs PR carries exactly the
    same hazard and a file-extension rule would miss every one of them.

⚠️ MUST_KEEP is the half that matters: the gate demotes, so widening it wrongly would silence
real findings. Allowing `-` as well as `+` is safe HERE only because a unicode bullet is never a
diff marker — the file's own comment rightly refuses the same widening for ASCII `-` bullets,
where `- text` is genuinely ambiguous between a markdown bullet and a removed code line.
"""

from __future__ import annotations

import pytest

from tools.repair_bay.services.pr_diff_analyzer import _evidence_is_prose_not_code

# Prose. Each must be recognised as prose so a finding citing it cannot block.
IS_PROSE = [
    # VERBATIM, forge_reviews.summary pr3406 att1 — the case that motivated this.
    ("#3406 markdown sentence behind '+'", "+⚠️ **The note distinguishes two causes with OPPOSITE remedies**"),
    # The #3089 house style the original gate was written for, now also behind a marker.
    ("#3089 '·' bullet behind '+'", "+· the index documents its own regenerated status"),
    # Pre-existing behaviour, must not regress.
    ("unicode bullet with no diff marker", "⚠️ the plan argues from the spec"),
    # A deleted prose line is still prose; polarity owns the removed-ness, not this gate.
    ("removed prose line", "-⚠️ **a sentence that was deleted**"),
]

# Code. Each must still be blockable.
MUST_KEEP = [
    ("an added def", "+def is_inference_path(path):"),
    ("a YAML list item", "+  - name: Build"),
    ("a removed code line", "-    return None"),
    ("an assignment", "+    excluded = len(rows) - len(considered)"),
    ("a call", "+    coverage_dropped_paths(summary)"),
    ("a dict/key-value line", "+    'verdict': 'APPROVE',"),
]


@pytest.mark.parametrize("label,evidence", IS_PROSE, ids=[c[0][:38] for c in IS_PROSE])
def test_prose_evidence_is_recognised(label, evidence):
    assert _evidence_is_prose_not_code({"evidence": evidence}) is True, label


@pytest.mark.parametrize("label,evidence", MUST_KEEP, ids=[c[0][:38] for c in MUST_KEEP])
def test_code_evidence_is_never_called_prose(label, evidence):
    assert _evidence_is_prose_not_code({"evidence": evidence}) is False, label


def test_it_fails_closed_on_nothing():
    for issue in ({}, {"evidence": ""}, {"evidence": "   "}, None):
        assert _evidence_is_prose_not_code(issue) is False
