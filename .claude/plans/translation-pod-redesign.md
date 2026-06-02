# Translation Pod Redesign — Plan (NOTHING TOUCHED YET)

**Goal:** Give the Documentation & Knowledge translation team the *right LLM per language*, consolidate `translate` work onto that pod (off Creative/Legal/internal/cloud), and route by language — all through the DHQ dispatcher so K.I.N. welfare / C.R.E.E.D. governance / cost + job tracking apply.

**Owner principle (confirmed):** dedicated agents per LLM / per-language specialists (Option 3). Re-equip existing department members rather than hire.

---

## 1. Language coverage — all 8 in scope

Scope = `en` (source) + 7 targets: `fr, es, de, pt, zh, ar, he`.

| Lang | Owner agent | Model | Bake-off status |
|------|-------------|-------|-----------------|
| en | (source) | — | n/a |
| fr | R.O.S.E.T.T.A. | mistral:7b | ✅ **verified** — best of all models |
| zh | R.O.S.E.T.T.A. | mistral:7b | ✅ **verified** — clean (欢迎回来 / 会话已过期…) |
| es | R.O.S.E.T.T.A. | mistral:7b | ⚠️ **not individually verified on mistral** (high-confidence — same Romance family as fr) |
| de | R.O.S.E.T.T.A. | mistral:7b | ⚠️ **not individually verified on mistral** (high-confidence — high-resource Germanic) |
| pt | R.O.S.E.T.T.A. | mistral:7b | ⚠️ **not individually verified on mistral** (high-confidence — Romance) |
| ar | **Amina** | gemma3:12b | ✅ **verified** — 4/4 clean; mistral failed (English leaks) |
| he | **Amina** | gemma3:12b | ✅ **verified** — natural; mistral garbled all |

**Answer: yes, all 8 are covered by design.** fr/zh/ar/he are bake-off-verified. **es/de/pt are covered by mistral but NOT individually bake-off-tested** — a 5-minute mistral es/de/pt check is step 0 below so we never claim untested coverage.

Models needed: just **two** — `mistral:7b` (en/fr/es/de/pt/zh) + `gemma3:12b` (ar/he). Both already on disk. No new model pull. **No `propose_hire`** — both agents already exist.

---

## 2. The team (all existing Documentation & Knowledge members)

| Agent | Type | New model | Role |
|-------|------|-----------|------|
| R.O.S.E.T.T.A. (134) | ai | mistral:7b (unchanged) | European + Chinese: en/fr/es/de/pt/zh |
| **Amina (341)** | internal | **gemma3:12b** (currently `none`) | **RTL specialist: ar/he** |
| Soleil (358) | internal | mistral:7b (unchanged) | support / fr / language work |
| C.O.D.E.X. (146) | ai | mistral:7b | reduce translate load (winding down) |

Amina is idle today (model `none`, no skills) — equipping her = re-using a department member, not a hire.

---

## 3. Changes (in order, each verified before the next)

### Step 0 — verify es/de/pt on mistral (diagnostic, direct Ollama)
Quick bake to confirm mistral handles es/de/pt cleanly. If any fails → that language joins gemma3/Amina. (No code; just data.)

### Step 1 — equip Amina (agent_service, no direct SQL)
- Set Amina's model → `gemma3:12b` via `agent_service.update_agent`.
- Add skills: `translate` (or `Arabic Translation` / `Hebrew Translation`) at L4–5 via the skills API.
- Set shift_state active. Verify she appears dispatchable for ar/he.

### Step 2 — realign R.O.S.E.T.T.A.'s skills to real coverage
- **Remove** her `Arabic Translation` skill (mistral can't back it — that's the mismatch you spotted).
- Keep French/translate/transliteration; she stays mistral.
- (Optional) add explicit `Chinese Translation` to reflect verified zh coverage.

### Step 3 — route `translate` by language to the right specialist
- In the translation generator(s) (`generator.py _generate_translation`, `semantic_scanner.back_translate_to_en`, gap_batcher), select `prefer_agent` by language: `ar/he → Amina`, else `R.O.S.E.T.T.A.`; and `model_override` accordingly (`gemma3:12b` for ar/he, `mistral:7b` otherwise).
- **gemma3 raw-output handling**: gemma3 doesn't emit the strict JSON the pipeline expects → for ar/he use raw text mode + lenient parse (take the model's output directly); set a sensible default confidence; the back-translation QA pass remains the backstop.
- Make the language→agent/model map **config-driven** (`platform_settings`) so it's tunable without a deploy.

### Step 4 — stop the scatter (investigate + fix)
- Trace **why M.U.S.E. (Creative) is the #1 translator (~10,700 jobs)** and E.T.H.O.S. (Legal) / internal agents get translate — via `task_execution_log.module_source`.
- Fix routing so `translate` resolves to the Documentation pod, not Creative/Legal/internal.
- Decide on `minimax-m2.5:cloud` (8,282 jobs, $0 logged): confirm free vs untracked-paid; if it's bypassing the design, gate it off for translate.

---

## 4. Everything stays in orchestration
- All production translation routes through `dispatch`/`dispatch_json` → DHQ → `task_execution_log` (agent, model, cost, module, job), K.I.N. welfare, C.R.E.E.D. governance. (The recent `ollama run` bake-offs were **diagnostic only**.)
- Agent mutations via `agent_service` (no direct SQL on agent tables).

## 5. Verification (per step, live, through the dispatcher)
- After Step 1: `dispatch(capability='translate', prefer_agent='Amina', ...)` an Arabic string → confirm `model_used=gemma3:12b`, agent=Amina, logged.
- After Step 3: run one gap per language end-to-end through the resolver; confirm each lands on the right agent/model and the translation is correct.
- Confirm K.I.N. welfare digest sees both translators.

## 6. Safety / rollback
- Config-driven map → revert by flipping `platform_settings`.
- Skill/model changes are reversible via `agent_service`.
- No new model pulls, no hires, no infra/Ollama changes.

## 7. Open items to confirm with owner before coding
- OK to **remove R.O.S.E.T.T.A.'s Arabic skill** (it's unbacked)?
- OK to **equip Amina** as the RTL translator (vs a brand-new named hire)?
- How aggressive on Step 4 (stopping M.U.S.E./cloud) — fix now or separate PR?

---
*Status: PLAN ONLY. No agent, code, model, or DB change made. Awaiting approval.*
