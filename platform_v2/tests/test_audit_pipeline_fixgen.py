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


# --- #4978: no-trailing-newline diffs must carry git's marker + apply cleanly ---


def test_finalize_diff_lines_inserts_marker_for_unterminated_body_line():
    r"""A hunk body line without a trailing newline must be terminated AND
    followed by the ``\ No newline at end of file`` marker — otherwise the
    un-terminated line runs into the next and git rejects a 'corrupt patch'."""
    raw = [
        "--- a/x.py\n",
        "+++ b/x.py\n",
        "@@ -1,2 +1,2 @@\n",
        " line1\n",
        "-last = eval(x)",  # difflib emits the last line WITHOUT a newline
        "+last = int(x)",
    ]
    out = ap._finalize_diff_lines(raw)
    text = "".join(out)
    # Both un-terminated body lines are now newline-terminated and each is
    # followed by its own marker line.
    assert "-last = eval(x)\n\\ No newline at end of file\n" in text
    assert "+last = int(x)\n\\ No newline at end of file\n" in text
    # No two body lines are merged onto one physical line.
    assert "-last = eval(x)+last = int(x)" not in text


def test_finalize_diff_lines_control_leaves_terminated_diff_untouched():
    """When every body line already ends in a newline, output is byte-identical
    (no spurious markers) — the common case must be unchanged."""
    raw = [
        "--- a/x.py\n",
        "+++ b/x.py\n",
        "@@ -1,2 +1,2 @@\n",
        " line1\n",
        "-last = eval(x)\n",
        "+last = int(x)\n",
    ]
    assert ap._finalize_diff_lines(raw) == raw


def test_finalize_diff_lines_does_not_mistake_dash_content_for_header():
    """A removed/added CONTENT line whose text begins with '--'/'++' must be
    treated as a hunk body line (marker-eligible), never as a '--- a/' header —
    markers are only inserted after the first @@."""
    raw = [
        "--- a/x.py\n",
        "+++ b/x.py\n",
        "@@ -1,2 +1,2 @@\n",
        " a\n",
        "--- SQL comment tail",  # removed line, content is "-- SQL comment tail", no \n
        "+-- SQL comment FIXED",
    ]
    out = ap._finalize_diff_lines(raw)
    text = "".join(out)
    # File headers untouched (still exactly one each, newline-terminated).
    assert text.count("--- a/x.py\n") == 1
    assert text.count("+++ b/x.py\n") == 1
    # The dash-content body lines got terminated + marked.
    assert "--- SQL comment tail\n\\ No newline at end of file\n" in text


def test_build_fix_diff_no_trailing_newline_applies_via_git():
    """End-to-end proof of #4978: a fix that touches a last line lacking a
    trailing newline produces a patch that `git apply` accepts and applies to
    exactly the intended content. Before the fix this failed 'corrupt patch'."""
    import os
    import shutil
    import subprocess
    import tempfile

    import pytest

    if not shutil.which("git"):
        pytest.skip("git not available")

    rel = "x.py"
    cases = {
        "old_no_nl__new_no_nl": ("line1\nlast = eval(x)", "line1\nlast = int(x)"),
        "old_nl__new_no_nl": ("line1\nlast = eval(x)\n", "line1\nlast = int(x)"),
        "old_no_nl__new_nl": ("line1\nlast = eval(x)", "line1\nlast = int(x)\n"),
    }
    for name, (old, new) in cases.items():
        diff_text, _stats = ap._build_fix_diff(old, new, rel)
        d = tempfile.mkdtemp()
        cwd = os.getcwd()
        try:
            os.chdir(d)
            subprocess.run(["git", "init", "-q"], check=True)
            subprocess.run(["git", "config", "user.email", "t@t"], check=True)
            subprocess.run(["git", "config", "user.name", "t"], check=True)
            with open(rel, "w") as f:
                f.write(old)
            subprocess.run(["git", "add", rel], check=True)
            subprocess.run(["git", "commit", "-qm", "base"], check=True)
            with open("p.diff", "w") as f:
                f.write(diff_text)
            chk = subprocess.run(["git", "apply", "--check", "p.diff"], capture_output=True, text=True)
            assert chk.returncode == 0, f"{name}: git apply --check failed: {chk.stderr}"
            subprocess.run(["git", "apply", "p.diff"], check=True)
            assert open(rel).read() == new, f"{name}: applied content mismatch"
        finally:
            os.chdir(cwd)
            shutil.rmtree(d, ignore_errors=True)


# --- #4989: attempt choke-point stamps a UTC timestamp for the drain measure ---


def test_mark_dispatch_attempted_stamps_utc_timestamp(monkeypatch):
    """Every attempt outcome routes through _mark_dispatch_attempted; it must
    stamp dispatch_attempted_at (parseable, tz-aware UTC ISO) alongside
    dispatch_attempted/dispatch_error so the #4989 measure can compute a clean
    attempts/day + yield/day. DB is monkeypatched — no side effects."""
    import contextlib
    import datetime as dt
    import json as _json

    captured = {}

    class _Cur:
        def execute(self, sql, params):
            captured["params"] = params

    @contextlib.contextmanager
    def _fake_cursor(commit=False):
        yield (None, _Cur())

    monkeypatch.setattr(ap, "get_db_cursor", _fake_cursor)
    ap._mark_dispatch_attempted(123, "find_not_located: no match")

    payload = _json.loads(captured["params"][0])
    assert payload["dispatch_attempted"] is True
    assert payload["dispatch_error"].startswith("find_not_located")
    parsed = dt.datetime.fromisoformat(payload["dispatch_attempted_at"])
    assert parsed.tzinfo is not None  # aware UTC per the timezone rule
    assert captured["params"][1] == 123  # proposal_id passed through


# --- fix-yield: fence-inside-FIND, debug-capture parser, indent-tolerant match ---


def test_strip_wrapping_fence():
    assert ap._strip_wrapping_fence("```python\ncode\n```") == "code"
    assert ap._strip_wrapping_fence("```\ncode\n```") == "code"
    # non-fenced content is returned untouched
    assert ap._strip_wrapping_fence("just code\nline2") == "just code\nline2"


def test_parse_fix_delimited_strips_fence_inside_find_block():
    """Real fix_debug sample #1654: the model wrapped code in ```python … ``` INSIDE
    the <<<FIND>>> block; the find must come back without the fence markers."""
    reply = (
        "<<<FIND>>>\n"
        "```python\n"
        "def f():\n"
        "    return 1\n"
        "```\n"
        "<<<REPLACE>>>\n"
        "def f():\n"
        "    return 2\n"
        "<<<END>>>\n"
    )
    d = ap._parse_fix_delimited(reply)
    assert d["find"] == "def f():\n    return 1"
    assert d["replace"] == "def f():\n    return 2"
    assert "```" not in d["find"]


def test_capture_fix_failure_populates_attempted_find_for_delimiter(monkeypatch):
    """Fix B: _capture_fix_failure must parse with _parse_fix_response (delimiter-
    first), else attempted_find is blank for every <<<FIND>>> reply (now dominant)."""
    import contextlib
    import json as _json

    captured = {}

    class _Cur:
        def execute(self, sql, params):
            captured["params"] = params

    @contextlib.contextmanager
    def _fake(commit=False):
        yield (None, _Cur())

    monkeypatch.setattr(ap, "get_db_cursor", _fake)
    reply = "<<<FIND>>>\nx = eval(y)\n<<<REPLACE>>>\nx = int(y)\n<<<END>>>"
    ap._capture_fix_failure(999, reply, "find_not_located")
    debug = _json.loads(captured["params"][0])
    assert debug["attempted_find"] == "x = eval(y)"
    assert debug["reason"] == "find_not_located"


# --- #387: indent-tolerant match (the dominant live find_not_located cause) ---

_INDENT_SOURCE = (
    "class X:\n"
    "    def run(self):\n"
    "        value = compute(\n"
    "            first,\n"
    "            second,\n"
    "        )\n"
    "        return value\n"
)


def test_indent_tolerant_match_reindents_to_source():
    # model reproduced the block flattened to 0-indent (imperfect indentation)
    find = "value = compute(\nfirst,\nsecond,\n)"
    replace = "value = compute(first, second)"
    orig, new = ap._indent_tolerant_match(_INDENT_SOURCE, find, replace)
    assert orig == "        value = compute(\n            first,\n            second,\n        )"
    assert new == "        value = compute(first, second)"  # reindented +8 to source


def test_apply_targeted_fix_indent_tolerant_end_to_end():
    """The whole point: a delimiter reply whose FIND has wrong internal indentation
    now applies (was find_not_located) — to the exactly-correct content."""
    resp = "<<<FIND>>>\nvalue = compute(\nfirst,\nsecond,\n)\n<<<REPLACE>>>\nvalue = compute(first, second)\n<<<END>>>"
    fixed, reason = ap._apply_targeted_fix(_INDENT_SOURCE, resp)
    assert reason == "ok"
    assert fixed == (
        "class X:\n" "    def run(self):\n" "        value = compute(first, second)\n" "        return value\n"
    )


def test_indent_tolerant_match_single_line_returns_none():
    # single lines are the strip-fallback's job, not this
    assert ap._indent_tolerant_match("    x = 1\n", "x = 1", "x = 2") is None


def test_indent_tolerant_match_ambiguous_returns_none():
    # the same block twice → not unique → fail closed
    source = "    a = f(\n        x,\n    )\n    a = f(\n        x,\n    )\n"
    assert ap._indent_tolerant_match(source, "a = f(\nx,\n)", "a = f(x)") is None


def test_indent_tolerant_match_no_match_returns_none():
    assert ap._indent_tolerant_match("a\nb\nc\n", "x\ny\nz", "q") is None


def test_indent_tolerant_match_tabs_return_none():
    # tab widths are ambiguous — never guess
    source = "\tvalue = compute(\n\t\tfirst,\n\t)\n"
    assert ap._indent_tolerant_match(source, "value = compute(\nfirst,\n)", "value = compute(first)") is None


def test_indent_tolerant_match_unsafe_dedent_returns_none():
    # source is LESS indented than the model's find, and a replace line can't dedent
    source = "value = compute(\nfirst,\n)\n"  # 0-indent
    find = "        value = compute(\n        first,\n        )"  # model over-indented to 8
    replace = "x = 1"  # only 0 leading spaces, cannot dedent by 8
    assert ap._indent_tolerant_match(source, find, replace) is None
