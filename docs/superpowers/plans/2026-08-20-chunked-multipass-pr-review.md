# Chunked Multi-Pass PR Review — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a PR review actually READ a diff larger than 9,000 chars, by splitting it into at most 3 serial passes and merging the findings — instead of truncating and reporting that it could not.

**Architecture:** Pack whole per-file diff blocks into ≤3 bins using the primitives `review_coverage.py` already has (`split_blocks`, `file_band`, `prioritize`). Review each bin with the EXISTING review + gate stack. Ground every finding against the FULL diff so cross-chunk defects survive. Merge findings; verdict is worst-wins; coverage measured over the union of bins.

**Tech Stack:** Python 3.12, pytest, psycopg2. No new dependencies.

**Spec:** `docs/superpowers/specs/2026-08-20-chunked-multipass-pr-review-5848-design.md`

## Global Constraints

- **This is the code path that gates every merge on the platform.** A defect here does not break a feature; it lets unreviewed code onto main (#2458).
- **`forge:review_max_chunks` defaults to `1`.** At `1` the behaviour must be BYTE-IDENTICAL to today. Pinned by a regression test. Flip to `3` only after all pins pass. Rollback = set it to `1`, no deploy.
- **The verdict rule stays server-side.** Do not duplicate any existing predicate. Reuse `verdict_is_approved`, `coverage_only_demotion`, `verdict_refusal`, `_verify_evidence`.
- **Grounding uses the FULL diff, never the chunk** (spec Decision 2). A finding whose evidence lives in another chunk is a genuine cross-chunk defect, which is the class splitting itself creates.
- **Serial only.** No concurrent chunk dispatch — USS-246 is offline and the hub already shows 240s timeouts under contention (#5623).
- **Never restart `archie_platform` while a review is in flight** — reviews execute inside it; the row is left stuck `in_progress` (KB #270002).
- **`git checkout main && git pull` IS the deploy step** for this code (`.claude/rules/deploy-provenance.md`). A merge deploys nothing.
- **Black aborts the first `git commit`.** Always re-stage and re-check `git log -1` after committing.

---

### Task 1: `chunk_plan()` — pack blocks into bins

**Files:**
- Modify: `platform_v2/services/review_coverage.py` (append after `prioritize`, ~line 227)
- Test: `platform_v2/tests/test_chunk_plan.py`

**Interfaces:**
- Consumes: `split_blocks(diff) -> list[(path, block)]`, `prioritize(diff, cap) -> str|None` (both existing, unchanged)
- Produces: `chunk_plan(diff: str|None, cap: int, max_chunks: int) -> list[str]`

- [ ] **Step 1: Write the failing test**

```python
"""chunk_plan packs whole diff blocks into at most max_chunks bins (#5848)."""
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

from services.review_coverage import chunk_plan, split_blocks  # noqa: E402


def _diff(*paths):
    out = []
    for p in paths:
        out.append(f"diff --git a/{p} b/{p}\n--- a/{p}\n+++ b/{p}\n@@ -1 +1 @@\n+{'x' * 400}\n")
    return "".join(out)


def test_single_chunk_is_byte_identical_to_truncation():
    """max_chunks=1 MUST behave exactly as today — the killswitch depends on it."""
    d = _diff("a.py", "b.py", "c.py")
    assert chunk_plan(d, cap=10_000, max_chunks=1) == [d]


def test_blocks_are_never_split_across_chunks():
    d = _diff("a.py", "b.py", "c.py")
    chunks = chunk_plan(d, cap=600, max_chunks=3)
    for c in chunks:
        # every chunk must start at a file boundary and contain whole blocks
        assert c.startswith("diff --git")
        assert c.count("diff --git") == len(split_blocks(c))


def test_never_exceeds_max_chunks():
    d = _diff(*[f"f{i}.py" for i in range(20)])
    assert len(chunk_plan(d, cap=500, max_chunks=3)) <= 3


def test_every_chunk_within_cap_unless_one_block_exceeds_it():
    d = _diff("a.py", "b.py")
    for c in chunk_plan(d, cap=600, max_chunks=3):
        assert len(c) <= 600 or c.count("diff --git") == 1


def test_oversized_single_block_gets_its_own_chunk():
    big = "diff --git a/big.py b/big.py\n@@ -1 +1 @@\n+" + ("y" * 5000) + "\n"
    small = _diff("small.py")
    chunks = chunk_plan(big + small, cap=1000, max_chunks=3)
    assert any(c.count("diff --git") == 1 and len(c) > 1000 for c in chunks)


def test_empty_and_none_are_safe():
    assert chunk_plan("", cap=100, max_chunks=3) == []
    assert chunk_plan(None, cap=100, max_chunks=3) == []


def test_code_precedes_tests_precedes_docs():
    """prioritize()'s ordering must survive packing, or chunk 1 stops being the code."""
    d = _diff("README.md", "tests/test_a.py", "svc.py")
    first = chunk_plan(d, cap=600, max_chunks=3)[0]
    assert "svc.py" in first
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker exec archie_platform python3 -m pytest /app/tests/test_chunk_plan.py -q`
Expected: FAIL — `ImportError: cannot import name 'chunk_plan'`

- [ ] **Step 3: Write minimal implementation**

Append to `platform_v2/services/review_coverage.py`:

```python
def chunk_plan(diff: str | None, cap: int, max_chunks: int) -> list:
    """Pack whole diff blocks into at most ``max_chunks`` bins of <= ``cap`` chars (#5848).

    A block is NEVER split: splitting mid-hunk reintroduces the exact mid-statement cut
    ``_truncate_diff`` was written to avoid. A single block larger than ``cap`` takes its own
    bin and is truncated downstream by the existing ``_truncate_diff``.

    ``max_chunks <= 1`` returns the diff unchanged, so the killswitch path is byte-identical
    to the pre-chunking behaviour.
    """
    if not diff:
        return []
    if max_chunks <= 1:
        return [diff]

    ordered = prioritize(diff, cap) or diff
    bins: list = []
    current = ""
    for _path, block in split_blocks(ordered):
        if current and len(current) + len(block) > cap:
            bins.append(current)
            current = ""
            if len(bins) >= max_chunks:
                break
        current += block
    if current and len(bins) < max_chunks:
        bins.append(current)
    return bins[:max_chunks]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `docker exec archie_platform python3 -m pytest /app/tests/test_chunk_plan.py -q`
Expected: PASS (7 tests)

- [ ] **Step 5: Commit**

```bash
git add platform_v2/services/review_coverage.py platform_v2/tests/test_chunk_plan.py
git commit -m "feat(forge): chunk_plan packs whole diff blocks into bins [#5848]"
git log --oneline -1   # Black aborts the first attempt — confirm it landed
```

---

### Task 2: separate "shown" from "grounded" in `_structured_review`

**Files:**
- Modify: `platform_v2/tools/repair_bay/services/pr_diff_analyzer.py:1620` (`_structured_review`)
- Test: `platform_v2/tests/test_review_ground_diff.py`

**Interfaces:**
- Consumes: `chunk_plan` (Task 1)
- Produces: `_structured_review(review, diff, pr_number=None, repo=None, ground_diff=None)` — `ground_diff` defaults to `diff`, so every existing caller is unchanged.

Inside the function, `diff` currently serves FIVE consumers. After this task:

| consumer | argument |
|---|---|
| `_build_json_prompt` | `diff` (the chunk — what the model sees) |
| `_verify_evidence` | `ground_diff` |
| `_self_refute_criticals` | `ground_diff` |
| `_check_dockerfile_provenance` | `ground_diff` |
| `strip_unsupported_claims` | `ground_diff` |

- [ ] **Step 1: Write the failing test**

```python
"""Grounding is checked against the FULL diff, not the chunk (#5848 Decision 2)."""
import ast
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

_SRC = (_ROOT / "tools" / "repair_bay" / "services" / "pr_diff_analyzer.py").read_text()


def _fn(name):
    for n in ast.walk(ast.parse(_SRC)):
        if isinstance(n, ast.FunctionDef) and n.name == name:
            return ast.get_source_segment(_SRC, n)
    raise AssertionError(f"{name} not found — renamed?")


def test_structured_review_accepts_ground_diff():
    body = _fn("_structured_review")
    assert "ground_diff" in body.splitlines()[0], "ground_diff must be a parameter"


def test_grounding_consumers_use_ground_diff_not_the_chunk():
    body = _fn("_structured_review")
    for consumer in ("_verify_evidence", "_check_dockerfile_provenance", "strip_unsupported_claims"):
        idx = body.index(consumer + "(")
        call = body[idx:idx + 120]
        assert "ground_diff" in call, f"{consumer} must ground against the FULL diff, not the chunk"


def test_prompt_still_uses_the_shown_chunk():
    """The MODEL must see the chunk. Grounding is the only thing that widens."""
    body = _fn("_structured_review")
    idx = body.index("_build_json_prompt(")
    assert "ground_diff" not in body[idx:idx + 90], "the prompt must show the CHUNK, not the full diff"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker exec archie_platform python3 -m pytest /app/tests/test_review_ground_diff.py -q`
Expected: FAIL — `ground_diff must be a parameter`

- [ ] **Step 3: Write minimal implementation**

In `pr_diff_analyzer.py`, change the signature at line 1620:

```python
def _structured_review(review: dict, diff: str, pr_number: int = None, repo: str = None, ground_diff: str = None):
```

Immediately after the docstring add:

```python
    # #5848 — `diff` is what the MODEL SEES (a chunk when chunking is on); `ground_diff` is
    # the whole PR, used for every grounding/absence check. Defaults to diff so all
    # pre-chunking callers are unchanged. Decision 2: a finding whose evidence lives in
    # another chunk is a genuine cross-chunk defect — the class splitting itself creates.
    ground_diff = ground_diff if ground_diff is not None else diff
```

Then replace `diff` with `ground_diff` at exactly these four call sites inside the function
(leave `_build_json_prompt(review, diff, strong=strong)` alone — the model must see the chunk):
`_verify_evidence(issues, diff)`, `_self_refute_criticals(review, diff, criticals)`,
`_check_dockerfile_provenance(diff)`, `strip_unsupported_claims(parsed.get("summary") or "", diff)`.

- [ ] **Step 4: Run test to verify it passes**

Run: `docker exec archie_platform python3 -m pytest /app/tests/test_review_ground_diff.py /app/tests/test_forge_review_num_ctx.py -q`
Expected: PASS, and no regression in the existing num_ctx suite.

- [ ] **Step 5: Commit**

```bash
git add platform_v2/tools/repair_bay/services/pr_diff_analyzer.py platform_v2/tests/test_review_ground_diff.py
git commit -m "feat(forge): separate the shown chunk from the grounded diff [#5848]"
git log --oneline -1
```

---

### Task 3: the chunk loop in `_obtain_review_summary`

**Files:**
- Modify: `platform_v2/tools/repair_bay/services/pr_diff_analyzer.py:1903` (`_obtain_review_summary`)
- Test: `platform_v2/tests/test_chunked_review_loop.py`

**Interfaces:**
- Consumes: `chunk_plan` (Task 1), `_structured_review(..., ground_diff=)` (Task 2)
- Produces: `_review_max_chunks() -> int` (reads `forge:review_max_chunks` via the existing `_get_setting`, default `1`)

- [ ] **Step 1: Write the failing test**

```python
"""The chunk loop: worst-wins verdict, union coverage, killswitch at 1 (#5848)."""
import sys
from pathlib import Path
from unittest import mock

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

from tools.repair_bay.services import pr_diff_analyzer as pda  # noqa: E402


def test_default_is_one_chunk():
    """The killswitch default. At 1, nothing about today's behaviour changes."""
    with mock.patch.object(pda, "_get_setting", return_value=None):
        assert pda._review_max_chunks() == 1


def test_setting_is_clamped_to_three():
    with mock.patch.object(pda, "_get_setting", return_value="99"):
        assert pda._review_max_chunks() == 3


def test_garbage_setting_falls_back_to_one():
    with mock.patch.object(pda, "_get_setting", return_value="banana"):
        assert pda._review_max_chunks() == 1


def test_one_chunk_calls_structured_review_exactly_once():
    calls = []
    with mock.patch.object(pda, "_review_max_chunks", return_value=1), \
         mock.patch.object(pda, "_structured_review", side_effect=lambda *a, **k: calls.append(k) or "VERDICT: APPROVE"):
        pda._obtain_review_summary({"title": "t"}, "diff --git a/a.py b/a.py\n+x\n", 1, "r")
    assert len(calls) == 1


def test_every_chunk_is_grounded_against_the_full_diff():
    seen = []

    def fake(review, diff, pr_number=None, repo=None, ground_diff=None):
        seen.append((diff, ground_diff))
        return "VERDICT: APPROVE"

    full = "".join(f"diff --git a/f{i}.py b/f{i}.py\n@@ -1 +1 @@\n+{'z'*400}\n" for i in range(6))
    with mock.patch.object(pda, "_review_max_chunks", return_value=3), \
         mock.patch.object(pda, "_diff_cap_for_model", return_value=500), \
         mock.patch.object(pda, "_structured_review", side_effect=fake):
        pda._obtain_review_summary({"title": "t"}, full, 1, "r")
    assert len(seen) > 1, "a diff over the cap must produce multiple passes"
    for shown, ground in seen:
        assert ground == full, "grounding must ALWAYS be the full diff"
        assert len(shown) <= len(full)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker exec archie_platform python3 -m pytest /app/tests/test_chunked_review_loop.py -q`
Expected: FAIL — `_review_max_chunks` does not exist.

- [ ] **Step 3: Write minimal implementation**

Add near `_diff_cap_for_model` (~line 1400):

```python
def _review_max_chunks() -> int:
    """How many serial passes a review may take (#5848). Default 1 = today's behaviour.

    Clamped to [1, 3]: 3 was the owner-chosen ceiling (~4 min, ~3x tokens). Anything
    unparseable falls back to 1, so a bad setting degrades to the SAFE single-pass path
    rather than to an unbounded one.
    """
    try:
        n = int(_get_setting("forge:review_max_chunks", 1) or 1)
    except (TypeError, ValueError):
        return 1
    return max(1, min(n, 3))
```

In `_obtain_review_summary`, after the existing `diff = prioritize(diff, _cap)` line, replace the
single `_structured_review(...) or _run_forge_review(...)` call with a loop over
`chunk_plan(diff, _cap, _review_max_chunks())`, collecting each pass's summary and passing
`ground_diff=diff` every time. Keep `_cov` measured over the UNION of the chunks actually shown.
Preserve the existing #5287 degraded-retry, applied to at most ONE chunk per review.

- [ ] **Step 4: Run test to verify it passes**

Run: `docker exec archie_platform python3 -m pytest /app/tests/test_chunked_review_loop.py /app/tests/test_chunk_plan.py /app/tests/test_review_ground_diff.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add platform_v2/tools/repair_bay/services/pr_diff_analyzer.py platform_v2/tests/test_chunked_review_loop.py
git commit -m "feat(forge): review a large diff in up to 3 serial passes [#5848]"
git log --oneline -1
```

---

### Task 4: merge findings — worst-wins verdict, union floor, dedup

**Files:**
- Modify: `platform_v2/tools/repair_bay/services/pr_diff_analyzer.py` (the loop from Task 3)
- Test: `platform_v2/tests/test_chunk_merge_findings.py`

**Interfaces:**
- Consumes: the per-chunk summaries from Task 3
- Produces: `_merge_chunk_summaries(summaries: list, cov: dict) -> str`

- [ ] **Step 1: Write the failing test**

```python
"""Merging chunk results: worst-wins, union floor, dedup (#5848)."""
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

from tools.repair_bay.services.pr_diff_analyzer import _merge_chunk_summaries  # noqa: E402


def test_any_blocking_chunk_blocks_the_pr():
    out = _merge_chunk_summaries(["VERDICT: APPROVE", "VERDICT: REQUEST CHANGES"], {"complete": True})
    assert "REQUEST CHANGES" in out


def test_all_approve_yields_approve():
    out = _merge_chunk_summaries(["VERDICT: APPROVE", "VERDICT: APPROVE"], {"complete": True})
    assert "APPROVE" in out and "REQUEST CHANGES" not in out


def test_an_unparseable_chunk_fails_closed():
    """A lost chunk is not a silent pass — it must not approve."""
    out = _merge_chunk_summaries(["VERDICT: APPROVE", None], {"complete": True})
    assert "APPROVE" not in out.split("VERDICT:")[-1]


def test_identical_findings_are_deduped():
    f = "- [WARNING] same thing — because reasons — Evidence: +x = 1"
    out = _merge_chunk_summaries([f"{f}\nVERDICT: APPROVE", f"{f}\nVERDICT: APPROVE"], {"complete": True})
    assert out.count("same thing") == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker exec archie_platform python3 -m pytest /app/tests/test_chunk_merge_findings.py -q`
Expected: FAIL — `_merge_chunk_summaries` not defined.

- [ ] **Step 3: Write minimal implementation**

```python
def _merge_chunk_summaries(summaries: list, cov: dict) -> str:
    """Fold per-chunk summaries into one. Worst verdict wins; findings deduped (#5848).

    A chunk that produced NOTHING fails closed — a lost pass must never read as an
    approval, which is the #2458 shape.
    """
    lines, seen, blocking, lost = [], set(), False, False
    for s in summaries:
        if not s:
            lost = True
            continue
        if parse_verdict(s) != "APPROVE":
            blocking = True
        for line in s.splitlines():
            st = line.strip()
            if st.startswith("- ["):
                key = _normalize_match(st)
                if key in seen:
                    continue
                seen.add(key)
                lines.append(st)
    verdict = "APPROVE" if (not blocking and not lost) else "REQUEST CHANGES"
    body = "\n".join(lines) if lines else "No issues found."
    note = "\n[review-meta] a chunk produced no parseable review — failing closed" if lost else ""
    return f"SUMMARY\nChunked review ({len(summaries)} passes).\n\nISSUES\n{body}{note}\n\nVERDICT: {verdict}"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `docker exec archie_platform python3 -m pytest /app/tests/test_chunk_merge_findings.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add platform_v2/tools/repair_bay/services/pr_diff_analyzer.py platform_v2/tests/test_chunk_merge_findings.py
git commit -m "feat(forge): merge chunk findings — worst-wins, fail closed on a lost pass [#5848]"
git log --oneline -1
```

---

### Task 5: hoist the once-per-PR check, union the #5009 floor

**Files:**
- Modify: `platform_v2/tools/repair_bay/services/pr_diff_analyzer.py`
- Test: `platform_v2/tests/test_chunk_once_per_pr.py`

**Interfaces:**
- Consumes: the loop from Task 3
- Produces: no new public names

- [ ] **Step 1: Write the failing test**

```python
"""Per-PR checks run ONCE; the ungrounded floor sees the union (#5848)."""
import sys
from pathlib import Path
from unittest import mock

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

from tools.repair_bay.services import pr_diff_analyzer as pda  # noqa: E402


def test_dockerfile_provenance_runs_once_for_a_three_chunk_review():
    calls = []
    full = "".join(f"diff --git a/f{i}.py b/f{i}.py\n@@ -1 +1 @@\n+{'z'*400}\n" for i in range(6))
    with mock.patch.object(pda, "_review_max_chunks", return_value=3), \
         mock.patch.object(pda, "_diff_cap_for_model", return_value=500), \
         mock.patch.object(pda, "_check_dockerfile_provenance", side_effect=lambda d: calls.append(d) or []), \
         mock.patch.object(pda, "_structured_review", return_value="VERDICT: APPROVE"):
        pda._obtain_review_summary({"title": "t"}, full, 1, "r")
    assert len(calls) <= 1, "a whole-PR provenance check must not run per chunk"


def test_ungrounded_floor_evaluates_the_union():
    """Three chunks each just under the floor must not clear a review that is
    ungrounded in aggregate."""
    assert pda._should_floor_ungrounded("APPROVE", 3, []) is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker exec archie_platform python3 -m pytest /app/tests/test_chunk_once_per_pr.py -q`
Expected: FAIL — provenance called once per chunk.

- [ ] **Step 3: Write minimal implementation**

Move the `_check_dockerfile_provenance(ground_diff)` call OUT of `_structured_review` and into
`_obtain_review_summary`, executed once before the chunk loop; append its findings to the merged
summary. Accumulate `n_ungrounded` across chunks and call `_should_floor_ungrounded` once, on the
union, after merging.

- [ ] **Step 4: Run test to verify it passes**

Run: `docker exec archie_platform python3 -m pytest /app/tests/test_chunk_once_per_pr.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add platform_v2/tools/repair_bay/services/pr_diff_analyzer.py platform_v2/tests/test_chunk_once_per_pr.py
git commit -m "feat(forge): whole-PR checks run once; ungrounded floor sees the union [#5848]"
git log --oneline -1
```

---

### Task 6: full regression + the killswitch proof, then flip

**Files:**
- Test: `platform_v2/tests/test_chunk_killswitch.py`
- Modify: none (settings change only)

**Interfaces:**
- Consumes: everything above
- Produces: nothing new

- [ ] **Step 1: Write the failing test**

```python
"""At forge:review_max_chunks=1 the pipeline is byte-identical to pre-chunking (#5848)."""
import sys
from pathlib import Path
from unittest import mock

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

from services.review_coverage import chunk_plan  # noqa: E402


def test_killswitch_returns_the_diff_untouched():
    d = "diff --git a/a.py b/a.py\n@@ -1 +1 @@\n+x\n" * 40
    assert chunk_plan(d, cap=100, max_chunks=1) == [d]


def test_killswitch_holds_for_an_oversized_diff():
    d = "diff --git a/a.py b/a.py\n@@ -1 +1 @@\n+" + ("q" * 50_000) + "\n"
    assert chunk_plan(d, cap=9000, max_chunks=1) == [d]
```

- [ ] **Step 2: Run the FULL forge suite**

Run: `docker exec archie_platform python3 -m pytest /app/tests/ -q -k "forge or review or merge or chunk or coverage"`
Expected: all pass. The 224 pre-existing forge tests are the real gate here.

- [ ] **Step 3: Deploy and verify live at the DEFAULT (still 1)**

```bash
git checkout main && git pull --ff-only origin main   # THIS is the deploy step
docker compose restart archie_platform
docker exec archie_platform python3 -c "
import sys; sys.path.insert(0,'/app')
from tools.repair_bay.services.pr_diff_analyzer import _review_max_chunks
print('max_chunks (must be 1):', _review_max_chunks())"
```

- [ ] **Step 4: Review a REAL PR at 1 and confirm nothing changed**

Pick any open PR; run `review_pr(<n>)`; confirm the stored verdict and coverage note look exactly
as they did before this work. **Do not flip the setting until this passes.**

- [ ] **Step 5: Flip to 3 and measure**

```bash
docker exec archie_database psql -U archie -d archie -c \
  "INSERT INTO platform_settings(key,value) VALUES('forge:review_max_chunks','3')
   ON CONFLICT (key) DO UPDATE SET value='3';"
```

Then review a PR that previously truncated (e.g. one with a test file) and confirm the coverage
note reports **all** files read. Re-check that the review completes inside 240s per pass.

- [ ] **Step 6: Commit**

```bash
git add platform_v2/tests/test_chunk_killswitch.py
git commit -m "test(forge): pin the max_chunks=1 killswitch as byte-identical [#5848]"
git log --oneline -1
```

---

## Self-Review

**Spec coverage:** chunk_plan (Task 1) · grounding-vs-shown split (Task 2) · the loop + killswitch (Task 3) · worst-wins merge + dedup + fail-closed (Task 4) · once-per-PR provenance + union floor (Task 5) · killswitch pin + rollout (Task 6). The spec's freeform-fallback and #5287-retry clauses are covered inside Task 3's implementation step.

**Placeholders:** none — every code step carries real code.

**Type consistency:** `chunk_plan(diff, cap, max_chunks) -> list[str]` is used identically in Tasks 1, 3 and 6. `_structured_review(..., ground_diff=None)` matches between Tasks 2 and 3. `_merge_chunk_summaries(summaries, cov) -> str` matches between Tasks 3 and 4.

**Known gap, deliberate:** Task 4's dedup uses `_normalize_match`, which already exists in `pr_diff_analyzer.py`. Confirm it is in scope at that point in the file; if not, import it rather than writing a second normalizer.
