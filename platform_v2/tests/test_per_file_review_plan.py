"""Per-file review planning + the degenerate-truncation fix (#6779).

WHY THIS EXISTS
---------------
Measured live 2026-09-15 on PR #3339. `platform_v2/services/omniroute_telemetry.py` is a
NEW 342-line file, so its diff block carries exactly ONE hunk header — `@@ -0,0 +1,342 @@`
at byte 214. `_truncate_diff` prefers the last structural boundary before the cap; the only
one is that header, so it cut there:

    chunk raw        : 15,950 chars
    after _truncate  :    214 chars

**1.3% of the file.** F.O.R.G.E. then judged the file and raised
`[WARNING] Unnecessary Import of 'database'` against a symbol imported at :269 and USED at
:293 — inside the 98.7% that was thrown away. A false BLOCKING finding, which is the most
expensive kind: it trains the owner to distrust the reviewer.

Two independent fixes, tested separately here because either can regress alone:

  1. `_truncate_diff` — a boundary in the first half of the window is not worth honouring;
     fall back to a LINE boundary near the cap. Rescues the packed path too.
  2. `file_plan` — one pass per FILE, so no file has to share a window in the first place.

NON-VACUITY
-----------
Every assertion below was checked against the pre-fix code by reverting the change and
confirming the test goes red. The `_truncate_diff` tests exercise the SHIPPED function,
extracted from the real module with `ast` — not a copy of it in this file, which would
only ever test itself.
"""

import ast
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

from services.review_coverage import coverage, file_plan, split_blocks  # noqa: E402

_ANALYZER = _ROOT / "tools" / "repair_bay" / "services" / "pr_diff_analyzer.py"


def _shipped(func_name: str):
    """Load ONE function from the real analyzer without importing the whole app.

    Importing `pr_diff_analyzer` drags in the dispatcher, the DB and Flask. Re-typing the
    function here instead would test this file's copy and nothing else — the vacuity trap.
    Extracting the real source is the honest middle: if the shipped function changes, these
    tests see the change.
    """
    tree = ast.parse(_ANALYZER.read_text(encoding="utf-8"))
    node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == func_name)
    namespace: dict = {}
    exec(compile(ast.Module(body=[node], type_ignores=[]), "<shipped>", "exec"), namespace)
    return namespace[func_name]


def _new_file_block(path: str, body_chars: int) -> str:
    """A diff for a NEWLY ADDED file: one hunk header, near the top, and nothing after it."""
    lines = "\n".join("+" + "x" * 78 for _ in range(body_chars // 80))
    return (
        f"diff --git a/{path} b/{path}\n"
        "new file mode 100644\n"
        "index 000000000..8cb55c310\n"
        "--- /dev/null\n"
        f"+++ b/{path}\n"
        f"@@ -0,0 +1,{body_chars // 80} @@\n"
        f"{lines}\n"
    )


def _modified_file_block(path: str, hunks: int = 6) -> str:
    """A MODIFIED file: several hunk headers spread through the block."""
    out = [f"diff --git a/{path} b/{path}\n--- a/{path}\n+++ b/{path}\n"]
    for h in range(hunks):
        out.append(f"@@ -{h * 50 + 1},5 +{h * 50 + 1},6 @@\n")
        out.append("\n".join("+" + "y" * 78 for _ in range(20)) + "\n")
    return "".join(out)


# --------------------------------------------------------------------------- #
# 1. _truncate_diff — the degenerate single-hunk case
# --------------------------------------------------------------------------- #


def test_new_file_larger_than_cap_is_not_cut_down_to_its_header():
    """THE REGRESSION. Pre-fix this returned 214 of 15,950 chars.

    A new file has exactly one `\\n@@`, near the top. Honouring it as "the last safe
    boundary" discards the entire file while reporting a successful truncation.
    """
    truncate = _shipped("_truncate_diff")
    cap = 9000
    block = _new_file_block("platform_v2/services/omniroute_telemetry.py", 15000)
    assert block.count("\n@@") == 1, "fixture must reproduce the single-hunk shape"

    shown, truncated = truncate(block, cap)

    assert truncated is True
    assert len(shown) > cap // 2, (
        f"only {len(shown)} of {len(block)} chars shown — the reviewer would judge this file "
        "having seen its header and nothing else (#6779 / PR #3339)"
    )
    assert shown.endswith("\n") or "\n" in shown[-120:], "cut should land on a line boundary"


def test_truncation_is_unchanged_when_a_real_boundary_exists():
    """The ordinary path must be byte-identical — this fix tightens a fallback, nothing else.

    Two files where the second starts past the halfway mark: the file boundary is still the
    right cut and the new line-boundary branch must not fire.
    """
    truncate = _shipped("_truncate_diff")
    cap = 9000
    block = _modified_file_block("a.py", hunks=4) + _modified_file_block("b.py", hunks=4)
    file_cut = block.rfind("\ndiff --git", 0, cap)
    if file_cut <= cap // 2:
        pytest.skip("fixture did not produce a late file boundary")

    shown, truncated = truncate(block, cap)
    assert truncated is True
    assert shown == block[:file_cut], "a healthy file boundary must still win outright"


def test_a_single_line_larger_than_the_cap_still_falls_back_to_a_byte_cut():
    """No boundary of ANY kind: the documented last resort must still work, not return ''."""
    truncate = _shipped("_truncate_diff")
    cap = 500
    shown, truncated = truncate("z" * 5000, cap)
    assert truncated is True
    assert len(shown) == cap, "must fall back to a raw byte cut rather than to nothing"


# --------------------------------------------------------------------------- #
# 2. file_plan
# --------------------------------------------------------------------------- #


def test_file_plan_gives_every_file_its_own_pass():
    diff = _modified_file_block("a.py") + _modified_file_block("b.py") + _modified_file_block("c.py")
    plan = file_plan(diff, 10)
    assert len(plan) == 3
    for block in plan:
        assert block.count("diff --git") == 1, "a pass must carry exactly ONE file"


def test_max_files_of_one_is_the_killswitch():
    """Identical property to chunk_plan's: 1 returns the diff UNCHANGED, not truncated.

    This is how the mode is disabled without touching `forge:review_plan`, so it must be
    byte-identity, never "one chunk that happens to be close".
    """
    diff = _modified_file_block("a.py") + _modified_file_block("b.py")
    assert file_plan(diff, 1) == [diff]
    assert file_plan(diff, 0) == [diff]
    assert file_plan(diff, -5) == [diff]


def test_file_plan_spends_its_budget_on_code_before_docs():
    """`prioritize` ordering must survive, or a truncating bound drops the code."""
    diff = (
        _modified_file_block(".claude/rules/big-rules-file.md")
        + _modified_file_block("platform_v2/services/thing.py")
        + _modified_file_block("platform_v2/tests/test_thing.py")
    )
    plan = file_plan(diff, 10)
    order = [b.split(" b/", 1)[1].split("\n", 1)[0] for b in plan]
    assert order.index("platform_v2/services/thing.py") < order.index(
        ".claude/rules/big-rules-file.md"
    ), f"code must be planned before docs, got {order}"


def test_the_bound_drops_files_and_coverage_says_so():
    """A bound that silently hid files would be #5836 again. It must be VISIBLE."""
    diff = "".join(_modified_file_block(f"platform_v2/services/m{i}.py") for i in range(5))
    plan = file_plan(diff, 2)
    assert len(plan) == 2

    cov = coverage(diff, "\n".join(plan))
    assert cov["complete"] is False
    assert len(cov["dropped"]) == 3, f"3 files were not planned; coverage says {cov['dropped']}"


def test_file_plan_on_an_unparseable_diff_still_yields_one_pass():
    """Returning [] would read to the caller as 'nothing to review' — a silent skip."""
    assert file_plan("not a diff at all", 10) == ["not a diff at all"]
    assert file_plan("", 10) == []
    assert file_plan(None, 10) == []


def test_every_planned_block_is_a_real_block_from_the_diff():
    """file_plan must not invent, reorder within, or reflow a block's bytes."""
    diff = _modified_file_block("a.py") + _new_file_block("b.py", 4000)
    originals = {block for _path, block in split_blocks(diff)}
    for block in file_plan(diff, 10):
        assert block in originals, "planned block is not verbatim from the diff"


# --------------------------------------------------------------------------- #
# 3. The two fixes together, on the PR #3339 shape
# --------------------------------------------------------------------------- #


def test_pr3339_shape_reaches_every_file_with_both_fixes():
    """End to end on the shape that produced the false finding.

    Packed-into-3-bins dropped 4 of 6 files and showed the main file at 1%. Per-file, at the
    patient cap #6023 escalates an over-window pass to, every file is read IN FULL.
    """
    truncate = _shipped("_truncate_diff")
    diff = (
        _new_file_block("platform_v2/services/omniroute_telemetry.py", 15000)
        + _new_file_block("platform_v2/tests/test_omniroute_telemetry.py", 16000)
        + _modified_file_block("platform_v2/tools/department_hq/jobs.py", hunks=2)
        + _modified_file_block("docker-compose.yml", hunks=1)
        + _modified_file_block(".claude/rules/service-registry.md", hunks=1)
    )
    strong_cap = 18768  # the patient window an over-cap pass is escalated to

    shown = "\n".join(truncate(b, strong_cap)[0] for b in file_plan(diff, 10))
    cov = coverage(diff, shown)

    assert cov["dropped"] == [], f"per-file must drop nothing, dropped {cov['dropped']}"
    assert cov["complete"] is True, f"expected full coverage, got partial {cov['partial']}"
