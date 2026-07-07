# Coordinator Lane — Design Spec

- **Date:** 2026-07-06
- **Author:** Claude (Opus) + Kytran (brainstorm)
- **Status:** Approved design — ready for implementation planning
- **Branch:** `feat/coordinator-lane`
- **Related:** ADR-887 (KB #278815, latency-first refined-B) · handoff cont-127 · #4661 (Agent Academy A/B, shipped) · Project #375 (dispatch optimization)
- **Approach:** A — thin `coordinator_lane` service + config key (alternatives B/C rejected, see §3)

---

## 1. Problem & Context

The dispatch pipeline's 8-step orchestration (`orchestration_engine.py:229 orchestrate`) invokes an LLM in only two places: **step 1 (parse intent)** — light — and **step 7 (execute)** — heavy. Steps 2–6 and 8 (creed, route decision, GPU check, agent select, welfare, log) are already **pure code**. So the north-star principle — *"keep routing decisions in code, not an LLM in the hot path"* — is already largely true.

What is **not** clean today (found via code map, cont-127 session):

1. **Heavy fallback landmine.** The intent-parser's LLM path resolves its model via `get_model_for_capability("classify")` with a **default of `dolphin3-8k:latest` (an 8B model)** at `archie_engine_staging/intent_parser.py:57`. A cold 8B in the meta-reasoning hot path is exactly the latency failure ADR-887 diagnosed (7B/8B cold-loads = 3–13 min, ~23% warmup timeouts).
2. **Scattered resolution.** The lightweight consumers (intent parse, `classify`, sentiment `emotional_intelligence.py:150,173`, tagging `auto_tagger.py:312,333`, detect_language `translation_service.py:99`, news-beat `wtf_beat_classifier.py:215`) each resolve their own model through the capability→department→agent chain. There is no single designated "coordinator" the lane shares.
3. **Not reproducible / not sized.** `qwen25-classify` is registered directly in Ollama on the fleet — **no committed Modelfile** — and is **absent from `model_sizes.py`** (only `qwen2.5:0.5b` at line 35). Nothing declares its size/`prefer_gpu`.
4. **No config designation.** There is no `platform_settings` key naming the coordinator model, so it cannot be swapped without a code deploy — blocking the benchmark-driven upgrade (#4661).
5. **No plan step.** There is no LLM planning/decompose step. Multi-agent need is detected by regex (`intent_parser.py:677 _detect_multi_agent_requirement`); `orchestrate_joint` (`orchestration_engine.py:2288`) exists but nothing decomposes a complex request into ordered sub-tasks.

**The existing coordinator-lane precedent** = capability `classify` → `CAPABILITY_DEPARTMENT_MAP` (`department_coordinator.py:46`) → Analytics & Intelligence → **I.R.I.S. (agent #8)** → Ollama `qwen25-classify` (~1.5B, CPU-only, <500ms; declared `smart_router.py:77-84`, tier `ModelTier.CLASSIFY` `:37`).

## 2. Principle (the invariant everything serves)

> The coordinator lane is dispatch's meta-reasoning fast path: **one designated, always-warm, small local model** performs the *linguistic* work of dispatch — parse intent, classify capability, decompose complex requests. **Routing decisions stay in code.** The LLM proposes structured output; code disposes. The lane is config-swappable and isolated so meta-reasoning never stalls behind a cold heavy model.

## 3. Approach decision

**Chosen: A — thin `coordinator_lane` service + config key.** Smallest new surface, fully unit-testable, does not perturb the tier/queue/admission code hardened in cont-126/127. Isolation via warm-pin + admission-control exemption (sufficient for a <500ms CPU model), not a new queue.

Rejected:
- **B — first-class `COORDINATOR` tier + dedicated `dispatch_pending_queue` lane.** Architecturally purest but reopens `smart_router` tiers + the queue + admission control — high regression risk on freshly-stabilized code, marginal gain over A.
- **C — agent-centric (make I.R.I.S. THE coordinator, swap model via agent row).** Elegant and reuses `select_agent`, but model-swap-via-agent-row is clunky for benchmarking and gives neither lane isolation nor the fallback fix on its own. Its best idea (pin capabilities to I.R.I.S.) is folded into A.

## 4. Scope (all three levels approved) + gating decisions

- **Level 1 — Consolidate + harden** (Phase 1).
- **Level 2 — Gated plan step** (Phase 2).
- **Level 3 — Benchmark + swap** (Phase 3).

Approved judgment calls:
- **Plan gating:** the plan step fires **only** when the multi-step/multi-agent gate fires; single-shot requests skip it entirely (zero added latency). Plan is **advisory** — the coordinator model emits ordered `[{sub_task, capability}]`; **code** dispatches each via the normal capability router.
- **Admission-control exemption (approved):** coordinator-lane calls **bypass** the hub backpressure gate (PR #2080/#2082). Rationale: the lane is what *relieves* saturation; shedding it is self-defeating, and a tiny CPU model is never the saturation source.
- **Phase 2 drives real execution (approved):** the plan step wires into the existing `orchestrate_joint` multi-agent path so decomposition drives actual sub-task execution — not a decorative plan object.
- **Nothing cut:** Modelfile commit and the sentiment/tagging/language consumers stay in Phase 1 scope.

## 5. Core component — `platform_v2/services/coordinator_lane.py` (new, thin)

Single owner of "what is the coordinator model + how do I call it."

```
get_coordinator_model() -> str
    Reads platform_settings['dispatch:coordinator_model']; default 'qwen25-classify'.
    TTL-cached (mirror existing resolver caches). THE only place the model is named.

coordinator_dispatch(capability, prompt, *, json_mode=False, timeout_s=30) -> DispatchResult
    Wraps department_dispatcher.dispatch() with:
      - model_override = get_coordinator_model()
      - prefer_agent = 'I.R.I.S.'  (belt-and-suspenders with the CAPABILITY_SPECIALIST_MAP pin)
      - lane = 'coordinator'  (threaded to admission-control exemption + task_execution_log telemetry)
      - short timeout (~30s, NOT the 240s heavy timeout)
    Fail-open: on failure returns a sentinel the caller maps to its non-LLM fallback.

plan(message, intent) -> list[PlanStep]
    ONE coordinator_dispatch(capability='plan', json_mode=True) call.
    Returns validated, bounded [{sub_task, capability}]:
      - cap at dispatch:coordinator_plan_max_steps (default 6)
      - drop steps whose capability is not a known capability (validate against CAPABILITY_DEPARTMENT_MAP / agent_skills)
      - dedupe
    Pure parse/validate around the single LLM call.

COORDINATOR_CAPABILITIES = {intent, classify, sentiment, tagging, detect_language, plan}
```

**Config keys** (all `platform_settings`, no-deploy tunable, fail-open):
- `dispatch:coordinator_model` — default `qwen25-classify`.
- `dispatch:coordinator_plan_max_steps` — default `6`.
- `dispatch:coordinator_lane_enabled` — kill switch; off → exact current behavior.

## 6. Phase 1 — Consolidate + harden (ships alone, low risk)

1. **Kill the landmine.** `intent_parser.py:57` — change the classify-model fallback so it resolves through `coordinator_lane.get_coordinator_model()` instead of defaulting to `dolphin3-8k:latest`. A heavy 8B is never the fallback for meta-reasoning again.
2. **Route light consumers through the lane.** Point the intent-parse LLM path (`intent_parser.py:481 _llm_classify` / `:510`), `classify`, sentiment, tagging, detect_language at `coordinator_dispatch`.
3. **Reproducibility + sizing.**
   - Add `qwen25-classify` to `platform_v2/services/model_sizes.py` with `prefer_gpu=False` (so the concurrent-heavy cap from PR #2085 never treats it as heavy) + realistic size.
   - Commit `/mnt/llm_drive/ollama/Modelfile.qwen25-classify` capturing the live `FROM <base>` + `SYSTEM` prompt of the running fleet model (read it off the fleet before writing).
4. **Lane isolation (two lightweight guarantees, no new queue):**
   - **Always-warm pin** — formalize the existing warm-keep (`ai_bridge/agent_loop.py:3433 ("qwen25-classify", 0)`, CPU-pinned `:502`) as a documented hard invariant across the warm-boot set.
   - **Admission-control exemption** — the hub backpressure guard at the top of `_execute_llm` (`department_dispatcher.py`, from PR #2080/#2082) and `welfare_governance_service.hub_lane_over_cap` must NOT shed `lane == 'coordinator'` calls. Add the exemption predicate.

**Phase 1 = the "consolidate + harden" level. Independently valuable; PR + F.O.R.G.E. + deploy + live-verify before Phase 2.**

## 7. Phase 2 — Gated plan step

- New `_step_plan` in `orchestration_engine.py`, placed between step 1 (`_step_parse_intent` `:920`) and step 2 (`_step_creed_check` `:949`).
- **Gate:** runs only when the intent flags multi-step/multi-agent work — reuse the existing regex `intent_parser.py:677 _detect_multi_agent_requirement` as the gate; the coordinator LLM does the decomposition. Single-shot → step skipped (zero latency).
- **Output:** `coordinator_lane.plan(message, intent)` → `[{sub_task, capability}]`, attached to the orchestration context.
- **Execution wiring (approved):** feed the plan into the existing `orchestrate_joint` (`:2288`) multi-agent path so each sub-task is dispatched via the normal capability router — code decides each route.
- **I.R.I.S. skill:** seed an `agent_skills` row `plan` / `task_planning` for agent #8 so capability routing resolves `plan → I.R.I.S.` naturally (belt-and-suspenders with the specialist pin). Add `plan → Analytics & Intelligence` to `CAPABILITY_DEPARTMENT_MAP` if not present.

## 8. Phase 3 — Benchmark + swap

- Reuse the **shipped #4661** Agent Academy A/B (`tools/agent_academy/ab_compare.py` + `ab_compare_worker` sidecar; LOCAL qwen2.5:7b judge).
- Feed a fixed set of **golden coordinator prompts** (intent + classify + plan cases) with known-good expected outputs.
- **Candidates:** `qwen25-classify` vs `phi4-mini` / `gemma2:2b`. ⚠️ Pulling a new model to the fleet nodes (OTA) may be owner-gated — flag, don't assume.
- **Promote-winner** action writes `platform_settings['dispatch:coordinator_model']` = winner. Because everything resolves through `get_coordinator_model()`, the swap is instant with no deploy — the entire reason the config key exists.

## 9. Data flow (end to end)

```
orchestrate(request)
 1   parse_intent:   regex _quick_classify (conf>0.9 → done, NO LLM)
                     else coordinator_dispatch(classify|intent, json)      ← LANE
 1.5 plan (ONLY if _detect_multi_agent_requirement):
                     coordinator_lane.plan(message, intent) → [{sub_task, capability}]  ← LANE
                     → orchestrate_joint dispatches each sub-task (CODE routes)
 2-6 creed / route_decision(classify_task) / gpu_check / select_agent / welfare  — ALL CODE
 7   execute:        heavy agent model                                     — NOT the lane
 8   log:            lane='coordinator' tag → task_execution_log
```

## 10. Error handling — fail-open, never fail-heavy

- Coordinator unavailable / timeout / malformed JSON → fall back to the regex `_quick_classify` result (intent) or the default capability (classify); plan → skip decomposition, treat as single-shot.
- **Never** fall back to a heavy model; **never** block dispatch on a coordinator failure.
- Kill switch (`dispatch:coordinator_lane_enabled=false`) → behaves exactly as today.
- Plan validation: bound step count, validate each capability against known capabilities (drop unknown), dedupe.

## 11. Testing

**Unit (no LLM — AST/source-exec pattern per cont-127's `db`-import gotcha, KB #278809/TestModelIsGpuClass):**
- `get_coordinator_model` — config resolution, default, cache behavior.
- `plan()` JSON parse/validate: valid, malformed, over-cap (>max_steps), unknown-capability step dropped, dedupe.
- The multi-step gate predicate.
- The admission-exemption predicate (`lane=='coordinator'` bypasses).

**Integration (live, via `bridge_jobs` / `task_execution_log` DB assertions):**
- Low-confidence intent → `model_used == qwen25-classify` (NOT `dolphin3-8k`) in `task_execution_log`.
- Complex request → plan produced + sub-tasks dispatched via `orchestrate_joint`.
- Simple request → no coordinator call (regex short-circuit).
- Admission over-cap → a `lane='coordinator'` call is NOT shed.

**Benchmark (Phase 3):** reuse #4661's tests; add coordinator golden prompts.

## 12. File-level change map (anchors from code map)

| Area | File:line | Change |
|------|-----------|--------|
| New service | `platform_v2/services/coordinator_lane.py` | NEW — model resolution, `coordinator_dispatch`, `plan` |
| Landmine fix | `archie_engine_staging/intent_parser.py:57` | fallback → `get_coordinator_model()` |
| Lane routing | `intent_parser.py:481,510`; `emotional_intelligence.py:150,173`; `auto_tagger.py:312,333`; `translation_service.py:99`; `wtf_beat_classifier.py:215` | call through `coordinator_dispatch` |
| Sizing | `platform_v2/services/model_sizes.py` | add `qwen25-classify` (`prefer_gpu=False`) |
| Modelfile | `/mnt/llm_drive/ollama/Modelfile.qwen25-classify` | NEW (capture live FROM+SYSTEM) |
| Warm pin | `ai_bridge/agent_loop.py:3433,502` | formalize invariant |
| Admission exemption | `department_dispatcher.py` `_execute_llm` guard; `welfare_governance_service.hub_lane_over_cap` | exempt `lane=='coordinator'` |
| Plan step | `orchestration_engine.py` (new `_step_plan` between `:920` and `:949`); `:2288 orchestrate_joint` | Phase 2 |
| Capability map | `department_coordinator.py:46 CAPABILITY_DEPARTMENT_MAP`; `agent_skills` (I.R.I.S. #8) | add `plan` |
| Benchmark | `tools/agent_academy/ab_compare.py` + `ab_compare_worker` | Phase 3 golden prompts + promote-winner writes config key |

## 13. Ship order & governance

Phase 1 → PR → F.O.R.G.E. review → deploy (`archie-deploy`) + live-verify → Phase 2 → … → Phase 3. Each phase is its own PR, independently valuable, live-verified before the next. Log ADRs for the admission-exemption decision and the coordinator-lane abstraction. Bookkeeping after each merge: `complete_task`, `log_decision`, `update_project_understanding`, C.O.D.E.X. docs.

## 14. Open risks

- **OTA model pull (Phase 3)** may be owner-gated — do not assume `phi4-mini`/`gemma2:2b` can be pulled to fleet nodes without approval.
- **`intent_parser.py` lives in `archie_engine_staging/`** (with an `archie_core` fallback) — confirm which path is live before editing; the map showed the staging path as primary.
- **Admission exemption** deliberately pokes freshly-hardened code (PR #2080/#2082) — must be a narrow, well-tested predicate with the kill switch as the safety net.
