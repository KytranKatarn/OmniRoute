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


def test_build_fix_diff_uses_repo_relative_header():
    import services.audit_pipeline as ap

    old = "def f():\n    return 1\n"
    new = "def f():\n    return 2\n"
    rel = "platform_v2/tools/department_hq/services/department_dispatcher.py"

    diff_text, stats = ap._build_fix_diff(old, new, rel)

    # git apply (from the worktree root) needs the FULL repo-relative path,
    # never a basename — a/department_dispatcher.py can't be located.
    assert f"--- a/{rel}" in diff_text
    assert f"+++ b/{rel}" in diff_text
    assert "department_dispatcher.py\n" not in diff_text.split("---")[1][:80] or rel in diff_text
    assert stats.get("added", 0) >= 1 and stats.get("removed", 0) >= 1


def test_build_fix_diff_is_well_formed_git_appliable_diff():
    """The exact bug found in live end-to-end verification: CodeDiffEngine's
    lineterm="" output collapses the ---/+++/@@ headers onto ONE line, which
    git apply rejects and the sandbox gate's line-start '+++ b/' parser can't
    find. This test proves _build_fix_diff produces a real, well-formed
    unified diff: each header on its own newline-terminated line, and exactly
    one line starting with '+++ b/' — precisely how the sandbox gate parses
    apply targets.
    """
    import services.audit_pipeline as ap

    old = "def f():\n" "    x = 1\n" "    y = 2\n" "    return x\n"
    new = "def f():\n" "    x = 1\n" "    y = 3\n" "    return x\n"
    rel = "platform_v2/validation.py"

    diff_text, stats = ap._build_fix_diff(old, new, rel)

    # Headers must be on their own newline-terminated lines, not collapsed
    # together with the hunk content.
    assert f"--- a/{rel}\n" in diff_text
    assert f"+++ b/{rel}\n" in diff_text

    lines = diff_text.splitlines()
    plus_header_lines = [ln for ln in lines if ln.startswith("+++ b/")]
    # Exactly one +++ b/ line — this is exactly how the sandbox gate locates
    # the target file. If the headers collapsed onto one giant line, this
    # would be 0 (the gate would see "diff has no target files").
    assert len(plus_header_lines) == 1
    assert plus_header_lines[0] == f"+++ b/{rel}"

    assert any(ln.startswith("@@ ") for ln in lines)
    assert stats.get("added", 0) >= 1 and stats.get("removed", 0) >= 1
