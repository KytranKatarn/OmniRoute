"""Unit tests for the audit_pipeline fix-generation search/replace applier.

The keystone bug: the old flow diffed the FULL source against a short model reply,
so any file > ~200 lines produced a whole-file-deletion diff. `_apply_targeted_fix`
is fail-closed — it splices a minimal {find, replace} into the full source and
refuses anything unparseable, un-locatable, ambiguous, or destructive.
"""

from __future__ import annotations

import json
import sys

if "/app" not in sys.path:
    sys.path.insert(0, "/app")

from services import audit_pipeline as ap  # noqa: E402


def test_parse_fix_json_plain():
    assert ap._parse_fix_json('{"find": "a", "replace": "b"}') == {"find": "a", "replace": "b"}


def test_parse_fix_json_fenced():
    assert ap._parse_fix_json('```json\n{"find":"a","replace":"b"}\n```') == {"find": "a", "replace": "b"}


def test_parse_fix_json_prose():
    assert ap._parse_fix_json('Sure:\n{"find":"a","replace":"b"}\ndone') == {"find": "a", "replace": "b"}


def test_parse_fix_json_garbage():
    assert ap._parse_fix_json("no json here") is None
    assert ap._parse_fix_json("") is None
    assert ap._parse_fix_json("[1, 2, 3]") is None  # not an object


def test_apply_targeted_fix_happy_is_minimal():
    src = "line1\nBAD = eval(user)\nline3\n"
    resp = json.dumps({"find": "BAD = eval(user)", "replace": "SAFE = int(user)"})
    fixed, reason = ap._apply_targeted_fix(src, resp)
    assert reason == "ok"
    # Exactly the one line changed — nothing else touched.
    assert fixed == "line1\nSAFE = int(user)\nline3\n"


def test_apply_targeted_fix_not_located():
    fixed, reason = ap._apply_targeted_fix("a\nb\nc\n", json.dumps({"find": "zzz", "replace": "q"}))
    assert fixed is None and reason == "find_not_located"


def test_apply_targeted_fix_ambiguous():
    fixed, reason = ap._apply_targeted_fix("x\nx\nx\n", json.dumps({"find": "x\n", "replace": "y\n"}))
    assert fixed is None and reason == "find_ambiguous"


def test_apply_targeted_fix_unparseable():
    fixed, reason = ap._apply_targeted_fix("abc", "not json at all")
    assert fixed is None and reason == "unparseable"


def test_apply_targeted_fix_missing_fields():
    fixed, reason = ap._apply_targeted_fix("abc", json.dumps({"find": "a"}))
    assert fixed is None and reason == "missing_find_or_replace"


def test_apply_targeted_fix_no_change():
    fixed, reason = ap._apply_targeted_fix("abc\n", json.dumps({"find": "abc", "replace": "abc"}))
    assert fixed is None and reason == "no_change"


def test_apply_targeted_fix_rejects_destructive_whole_file():
    # The exact old bug: a short reply that would gut a big file.
    big = "KEEP\n" + ("payload line\n" * 500)
    tail = "payload line\n" * 500  # the whole body, appears once
    resp = json.dumps({"find": tail, "replace": "x"})
    fixed, reason = ap._apply_targeted_fix(big, resp)
    assert fixed is None and reason == "destructive_shrink"
