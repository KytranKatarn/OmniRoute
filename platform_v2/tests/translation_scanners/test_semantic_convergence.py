"""The semantic QA sweep must CONVERGE — it must record what it reviewed.

THE BUG (measured 2026-09-07):

`orchestrator._semantic_candidate_rows` selects rows on
    last_semantic_review_at IS NULL OR < NOW() - INTERVAL '30 days'
but NOTHING in the QA path ever wrote that column. The only writers were
`generator.py:282/289`, which fire when a NEW translation is created.
`SemanticScanner.scan()` was a pure generator with no write-back.

So every scan re-attempted the same rows, forever. Measured state at the time:
    never_reviewed = 34,343   reviewed = 4,018
and all 4,018 had been stamped by the generator, never by the scanner.

That non-convergence is what drove ~13,000 translate dispatches/30d at the hub and
6,309 admission-cap sheds — against a translation corpus that is COMPLETE (every
language 4,468-4,579 approved, 9 rows pending review, ZERO open `missing` gaps).
It was re-verification of finished work, on an infinite loop.

⚠️ THE INVARIANT THAT MATTERS MOST is the negative one: a row that was NOT actually
evaluated must NOT be stamped. Stamping a short-skip or a shed dispatch buys 30 days
of silence on a string nobody checked — "unmonitored while appearing monitored", the
failure shape this codebase keeps rediscovering.

Run from platform_v2/:
    docker exec archie_platform python3 -m pytest tests/translation_scanners/test_semantic_convergence.py -v
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # platform_v2 on path

from tools.consciousness.translation_scanners import semantic_scanner as ss  # noqa: E402
from tools.consciousness.translation_scanners.semantic_scanner import SemanticScanner  # noqa: E402


def _row(rid, text, lang="fr", en="Save your changes to continue"):
    return {"id": rid, "language": lang, "key": f"k{rid}", "text": text, "source_en_text": en}


# ── the positive case: evaluated rows get recorded ───────────────────────────


def test_evaluated_rows_are_recorded(monkeypatch):
    """A row that got a real back-translation must be marked reviewed —
    INCLUDING when it passes QA, which is the majority case on a healthy corpus."""
    monkeypatch.setattr(ss, "back_translate_to_en", lambda t, l: "Save your changes to continue")
    rows = [
        _row(1, "Enregistrez vos modifications pour continuer"),
        _row(2, "Enregistrez vos modifications pour continuer"),
    ]
    scanner = SemanticScanner(source="site", rows=rows)
    list(scanner.scan())
    assert scanner.reviewed_ids == [1, 2], (
        "rows that were successfully back-translated must be recorded, or the sweep " "re-attempts them forever"
    )


def test_a_flagged_row_is_still_recorded_as_reviewed(monkeypatch):
    """Yielding a gap means the row WAS evaluated — it must still be stamped, else
    every genuinely-bad row is re-reviewed on every single run."""
    monkeypatch.setattr(ss, "back_translate_to_en", lambda t, l: "completely unrelated text")
    scanner = SemanticScanner(source="site", rows=[_row(7, "Enregistrez vos modifications pour continuer")])
    results = list(scanner.scan())
    assert results, "a low-similarity row should yield a gap"
    assert scanner.reviewed_ids == [7]


# ── the negative case: this is the one that must never regress ───────────────


def test_a_shed_or_failed_dispatch_is_NOT_recorded(monkeypatch):
    """An empty back-translation means the dispatch was shed/failed. The row was
    NOT reviewed and must stay eligible."""
    monkeypatch.setattr(ss, "back_translate_to_en", lambda t, l: "")
    scanner = SemanticScanner(source="site", rows=[_row(3, "Enregistrez vos modifications pour continuer")])
    list(scanner.scan())
    assert scanner.reviewed_ids == [], (
        "a shed dispatch must NOT be stamped — stamping it hides an unchecked string " "for 30 days"
    )


def test_whitespace_only_back_translation_is_NOT_recorded(monkeypatch):
    monkeypatch.setattr(ss, "back_translate_to_en", lambda t, l: "   \n  ")
    scanner = SemanticScanner(source="site", rows=[_row(4, "Enregistrez vos modifications pour continuer")])
    list(scanner.scan())
    assert scanner.reviewed_ids == []


def test_short_skip_is_NOT_recorded(monkeypatch):
    """Short strings never reach the model, so they were never reviewed."""
    called = []
    monkeypatch.setattr(ss, "back_translate_to_en", lambda t, l: called.append(t) or "back")
    scanner = SemanticScanner(source="site", rows=[_row(5, "Oui")])
    list(scanner.scan())
    assert called == [], "short strings must not be dispatched at all"
    assert scanner.reviewed_ids == []


def test_mixed_batch_records_only_the_evaluated_ones(monkeypatch):
    """The realistic case: some evaluated, some shed, some too short."""

    def fake_back(text, lang):
        return "" if "SHED" in text else "Save your changes to continue"

    monkeypatch.setattr(ss, "back_translate_to_en", fake_back)
    rows = [
        _row(10, "Enregistrez vos modifications pour continuer"),  # evaluated
        _row(11, "SHED this one please entirely"),  # shed
        _row(12, "Non"),  # too short
        _row(13, "Enregistrez vos modifications pour continuer"),  # evaluated
    ]
    scanner = SemanticScanner(source="site", rows=rows)
    list(scanner.scan())
    assert scanner.reviewed_ids == [10, 13]


def test_rows_without_an_id_do_not_crash_the_scan(monkeypatch):
    """Defensive: a row missing 'id' must not raise mid-sweep."""
    monkeypatch.setattr(ss, "back_translate_to_en", lambda t, l: "Save your changes to continue")
    rows = [
        {"language": "fr", "key": "x", "text": "Enregistrez vos modifications pour continuer", "source_en_text": "Save"}
    ]
    scanner = SemanticScanner(source="site", rows=rows)
    list(scanner.scan())
    assert scanner.reviewed_ids == []


# ── the orchestrator half ────────────────────────────────────────────────────


def test_stamp_helper_is_a_noop_on_empty_input():
    from tools.consciousness.translation_scanners import orchestrator as orch

    assert orch._stamp_semantic_reviewed([]) == 0
    assert orch._stamp_semantic_reviewed(None) == 0
    assert orch._stamp_semantic_reviewed([None, None]) == 0


def test_stamp_helper_fails_soft(monkeypatch):
    """A DB error must never abort the scan pass — a missed stamp only costs a
    repeated review next run."""
    from tools.consciousness.translation_scanners import orchestrator as orch

    def boom(*a, **k):
        raise RuntimeError("simulated DB failure")

    monkeypatch.setattr(orch, "get_db_cursor", boom)
    assert orch._stamp_semantic_reviewed([1, 2, 3]) == 0  # swallowed, not raised
