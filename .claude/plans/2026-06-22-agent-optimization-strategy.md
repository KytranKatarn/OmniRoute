# Agent Optimization — F.O.R.G.E. + Right-Sized, Learning, Resellable Custom Agents

**Date:** 2026-06-22 · **Source:** 6-agent read-only investigation + synthesis (workflow `wf_92388405`)
**Trigger:** F.O.R.G.E. (code-review agent, qwen2.5:7b) hallucinated review flags on ~8/10 verified-correct PRs.
**Owner vision:** agents read + learn from a growing KB; Agent Academy tunes/trains/creates **right-sized** custom
LLMs per role (not full LLMs saturating on simple tasks); productize as sovereign, CREED-aligned, energy-efficient
custom agents — internal AND resellable.

## North star
> A repeatable pipeline that **creates an optimized, right-sized, correctness-verified agent for role X**, runs it
> on sovereign Canadian hardware, measures its energy/CO₂, grades it under CREED, and lets it learn from a growing KB —
> first for Kytran Empowerment, then sold as a SKU.

**~60% of the machine already exists; the work is WIRING + one keystone (a correctness grader).**

---

## Root cause: why F.O.R.G.E. hallucinates
All 4 observed false flags map 1:1 to fixable causes (NOT "the model is bad"):
1. **Zero KB grounding** — `pr_diff_analyzer._build_prompt` (lines 153-181) never calls `search_mistakes`/`search_knowledge`. It repeats myths forever (parameterized ≠ injection; compiling file ≠ syntax error; same-PR test file = tests).
2. **Freeform output → regex `parse_verdict`** — no rubric, no forced evidence; it can *say* anything.
3. **6000-char diff truncation cuts mid-file** (line 156) → produced "no tests added" (test file cut) + "unclosed loop" (loop body truncated).
4. Only `qwen2.5:7b` (code floor, ~15% hallucination) is ever used; `gemma3:12b` (3-5%, already warm) never used for review.
5. No confidence tracking → non-deterministic verdicts silently auto-merge.

---

## PHASE 1 — Stop F.O.R.G.E. hallucinating + KB-ground reviews (DAYS)
**Goal:** ~15% false-rate → <2-3%, every issue cites a diff line, no model retrain. All on existing infra.
Files: `platform_v2/tools/repair_bay/services/pr_diff_analyzer.py`, `pr_review_service.py`, `services/agent_kb_service.py`, `department_dispatcher.py` (`_get_rag_context`).

| # | Fix | Effort |
|---|-----|--------|
| 1 | **Grounding rubric** in `_build_prompt`: `search_mistakes('code review false positive')` + seed the 4 confirmed myths + "if you can't cite the exact ± line, don't raise it." | small (~30 lines) — **biggest win** |
| 2 | **Force JSON output** — `dispatch(json_mode=True)` (plumbing exists, dept_dispatcher:10138) with `{verdict, confidence, issues:[{severity, line, why, evidence:"<verbatim diff line>"}]}`; `parse_verdict_json()` + regex fallback. | small |
| 3 | **Hunk-boundary truncation** — cut at last `\n@@` < limit (not byte 6000); raise cap ~12k. | tiny (2 lines) |
| 4 | **Confidence-gated**: `<0.7` → `mark_review_pending` (no auto-merge); `classify_pr_tier ≥ 3` → `preferred_model='gemma3:12b'`. | small |
| 5 | **Self-refute pass** on low-confidence/CRITICAL → second dispatch "audit your own findings, cite the line or delete"; **intersect** findings. | medium |
| 6 | **False-positive KB write-back** — clean-merge after a flag → `agent_kb_service.propose_agent_memory(agent 136, mistake_learned, tags=[code_review,false_positive])` → quarantine → C.O.D.E.X. promote → next review's grounding reads it (self-improving). | medium |
| 7 | **Generalize**: capability→KB-tags map in `_get_rag_context` so ALL agents auto-inject role-relevant mistakes. | medium |

**Sequencing:** PR-A = #1 + #3 (the anti-hallucination core; verify by re-reviewing a PR that hallucinated today and confirming the false flag is gone). PR-B = #2 + #4. PR-C = #5 + #6. PR-D = #7.
**Verification:** re-run `review_pr()` on PRs #1867 (false "SQL injection") / #1869 (false "unclosed loop") and confirm the flags disappear.

---

## PHASE 2 — Optimized-agent-creation pipeline (WEEKS)
**Goal:** repeatable "create a right-sized, correctness-verified agent for role X"; fleet stops running 7B on trivial work.
- **KEYSTONE — correctness grader:** `benchmark_service.grade_response()` → 0-5 correctness via grader agent (P.R.O.B.E./V.E.R.I.F.Y.), stored as the **primary** score (today benchmarks measure length/speed → why hallucinations slipped through).
- **Complexity overlay** before capability routing in `orchestration_engine`: 0-3→smallest model, 4-6→default, 7-10→escalate (wire the existing `complexity_threshold` DB values; dispatch currently routes by capability ALONE — no complexity gate).
- **Auto-promotion:** flip `update_roster_models(dry_run)` → live scheduled job: majority-vote over ≥5 graded samples/14d + **Pareto guard** (no bigger/slower model for <2% gain) → auto-export Modelfile.
- **Role→prompt template library** (capability→role instruction) + wire `proficiency_level` + `agent_identity` persona into the system prompt.
- **Per-agent carbon ledger:** `energy_joules`/`carbon_kg_co2e` on `task_execution_log` + daily rollup → K.I.N. tab. (Carbon is *measured* hourly today but never *enforced*; no per-agent ledger.)
- **Per-capability welfare budgets** (split `MODEL_TOKEN_BUDGETS`) so over-work/idle is visible per role.
- **CREED "efficiency" pillar** — tokens/dispatch, % right-sized, CO₂/task as a public governance metric.

## PHASE 3 — Resellable sovereign custom-agent SKU (MONTHS, gated on Phase 2 grader)
**SKU:** *"a sovereign, CREED-certified, carbon-measured custom agent, right-sized to your role, on Canadian hardware."*
**~60% exists:** `create_agent`/`propose_hire`, Modelfile auto-export, multi-tenant orgs+`org_nodes` (sovereignty), Stripe billing, CREED tenanting, fleet. **Gaps:**
- `custom_agent` billing SKU + `agent_quota` enforced in `propose_hire` (starter 1 / pro 3 / enterprise ∞).
- Per-org self-service provisioning (`/orgs/<id>/agents`) — delegate approval to the org owner within tier; auto `creed_tenant` + node bind.
- Per-agent CREED welfare score + public carbon/efficiency SVG badge.
- **Per-agent KB isolation** (`agent_knowledge_access` + `knowledge_base.org_id/is_private`) — data sovereignty (also a selling point).
- Per-org resource quotas (VRAM reservation + concurrency) at dispatch-queue entry, tied to tier.
- **`ft_*` QLoRA distillation service** (tables exist in migration 042, zero routes) — distill big-model graded *wins* into a role-tuned **small** model. **The moat no general-LLM reseller can match.**

---

## Decisions for Kytran (gate Phases 2/3)
1. **GPU/fine-tune budget** — dedicated training node, or QLoRA-on-M4000 (4-bit, slow) only? Gates true fine-tunes vs prompt/Modelfile tuning.
2. **Auto-promotion autonomy** — may Academy auto-swap an agent's model on a Pareto-guarded benchmark win, or Tier-2 gate every change?
3. **CREED efficiency grade — public or internal?** Public = stronger grant/AI-for-All narrative.
4. **Custom-agent pricing/tiers** — per-agent seat? bundled with Watch? carbon-offset fee?
5. **Data-sovereignty default** — isolated KB (stronger claim, more build) or shared-KB + opt-in privacy?
6. **Cloud escalation for reviews** — escalation is global-OFF (local-only); allow paid cloud for high-stakes low-confidence PRs, or stay strictly sovereign?

## Quick wins (ship-this-week)
F.O.R.G.E. grounding rubric · `json_mode` + evidence field · hunk-boundary truncation · tier-3→gemma3:12b + confidence-gate · turn ON `agentic_tool_search` for code_review/research/docs agents · false-positive KB write-back.
