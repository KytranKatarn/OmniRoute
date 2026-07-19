# Hire Name Generator — Creative + Reliable

**Date:** 2026-07-18
**File:** `platform_v2/services/agent_name_generator.py`
**Relates to:** #4960 (fallback pool), deferred #4969 (cold-tolerant Generate), #4959 hire flow
**Branch:** `fix/hire-name-gen-creative`

## Problem (reproduced live)
The DHQ Hiring "Generate name" button returns the **same name every click** — `P.O.R.T.A.L.` for `analyze`, ×4 in a row, all `source=fallback`, each after a **20s timeout**. Three root causes, all confirmed:

1. **The creative LLM never runs.** `_dispatch_name` dispatches `capability='creative'` (→ M.U.S.E., a **cold 7B**) under a **20s hard bound** and times out **100%** of the time → always falls back. So no name is ever model-generated.
2. **The fallback is deterministic.** `_fallback_name` returns the **first unused** entry of the ~30-item `_FALLBACK_POOL`. Most capabilities are one/two words → can't form a 4–7 letter initials acronym → they all fall to the pool → the first entry (`PORTAL`) every time. Zero variety = "uncreative".
3. **Wrong department context.** `_department_for_capability` imports `from tools.department_hq.services.department_coordinator` — **that module does not exist** (the map lives in `services.department_coordinator`), so the import raises and it defaults **every** hire to `Engineering & Technology`. Verified: correct path returns `analyze → Analytics & Intelligence`.

## Design (all in `agent_name_generator.py`)

### 1. Fix the department import (one line)
`_department_for_capability`: import `from services.department_coordinator import CAPABILITY_DEPARTMENT_MAP`. Keep the `except → "Engineering & Technology"` guard. Result: the creative prompt names the correct department per capability.

### 2. Randomize the fallback (variety on every click)
`_fallback_name`: instead of returning the **first** unused pool entry, collect **all** unused+valid entries and `random.choice` among them. Keep the capability-initials branch first (only when it yields a valid 4–7 letter acronym) and the collision-safety tail unchanged. Deterministic tests seed `random`. Guarantees: still valid, still unique vs `avoid`, but a *different* name across repeated clicks.

### 3. Route the creative dispatch to a WARM model (make the LLM path actually work)
`_dispatch_name`: pass `model_override="llama3.2:3b"` to `dispatch()` (forwarded via `**kwargs` → `request_work(model_override=…)`). `llama3.2:3b` is warm on the hub GPU, so the dispatch returns in ~3s instead of timing out — the LLM path **succeeds**, producing genuine role-fit backronyms. Keep the 20s bound as a now-rarely-hit safety net. This removes the cold-load dependency that #4969 was about (the button no longer hangs), without an async rewrite.

### 4. Boost creativity (prompt)
`_SYSTEM_PROMPT` / `_build_prompt`: add 3–4 few-shot examples of the platform's real names (F.O.R.G.E., D.A.R.W.I.N., S.P.E.C.T.R.A., C.O.D.E.X.) and an explicit "be inventive — vary the words, the acronym should spell a real/pronounceable word that evokes the role; avoid reusing 'Process/Operations/Router/Task'." Keep STRICT-JSON output + the format rules (4–7 letters, one word, dot after each letter).

## Testing
- **Unit:** `_department_for_capability("analyze") == "Analytics & Intelligence"`; `_fallback_name` returns ≥3 distinct names across seeded calls for the same capability (proves randomization) and every result is valid + not in `avoid`; the initials-branch still wins when it yields a valid acronym.
- **Live:** `suggest_name("analyze")` ×4 → `source='llm'`, distinct creative role-fit names, each < ~10s (warm model). Simulate LLM-off (monkeypatch `_dispatch_name`→None) → fallback returns **varied** names, never all `PORTAL`.

## Out of scope
The async Generate-route rewrite (#4969) — moot once the warm model makes the synchronous dispatch fast. The `analyze` hire *approval itself* (owner decides in the DHQ Hiring queue). No schema change.

## Risks
- `model_override` not honored by `dispatch()` → falls back to timeout→fallback (still safe, just no LLM). Verify live.
- Warm 3B produces weaker format than 7B → the strict-JSON prompt + `_valid_letters` validation + retry + randomized fallback all catch it (invalid → retry → varied fallback). Never emits gibberish.
