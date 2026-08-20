# Chunked multi-pass PR review — design (#5848)

**Date:** 2026-08-20 · **Task:** #5848 · **Status:** approved design, not yet implemented

## Problem (measured, not assumed)

`_DIFF_MAX_7B = 9000` caps the diff for **every** Tier-1/2 structured review and the freeform
fallback. Only the Tier-3 `gemma3:12b` strong path sees the wider `_diff_max_chars()` (18,768 at
`forge:review_num_ctx=8192`). A PR larger than 9,000 chars is reviewed partially, forever.

The standing assumption was that raising the cap is the lever, traded against the 240s dispatch
window. **The measurement says the window is already overspent at the current cap.**

`task_execution_log`, `capability='code_review'`, 14 days, 1,239 runs:

| model | runs | avg | p90 | >240s | success |
|---|---|---|---|---|---|
| qwen2.5:7b | 850 | 77.8s | **240.2s** | **19%** | 82% |
| qwen2.5-coder:7b | 311 | 94.5s | 264.8s | **25%** | 79% |
| mistral:7b | 78 | 152.8s | 492.3s | 35% | 97% |

The primary reviewer's p90 sits exactly on the 240s window; ~1 review in 5 already times out and
degrades to the weaker freeform path (the #1901 failure the cap exists to prevent). Raising
`_DIFF_MAX_7B` spends a budget that is already overdrawn.

⚠️ `duration_ms` is end-to-end dispatch (includes queue + cold-load), not pure inference. That is
the correct number for "does it fit the dispatch window" and the WRONG one for "how fast is the
model". Do not reuse it for model comparison.

## STRONGER EVIDENCE, gathered after this spec was first written (2026-08-20, same day)

The spec was originally motivated on LATENCY (p90 sitting on the 240s window). Nine PRs were
merged that day and the truncation pattern turned out to be the far stronger argument:

| PR | coverage | file the reviewer never read |
|---|---|---|
| #2718 | 1 of 2 | `tests/test_idle_auth_backoff.py` |
| #2721 | 3 of 4 | `tools/email_manager/mailbox_routes.py` |
| #2722 | 3 of 4 | `tests/test_merge_verdict_parity.py` |
| #2724 | **3 of 6** | both service files **+** `tests/test_coverage_discharge.py` |
| #2727 | 1 of 2 | `tests/test_translate_backpressure.py` |

**Five of six truncations were the TEST file.** That is not chance: `prioritize()` (#2715)
deliberately orders code before tests before docs, so tests sit at the BACK of the window and are
STRUCTURALLY the first thing to fall off the 9,000-char `_DIFF_MAX_7B` cliff.

Consequences observed, not theorised:
- **Every APPROVE issued that day was issued without the tests in view.** A reviewer that cannot
  see tests cannot judge whether a change is tested, which is a large part of what review is for.
- On **#2722** the model raised *"verdict_refusal is duplicated across multiple files"* — while the
  one file it never read was the test asserting there is exactly ONE definition. The evidence
  against its own finding was the thing truncated away.
- **#2724** was APPROVED having read 3 of 6 files, missing BOTH service files carrying the safety
  logic AND their tests.

The coverage gate (#5836) is the only reason these did not become false clean bills of health — it
demoted every one to NEEDS REVIEW. But a gate that fires on nearly every PR is a queue, not a
safeguard. Chunking is what lets the reviewer actually READ the diff instead of being told it
could not.

## Decisions (owner-approved 2026-08-20)

1. **Serial, max 3 chunks.** One pass at a time, hard cap 3. ~4 min and ~3x tokens worst case;
   covers ~27,000 chars. Beyond that the diff still truncates and the coverage block reports the
   dropped paths. Parallel fan-out was rejected: USS-246 is offline and the hub already shows
   240s timeouts under contention (#5623), so concurrency would feed the very problem being fixed.
2. **Grounding is checked against the FULL diff, not the chunk.** A finding is grounded when its
   evidence is real code anywhere in the PR. This preserves genuine cross-chunk defects — a caller
   in chunk 1 broken by a signature change in chunk 3 — which is the defect class that splitting
   itself manufactures. Invented code is still dropped, which is what #2716 is for.
   Accepted risk: a chunk can cite code it never read and be coincidentally right.
3. **Approach A — chunk-and-merge.** Run the existing review + full gate stack per chunk, merge
   findings, verdict = worst. Map-reduce (a final synthesis pass) was rejected on two grounds: it
   consumes one of the three slots, and a model summarizing findings without touching the diff is
   a NEW ungrounded surface no gate covers.

## Architecture

`prioritize()` already reorders code before tests before docs, and `split_blocks()` already yields
`(path, block)` pairs verbatim. Chunking is **packing those blocks into bins** — no new parsing.

```
full_diff
  -> prioritize(full_diff, cap)          # existing #2715, code-first ordering
  -> chunk_plan(diff, cap, max_chunks)   # NEW: pack blocks into <=3 bins of <=cap
  -> for each chunk (serial):
         _structured_review(review, chunk, ground_diff=full_diff)
  -> merge findings, dedup
  -> verdict = worst surviving
  -> coverage(full_diff, union(chunks)) -> annotate()
```

### New: `review_coverage.chunk_plan(diff, cap, max_chunks) -> list[str]`

Home is `review_coverage.py` (245 lines, already owns `split_blocks`/`file_band`/`prioritize`).

- Packs whole blocks; a block is **never** split across chunks (splitting mid-hunk reintroduces
  the exact mid-statement cut `_truncate_diff` was written to avoid).
- Preserves `prioritize()` order, so chunk 1 is code and docs land last.
- A single block larger than `cap` occupies its own chunk and is truncated by the existing
  `_truncate_diff` — the last-resort byte cut, unchanged.
- Returns at most `max_chunks`; remaining blocks are dropped and surface via `coverage()`.
- `max_chunks=1` MUST return `[_truncate_diff(diff, cap)[0]]` — byte-identical to today.

### Changed: `_structured_review(review, diff, pr_number, repo, ground_diff=None)`

One argument currently serves five consumers. Thread a second so "shown" and "ground" separate;
`ground_diff` defaults to `diff`, so every existing caller is unchanged.

| consumer | scope after change |
|---|---|
| `_build_json_prompt` | **chunk** (what the model sees) |
| `_verify_evidence` (#2716) + `_evidence_polarity` | **full diff** |
| `_self_refute_criticals` | **full diff** |
| `_check_dockerfile_provenance` | **full diff, ONCE** — hoisted out of the per-chunk loop |
| `strip_unsupported_claims` | **full diff** |

`strip_unsupported_claims` against the full diff is load-bearing: a code-only chunk would
otherwise truthfully report "no tests added" while the tests sit in chunk 3. Decision 2 makes that
correct automatically.

### The freeform fallback and the #5287 retry

`_obtain_review_summary` is `_structured_review(...) or _run_forge_review(_build_prompt(...))`.
The fallback runs on the **same chunk** as the structured attempt it replaces (it already uses the
same `_diff_cap_for_model(strong=False)` cap), so a chunk is reviewed by exactly one path.

The #5287 degraded-blocking structured retry applies to **at most one chunk per review** — the
first chunk that yields a degraded blocking verdict. This preserves #5287's "bounded by
construction" property and holds the worst case at 4 dispatches rather than 6. A second chunk
producing a degraded blocking verdict keeps it, annotated, without a retry.

### Gate composition

| gate | scope |
|---|---|
| prioritize (#2715) | once, before chunking |
| per-chunk review + severity gates (#2717/#2719) | per chunk (scope-free, per finding) |
| grounding + polarity (#2716, ADR-001) | full diff |
| dockerfile provenance | full diff, once |
| ungrounded-APPROVE floor (#5009) | **union of drops, evaluated once** |
| coverage (#2714) | union of shown chunks vs full diff |

The #5009 floor over the union is not cosmetic: three chunks each sitting just under the
per-chunk floor would otherwise clear a review that is ungrounded in aggregate.

### Verdict composition

Worst-wins. Any surviving blocking finding in any chunk blocks the PR. An APPROVE requires every
chunk to approve AND the union coverage/floor checks to pass. A chunk that fails to produce a
parseable review is treated as **not approving** (fail closed), annotated so a human sees which
chunk was lost — never silently skipped.

### Dedup

Merge on `(path, _normalize_match(evidence_core), severity)` using the module's existing
`_normalize_match` — no new normalizer. Chunks do not overlap, so exact
duplicates are rare; the real case is the same systemic observation raised against several files.
Dedup keeps the first and appends the additional paths rather than emitting N near-identical rows.

## Rollout

`platform_settings` key **`forge:review_max_chunks`**, read via the existing `_get_setting`.
- `0` or `1` -> current single-pass behaviour, byte-identical. This is the default at merge.
- `3` -> the approved configuration, flipped after the byte-identical regression pins pass.

No deploy needed to roll back: set the key to 1.

## Testing

Pinned in `platform_v2/tests/` alongside the existing 224 forge tests.

1. `chunk_plan`: blocks never split; `prioritize` order preserved; every chunk <= cap; never more
   than `max_chunks`; oversized single block isolated; dropped blocks reported.
2. **Regression pin:** `max_chunks=1` produces a prompt byte-identical to today's path.
3. A cross-chunk finding (evidence from chunk 3, raised in chunk 1) SURVIVES grounding.
4. An invented-evidence finding is still DROPPED with `evidence_not_in_diff`.
5. "no tests added" from a code-only chunk is stripped when tests exist elsewhere in the PR.
6. #5009 floor triggers on the union when no single chunk would trip it.
7. Verdict is worst-wins; an unparseable chunk fails closed.
8. `_check_dockerfile_provenance` is invoked exactly once for a 3-chunk review.

Per `.claude/rules/repair-bay.md`: a test that cannot fail is worse than no test. Each gate test
must be shown to fail against a copy of the module with the guard removed — never by mutating the
live file.

## Out of scope

- Raising `_DIFF_MAX_7B` (explicitly rejected above).
- Parallel chunk dispatch (revisit only if fleet contention is resolved; see #5623/#5809).
- Any change to the severity-calibration problem — four review cycles produced four different
  non-defect blockers, and that is a prompt/rubric issue, not a coverage one. Tracked separately.
- PRs needing more than 3 chunks still truncate. That is a deliberate, reported limit, not a bug.
