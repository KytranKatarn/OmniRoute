# Cloud Dispatch Governance & Hybrid Acceleration — Plan

**Vision (owner, 2026-06-01):** Leverage BOTH local + cloud. **Offload the slow/contended local work to fast cloud to accelerate it — unless the cloud toggle is OFF.** Track every cloud dispatch, make K.I.N. + A.R.C.H.I.E. budget-aware so we never exceed free limits, surface it in A.R.M.A.D.A. + C.R.E.E.D., and gate it with a Cluster-tab on/off toggle (mirrors the AGENT MOBILITY PROFILE pattern already shipped in PR #1371).

This benefits ALL future cloud delegation, not just translation.

---

## Foundation status (verified 2026-06-01)
- ✅ `cloud_model_usage` tracks cloud (1,047/7d) ≈ `task_execution_log` cloud (1,035/7d) — minor 12-row drift to reconcile.
- ✅ Per-provider weekly count vs `contractor_providers.rate_limits.free.weekly_limit` is computable (minimax 1,046/7,000 = 15%).
- ⚠️ `escalation_mode='local_only'` only blocks AUTO-escalation; explicit `model_override=…:cloud` bypasses it (1,046 minimax jobs ran despite it).
- ⚠️ `model_disabled:<model>` per-model flags exist (e.g. `model_disabled:minimax-m2.5:cloud=false`).
- 🔴 NO weekly-budget enforcement anywhere in code.
- Free limits (contractor_providers): minimax 7k/wk, groq 14.4k/wk, cerebras 8.4k/wk, cohere 1k/wk, gemini 1.5k/wk, qwen3 7k/wk. Combined ~30k+/wk.

---

## The hybrid acceleration model
```
work → DHQ dispatcher → is it slow/contended locally AND cloud toggle ON AND under budget?
        YES → route to a cloud provider (fast, tracked, budget-decremented)
        NO  → local (mistral/gemma3/etc.)
   cloud toggle OFF → always local (current escalation_mode=local_only behaviour)
```

## Components (the owner's 5 asks)

### A. Harden cloud tracking (foundation)
- Reconcile `cloud_model_usage` ↔ `task_execution_log` (the 12-row drift) — single source of truth per cloud dispatch.
- Ensure EVERY cloud dispatch writes: provider, model, tokens, agent, capability, module, timestamp.
- A `cloud_budget_status()` helper: per-provider rolling 7-day count + remaining vs free limit.

### B. Budget awareness + enforcement (K.I.N. + A.R.C.H.I.E.)
- A pre-dispatch budget guard: before a cloud dispatch, check the provider's rolling weekly count vs free limit. If over (or within a safety margin) → refuse cloud, fall back to local (or next provider with headroom).
- Provider rotation: spread load across providers with remaining budget (minimax→groq→cerebras…).
- K.I.N. surfaces cloud-budget status in her welfare/ops view; A.R.C.H.I.E. is aware (briefing) so delegation respects it.
- Telegram/alert at e.g. 80% of a weekly limit.

### C. A.R.M.A.D.A. (DHQ Cluster Activity) visibility
- Show cloud as a routing tier/"node" in Cluster Activity (cloud dispatches have `node_used_id=NULL` today → attribute to a synthetic "Cloud" lane).
- Per-provider usage-vs-limit meters in the Cluster/Contractors view.
- Contractor cards show on/off + remaining budget when cloud dispatch is active.

### D. C.R.E.E.D. governance
- Cloud dispatch = a governed action: log to governance_audit_log (cost/limit awareness, data-leaves-premises consideration).
- C.R.E.E.D. surface shows cloud usage posture.

### E. Cluster-tab CLOUD DISPATCH toggle (mirrors AGENT MOBILITY PROFILE)
- New `system_config` flag `cloud_dispatch_enabled` (default per owner).
- Cluster Activity toggle button next to AGENT MOBILITY / HARDWARE REST.
- ON → hybrid acceleration (offload slow→cloud within budget). OFF → local only (true `local_only`).
- Node details show contractors as on/off depending on whether cloud dispatch is active.
- Optionally a profile (like AUTO/NEWS/PLATFORM): e.g. cloud "accelerate-slow-only" vs "cloud-first" vs "off".

---

## Sequencing (proposed)
1. **A — tracking + `cloud_budget_status()`** (foundation; low risk; read-only).
2. **B — budget guard in the dispatch path** (the safety net — prevents over-limit; the most important).
3. **E — Cluster-tab cloud toggle** (reuses the mobility-profile infra; user control).
4. **C — A.R.M.A.D.A. cloud lane + meters** (observability).
5. **D — C.R.E.E.D. governance hooks** (compliance).
6. **Then** wire groq/cohere/cerebras text adapters (task #3658) so the hybrid has real cloud headroom; route translation accordingly.

## Ties to in-flight work
- Translation pod (Amina/gemma3 + per-language config map, uncommitted branch `feat/translate-language-pod`): once the cloud governor + budget guard exist, point `ar/he → cloud` *safely within budget* (config map already supports it).
- Task #3658 (wire groq/cohere/cerebras text) feeds component B's provider rotation.

---
*Status: PLAN ONLY. Foundation verified, nothing built. Awaiting owner approval + sequencing call.*
