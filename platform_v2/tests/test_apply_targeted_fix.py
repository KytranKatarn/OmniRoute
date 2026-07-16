"""Fix C (#4939): _apply_targeted_fix must tolerate SURROUNDING whitespace on the
model's `find` string, without weakening the fail-closed guarantee.

Drain observation (KB #281385): after the plumbing fixes, the dominant fix-gen
rejection is `find_not_located` — the model returns a good {find,replace} but its
`find` isn't a byte-exact substring, most often because it wrapped the snippet in
extra leading/trailing whitespace. A guarded whitespace-trimmed fallback recovers
those, while STILL requiring a unique match and keeping the no-gut guard — so it
never reintroduces the whole-file-corruption risk PR #2291 closed.
"""

import json

import services.audit_pipeline as ap


def _resp(find, replace):
    return json.dumps({"find": find, "replace": replace})


def test_exact_match_still_works():
    src = "def foo():\n    return 1\n"
    fixed, reason = ap._apply_targeted_fix(src, _resp("return 1", "return 2"))
    assert reason == "ok"
    assert "return 2" in fixed


def test_whitespace_wrapped_find_now_matches():
    src = "def foo():\n    total = a + b + c\n    return total\n"
    fixed, reason = ap._apply_targeted_fix(src, _resp("   total = a + b + c   ", "total = a + b + c + d"))
    assert reason == "ok", f"strip-retry should have matched, got {reason}"
    assert "a + b + c + d" in fixed


def test_source_surrounding_whitespace_is_preserved():
    # strip-retry matches only the trimmed core; the source's own indentation stays.
    src = "class C:\n    def m(self):\n        value = 10\n"
    fixed, reason = ap._apply_targeted_fix(src, _resp("  value = 10  ", "value = 20"))
    assert reason == "ok"
    assert "        value = 20\n" in fixed  # 8-space indent preserved


def test_absent_find_still_rejected():
    src = "def foo():\n    return 1\n"
    fixed, reason = ap._apply_targeted_fix(src, _resp("nowhere in the source at all", "x"))
    assert fixed is None
    assert reason == "find_not_located"


def test_ambiguous_exact_find_still_rejected():
    src = "x = 1\nx = 1\n"
    fixed, reason = ap._apply_targeted_fix(src, _resp("x = 1", "x = 2"))
    assert fixed is None
    assert reason == "find_ambiguous"


def test_ambiguous_after_trim_still_rejected():
    # exact (with wrapping spaces) not found, but trimmed core appears twice -> reject
    src = "value = 10\nvalue = 10\n"
    fixed, reason = ap._apply_targeted_fix(src, _resp("  value = 10  ", "value = 20"))
    assert fixed is None
    assert reason == "find_ambiguous"


def test_trivially_short_trimmed_find_not_matched():
    # a 1-char trimmed find must not get the tolerant path
    src = "a = 1\nb = 2\n"
    fixed, reason = ap._apply_targeted_fix(src, _resp("  a  ", "aa"))
    assert fixed is None
    assert reason == "find_not_located"


def test_destructive_shrink_guard_preserved():
    src = "y" * 100 + "\nkeep = 1\n"
    fixed, reason = ap._apply_targeted_fix(src, _resp("y" * 100, ""))
    assert fixed is None
    assert reason == "destructive_shrink"
