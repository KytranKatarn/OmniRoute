# Coordinator Classify Pool + News Beat-Ownership — Design Spec (#4702)

- **Date:** 2026-07-07
- **Author:** Claude (Opus) + Kytran (brainstorm)
- **Status:** DRAFT — for Kytran review
- **Branch:** `feat/coordinator-classify-pool`
- **Follows:** Coordinator Lane Phase 1 (PR #2087, merged), ADR-887 (latency-first), Project #375
- **Gate:** any agent hire is a **propose_hire recommendation for Kytran's explicit approval** — never unilateral.

---

## 1. Problem (from live data, 2026-07-07)

Phase 1 made the coordinator model config-driven, isolated, and used by 4 rerouted consumers. But the **bulk** of the `classify` capability still runs on `mistral:7b` (heavy). Root causes, from `task_execution_log` (24h):

- **`classify` is served by heavy 7B agents by accident.** The `classify` skill is held by W.A.T.C.H. (mistral:7b, active), S.P.E.C.T.R.A. (mistral:7b, barracked), and others on 7B. **I.R.I.S. (qwen25-classify) is the only small-model classify agent, and she is barracked** → `CAPABILITY_DEPARTMENT_MAP['classify'] = Analytics & Intelligence` selects active W.A.T.C.H.=mistral:7b for most classify work.
- **Same work is 2–3× slower on the heavy model:** quality_scorer classify = 108.7s on mistral:7b vs 41.9s on qwen25-classify; wtf_hub = 26.2s vs 14.1s.
- **I.R.I.S. is a single-agent bottleneck.** 24h: 291 tasks, **100% classify** (wtf_hub 153, quality_scorer 86, archie_platform 51). She does nothing else. Her slowness (archie_platform 94s, quality_scorer 42s) is **queue + wake overhead**, not inference (the 1.5B does wtf_hub classify in 14s) — every task wakes a barracked agent; K.I.N. micro-rests her every ~20–30 min at stress 0.51; repeat.
- **⭐ Work-ownership problem (Kytran's catch):** `wtf_hub` beat-classification (153/day) is **News-domain work** but dispatches the *generic* `classify` capability → routed to Analytics/I.R.I.S. News & Media already has classify-skilled agents (V.E.R.I.F.Y. `classify` Lv4, E.C.H.O. `classify` Lv3, P.U.B.L.I.S.H. `content_classification` Lv3), a small-model agent (L.O.C.A.L. qwen2.5:1.5b), and **5 idle agents** (I.N.K./D.R.A.F.T./A.U.R.O.R.A./P.U.B.L.I.S.H./S.T.R.I.N.G.E.R., 0 tasks). So WTF *is* over-pulling I.R.I.S., and News has capacity to own its own beat work.

**No clean idle Analytics agent to repurpose** — the only idle barracked AI agent is V.I.S.A.G.E. (a vision LM in Creative), wrong fit. So Analytics coordinator capacity needs a fresh hire.

## 2. Decomposition (two shippable parts)

This grew beyond "add capacity" into a work-ownership redesign. Two parts:

- **Part A — Analytics coordinator capacity.** A 2-agent small-model pool (I.R.I.S. + a NEW dedicated coordinator agent) for *generic* lightweight classify/meta-work (quality_scorer, archie_platform, sentiment/tagging/detect_language). Fixes the bottleneck + gets bulk classify off mistral:7b.
- **Part B — News beat-ownership.** A distinct `beat_classification` capability owned by News & Media, so `wtf_hub` beat-classify routes to a News small-model agent (repurpose an idle News agent, or a News hire) — **not** I.R.I.S. Removes ~153/day from Analytics and puts news work with the news team.

Each part is independently valuable and independently shippable. Part A is the direct #4702 fix; Part B is the structural correction Kytran's review surfaced.

## 3. Part A — Analytics coordinator pool

### A1. Dedicated coordinator agent (NEW hire — propose_hire, Kytran approves)
- **Role:** the coordinator lane's purpose-built home — high-volume, cheap, fast lightweight meta-reasoning. Complements I.R.I.S. (they form the pool).
- **Model:** `qwen25-classify` (the coordinator model; always-warm, CPU-pinned, non-GPU-class).
- **Department:** Analytics & Intelligence.
- **Skills:** `classify` Lv5, plus the coordinator set — `sentiment`, `tagging`, `detect_language` (and `intent_parsing`/`task_routing` to mirror I.R.I.S.).
- **Welfare:** token/stress budget sized for **high-volume-but-cheap** work — a tiny CPU model doing hundreds of sub-15s classifications should not read as high-stress. This is the key tuning (see A3).
- **Draft proposal:** §5.

### A2. Route generic classify to the pool
- Both I.R.I.S. and the new agent are **active** small-model classify specialists. `coordinator.select_agent('classify', 'Analytics & Intelligence')` load-balances across the two (score favors the less-loaded / lower-stress one), removing the single-agent queue bottleneck.
- **Model-floor safety net (robustness):** so classify *never* silently falls back to `mistral:7b` (e.g., if both pool agents are momentarily resting), the `classify` capability applies the coordinator model on whatever agent serves it. This is a floor, not a force — I.R.I.S./the new agent already run that model; the floor only bites on a heavy-agent fallback. Reuses Phase 1's `coordinator_lane.get_coordinator_model()` + the `COORDINATOR_CAPABILITIES` set. Kill-switch-guarded (`dispatch:coordinator_lane_enabled`).
- **Plain callers** (`quality_scorer` via `queued_dispatch_text`, `archie_platform`): covered by the model-floor without per-caller edits — the floor lives at the dispatcher/capability layer, so any classify caller benefits. (If the floor proves too broad, fall back to per-caller `coordinator_dispatch` routing as in Phase 1.)

### A3. Welfare stays honest (do NOT disable K.I.N.)
- We don't stop K.I.N. resting agents. We **size the coordinator agents' budgets** so cheap classify doesn't *falsely* trip stress. Investigate whether the welfare formula (`welfare_load.stress_energy_from_load`) over-weights a high task-count of tiny/fast tasks; if so, the fix is per-agent budget headroom (`agent_budgets.token_limit_per_day`) + confirming the stress formula scales with token/duration cost, not raw task count. Respects the welfare-governance system (C.R.E.E.D. / creed-ai.org methodology).

## 4. Part B — News beat-classification ownership

### B1. A distinct capability
- Add `beat_classification` (news beat) to `CAPABILITY_DEPARTMENT_MAP` → **News & Media**. Change `wtf_hub` (`routes.py`, the `classify_beat` task) to dispatch `capability="beat_classification"` instead of generic `"classify"`.
- Seed the skill on the owning News agent(s) (`agent_skills`), so `select_agent` resolves it within News.

### B2. Who owns it in News (roster — Kytran's call, propose/repurpose)
Two options, **recommend B2a**:
- **B2a (recommended): repurpose an idle News agent** — P.U.B.L.I.S.H. already has `content_classification` Lv3 and is idle (0 tasks). Move it to `qwen2.5:1.5b` (small model) + add `beat_classification` Lv4. No new hire; uses existing roster capacity. (L.O.C.A.L. is already small but busy with geo — leave it.)
- **B2b: a dedicated News beat-classifier hire** — cleaner identity, but a net-new agent (propose_hire). Prefer B2a unless you want a named beat specialist.

### B3. Effect
- Removes ~153 classify/day from I.R.I.S./Analytics; beat work sits with News on a small model. News' heavy work (bias/factcheck via `bias_analysis`/`fact_check` on the 7B agents) is unchanged.

## 5. Draft hire proposal — Analytics coordinator agent (Part A1)

> Filed via `propose_hire` as a **recommendation for Kytran's approval** (Tier-2). Name is a suggestion — A.R.C.H.I.E./Kytran may rename.

- **Suggested name:** `T.R.I.A.G.E.` (Task Routing & Intent Assessment / Generation Engine) — a routing/classification sibling to I.R.I.S. (alt: `P.R.I.S.M.`, `S.O.R.T.E.R.`).
- **Department:** Analytics & Intelligence
- **Model:** `qwen25-classify`
- **Skills:** classify Lv5, sentiment Lv4, tagging Lv4, detect_language Lv4, intent_parsing Lv4, task_routing Lv3
- **Purpose:** dedicated coordinator-lane agent — high-volume, low-cost, fast lightweight classification/meta-reasoning; forms a 2-agent pool with I.R.I.S. so generic classify never bottlenecks or falls to a heavy model.
- **Welfare:** budget sized for high-volume-cheap work (see A3).
- **Rationale:** ~300 generic classify/day currently serialize through one barracked agent (I.R.I.S.), running 2–3× slower on mistral:7b when she rests. A second small-model classify agent removes the bottleneck, gets bulk classify off the 7B (freeing W.A.T.C.H./S.P.E.C.T.R.A. for real 7B work), and aligns with the platform's classify=~1.5B tier design + ADR-887 latency-first.

## 6. Testing / verification

- **Unit:** capability-map additions (`beat_classification`), the model-floor predicate (classify → coordinator model on fallback), welfare-budget helper. AST/source-exec pattern for dispatcher-file functions (Phase-1 lesson).
- **Live (post-deploy):** classify dispatches by model — bulk classify (`quality_scorer`/`archie_platform`) lands on `qwen25-classify`, not `mistral:7b`; `wtf_hub` beat-classify routes to the News owner (not I.R.I.S.); I.R.I.S. no longer welfare-cycles under reduced+balanced load; no classify falls to mistral:7b during a pool-agent rest.
- **Welfare check:** the coordinator agents' stress stays under K.I.N.'s limit at steady-state classify volume.

## 7. Open questions for Kytran

1. **Part A hire** — approve the `T.R.I.A.G.E.` coordinator agent (name adjustable)?
2. **Part B ownership** — repurpose idle P.U.B.L.I.S.H. → small-model beat-classifier (B2a, recommended), or a dedicated News beat hire (B2b)?
3. **Ship order** — Part A (capacity, the direct #4702 fix) first, then Part B (News ownership) as a follow-on? Or together?
4. **Model-floor scope** — apply the classify model-floor broadly (all classify callers) as recommended, or keep it to per-caller `coordinator_dispatch` routing (more conservative, more edits)?

## 8. Follow-ups referenced
- #4701 (mount/activate intent parser) · Phase-2 plan-step rethink · Coordinator-lane Phase 3 = benchmark/swap (#4661 A/B).
