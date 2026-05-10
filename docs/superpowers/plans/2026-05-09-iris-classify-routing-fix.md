# I.R.I.S. Classify Routing Fix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix S.P.E.C.T.R.A. stealing all `classify` dispatches from I.R.I.S., the purpose-built agent for that capability, by (A) pinning auto_tagger + emotional_intelligence callers to I.R.I.S. and (B) adding capability-name model affinity scoring so any future caller naturally routes there too.

**Architecture:** Two independent fixes. Fix A is surgical — pins the two legacy callers that hardcode `timeout=10` (correct for I.R.I.S./qwen25-classify, wrong for S.P.E.C.T.R.A./mistral:7b). Fix B is structural — adds a +1.0 scoring bonus in `score_agent()` when an agent's model name contains the capability string, making I.R.I.S. win classify dispatches regardless of caller.

**Tech Stack:** Python 3.12, Flask, PostgreSQL, Ollama (qwen25-classify CPU model), APScheduler, pytest

---

## Context (read before touching anything)

- **I.R.I.S.** (agent id=8, model=`qwen25-classify`, Analytics & Intelligence, active, Lv5 classify) — purpose-built for classify. Fast CPU model, <2s responses.
- **S.P.E.C.T.R.A.** (agent id=137, model=`mistral:7b`, department director, is_department_ai=true) — wins all classify dispatches due to +0.3 director bonus. Takes 4–40s.
- `auto_tagger.py` and `emotional_intelligence.py` both call `dispatcher.request_work("classify", ..., timeout=10)`. 10s was correct for I.R.I.S.; wrong for mistral:7b → 23.5% failure rate.
- Both files import from `ai_bridge/bridge_dispatcher` (deprecated shim) — this is in the Task #2536 migration scope. Do NOT migrate shim imports in this PR; just add `prefer_agent`.
- The coordinator's `score_agent()` already has a tier-based model affinity check (lines 506–520) that fires when `recommended_tier` matches. This plan adds a direct capability-name check that fires unconditionally.

## Files Modified

| File | Change |
|------|--------|
| `ai_bridge/auto_tagger.py` | Add `prefer_agent="I.R.I.S."` to `request_work()` call (~line 336) |
| `ai_bridge/emotional_intelligence.py` | Add `prefer_agent="I.R.I.S."` to `request_work()` call (~line 173) |
| `platform_v2/services/department_coordinator.py` | Add capability-name model affinity bonus in `score_agent()` (~line 521) |
| `tests/test_dispatch_scoring.py` | Add test: I.R.I.S. beats S.P.E.C.T.R.A. for classify with affinity bonus |

---

## Task 1: Fix B — capability-name model affinity in score_agent()

**Files:**
- Modify: `platform_v2/services/department_coordinator.py:506-522`
- Test: `tests/test_dispatch_scoring.py`

### Step 1.1: Write the failing test

Add to `tests/test_dispatch_scoring.py`:

```python
def test_iris_beats_spectra_for_classify_via_model_affinity():
    """I.R.I.S. (qwen25-classify) should outscore S.P.E.C.T.R.A. (mistral:7b)
    for classify capability due to model-name affinity bonus."""
    from services.department_coordinator import DepartmentCoordinator
    coord = DepartmentCoordinator.__new__(DepartmentCoordinator)
    coord._welfare_cache = {}
    coord._cache_ts = float("inf")
    coord._model_service = None

    iris_info = {
        "id": 8,
        "status": "active",
        "shift_state": "active",
        "model": "qwen25-classify",
        "department": "Analytics & Intelligence",
        "is_department_ai": False,
        "skills": {"classify": 5},
        "competency_scores": {},
    }
    spectra_info = {
        "id": 137,
        "status": "active",
        "shift_state": "active",
        "model": "mistral:7b",
        "department": "Analytics & Intelligence",
        "is_department_ai": True,
        "skills": {"classify": 5},
        "competency_scores": {},
    }

    iris_score, _ = coord.score_agent("I.R.I.S.", iris_info, "classify", "Analytics & Intelligence")
    spectra_score, _ = coord.score_agent("S.P.E.C.T.R.A.", spectra_info, "classify", "Analytics & Intelligence")

    assert iris_score > spectra_score, (
        f"I.R.I.S. ({iris_score:.2f}) should beat S.P.E.C.T.R.A. ({spectra_score:.2f}) "
        f"for classify — model affinity bonus missing"
    )
```

- [ ] **Step 1.2: Run to confirm it fails**

```bash
docker exec archie_platform python3 -m pytest tests/test_dispatch_scoring.py::test_iris_beats_spectra_for_classify_via_model_affinity -v 2>&1 | tail -20
```

Expected: `FAILED — AssertionError: I.R.I.S. (X.XX) should beat S.P.E.C.T.R.A. (X.XX)`

- [ ] **Step 1.3: Add the capability-name affinity block to score_agent()**

In `platform_v2/services/department_coordinator.py`, after the `recommended_tier` block (after line 520, before `return (max(score, 0.01), None)`), insert:

```python
        # Capability-name model affinity: +1.0 when the agent's model name
        # contains the capability string. Ensures purpose-built models (e.g.,
        # qwen25-classify for "classify") beat general-purpose directors.
        # Guard: capability must be ≥4 chars to avoid spurious matches.
        if capability and len(capability) >= 4:
            _cap_slug = capability.lower().replace("-", "_")
            _model_slug = agent_info.get("model", "").lower().replace("-", "_")
            if _cap_slug in _model_slug:
                score += 1.0
```

The full tail of `score_agent()` should look like:

```python
        if recommended_tier:
            agent_model = agent_info.get("model", "")
            try:
                from tools.department_hq.services.smart_router import get_router

                router = get_router()
                configs = router._get_model_configs()
                tier_config = configs.get(recommended_tier)
                if tier_config and (
                    agent_model == tier_config.model_name
                    or agent_model.startswith(tier_config.model_name.split(":")[0])
                ):
                    score += 1.0
            except Exception:
                pass

        # Capability-name model affinity: +1.0 when the agent's model name
        # contains the capability string. Ensures purpose-built models (e.g.,
        # qwen25-classify for "classify") beat general-purpose directors.
        # Guard: capability must be ≥4 chars to avoid spurious matches.
        if capability and len(capability) >= 4:
            _cap_slug = capability.lower().replace("-", "_")
            _model_slug = agent_info.get("model", "").lower().replace("-", "_")
            if _cap_slug in _model_slug:
                score += 1.0

        return (max(score, 0.01), None)
```

- [ ] **Step 1.4: Run test to confirm it passes**

```bash
docker exec archie_platform python3 -m pytest tests/test_dispatch_scoring.py::test_iris_beats_spectra_for_classify_via_model_affinity -v 2>&1 | tail -10
```

Expected: `PASSED`

- [ ] **Step 1.5: Run full scoring test suite to confirm no regressions**

```bash
docker exec archie_platform python3 -m pytest tests/test_dispatch_scoring.py -v 2>&1 | tail -20
```

Expected: All existing tests still PASS.

---

## Task 2: Fix A — pin auto_tagger and emotional_intelligence to I.R.I.S.

**Files:**
- Modify: `ai_bridge/auto_tagger.py:335-337`
- Modify: `ai_bridge/emotional_intelligence.py:172-174`

No new tests needed — Fix B's test covers the routing logic. These are one-line caller changes.

- [ ] **Step 2.1: Update auto_tagger.py**

In `ai_bridge/auto_tagger.py`, find the `dispatcher.request_work(...)` call (~line 335):

```python
        result = dispatcher.request_work(
            "classify", prompt, "auto_tagger", json_mode=True, timeout=10
        )
```

Change to:

```python
        result = dispatcher.request_work(
            "classify", prompt, "auto_tagger", json_mode=True, timeout=10,
            prefer_agent="I.R.I.S.",
        )
```

- [ ] **Step 2.2: Update emotional_intelligence.py**

In `ai_bridge/emotional_intelligence.py`, find the `dispatcher.request_work(...)` call (~line 172):

```python
        dispatch_result = dispatcher.request_work(
            "classify", prompt, "emotional_intelligence", json_mode=True, timeout=10
        )
```

Change to:

```python
        dispatch_result = dispatcher.request_work(
            "classify", prompt, "emotional_intelligence", json_mode=True, timeout=10,
            prefer_agent="I.R.I.S.",
        )
```

- [ ] **Step 2.3: Verify syntax**

```bash
docker exec archie_platform python3 -c "
import sys; sys.path.insert(0, '/app/ai_bridge')
import auto_tagger
import emotional_intelligence
print('both import OK')
"
```

Expected: `both import OK`

---

## Task 3: Branch, deploy, verify

- [ ] **Step 3.1: Create branch**

```bash
git checkout -b fix/iris-classify-routing
```

- [ ] **Step 3.2: Stage and commit**

```bash
git add platform_v2/services/department_coordinator.py \
        ai_bridge/auto_tagger.py \
        ai_bridge/emotional_intelligence.py \
        tests/test_dispatch_scoring.py
git commit -m "$(cat <<'EOF'
fix(dispatch): route classify to I.R.I.S. — model affinity + prefer_agent

S.P.E.C.T.R.A. (mistral:7b, director +0.3) was winning all classify
dispatches over I.R.I.S. (qwen25-classify, purpose-built). auto_tagger
and emotional_intelligence had timeout=10 designed for qwen25-classify
(<500ms) but were hitting mistral:7b (4-40s) → 23.5% timeout rate.

Fix A: pin auto_tagger + emotional_intelligence callers to I.R.I.S.
Fix B: +1.0 model-name affinity bonus in score_agent() when capability
       string appears in agent model name (e.g. "classify" in
       "qwen25-classify"). Any future caller also benefits.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)"
```

- [ ] **Step 3.3: Deploy**

```bash
docker compose restart archie_platform
```

Wait 15 seconds, then:

```bash
docker logs archie_platform --since 30s 2>&1 | grep -iE 'error|traceback|import' | head -20
```

Expected: no import errors, no tracebacks.

- [ ] **Step 3.4: Verify I.R.I.S. is now getting classify calls**

Wait ~5 minutes for scheduled classify dispatches, then:

```bash
docker exec archie_database psql -U archie -d archie -c "
SELECT agent_name, capability, success, duration_ms, created_at
FROM task_execution_log
WHERE capability='classify'
ORDER BY created_at DESC LIMIT 10;
"
```

Expected: `agent_name = I.R.I.S.` for recent entries, duration_ms < 3000.

- [ ] **Step 3.5: Push and create PR**

```bash
git push -u origin fix/iris-classify-routing
gh pr create \
  --title "fix(dispatch): route classify to I.R.I.S. — model affinity + prefer_agent" \
  --body "$(cat <<'EOF'
## Summary
- **Root cause**: S.P.E.C.T.R.A. (mistral:7b, director +0.3 bonus) was winning all \`classify\` dispatches over I.R.I.S. (qwen25-classify, purpose-built). \`auto_tagger\` and \`emotional_intelligence\` had \`timeout=10\` written for qwen25-classify (<500ms), but were hitting mistral:7b (4–40s) → 23.5% failure rate in misroute audit.
- **Fix A**: Added \`prefer_agent="I.R.I.S."\` to both legacy callers (\`auto_tagger.py\`, \`emotional_intelligence.py\`). Timeout=10 is now correct again.
- **Fix B**: Added capability-name model affinity bonus (+1.0) to \`score_agent()\` in \`department_coordinator.py\`. When agent's model name contains the capability string (e.g., "classify" ⊂ "qwen25-classify"), it wins over a general-purpose director. Future classify callers benefit automatically.

## Test plan
- [ ] \`test_iris_beats_spectra_for_classify_via_model_affinity\` passes
- [ ] Full \`test_dispatch_scoring.py\` suite passes with no regressions
- [ ] After deploy: \`task_execution_log\` shows \`agent_name=I.R.I.S.\` for classify, duration_ms < 3000
- [ ] Misroute audit S.P.E.C.T.R.A./classify failure rate drops to 0% within 24h window

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

---

## Self-Review

**Spec coverage:**
- ✅ Fix A: auto_tagger + emotional_intelligence pinned to I.R.I.S. via prefer_agent
- ✅ Fix B: capability-name affinity added to score_agent()
- ✅ Test covers Fix B scoring logic
- ✅ Deploy + verification steps included

**Placeholder scan:** None found.

**Type consistency:** `score_agent()` returns `tuple` — new block doesn't change signature. `request_work()` `prefer_agent: Optional[str]` — "I.R.I.S." matches type. Consistent throughout.
