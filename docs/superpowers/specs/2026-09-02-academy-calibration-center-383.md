# Agent Academy as the Calibration Center (project #383)

**Date:** 2026-09-02 · **Project:** #383 Local Model Diversification & A/B Program
**Supersedes the scope of:** `.claude/plans/2026-07-07-local-model-diversification.md` (still
correct on candidates; stale on hardware — see below)
**Revives the intent of:** #825 "Performance benchmarking across models and nodes" (CANCELLED)
**Unblocks:** #4707, #5870 · **Evidenced by:** #6276

---

## The charter (owner, 2026-09-02)

> "The Academy Bay module is supposed to be the Main Center for all the testing, Platform
> jobs and LLM agent coordination — so that K.I.N. can staff and schedule optimal."

Academy is not a training side-module. It is the **measurement organ** of the fleet. It
answers, empirically and continuously:

> for capability C, which MODEL on which HARDWARE gives the best output per unit of time
> and welfare — and is that still true this week?

Its output is not a report anybody reads. It is **an input to two automated consumers**:

```
Academy measures ──> (capability, model, node, tier) winners
                          │
                          ├──> smart_router / CAPABILITY_DEPARTMENT_MAP   → placement
                          └──> K.I.N.  → staffing, scheduling, hire proposals
```

That loop is the whole point. A benchmark nobody routes on is a blog post.

## Why this is urgent, not theoretical — #6276

On 2026-09-02 three consecutive F.O.R.G.E. reviews produced NO verdict, ~60 min of fleet
time, zero output. Root cause: **#6040 changed WHO reviews machine-authored PRs (F.O.R.G.E.
→ P.R.O.B.E.) without changing WHAT the residency profile keeps warm.** F.O.R.G.E. runs
`qwen2.5:7b` (warm on the Defiant's reserved 8GB, confirmed in `model_load_state`);
P.R.O.B.E. runs `qwen2.5-coder:7b`, resident on NO node. Every machine-PR review is a cold
load onto a card already 4.8GB spoken for.

Nobody was checking that **the model a capability actually dispatches** is **the model the
fleet is optimised for**. That is precisely the check Academy exists to automate, and it
went unnoticed for weeks. It surfaced only because a human pushed on three dead reviews.

## What already works (do NOT rebuild)

Measured by reading the code 2026-09-02:

- **`ab_compare.py` is already model-agnostic.** `classify_run()` sets `has_cloud=False`
  when neither side is cloud. `build_judge_prompt` / `parse_judge_result` never mention
  provider. **No change needed.**
- **`/api/ab-test/run` already executes local-vs-local.** The cloud branch is
  `if klass["has_cloud"]:` and the code comment states: *"Both-local falls through
  unchanged to the existing synchronous path below."*
- Storage exists: `action_benchmark_runs` / `action_benchmark_results` (migration 448 added
  `pending_approval`), plus `agent_benchmark_results`, `agent_competency_scores`.
- History + status endpoints exist: `/api/ab-test/history`, `/api/ab-test/run/<id>`.

⚠️ So **#4707 is NOT "build local-vs-local"** — that runs today. The task description is
misleading and should be corrected. The real gap is the HARDWARE dimension.

## The actual gap — there is no node axis anywhere

`ab_test_models()` enumerates local models via
`get_ollama_models(OLLAMA_LOCAL_HOST, OLLAMA_DEFAULT_PORT)` — **the hub, and only the hub.**
Consequences:

1. The dropdown cannot offer a model that lives on USS-246 but not the hub.
2. `/api/ab-test/run` accepts `{model_a, model_b, test_prompt, capability}` — **no node per
   side**, so you cannot express "same model, different hardware", which is the entire
   question #825 was cancelled before answering.
3. Results therefore cannot record WHERE a run executed, so a "winner" is a bare model name
   — and today's data proves that is not a well-formed answer.

**Evidence that placement is as decisive as model choice:** `gemma3:12b` measures **35% on
the hub vs 95% on USS-246** (2,918 runs). That is not a model verdict. Reporting it as one
is how the blocklist got seeded off a 56% fleet-wide average and reversed the same day
(fleet.md, 2026-08-21).

## Slice plan

### Slice 1 — the node axis (this is the unblock; everything else waits on it)
- `GET /api/ab-test/models` returns fleet-wide `{node_id, node_name, model, tier_hint}`,
  sourced from `node_ollama_models` + `remote_nodes.extra_capabilities.ollama_models`
  (both live and agreeing), NOT from a single Ollama host.
- `POST /api/ab-test/run` accepts optional `node_a` / `node_b`; passes them as
  `preferred_node` per side. Absent = today's behaviour, byte-identical.
- Persist `node`, `tier` (gpu/cpu — the tier ACHIEVED, read after the fact) and
  `duration_ms` per side into `action_benchmark_results`.
- ⚠️ A "winner" is the tuple **(capability, model, node, tier)**. Never a bare model name.

### Slice 2 — real prompts, not synthetic
Pull recent REAL prompts per capability (WTF bias/fact_check, a code-review diff, classify
items). A synthetic prompt measures the wrong thing; the plan already says this.

### Slice 3 — the consumers (the payoff)
Winners feed `smart_router` + K.I.N. staffing. Until this lands, Academy is advisory only.
⚠️ **Adoption must stay human-gated**: an automatic model swap driven by a scorer is a
governance change wearing a benchmark's clothes.

### Slice 4 — the drift check that would have caught #6276
A scheduled comparison of **declared vs actual**: for each capability, the model the router
dispatches vs the model the residency profile warms vs what `model_load_state` holds. Alert
on divergence. This is cheap, deterministic, needs NO LLM — and is arguably higher value
than any A/B result, because it catches the class of bug that just cost an hour.

## Traps to respect (each already cost this platform once)

- ⚠️ **`status()['active']` means "we asked", NOT "it is warm."** Verify residency via
  `residency_monitor.check_residency()` / `model_load_state`.
- ⚠️ **`can_node_run_model` is a CAPACITY predicate, not a POLICY one.** It returns True for
  `gemma3:12b` on USS-246 while the residency profile forbids it in writing (#1905: gemma3
  6.3GB + 7B ~5GB cannot coexist on 8GB). Reading the predicate alone nearly produced a
  recommendation that would have EVICTED the warm review 7B.
- ⚠️ **The 2026-07-07 plan's hardware ceiling is STALE.** It says "hub Quadro M4000 8GB → 8B
  is the GPU ceiling"; the hub gained a **TITAN X 12GB on 2026-07-25**, 18 days later.
  Largest single card is now 12GB (total 20GB, and Ollama DOES span cards). Re-derive the
  ceiling before using it to exclude candidates.
- ⚠️ **A model can be resident and still be the wrong choice** — CPU vs GPU tier changes the
  answer entirely. USS-246 is an **i9-12900K with 29.4GB RAM**; the hub is a **2013 pre-AVX2
  Xeon**. "CPU inference is too slow" is a HUB fact and must not be generalised to the
  Starships without measuring.
- ⚠️ Model choice and placement are **separate questions** and must be reported separately.

## Open question for the owner
Should `qwen2.5-coder:7b` be CPU-warm on the Defiant (8GB of 29.4GB RAM, zero VRAM cost, so
both review models stay warm)? It is the first natural Slice-1 datapoint. Unknown until
measured: warm-on-CPU removes LOAD time, not INFERENCE time — if the 600s timeouts are
inference-bound, it helps less than it looks.
