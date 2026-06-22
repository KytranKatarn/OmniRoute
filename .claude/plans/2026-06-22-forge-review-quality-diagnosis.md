# F.O.R.G.E. PR-Review Quality — Residual False-Flag Diagnosis & Ranked Fix Plan

**Date:** 2026-06-22 · **Project #381 (Phase 2)** · Read-only investigation, no files mutated.
**Files in scope (verified line-by-line):**
- `/mnt/archie_brain/platform_v2/tools/repair_bay/services/pr_diff_analyzer.py`
- `/mnt/archie_brain/platform_v2/tools/repair_bay/services/pr_review_service.py`
- `/mnt/archie_brain/ai_bridge/archie_bridge.py` (`call_ollama_json`)

---

## Root causes

All four independent investigations converge on **one dominant architectural defect plus two
secondary ones**. Phase 1 worked exactly as designed — it just guarded the wrong path.

### RC-1 (DOMINANT, severity HIGH) — the strong guards live ONLY on the structured-JSON path, which fires ~4–20% of the time; the freeform fallback is ungated and handles the rest

`review_pr` / `analyze_pending_prs` both do:
```python
summary = _structured_review(...) or _run_forge_review(_build_prompt(...))   # :84, :136
```
Every Phase-1 grounding guard — `_verify_evidence` → `_evidence_in_diff` + `_is_spurious_injection`
(:603–610), `_self_refute_criticals` (:612–623), and the deterministic `_recompute_verdict` (:625) —
lives **inside `_structured_review`** (:563–626). `_structured_review` returns `None` (→ fall through
to freeform) on **any** of: structured flag off (:566), dispatch exception (:589–591), `result.queued`
cold model (:592–593), empty/unsuccessful response (:594–595), **or `_parse_review_json` fails** (:596–599).
The last case is the common one: qwen2.5:7b wraps its JSON in markdown/prose, so the JSON parse returns
`None` and the review silently drops to the freeform path.

`_run_forge_review` (:629–672) runs exactly **one** guard: `_apply_severity_gate` (:667), which
**downgrades REQUEST CHANGES→APPROVE ONLY when there is zero `[CRITICAL]`/`[WARNING]` in the text**
(:271–273). It never runs evidence verification, injection drop, self-refute, or verdict recompute.
So any single `[WARNING]` line the 7B emits — true, false, or fabricated — blocks the PR unconditionally.

**Live evidence:** across `#1864–#1873`, only `#1867` and `#1869` carry the `[review-meta]
structured=json` stamp (`_render_review_text`, :400); both cleanly APPROVED. The 13/15 (and every
observed false-block: `#1865`, `#1872`, `#1873`, plus `#1864`, `#1868`, `#1871`) carry **no**
`[review-meta]` line = freeform = ungated. The 80%→20% improvement IS the gap between "structured path
parsed" and "fell back to freeform."

### RC-2 (severity HIGH) — severity is 100% model-controlled; the 7B over-labels non-blocking nits as `[WARNING]`, and both gates treat every WARNING as a hard block

There is **no severity normalizer / category allow-list** anywhere. The rubric (:34–52) tells the model
what *not to flag* but never maps style/tests/type-hints/docstrings/duplication → `[INFO]`. The 7B
systematically self-labels "missing type hints" (`#1868`), "no unit tests" (`#1872`/`#1873`),
"code duplication" (`#1865`/`#1864`), "sys.path / best-effort except" (`#1871`) as `[WARNING]`. Then:
- freeform `_apply_severity_gate` (:271–273): `has_blocking = any [CRITICAL|WARNING]` → refuses to relax.
- structured `_recompute_verdict` (:373): `blocking = severity in (CRITICAL, WARNING)` → REQUEST CHANGES.

So a *correctly-true-but-trivial* WARNING blocks on **both** paths. This is the dominant residual class
in `#1864–#1873` and is **independent of hallucination** — fixing RC-1 alone leaves these blocking on the
structured path too.

### RC-3 (severity MEDIUM, several distinct sub-bugs)

- **RC-3a — `classify_pr_tier` branch-key bug (`pr_review_service.py:529`).** It reads
  `review.get("branch")`, but `get_review` does `SELECT * FROM pr_reviews` (:493–498) and the column is
  `head_branch` / `base_branch` — there is **no `branch` key**. So `branch` is always `""`, and the
  numbered-migration / `migration`-in-branch Tier-3 escalation (:539) **never fires**. A migration PR
  with a neutral title (e.g. `#1867` "idempotency") is reviewed by the weak qwen2.5:7b instead of
  gemma3:12b — exactly the files most prone to truncation/`missing semicolon`/`injection` false-flags.
  *(VERIFIED: `get_review` uses `SELECT *`; no `branch` column exists.)*

- **RC-3b — `_truncate_diff` cuts at hunk boundary, not file/statement boundary
  (`pr_diff_analyzer.py:186–187`).** `cut = diff.rfind("\n@@", 0, _DIFF_MAX_CHARS)`; if a long single
  SQL migration is one oversized hunk with no earlier `\n@@` inside the 12000-char cap, it falls back to
  the raw byte slice `diff[:_DIFF_MAX_CHARS]` — chopping a `CREATE TABLE` mid-statement → the model sees
  a statement with no terminating `;` → false "missing semicolon" (the `#1867` class).

- **RC-3c — `call_ollama_json` uses Ollama's default 2048-token context
  (`ai_bridge/archie_bridge.py:~168`).** The payload has `model/prompt/stream/format:json` but
  **no `options` / `num_ctx` / `temperature`**. *(VERIFIED.)* The prompt (rubric + 12000-char diff +
  scaffolding ≈ 4000–5000 tokens) is ~2× the window; Ollama slides the window and **drops the earliest
  tokens — the rubric, which sits at the TOP of the prompt** (:204). On long diffs the model never sees
  the anti-hallucination rules. Compounding: `format:json` grammar-constrained decoding degrades 7B
  reasoning, and default temp (~0.8) makes verdicts non-deterministic run-to-run.

- **RC-3d — the prompt prints the literal verdict MENU (`pr_diff_analyzer.py:225`):**
  `VERDICT: APPROVE | REQUEST CHANGES | NEEDS REVIEW`. A weak 7B echoes it verbatim; `parse_verdict`
  checks `_VERDICT_REJECT_RE` FIRST (`pr_review_service.py:49,70`), so an echoed menu line is read as
  REQUEST CHANGES regardless of the leading APPROVE (`#1865`/`#1866` near-miss — landed APPROVE only by
  luck of "APPROVE" appearing first after the colon).

### Confirmed NON-issues (don't waste effort)
- **Real diff reaches the model.** `_fetch_diff` pulls `application/vnd.github.v3.diff` (:170–177); the
  bare-`diff_url`-as-prompt failure mode is already fixed.
- **Injection regex is correct on the structured path.** `_is_spurious_injection` (:438–456) drops
  parameterized `%s`/`%(name)s` and keeps concat/f-string/`.format()`/`%`-operator. (One narrow edge: a
  named placeholder `"%(n)s"` at the *start* of a string literal can match the `["']\s*%\s*[\(\w]` marker
  → kept as "string-build"; minor.) `#1873`'s injection note survived only because it was FREEFORM (guard
  never ran) AND was `[INFO]` (not the blocker; the blocker was a `[WARNING]` "no unit tests").
- **Evidence verification handles multi-file diffs** — `_evidence_in_diff` concatenates all `+/-` lines
  across the whole diff (:425), file-agnostic. Sound, but unreachable on freeform.
- **`platform_settings` has zero `forge:%` rows** → all guards run on code defaults (enabled). Benign,
  but there is no telemetry of structured-vs-freeform fallback and no lever to force the structured path.
- **`_self_refute_criticals` is fail-OPEN** (:521,529,531) — under `escalation_mode='local_only'` a
  cold/blocked gemma3:12b audit keeps the unrefuted CRITICAL. Only matters on the structured path.

---

## Quick wins (prompt/guard tweaks — no model change, low risk)

Ranked by leverage. All are edits to `pr_diff_analyzer.py` (or one cross-file deletion).

### QW-1 — Run the same evidence/severity recompute on the FREEFORM text *(closes RC-1, the dominant cause)*
Parse the freeform `- [SEV] <title> — <why> — Evidence: <line>` lines (the prompt already mandates this
format, :219–221) into the same issue dicts the structured path uses, then run `_verify_evidence` +
`_is_spurious_injection` + `_recompute_verdict` before persisting. Replace the lone `_apply_severity_gate`
call at `_run_forge_review:667`.
- **Mechanism closed:** the ungated freeform escape hatch that handles ~80% of reviews.
- **File:** `pr_diff_analyzer.py` (`_run_forge_review` :629–672; reuse `_verify_evidence`/`_recompute_verdict`).
- **Effort:** M · **Risk:** Low–Med (needs a robust freeform-issue parser; fail-open to current behavior).
- **Would have caught:** `#1865` duplication, `#1872`/`#1873` test flags (via severity normalizer below),
  `#1867`/`#1873` injection (the `%s` evidence is droppable once the guard runs on freeform).

### QW-2 — Deterministic severity normalizer / non-blocking category allow-list *(closes RC-2)*
Before the `has_blocking` / `_recompute_verdict` check on BOTH paths, demote issues whose title matches a
non-blocking class — `missing tests|no unit tests|add tests|type hint|docstring|duplication|naming|
style|sys.path|consider|best-effort except` — to `[INFO]` regardless of the model's label. (Alternative:
WARNING → NEEDS REVIEW, only CRITICAL blocks — but the explicit allow-list is safer and auditable.)
- **Mechanism closed:** model-controlled severity over-labeling escalating true-but-trivial nits to a block.
- **File:** `pr_diff_analyzer.py` (new `_normalize_severity(issues)`; call in `_recompute_verdict` and the
  freeform path from QW-1). Optionally extend the rubric (:34–52) with an explicit severity table.
- **Effort:** S–M · **Risk:** Low (only relaxes; pair with a CRITICAL allow-list so real bugs still block).
- **Would have caught:** `#1868` type-hints, `#1872`/`#1873` "no/lack of tests", `#1865`/`#1864` duplication,
  `#1871` sys.path/except — i.e. **every** residual false-block in the observed set.

### QW-3 — Fix the `classify_pr_tier` branch-key bug *(closes RC-3a)*
Change `branch = (review.get("branch") or "")` → `(review.get("head_branch") or "")` at
`pr_review_service.py:529`.
- **Mechanism closed:** migrations/numbered branches silently reviewed by qwen2.5:7b instead of gemma3:12b.
- **File:** `pr_review_service.py:529`. · **Effort:** S · **Risk:** Very low (one-line; widens Tier-3).
- **Would have caught:** `#1867` "missing semicolon" on a numbered SQL migration (routes it to the
  stronger model that doesn't hallucinate the syntax error).

### QW-4 — Quote/remove the verdict MENU line in the prompt *(closes RC-3d)*
Change `_build_prompt:225` from the literal `VERDICT: APPROVE | REQUEST CHANGES | NEEDS REVIEW` menu to a
single-choice instruction (e.g. `End with exactly one line: "VERDICT: <APPROVE|REQUEST CHANGES|NEEDS
REVIEW>" — choose ONE.`). Add a guard in `parse_verdict` for a line containing *all three* tokens →
treat as un-chosen / NEEDS REVIEW.
- **Mechanism closed:** model echoes the menu; reject-first regex misreads it.
- **File:** `pr_diff_analyzer.py:225` (+ optional `pr_review_service.py:56` parse guard). · **Effort:** S ·
  **Risk:** Very low.
- **Would have caught:** `#1865`/`#1866` (currently a luck-of-regex near-miss, not yet a false-block).

### QW-5 — Set `num_ctx≈8192` + `temperature≈0` for the review dispatch *(closes RC-3c)*
The review prompt must keep the rubric in-window and be deterministic. Pass review-specific Ollama options
so the rubric (top of prompt) is never slid out of a 2048 default window, and decoding is deterministic.
- **Mechanism closed:** rubric truncated out of the context window on long diffs; high-temp nondeterminism.
- **File:** the `dispatch(..., capability='code_review', json_mode=True)` call sites (:581, :641) — thread
  an `options`/`num_ctx`/`temperature` through to `call_ollama_json` (`archie_bridge.py:~168`).
  ⚠️ `num_ctx` inflates the 8GB-GPU KV cache (ai-bridge.md) — scope it to the code_review dispatch ONLY,
  do **not** raise it globally.
- **Effort:** M · **Risk:** Med (VRAM on the M4000/3070 — verify it fits; review runs on Defiant/hub only).
- **Would have caught:** the whole "rubric ignored on long diffs" class — indirectly reduces the freeform
  fallback rate too (cleaner JSON when the model actually sees the JSON-only instruction).

### QW-6 — Make `_truncate_diff` split at a `diff --git` / file boundary *(closes RC-3b)*
Prefer the last `\ndiff --git` before the cap; only fall back to `\n@@`, then a raw byte cut. Stops slicing
a single oversized SQL hunk mid-`CREATE TABLE`.
- **File:** `pr_diff_analyzer.py:186–187`. · **Effort:** S · **Risk:** Low.
- **Would have caught:** `#1867` "missing semicolon" (the truncation trigger; QW-3 also helps by upgrading
  the model).

---

## Structural (evidence-gate redesign, model tier — higher effort/risk)

### ST-1 — Collapse to ONE grounded path: make structured the only path; retry instead of falling to ungated freeform
Harden `_parse_review_json` against markdown fences/prose (strip ```json fences, take the largest
balanced `{...}`), and on parse failure **re-prompt once** ("return ONLY JSON") before falling back. If it
still fails, fall back to **freeform-through-the-same-gates** (QW-1), never to raw ungated text. This makes
RC-1 structurally impossible rather than patched.
- **Mechanism closed:** the existence of two non-equivalent verdict paths.
- **File:** `pr_diff_analyzer.py` (`_parse_review_json` :348–367, `_structured_review` :563–626, the
  `or _run_forge_review(...)` fallthroughs :84/:136). · **Effort:** M–L · **Risk:** Med.

### ST-2 — Make `_self_refute_criticals` fail-CLOSED / quarantine under `local_only`
When the gemma3:12b audit is unavailable (cold/queued/`escalation_mode=local_only`) or returns
unparseable JSON, **do not keep the unrefuted CRITICAL** — downgrade to NEEDS REVIEW (human) or quarantine,
instead of fail-open (:521/529/531).
- **File:** `pr_diff_analyzer.py:494–531`. · **Effort:** S–M · **Risk:** Med (could surface a real CRITICAL
  as NEEDS REVIEW — acceptable: human sees it).
- **Would have caught:** `#1869` `[CRITICAL] "unclosed loop"` recurrence when the auditor is unavailable.

### ST-3 — Right-size the model tier for code review (MODEL-CAPABILITY limit, not a guard gap)
The 7B is a *contributing* constraint, not the binding one (prompt/plumbing is). But after QW-1/QW-2/QW-5,
the residual hallucination floor is the 7B's reasoning under `format:json`. Options, in order of cost:
(a) default code_review to gemma3:12b on the hub/Defiant (already wired via Tier-3 — just widen who gets it
once QW-3 lands); (b) a small fine-tune/distillation on the accumulating `_writeback_false_positives` KB
quarantine (:534–559) so the 7B stops repeating its own confirmed false positives.
- **File:** dispatch model selection (`_structured_review` :577–579; `CAPABILITY_*` routing). · **Effort:**
  L · **Risk:** Med (VRAM/latency: 12B is slower; reserve for migration/security/large PRs).

### ST-4 — Observability: emit `forge:%` telemetry + a structured-vs-freeform metric
Persist per-review which path ran (already inferable from `[review-meta]`) into a counter, and seed
`platform_settings forge:*` rows so an operator can force the structured path / tune
`forge:review_confidence_min` without a code change. Prevents a future silent 100%-freeform regression if
someone sets `forge:structured_review_enabled=false`.
- **File:** `pr_diff_analyzer.py` (`_get_setting` :299–312) + a small metrics write. · **Effort:** M ·
  **Risk:** Low.

---

## Recommended order

1. **QW-3** (one-line branch-key fix) — trivial, immediately routes migrations to gemma3:12b. *(RC-3a)*
2. **QW-2** (severity normalizer) — kills the **dominant residual class** (true-but-trivial WARNINGs) on
   BOTH paths in one change. *(RC-2)*
3. **QW-1** (gate the freeform text) — closes the **dominant root cause** (the ungated 80% path). *(RC-1)*
4. **QW-4** (verdict menu) + **QW-6** (file-boundary truncation) — small, independent, low-risk. *(RC-3d/3b)*
5. **QW-5** (num_ctx/temperature) — bigger blast radius (VRAM), do after the cheap wins prove out. *(RC-3c)*
6. **ST-1** (collapse to one grounded path) — makes RC-1 structurally impossible; supersedes the QW-1 patch.
7. **ST-2** (fail-closed self-refute), **ST-4** (telemetry), then **ST-3** (model tier / distillation).

QW-1 + QW-2 together would have caught **all five** observed false-flags; with QW-3/QW-6 added, the
migration/SQL class (`#1867`) is fixed at both the model-routing and truncation layers.

---

## Guard GAPS (fixable in pr_diff_analyzer / pr_review_service) vs MODEL-CAPABILITY limits (7B)

| Defect | Category | Fix |
|---|---|---|
| Guards only on structured path; freeform ungated (RC-1) | **Guard gap** | QW-1 / ST-1 |
| Severity over-labeling treated as blocking (RC-2) | **Guard gap** | QW-2 |
| `classify_pr_tier` reads non-existent `branch` key (RC-3a) | **Guard gap (plain bug)** | QW-3 |
| Hunk-only truncation slices SQL mid-statement (RC-3b) | **Guard gap** | QW-6 |
| Verdict menu echoed + reject-first parse (RC-3d) | **Guard gap** | QW-4 |
| 2048 num_ctx drops the rubric; default temp (RC-3c) | **Plumbing gap** (not the model) | QW-5 |
| 7B reasoning floor under `format:json` after all above | **Model-capability limit** | ST-3 |
| Fail-open self-refute under local_only (RC-3 secondary) | **Guard gap** | ST-2 |

The binding constraint is **plumbing + guard-path routing, not the 7B**. A stronger model would *mask*
the problem, but QW-1/QW-2/QW-3/QW-5 recover most of the loss on the existing 7B.

---

## Evidence

| Claim | Location |
|---|---|
| Dual path `_structured_review(...) or _run_forge_review(...)` | `pr_diff_analyzer.py:84`, `:136` |
| `_structured_review` returns None on flag/dispatch/queue/empty/unparseable | `:566`, `:589–591`, `:592–593`, `:594–595`, `:596–599` |
| All PR-C guards inside structured path only | `_verify_evidence` :603–610 · `_self_refute` :612–623 · `_recompute_verdict` :625 |
| Freeform path runs only `_apply_severity_gate` | `:666–667` |
| Severity gate relaxes ONLY when no CRITICAL/WARNING | `:271–273` |
| `_recompute_verdict` blocks on any CRITICAL/WARNING | `:373` |
| `_evidence_in_diff` keeps empty/`<6`-char evidence (absence-class flags survive) | `:423`, `:428–429` |
| `_is_spurious_injection` regex (correct; parameterized `%s` dropped) | `:455` |
| `_truncate_diff` hunk-boundary + raw byte fallback | `:186–187` |
| Rubric is at the TOP of the prompt (slid out of 2048 window) | `:204` |
| Verdict MENU line in prompt | `:225` |
| `[review-meta] structured=json` stamp only on structured path | `_render_review_text` :400 |
| `_self_refute_criticals` fail-open | `:521`, `:529`, `:531` |
| `classify_pr_tier` reads `review.get("branch")` — no such column | `pr_review_service.py:529` |
| `get_review` does `SELECT *` (columns are `head_branch`/`base_branch`) | `pr_review_service.py:493–498` (VERIFIED) |
| `parse_verdict` checks REJECT regex first | `pr_review_service.py:49`, `:70` |
| `call_ollama_json` payload: `format:json`, NO `options`/`num_ctx`/`temperature` | `ai_bridge/archie_bridge.py:~168` (VERIFIED) |
| Live DB: only `#1867`/`#1869` structured+APPROVE; `#1865`/`#1872`/`#1873` (+`#1864`/`#1868`/`#1871`) freeform | findings — `pr_reviews` SELECT, 13/15 no `[review-meta]` |
| `platform_settings` has 0 `forge:%` rows → all defaults | findings — `SELECT … WHERE key LIKE 'forge:%'` → 0 rows |
| Real diff reaches model (not bare diff_url) | `_fetch_diff` :170–177 |
