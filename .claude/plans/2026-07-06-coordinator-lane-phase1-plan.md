# Coordinator Lane — Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Consolidate dispatch's lightweight meta-reasoning behind one config-driven, always-warm, correctly-classified-as-small coordinator model, and remove the heavy-model fallbacks in that path.

**Architecture:** Approach A — a thin `platform_v2/services/coordinator_lane.py` owns the coordinator model name (config key `dispatch:coordinator_model`, default `qwen25-classify`) and a `coordinator_dispatch()` wrapper that forces that model + pins I.R.I.S. The lightweight consumers (intent parse, classify, sentiment, tagging, detect_language) call through it. Isolation is achieved by fixing a latent bug — the coordinator model is currently mis-tagged as GPU-class in `_model_is_gpu_class` and `model_sizes`, so it gets shed by hub admission control and mis-escalated to GPU nodes during saturation. **We do NOT edit the hardened `_execute_llm` admission guard** (spec §14 risk resolved); we make the model correctly small instead.

**Tech Stack:** Python 3.12, Flask, psycopg2, Postgres `platform_settings`, Ollama via DHQ dispatcher, pytest.

## Global Constraints

- **Fail-open, never fail-heavy.** A coordinator failure/timeout/bad-JSON must NEVER block dispatch and NEVER fall back to a heavy (7B+) model. Degraded path → the existing regex/`conversation`-free default.
- **No direct Ollama calls** (ADR-013) — everything routes through `department_dispatcher.dispatch()` / `request_work()`.
- **Kill switch:** `platform_settings['dispatch:coordinator_lane_enabled']` (default `true`). When `false`, `coordinator_dispatch` behaves exactly as today (plain capability routing, no `model_override`).
- **Config reads:** no getter helper exists in this codebase — use a parameterized `SELECT value FROM platform_settings WHERE key = %s` with an in-code default (mirror `welfare_governance_service.hub_lane_over_cap` lines 241–248). Wrap coordinator reads in a short TTL cache.
- **Coordinator model MUST be non-GPU-class (small).** Enforced by Task 2 (marker + `model_sizes` entry) and asserted in tests. Benchmark candidates (Phase 3) are constrained to small models for this reason.
- **Tests:** pure modules (`coordinator_lane`, `model_sizes`) run via `python -m pytest platform_v2/tests/<file> -v`. Functions living in `department_dispatcher.py` (which imports `db`) must be tested by **AST source-extraction** — copy the pattern in `platform_v2/tests/test_dispatch_scoring.py::TestModelIsGpuClass` (`_extract`/`_source` at lines ~307–358). Do NOT `import department_dispatcher` in a bare test — it fails `ModuleNotFoundError: No module named 'db'` (KB #278809/cont-127).
- **Black** reformats on pre-commit — if a commit fails on formatting, re-stage and re-commit.
- **Branch:** `feat/coordinator-lane` (already created). Each task commits. Phase 1 ships as ONE PR → F.O.R.G.E. review → `archie-deploy` restart + live-verify before Phase 2.
- **DHQ import (canonical):** `from tools.department_hq.services.department_dispatcher import dispatch, get_dispatcher`. Lazy-import it INSIDE functions in `coordinator_lane.py` to avoid an import cycle (the codebase does this routinely, e.g. `_execute_llm` lazily imports `hub_lane_over_cap`).

---

### Task 1: `coordinator_lane` service — model resolution + config seed

**Files:**
- Create: `platform_v2/services/coordinator_lane.py`
- Create: `platform_v2/tests/test_coordinator_lane.py`
- Create: `database/migrations/<NNN>_coordinator_lane_settings.sql` (NNN = next number)

**Interfaces:**
- Produces: `get_coordinator_model() -> str` (default `"qwen25-classify"`); `coordinator_lane_enabled() -> bool` (default `True`); module constant `DEFAULT_COORDINATOR_MODEL = "qwen25-classify"`; `_reset_cache()` (test hook).

- [ ] **Step 1: Write the failing test**

```python
# platform_v2/tests/test_coordinator_lane.py
import importlib

import services.coordinator_lane as cl


def setup_function(_):
    cl._reset_cache()


def test_default_when_key_absent(monkeypatch):
    # No DB row → the hard default
    monkeypatch.setattr(cl, "_read_setting", lambda key, default: default)
    assert cl.get_coordinator_model() == "qwen25-classify"


def test_returns_configured_value(monkeypatch):
    monkeypatch.setattr(
        cl, "_read_setting",
        lambda key, default: "phi4-mini" if key == "dispatch:coordinator_model" else default,
    )
    cl._reset_cache()
    assert cl.get_coordinator_model() == "phi4-mini"


def test_enabled_default_true(monkeypatch):
    monkeypatch.setattr(cl, "_read_setting", lambda key, default: default)
    cl._reset_cache()
    assert cl.coordinator_lane_enabled() is True


def test_enabled_false_when_set(monkeypatch):
    monkeypatch.setattr(
        cl, "_read_setting",
        lambda key, default: "false" if key == "dispatch:coordinator_lane_enabled" else default,
    )
    cl._reset_cache()
    assert cl.coordinator_lane_enabled() is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest platform_v2/tests/test_coordinator_lane.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'services.coordinator_lane'`

- [ ] **Step 3: Write minimal implementation**

```python
# platform_v2/services/coordinator_lane.py
"""Coordinator lane — the single owner of dispatch's meta-reasoning model.

One designated, always-warm, SMALL local model performs the linguistic work of
dispatch (parse intent, classify capability, and — Phase 2 — decompose). Routing
DECISIONS stay in code. The model is config-swappable via platform_settings so a
benchmark (Phase 3) can promote a winner with no deploy.

Isolation invariant: the coordinator model MUST be non-GPU-class (small) so the hub
admission gate (department_dispatcher._execute_llm) never sheds it — see model_sizes
+ _SMALL_MODEL_MARKERS.
"""
import time
import logging

logger = logging.getLogger(__name__)

DEFAULT_COORDINATOR_MODEL = "qwen25-classify"
_MODEL_KEY = "dispatch:coordinator_model"
_ENABLED_KEY = "dispatch:coordinator_lane_enabled"

_CACHE: dict = {}
_CACHE_TTL_S = 60.0


def _reset_cache() -> None:
    """Test hook — clear the TTL cache."""
    _CACHE.clear()


def _read_setting(key: str, default: str) -> str:
    """Read a single platform_settings value with an in-code default. Fail-open."""
    try:
        from database import get_db_cursor

        with get_db_cursor() as (conn, cur):
            cur.execute("SELECT value FROM platform_settings WHERE key = %s", (key,))
            row = cur.fetchone()
        if row and row.get("value") not in (None, ""):
            return str(row["value"])
        return default
    except Exception:
        logger.warning("[coordinator_lane] setting read failed for %s; using default", key, exc_info=True)
        return default


def _cached(key: str, default: str) -> str:
    now = time.monotonic()
    hit = _CACHE.get(key)
    if hit and (now - hit[1]) < _CACHE_TTL_S:
        return hit[0]
    val = _read_setting(key, default)
    _CACHE[key] = (val, now)
    return val


def get_coordinator_model() -> str:
    """The designated coordinator model name (config-driven, TTL-cached)."""
    return _cached(_MODEL_KEY, DEFAULT_COORDINATOR_MODEL)


def coordinator_lane_enabled() -> bool:
    """Kill switch — False reverts callers to plain capability routing."""
    return _cached(_ENABLED_KEY, "true").strip().lower() not in ("false", "0", "no", "off")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest platform_v2/tests/test_coordinator_lane.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Create the idempotent settings-seed migration**

Determine the number: `ls database/migrations/ | sort | tail -3` → use the next integer as `<NNN>`.

```sql
-- database/migrations/<NNN>_coordinator_lane_settings.sql
-- Seed coordinator-lane settings so they are visible/tunable in the Autonomy tab.
-- get_coordinator_model() already defaults to qwen25-classify when absent; this makes it explicit.
INSERT INTO platform_settings (key, value)
VALUES
  ('dispatch:coordinator_model', 'qwen25-classify'),
  ('dispatch:coordinator_lane_enabled', 'true'),
  ('dispatch:coordinator_plan_max_steps', '6')
ON CONFLICT (key) DO NOTHING;
```

Apply: `docker exec -i archie_database psql -U archie -d archie < database/migrations/<NNN>_coordinator_lane_settings.sql`
Expected: `INSERT 0 3` (first run) or `INSERT 0 0` (already seeded).

- [ ] **Step 6: Commit**

```bash
git add platform_v2/services/coordinator_lane.py platform_v2/tests/test_coordinator_lane.py database/migrations/*_coordinator_lane_settings.sql
git commit -m "feat(dispatch): coordinator_lane service — config-driven model resolution + kill switch"
```

---

### Task 2: Fix coordinator-model misclassification (isolation linchpin)

**Why:** `_model_is_gpu_class("qwen25-classify")` returns **True** today (marker list `("1.5b","1b","0.5b","3b","embed","nomic","moondream","tiny")` matches none), and `model_sizes.lookup("qwen25-classify")` falls to the GPU-leaning default. So the coordinator model is treated as a heavy 7B → shed by the hub admission gate and mis-escalated to GPU nodes during saturation. Fixing this IS the lane isolation.

**Files:**
- Modify: `platform_v2/tools/department_hq/services/department_dispatcher.py:848` (`_SMALL_MODEL_MARKERS`)
- Modify: `platform_v2/services/model_sizes.py:33` (`_TABLE`)
- Test: `platform_v2/tests/test_dispatch_scoring.py` (extend `TestModelIsGpuClass`)
- Test: `platform_v2/tests/test_model_sizes_coordinator.py` (new)

**Interfaces:**
- Consumes: nothing new.
- Produces: `_model_is_gpu_class("qwen25-classify") == False`; `model_sizes.lookup("qwen25-classify").prefer_gpu == False`.

- [ ] **Step 1: Write the failing tests**

Extend the existing AST-extraction class (append inside `TestModelIsGpuClass` in `platform_v2/tests/test_dispatch_scoring.py`):

```python
    def test_coordinator_and_small_candidates_are_not_gpu_class(self):
        fn = self._extract()  # existing helper that execs _SMALL_MODEL_MARKERS + _model_is_gpu_class
        for m in ("qwen25-classify", "gemma2:2b", "phi4-mini"):
            assert fn(m) is False, f"{m} must be small/non-GPU-class"
```

New pure-module test:

```python
# platform_v2/tests/test_model_sizes_coordinator.py
from services import model_sizes


def test_coordinator_model_is_cpu_small():
    fp = model_sizes.lookup("qwen25-classify")
    assert fp.prefer_gpu is False
    assert fp.vram_gb <= 2.0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest platform_v2/tests/test_dispatch_scoring.py::TestModelIsGpuClass -v platform_v2/tests/test_model_sizes_coordinator.py -v`
Expected: FAIL — `qwen25-classify must be small/non-GPU-class` and `assert True is False` (prefer_gpu default True).

- [ ] **Step 3: Implement — extend the marker tuple**

`department_dispatcher.py:848` — add small markers covering the coordinator model + the Phase-3 candidates:

```python
_SMALL_MODEL_MARKERS = ("1.5b", "1b", "0.5b", "3b", "2b", "classify", "mini", "embed", "nomic", "moondream", "tiny")
```

- [ ] **Step 4: Implement — add the `model_sizes` entry**

In `platform_v2/services/model_sizes.py`, inside `_TABLE`, under the `# Tiny — fit anywhere` group (after the `qwen2.5:0.5b` line ~35):

```python
    "qwen25-classify": ModelFootprint(1.0, 2.0, False),
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest platform_v2/tests/test_dispatch_scoring.py::TestModelIsGpuClass -v platform_v2/tests/test_model_sizes_coordinator.py -v`
Expected: PASS (all)

- [ ] **Step 6: Commit**

```bash
git add platform_v2/tools/department_hq/services/department_dispatcher.py platform_v2/services/model_sizes.py platform_v2/tests/test_dispatch_scoring.py platform_v2/tests/test_model_sizes_coordinator.py
git commit -m "fix(dispatch): classify coordinator model as small — restores lane isolation from hub admission control"
```

---

### Task 3: `coordinator_dispatch()` wrapper

**Files:**
- Modify: `platform_v2/services/coordinator_lane.py`
- Test: `platform_v2/tests/test_coordinator_lane.py`

**Interfaces:**
- Consumes: `get_coordinator_model()`, `coordinator_lane_enabled()` (Task 1).
- Produces: `coordinator_dispatch(capability, prompt, *, module_id="coordinator", json_mode=False, timeout_s=30, **kwargs)` → `DispatchResult`. When the lane is enabled it forces `model_override=get_coordinator_model()` + `prefer_agent="I.R.I.S."`; when disabled it calls plain `dispatch()` (today's behavior).

- [ ] **Step 1: Write the failing test**

```python
# append to platform_v2/tests/test_coordinator_lane.py
class _FakeResult:
    success = True
    response = "{}"


def test_coordinator_dispatch_forces_model_and_agent(monkeypatch):
    cl._reset_cache()
    monkeypatch.setattr(cl, "get_coordinator_model", lambda: "qwen25-classify")
    monkeypatch.setattr(cl, "coordinator_lane_enabled", lambda: True)
    seen = {}

    def fake_dispatch(capability, prompt, **kwargs):
        seen.update(capability=capability, **kwargs)
        return _FakeResult()

    monkeypatch.setattr(cl, "_dispatch", lambda: fake_dispatch)
    cl.coordinator_dispatch("classify", "hi", module_id="intent_parser", json_mode=True)
    assert seen["capability"] == "classify"
    assert seen["model_override"] == "qwen25-classify"
    assert seen["prefer_agent"] == "I.R.I.S."
    assert seen["json_mode"] is True


def test_coordinator_dispatch_disabled_is_plain(monkeypatch):
    cl._reset_cache()
    monkeypatch.setattr(cl, "coordinator_lane_enabled", lambda: False)
    seen = {}

    def fake_dispatch(capability, prompt, **kwargs):
        seen.update(capability=capability, **kwargs)
        return _FakeResult()

    monkeypatch.setattr(cl, "_dispatch", lambda: fake_dispatch)
    cl.coordinator_dispatch("classify", "hi")
    assert "model_override" not in seen  # plain routing when disabled
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest platform_v2/tests/test_coordinator_lane.py -v`
Expected: FAIL — `AttributeError: module ... has no attribute '_dispatch'` / `coordinator_dispatch`.

- [ ] **Step 3: Write minimal implementation (append to `coordinator_lane.py`)**

```python
def _dispatch():
    """Lazy handle to the module-level dispatch() (avoids an import cycle)."""
    from tools.department_hq.services.department_dispatcher import dispatch
    return dispatch


def coordinator_dispatch(capability, prompt, *, module_id="coordinator", json_mode=False, timeout_s=30, **kwargs):
    """Dispatch a lightweight meta-reasoning task through the coordinator lane.

    Enabled  → forces the config-driven coordinator model + pins I.R.I.S.
    Disabled → plain capability routing (today's behavior). Fail-open: any error
    is the caller's to handle via DispatchResult.success (never raises past dispatch()).
    """
    dispatch = _dispatch()
    if coordinator_lane_enabled():
        kwargs.setdefault("model_override", get_coordinator_model())
        kwargs.setdefault("prefer_agent", "I.R.I.S.")
    return dispatch(
        capability,
        prompt,
        module_id=module_id,
        json_mode=json_mode,
        timeout=timeout_s,
        **kwargs,
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest platform_v2/tests/test_coordinator_lane.py -v`
Expected: PASS (6 passed)

- [ ] **Step 5: Commit**

```bash
git add platform_v2/services/coordinator_lane.py platform_v2/tests/test_coordinator_lane.py
git commit -m "feat(dispatch): coordinator_dispatch() wrapper — forces coordinator model + I.R.I.S. pin, kill-switch aware"
```

---

### Task 4: Kill the heavy fallback in the intent parser

**Why:** `archie_engine_staging/intent_parser.py:56-60` sets `self.classification_model` to `get_model_for_capability("classify") or get_model_for_capability("conversation") or "dolphin3-8k:latest"` — the `conversation`/`dolphin3-8k` fallbacks are heavy models in the meta-reasoning path. Route the model to the coordinator lane instead, and send `_llm_classify` through `coordinator_dispatch`.

**Files:**
- Modify: `archie_engine_staging/intent_parser.py:56-60` and the `_llm_classify` dispatch call (~:505-512)
- Test: `platform_v2/tests/test_intent_parser_coordinator.py` (new, AST/attribute-level — do NOT boot the full parser)

**Interfaces:**
- Consumes: `coordinator_lane.get_coordinator_model()`, `coordinator_lane.coordinator_dispatch()`.
- Produces: `IntentParser().classification_model == get_coordinator_model()`; no `dolphin3-8k`/`conversation` fallback remains in the file.

- [ ] **Step 1: Locate the exact import style the file already uses to reach platform services**

Run: `grep -n "^import\|^from\|_dispatcher =" archie_engine_staging/intent_parser.py | head -20`
Use the SAME package-root style for the new `coordinator_lane` import (e.g. `from services.coordinator_lane import ...` if that is how `_dispatcher` is reached; otherwise mirror the working path).

- [ ] **Step 2: Write the failing test**

```python
# platform_v2/tests/test_intent_parser_coordinator.py
import re
from pathlib import Path

SRC = Path("archie_engine_staging/intent_parser.py").read_text()


def test_no_heavy_fallback_remains():
    assert "dolphin3-8k" not in SRC, "heavy dolphin3-8k fallback must be gone"
    # the conversation-model fallback for classification_model must be gone
    assert "get_model_for_capability(\"conversation\")" not in SRC


def test_classification_model_uses_coordinator():
    assert "get_coordinator_model()" in SRC
```

- [ ] **Step 3: Run test to verify it fails**

Run: `python -m pytest platform_v2/tests/test_intent_parser_coordinator.py -v`
Expected: FAIL — `dolphin3-8k` still present.

- [ ] **Step 4: Implement — replace the fallback (lines 56-60)**

Replace:

```python
        # Use BridgeDispatcher for model selection
        _classify_model = _dispatcher.get_model_for_capability("classify") if _dispatcher else ""
        self.classification_model = _classify_model or (
            _dispatcher.get_model_for_capability("conversation") if _dispatcher else "dolphin3-8k:latest"
        )
```

with:

```python
        # Coordinator lane owns the meta-reasoning model (config-driven, always small).
        from services.coordinator_lane import get_coordinator_model
        self.classification_model = get_coordinator_model()
```

- [ ] **Step 5: Implement — route `_llm_classify` through the lane**

In `_llm_classify`, replace the dispatcher call:

```python
            if _dispatcher:
                dr = _dispatcher.request_work(
                    capability="classify",
                    prompt=prompt,
                    module_id="intent_parser",
                    json_mode=True,
                    timeout=30,
                )
                result_text = dr.response.strip() if dr.success else ""
```

with:

```python
            if _dispatcher:
                from services.coordinator_lane import coordinator_dispatch
                dr = coordinator_dispatch(
                    "classify",
                    prompt,
                    module_id="intent_parser",
                    json_mode=True,
                    timeout_s=30,
                )
                result_text = dr.response.strip() if dr.success else ""
```

- [ ] **Step 6: Run test to verify it passes**

Run: `python -m pytest platform_v2/tests/test_intent_parser_coordinator.py -v`
Expected: PASS (2 passed)

- [ ] **Step 7: Commit**

```bash
git add archie_engine_staging/intent_parser.py platform_v2/tests/test_intent_parser_coordinator.py
git commit -m "fix(dispatch): intent parser routes classify through coordinator lane — removes dolphin3-8k/conversation heavy fallback"
```

---

### Task 5: Route the lightweight consumers through the lane

**Why:** sentiment / tagging / detect_language / news-beat each call `request_work("classify"|"detect_language", ...)` directly. Routing them through `coordinator_dispatch` makes the coordinator model config-driven + consistent for all meta-reasoning.

**Files:**
- Modify: `ai_bridge/emotional_intelligence.py:171-179`
- Modify: `ai_bridge/auto_tagger.py:331-339`
- Modify: `ai_bridge/translation_service.py` (the `detect_language` caller ~:150 and `_dispatch` at ~:109)
- Modify: `scripts/wtf_beat_classifier.py:213-219`
- Test: `platform_v2/tests/test_coordinator_consumers.py` (new, source-level)

**Interfaces:**
- Consumes: `coordinator_lane.coordinator_dispatch()`.
- Produces: each consumer's classify/detect_language call goes through `coordinator_dispatch`.

- [ ] **Step 1: Write the failing test**

```python
# platform_v2/tests/test_coordinator_consumers.py
from pathlib import Path

FILES = [
    "ai_bridge/emotional_intelligence.py",
    "ai_bridge/auto_tagger.py",
    "scripts/wtf_beat_classifier.py",
]


def test_consumers_use_coordinator_dispatch():
    for f in FILES:
        src = Path(f).read_text()
        assert "coordinator_dispatch" in src, f"{f} should route classify via coordinator_dispatch"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest platform_v2/tests/test_coordinator_consumers.py -v`
Expected: FAIL — no `coordinator_dispatch` in the files yet.

- [ ] **Step 3: Implement — `emotional_intelligence.py:171-179`**

Replace:

```python
        dispatcher = get_dispatcher()
        dispatch_result = dispatcher.request_work(
            "classify",
            prompt,
            "emotional_intelligence",
            json_mode=True,
            timeout=10,
            prefer_agent="I.R.I.S.",
        )
```

with:

```python
        from services.coordinator_lane import coordinator_dispatch
        dispatch_result = coordinator_dispatch(
            "classify",
            prompt,
            module_id="emotional_intelligence",
            json_mode=True,
            timeout_s=10,
        )
```

- [ ] **Step 4: Implement — `auto_tagger.py:331-339`**

Replace:

```python
        dispatcher = get_dispatcher()
        result = dispatcher.request_work(
            "classify",
            prompt,
            "auto_tagger",
            json_mode=True,
            timeout=10,
            prefer_agent="I.R.I.S.",
        )
```

with:

```python
        from services.coordinator_lane import coordinator_dispatch
        result = coordinator_dispatch(
            "classify",
            prompt,
            module_id="auto_tagger",
            json_mode=True,
            timeout_s=10,
        )
```

- [ ] **Step 5: Implement — `wtf_beat_classifier.py:213-219`**

Replace:

```python
    try:
        result = dispatch(
            capability="classify",
            prompt=prompt,
            module_id="wtf_beat_backfill",
            json_mode=True,
        )
```

with:

```python
    try:
        from services.coordinator_lane import coordinator_dispatch
        result = coordinator_dispatch(
            "classify",
            prompt,
            module_id="wtf_beat_backfill",
            json_mode=True,
        )
```

- [ ] **Step 6: Implement — `translation_service.py` detect_language**

`translation_service.py` funnels through a private `_dispatch(capability, prompt)` helper (~:109) that calls `dispatcher.request_work(capability=capability, ...)`. Narrowest change: in that helper, when `capability == "detect_language"`, route via the lane. At the top of `_dispatch`'s body, before the existing `dispatcher = get_dispatcher()`:

```python
        if capability == "detect_language":
            from services.coordinator_lane import coordinator_dispatch
            return coordinator_dispatch(capability, prompt, module_id="translation_service", json_mode=True, timeout_s=10)
```

(Confirm the return shape `_dispatch` expects — it returns a `DispatchResult`; `coordinator_dispatch` returns the same. If `_dispatch` post-processes `result.response`, keep that by returning `coordinator_dispatch(...)` and letting the caller handle it, or adapt to match the helper's existing return.) Add `translation_service.py` to the `FILES` list in the test and re-run.

- [ ] **Step 7: Run test to verify it passes**

Run: `python -m pytest platform_v2/tests/test_coordinator_consumers.py -v`
Expected: PASS

- [ ] **Step 8: Commit**

```bash
git add ai_bridge/emotional_intelligence.py ai_bridge/auto_tagger.py ai_bridge/translation_service.py scripts/wtf_beat_classifier.py platform_v2/tests/test_coordinator_consumers.py
git commit -m "refactor(dispatch): route sentiment/tagging/detect_language/beat classify through coordinator lane"
```

---

### Task 6: Dynamic warm-keep of the coordinator model

**Why:** `ai_bridge/agent_loop.py:3428-3434` hardcodes `("qwen25-classify", 0)` in the keep-warm registry. If Phase 3 swaps the coordinator model via config, keep-warm must follow. Make the registry include the configured coordinator model.

**Files:**
- Modify: `ai_bridge/agent_loop.py:3431-3434`
- Test: `platform_v2/tests/test_warm_keep_coordinator.py` (new, source-level)

**Interfaces:**
- Consumes: `coordinator_lane.get_coordinator_model()`.
- Produces: the keep-warm registry contains `get_coordinator_model()`.

- [ ] **Step 1: Write the failing test**

```python
# platform_v2/tests/test_warm_keep_coordinator.py
from pathlib import Path

SRC = Path("ai_bridge/agent_loop.py").read_text()


def test_warm_keep_uses_configured_coordinator_model():
    assert "get_coordinator_model()" in SRC, "keep-warm registry must include the configured coordinator model"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest platform_v2/tests/test_warm_keep_coordinator.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement**

Replace the registry block (`agent_loop.py:3431-3434`):

```python
        registry = [
            ("qwen2.5:7b", 0),
            ("mistral:7b", 0),
            ("qwen25-classify", 0),
        ]
```

with:

```python
        from services.coordinator_lane import get_coordinator_model
        registry = [
            ("qwen2.5:7b", 0),
            ("mistral:7b", 0),
            (get_coordinator_model(), 0),
        ]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest platform_v2/tests/test_warm_keep_coordinator.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add ai_bridge/agent_loop.py platform_v2/tests/test_warm_keep_coordinator.py
git commit -m "feat(dispatch): keep-warm follows the configured coordinator model"
```

---

### Task 7: Commit a reproducible Modelfile for `qwen25-classify`

**Why:** the model is registered directly in fleet Ollama with no committed Modelfile — not reproducible. Capture and commit it. (Infra/reproducibility; not unit-testable.)

**Files:**
- Create: `/mnt/llm_drive/ollama/Modelfile.qwen25-classify`

- [ ] **Step 1: Capture the live modelfile off the hub Ollama**

Run (hub): `ollama show qwen25-classify --modelfile > /mnt/llm_drive/ollama/Modelfile.qwen25-classify`
(If `ollama` is not directly available in this shell, capture via the hub Ollama host that already serves it — do NOT invent the FROM/SYSTEM; it must be the live definition.)

- [ ] **Step 2: Verify it re-creates the model identically**

Run: `ollama create qwen25-classify-verify -f /mnt/llm_drive/ollama/Modelfile.qwen25-classify && ollama show qwen25-classify-verify --modelfile | diff - /mnt/llm_drive/ollama/Modelfile.qwen25-classify; ollama rm qwen25-classify-verify`
Expected: no diff.

- [ ] **Step 3: Commit**

```bash
git add -f /mnt/llm_drive/ollama/Modelfile.qwen25-classify 2>/dev/null || cp /mnt/llm_drive/ollama/Modelfile.qwen25-classify ops/modelfiles/Modelfile.qwen25-classify && git add ops/modelfiles/Modelfile.qwen25-classify
git commit -m "chore(ollama): commit reproducible Modelfile for qwen25-classify (coordinator model)"
```

(If `/mnt/llm_drive/` is outside the repo tree, commit a copy under a tracked path such as `ops/modelfiles/` — confirm the repo's convention for Modelfiles first with `git ls-files '*Modelfile*' | head`.)

---

## Phase 1 — Live verification (before PR)

After all tasks + `archie-deploy` (restart `archie_platform` + `archie_scheduler`):

1. **Isolation fix live:** `docker exec archie_platform python -m pytest platform_v2/tests/test_dispatch_scoring.py::TestModelIsGpuClass platform_v2/tests/test_model_sizes_coordinator.py platform_v2/tests/test_coordinator_lane.py -v` → all pass.
2. **Intent path uses the coordinator model, not a heavy one:** trigger a low-confidence intent (a dispatch that misses the >0.9 regex short-circuit) and confirm in `task_execution_log`:
   ```sql
   SELECT model_used, module_source, created_at FROM task_execution_log
   WHERE module_source = 'intent_parser' ORDER BY created_at DESC LIMIT 5;
   ```
   Expected `model_used = qwen25-classify` (NEVER `dolphin3-8k` / a 7B conversation model).
3. **No regression:** container healthy after restart (`docker ps` + `docker logs archie_platform --tail 50` clean); a normal dispatch still succeeds.

## Phase 1 — Ship

`/commit-push-pr` → F.O.R.G.E. review via Repair Bay → address findings → `/merge-pr` after APPROVE (Tier-3 gated items pause for Kytran's OK). Then bookkeeping: `complete_task`, `log_decision` (ADR: coordinator-lane abstraction + the misclassification fix), `update_project_understanding` (#375), C.O.D.E.X. doc. Only then start the Phase 2 plan (the gated plan step).

---

## Self-Review (spec coverage)

- Spec §5 coordinator_lane service → Tasks 1, 3. ✅
- Spec §6.1 kill dolphin3-8k → Task 4. ✅
- Spec §6.2 route light consumers → Task 5. ✅
- Spec §6.3 model_sizes + Modelfile → Tasks 2, 7. ✅
- Spec §6.4 lane isolation → **Task 2 (revised: fix misclassification instead of editing `_execute_llm` — lower risk, resolves §14 risk).** ✅
- Spec §6.4 always-warm pin → Task 6. ✅
- Spec §10 fail-open → Global Constraints + Task 3 kill switch. ✅
- Spec §11 testing → each task is TDD; live-verify section. ✅
- Deferred to later phases (out of Phase 1 scope): plan step (Phase 2), benchmark/swap (Phase 3), lane telemetry tag in task_execution_log (nice-to-have; `model_used`+`module_source` already identify coordinator calls).

## Open items flagged for the reviewer / Kytran

- **Task 7 (Modelfile)** needs hub Ollama access + confirmation of the repo's Modelfile convention (`git ls-files '*Modelfile*'`). If `/mnt/llm_drive/` is outside the repo, commit a tracked copy.
- **Task 4** edits `archie_engine_staging/intent_parser.py` (confirmed tracked in THIS repo). If a future refactor moves the live parser to `archie_core`, re-point.
- Design deviation from spec §6.4 documented above — **no edit to the hardened `_execute_llm`**; isolation via correct model-class classification. This is the biggest and most beneficial change the code-reading surfaced.
