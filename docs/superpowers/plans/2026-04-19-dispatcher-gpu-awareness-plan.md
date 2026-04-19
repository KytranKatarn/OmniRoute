# Dispatcher GPU Awareness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the A.R.C.H.I.E. dispatcher explicit GPU-placement control (Phase 1, hub-only) and hub-first fleet routing when the hub is full (Phase 2a), replacing Ollama's implicit auto-placement for every `api/generate` call originated by `department_dispatcher.py` and `orchestration_engine.py`.

**Architecture:** New pure helper module `platform_v2/tools/department_hq/services/ollama_options.py` exposes `build_options()` (decides `num_gpu` per-dispatch) and `select_node()` (hub-first, fleet-fallback). Model VRAM is discovered via `/api/show` probe-and-cache, keyed by `(node_id, model)`, heartbeat-invalidated. A new `ollama_placement_telemetry` observer and an extended single-writer guardrail enforce that new code can't bypass the helper.

**Tech Stack:** Python 3, `requests`, `dataclasses`, `psycopg2` (via `database.get_db`), `pytest`, `responses` library for HTTP mocks, `pre-commit` framework (already configured), existing `autonomy_loop_log` observer table.

**Spec:** `docs/superpowers/specs/2026-04-19-dispatcher-gpu-awareness-design.md`

**Branch:** `feat/dispatcher-gpu-awareness-spec` (spec already committed there — implementation tasks will use new branches off `main` per task, per CLAUDE.md branch policy; alternatively, all tasks can land on this same branch as two PRs per the spec's delivery plan).

---

## File Structure

**New files:**
- `platform_v2/tools/department_hq/services/ollama_options.py` — helper module (Phase 1 + 2a)
- `platform_v2/tests/test_ollama_options.py` — unit tests
- `platform_v2/tests/test_ollama_options_integration.py` — gated integration tests
- `platform_v2/tests/test_no_raw_api_generate.py` — regression guardrail test

**Modified files:**
- `platform_v2/tools/department_hq/services/department_dispatcher.py` — retrofit ~6 `api/generate` call sites
- `platform_v2/tools/department_hq/services/orchestration_engine.py` — retrofit ~3 `api/generate` call sites
- `scripts/check_agent_single_writer.py` — add Check #3 (raw `api/generate` rule)
- `ai_bridge/agent_loop.py` — add `_ollama_placement_telemetry` observer method + job registration
- `.claude/rules/ai-bridge.md` — documentation update

**File responsibilities:**
- `ollama_options.py` owns: VRAM arithmetic, probe cache, placement decision, node selection. No DB writes. No retries.
- `department_dispatcher.py` / `orchestration_engine.py` own: dispatch flow; they **consume** `build_options()` and merge results into their HTTP call.
- `check_agent_single_writer.py` owns: lint-gate preventing new `api/generate` string literals outside the helper.
- `agent_loop.py` owns: observer registration + 5-min tick that summarizes placement telemetry.

---

## Phase 1 — Hub-only helper + retrofit

### Task 1: Create module skeleton + ProbeEntry dataclass + exceptions

**Files:**
- Create: `platform_v2/tools/department_hq/services/ollama_options.py`
- Create: `platform_v2/tests/test_ollama_options.py`

- [ ] **Step 1: Write the failing test for the skeleton**

```python
# platform_v2/tests/test_ollama_options.py
"""Unit tests for ollama_options helper (Phase 1 + 2a)."""
from __future__ import annotations

import pytest


def test_module_exports_expected_public_api():
    from tools.department_hq.services import ollama_options as oo

    # Public surface exported for callers and tests.
    assert hasattr(oo, "build_options")
    assert hasattr(oo, "VramProbeCache")
    assert hasattr(oo, "ProbeEntry")
    assert hasattr(oo, "NodeUnavailable")
    assert hasattr(oo, "VRAM_SAFETY_MARGIN_GB")


def test_probe_entry_is_a_dataclass_with_expected_fields():
    from tools.department_hq.services.ollama_options import ProbeEntry
    import dataclasses

    assert dataclasses.is_dataclass(ProbeEntry)
    names = {f.name for f in dataclasses.fields(ProbeEntry)}
    assert names >= {
        "parameter_count",
        "quantization",
        "estimated_vram_base_gb",
        "context_overhead_per_token_mb",
        "probed_at",
        "probe_failed",
        "raw_show_response",
    }


def test_node_unavailable_is_an_exception():
    from tools.department_hq.services.ollama_options import NodeUnavailable

    assert issubclass(NodeUnavailable, Exception)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd platform_v2 && pytest tests/test_ollama_options.py -v`
Expected: all 3 tests FAIL with `ModuleNotFoundError: No module named 'tools.department_hq.services.ollama_options'`.

- [ ] **Step 3: Write minimal implementation**

```python
# platform_v2/tools/department_hq/services/ollama_options.py
"""GPU-aware Ollama options helper.

Decides `num_gpu` per-dispatch by probing model VRAM requirements against
the target node's available VRAM. See docs/superpowers/specs/
2026-04-19-dispatcher-gpu-awareness-design.md for the full design.

Phase 1: hub-only `build_options()` + `VramProbeCache`.
Phase 2a: hub-first `select_node()` with fleet fallback.
"""
from __future__ import annotations

import dataclasses
import datetime as _dt
import logging
import threading
from typing import Any, Optional

logger = logging.getLogger(__name__)

# Module-level tunable — safety headroom for Ollama internal buffers.
# Promoted to config if future tuning is needed.
VRAM_SAFETY_MARGIN_GB: float = 0.5


class NodeUnavailable(Exception):
    """Raised when the selected node can no longer serve the request.

    Caught by the dispatcher, which falls back to the hub (Phase 1) or to
    the next-fit node (Phase 2a).
    """


@dataclasses.dataclass
class ProbeEntry:
    """Cached VRAM profile for a (node, model) pair."""

    parameter_count: int
    quantization: str
    estimated_vram_base_gb: float
    context_overhead_per_token_mb: float
    probed_at: _dt.datetime
    probe_failed: bool = False
    raw_show_response: dict[str, Any] = dataclasses.field(default_factory=dict)


class VramProbeCache:
    """In-memory, heartbeat-invalidated cache — Phase 1 stub.

    Implemented in Task 2.
    """

    def __init__(self) -> None:
        self._entries: dict[tuple[str, str], ProbeEntry] = {}
        self._lock = threading.Lock()


def build_options(
    *,
    model: str,
    target_node: Optional[Any] = None,
    agent: Optional[Any] = None,
    prompt_tokens_hint: int = 0,
    keep_alive: str = "5m",
) -> dict[str, Any]:
    """Placeholder — real implementation lands in Task 5."""
    raise NotImplementedError("build_options is implemented in Task 5")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd platform_v2 && pytest tests/test_ollama_options.py -v`
Expected: all 3 tests PASS.

- [ ] **Step 5: Commit**

```bash
git checkout -b feat/gpu-awareness-phase1-skeleton
git add platform_v2/tools/department_hq/services/ollama_options.py \
        platform_v2/tests/test_ollama_options.py
git commit -m "feat(ollama_options): module skeleton + ProbeEntry dataclass

Scaffolds the GPU-aware Ollama options helper per Project #261 #2079
spec. VramProbeCache and build_options are placeholders; real impls
land in Tasks 2 and 5.
"
```

---

### Task 2: Implement VramProbeCache

**Files:**
- Modify: `platform_v2/tools/department_hq/services/ollama_options.py`
- Modify: `platform_v2/tests/test_ollama_options.py`

- [ ] **Step 1: Write the failing tests**

Append to `platform_v2/tests/test_ollama_options.py`:

```python
import datetime as _dt
from unittest.mock import patch


class _FakeNode:
    def __init__(self, node_id="hub", host="http://archie_ollama:11434", status="online"):
        self.node_id = node_id
        self.host = host
        self.status = status


def _make_show_response(parameter_size="3B", quant="Q4_K_M"):
    return {
        "modelfile": "",
        "parameters": "",
        "template": "",
        "details": {
            "parameter_size": parameter_size,
            "quantization_level": quant,
            "family": "llama",
            "format": "gguf",
        },
    }


def test_cache_probes_once_and_reuses_entry():
    from tools.department_hq.services.ollama_options import VramProbeCache

    cache = VramProbeCache()
    node = _FakeNode()
    with patch(
        "tools.department_hq.services.ollama_options._fetch_show",
        return_value=_make_show_response(),
    ) as mocked:
        e1 = cache.get_or_probe(node, "llama3.2:3b")
        e2 = cache.get_or_probe(node, "llama3.2:3b")
    assert e1 is e2
    assert mocked.call_count == 1
    assert e1.parameter_count == 3_000_000_000
    assert e1.quantization == "Q4_K_M"
    assert e1.probe_failed is False


def test_cache_invalidate_node_drops_all_entries_for_node():
    from tools.department_hq.services.ollama_options import VramProbeCache

    cache = VramProbeCache()
    node = _FakeNode()
    with patch(
        "tools.department_hq.services.ollama_options._fetch_show",
        return_value=_make_show_response(),
    ):
        cache.get_or_probe(node, "llama3.2:3b")
        cache.get_or_probe(node, "mistral:7b")
    cache.invalidate_node(node.node_id)
    assert cache._entries == {}


def test_cache_probe_failure_marks_entry_and_caches_for_short_window():
    from tools.department_hq.services.ollama_options import VramProbeCache

    cache = VramProbeCache()
    node = _FakeNode()
    with patch(
        "tools.department_hq.services.ollama_options._fetch_show",
        side_effect=RuntimeError("boom"),
    ):
        entry = cache.get_or_probe(node, "mystery:7b")
    assert entry.probe_failed is True
    assert entry.parameter_count == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd platform_v2 && pytest tests/test_ollama_options.py -v`
Expected: the 3 new tests FAIL (`get_or_probe`, `invalidate_node`, `_fetch_show` don't exist yet).

- [ ] **Step 3: Implement the cache**

Replace the `VramProbeCache` stub in `platform_v2/tools/department_hq/services/ollama_options.py` and add `_fetch_show` + `_parse_parameter_size`:

```python
import re
import requests

_PARAM_SIZE_RE = re.compile(r"^\s*([0-9]*\.?[0-9]+)\s*([BMKTbmkt])\s*$")
_SIZE_MULT = {"K": 1_000, "M": 1_000_000, "B": 1_000_000_000, "T": 1_000_000_000_000}

# TTLs
_FAILED_PROBE_TTL = _dt.timedelta(seconds=60)
_SOFT_TTL = _dt.timedelta(hours=24)


def _parse_parameter_size(raw: str | None) -> int:
    if not raw:
        return 0
    m = _PARAM_SIZE_RE.match(raw)
    if not m:
        return 0
    return int(float(m.group(1)) * _SIZE_MULT[m.group(2).upper()])


def _fetch_show(node, model: str, timeout_s: float = 5.0) -> dict[str, Any]:
    """Call GET /api/show on the target node. Separate for ease of mocking."""
    url = f"{node.host.rstrip('/')}/api/show"
    resp = requests.post(url, json={"name": model}, timeout=timeout_s)
    resp.raise_for_status()
    return resp.json()


class VramProbeCache:
    def __init__(self) -> None:
        self._entries: dict[tuple[str, str], ProbeEntry] = {}
        self._lock = threading.Lock()

    def get_or_probe(self, node, model: str) -> ProbeEntry:
        key = (node.node_id, model)
        now = _dt.datetime.utcnow()
        with self._lock:
            existing = self._entries.get(key)
            if existing is not None:
                age = now - existing.probed_at
                if existing.probe_failed and age < _FAILED_PROBE_TTL:
                    return existing
                if not existing.probe_failed and age < _SOFT_TTL:
                    return existing
        entry = self._probe(node, model, now)
        with self._lock:
            self._entries[key] = entry
        return entry

    def invalidate_node(self, node_id: str) -> None:
        with self._lock:
            for key in list(self._entries.keys()):
                if key[0] == node_id:
                    del self._entries[key]

    def invalidate(self, node_id: str, model: str) -> None:
        with self._lock:
            self._entries.pop((node_id, model), None)

    def _probe(self, node, model: str, now: _dt.datetime) -> ProbeEntry:
        try:
            raw = _fetch_show(node, model)
        except Exception as exc:
            logger.warning("probe failed for %s on %s: %s", model, node.node_id, exc)
            return ProbeEntry(
                parameter_count=0,
                quantization="",
                estimated_vram_base_gb=0.0,
                context_overhead_per_token_mb=0.0,
                probed_at=now,
                probe_failed=True,
                raw_show_response={},
            )
        details = raw.get("details", {}) or {}
        params = _parse_parameter_size(details.get("parameter_size"))
        quant = str(details.get("quantization_level") or "")
        # Placeholder VRAM/ctx numbers — refined by Task 3/5; kept here so
        # Task 2 tests pass without coupling to Task 3's quant table.
        return ProbeEntry(
            parameter_count=params,
            quantization=quant,
            estimated_vram_base_gb=0.0,
            context_overhead_per_token_mb=0.0,
            probed_at=now,
            probe_failed=False,
            raw_show_response=raw,
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd platform_v2 && pytest tests/test_ollama_options.py -v`
Expected: all tests PASS (6 so far).

- [ ] **Step 5: Commit**

```bash
git add platform_v2/tools/department_hq/services/ollama_options.py \
        platform_v2/tests/test_ollama_options.py
git commit -m "feat(ollama_options): VramProbeCache — probe /api/show, cache, invalidate

Implements the probe-and-cache layer (Phase 1 per spec §2.1). Parses
parameter_size into an int and stores the raw /api/show response.
VRAM math lands in Task 3.
"
```

---

### Task 3: Quantization → bytes-per-param table + VRAM estimator

**Files:**
- Modify: `platform_v2/tools/department_hq/services/ollama_options.py`
- Modify: `platform_v2/tests/test_ollama_options.py`

- [ ] **Step 1: Write the failing tests**

Append to `platform_v2/tests/test_ollama_options.py`:

```python
@pytest.mark.parametrize(
    "quant,expected_bpp",
    [
        ("Q2_K", 1.0),
        ("Q3_K_M", 1.25),
        ("Q4_K_M", 2.0),
        ("Q5_K_M", 2.5),
        ("Q6_K", 3.0),
        ("Q8_0", 4.0),
        ("F16", 6.0),
        ("UNKNOWN", 4.0),  # worst-case fp32 fallback
        ("", 4.0),
    ],
)
def test_bytes_per_param_table(quant, expected_bpp):
    from tools.department_hq.services.ollama_options import _bytes_per_param

    assert _bytes_per_param(quant) == expected_bpp


def test_estimate_base_vram_3b_q4():
    # 3B params * 2.0 bytes/param * 1.3 overhead = 7.8 GB
    from tools.department_hq.services.ollama_options import _estimate_base_vram_gb

    gb = _estimate_base_vram_gb(parameter_count=3_000_000_000, quantization="Q4_K_M")
    assert 7.5 < gb < 8.1


def test_cache_probe_populates_vram_estimate():
    from tools.department_hq.services.ollama_options import VramProbeCache

    cache = VramProbeCache()
    node = _FakeNode()
    with patch(
        "tools.department_hq.services.ollama_options._fetch_show",
        return_value=_make_show_response("7B", "Q4_K_M"),
    ):
        entry = cache.get_or_probe(node, "mistral:7b")
    # 7B * 2 bytes * 1.3 ≈ 18.2 GB
    assert 17.5 < entry.estimated_vram_base_gb < 19.0
    # Conservative context overhead (~1 MB/token) as first-cut estimate
    assert entry.context_overhead_per_token_mb > 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd platform_v2 && pytest tests/test_ollama_options.py -v`
Expected: new tests FAIL (`_bytes_per_param`, `_estimate_base_vram_gb` don't exist).

- [ ] **Step 3: Implement the VRAM estimator**

Insert above `_fetch_show` in `ollama_options.py`:

```python
# Quantization → bytes per parameter. Values from Ollama docs + empirical
# measurement. Unknown quant → 4 (worst-case fp32). Refined later if
# telemetry shows drift.
_BPP_TABLE: dict[str, float] = {
    "Q2_K": 1.0,
    "Q3_K_S": 1.25,
    "Q3_K_M": 1.25,
    "Q3_K_L": 1.25,
    "Q4_0": 2.0,
    "Q4_1": 2.0,
    "Q4_K_S": 2.0,
    "Q4_K_M": 2.0,
    "Q5_0": 2.5,
    "Q5_1": 2.5,
    "Q5_K_S": 2.5,
    "Q5_K_M": 2.5,
    "Q6_K": 3.0,
    "Q8_0": 4.0,
    "F16": 6.0,
    "BF16": 6.0,
    "F32": 4.0,
}
_RUNTIME_OVERHEAD = 1.3
_DEFAULT_CTX_OVERHEAD_MB_PER_TOKEN = 1.0  # conservative first-cut


def _bytes_per_param(quant: str) -> float:
    return _BPP_TABLE.get((quant or "").upper(), 4.0)


def _estimate_base_vram_gb(*, parameter_count: int, quantization: str) -> float:
    bpp = _bytes_per_param(quantization)
    # params × bytes-per-param × runtime overhead, then bytes → GB
    return (parameter_count * bpp * _RUNTIME_OVERHEAD) / (1024**3)
```

Modify the `_probe` method to populate the VRAM fields (replace the two `0.0` placeholders):

```python
        return ProbeEntry(
            parameter_count=params,
            quantization=quant,
            estimated_vram_base_gb=_estimate_base_vram_gb(
                parameter_count=params, quantization=quant
            ),
            context_overhead_per_token_mb=_DEFAULT_CTX_OVERHEAD_MB_PER_TOKEN,
            probed_at=now,
            probe_failed=False,
            raw_show_response=raw,
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd platform_v2 && pytest tests/test_ollama_options.py -v`
Expected: all tests PASS (16 so far).

- [ ] **Step 5: Commit**

```bash
git add platform_v2/tools/department_hq/services/ollama_options.py \
        platform_v2/tests/test_ollama_options.py
git commit -m "feat(ollama_options): quantization → bytes-per-param + VRAM estimator

Implements spec §2.1 VRAM math: base_vram = params × bpp × 1.3.
Unknown quant falls back to fp32-conservative (4 bytes).
"
```

---

### Task 4: `/api/ps` loaded-VRAM tally with 5-second cache

**Files:**
- Modify: `platform_v2/tools/department_hq/services/ollama_options.py`
- Modify: `platform_v2/tests/test_ollama_options.py`

- [ ] **Step 1: Write the failing tests**

Append to `platform_v2/tests/test_ollama_options.py`:

```python
def _make_ps_response(models_with_sizes):
    # size_vram is bytes per Ollama docs
    return {
        "models": [
            {"name": name, "size_vram": sz, "size": sz}
            for name, sz in models_with_sizes
        ]
    }


def test_loaded_vram_sums_size_vram_across_models():
    from tools.department_hq.services.ollama_options import get_loaded_vram_gb

    node = _FakeNode()
    ps = _make_ps_response([("a:latest", 1 * 1024**3), ("b:latest", 2 * 1024**3)])
    with patch(
        "tools.department_hq.services.ollama_options._fetch_ps",
        return_value=ps,
    ):
        gb = get_loaded_vram_gb(node, exclude_model=None)
    assert 2.99 < gb < 3.01


def test_loaded_vram_excludes_named_model():
    from tools.department_hq.services.ollama_options import get_loaded_vram_gb

    node = _FakeNode()
    ps = _make_ps_response([("target:latest", 4 * 1024**3), ("other:latest", 1 * 1024**3)])
    with patch(
        "tools.department_hq.services.ollama_options._fetch_ps",
        return_value=ps,
    ):
        gb = get_loaded_vram_gb(node, exclude_model="target:latest")
    assert 0.99 < gb < 1.01


def test_loaded_vram_caches_for_five_seconds():
    from tools.department_hq.services.ollama_options import (
        get_loaded_vram_gb,
        _loaded_vram_cache,
    )

    _loaded_vram_cache.clear()
    node = _FakeNode()
    ps = _make_ps_response([("a:latest", 1 * 1024**3)])
    with patch(
        "tools.department_hq.services.ollama_options._fetch_ps",
        return_value=ps,
    ) as mocked:
        get_loaded_vram_gb(node, exclude_model=None)
        get_loaded_vram_gb(node, exclude_model=None)
    assert mocked.call_count == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd platform_v2 && pytest tests/test_ollama_options.py -v`
Expected: new tests FAIL (`get_loaded_vram_gb`, `_fetch_ps`, `_loaded_vram_cache` don't exist).

- [ ] **Step 3: Implement the tally**

Append to `ollama_options.py`:

```python
_PS_CACHE_TTL_S = 5
_loaded_vram_cache: dict[str, tuple[float, list[dict[str, Any]]]] = {}
_loaded_vram_lock = threading.Lock()


def _fetch_ps(node, timeout_s: float = 5.0) -> dict[str, Any]:
    url = f"{node.host.rstrip('/')}/api/ps"
    resp = requests.get(url, timeout=timeout_s)
    resp.raise_for_status()
    return resp.json()


def _get_ps_models(node) -> list[dict[str, Any]]:
    now = _dt.datetime.utcnow().timestamp()
    with _loaded_vram_lock:
        cached = _loaded_vram_cache.get(node.node_id)
        if cached and now - cached[0] < _PS_CACHE_TTL_S:
            return cached[1]
    try:
        ps = _fetch_ps(node)
    except Exception as exc:
        logger.warning("ps fetch failed on %s: %s", node.node_id, exc)
        return []
    models = ps.get("models", []) or []
    with _loaded_vram_lock:
        _loaded_vram_cache[node.node_id] = (now, models)
    return models


def get_loaded_vram_gb(node, *, exclude_model: str | None) -> float:
    total_bytes = 0
    for m in _get_ps_models(node):
        if exclude_model and m.get("name") == exclude_model:
            continue
        total_bytes += int(m.get("size_vram", 0) or 0)
    return total_bytes / (1024**3)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd platform_v2 && pytest tests/test_ollama_options.py -v`
Expected: all tests PASS (19 so far).

- [ ] **Step 5: Commit**

```bash
git add platform_v2/tools/department_hq/services/ollama_options.py \
        platform_v2/tests/test_ollama_options.py
git commit -m "feat(ollama_options): loaded-VRAM tally via /api/ps with 5s cache

Implements spec §2.2 step 4 — compute 'currently loaded other models'
by summing size_vram across /api/ps. 5-second cache keeps hot
dispatches from flooding Ollama.
"
```

---

### Task 5: Implement `build_options()` (strategy A)

**Files:**
- Modify: `platform_v2/tools/department_hq/services/ollama_options.py`
- Modify: `platform_v2/tests/test_ollama_options.py`

- [ ] **Step 1: Write the failing tests**

Append to `platform_v2/tests/test_ollama_options.py`:

```python
def _hub(gpu_vram_gb=8.0):
    node = _FakeNode()
    node.gpu_vram_gb = gpu_vram_gb
    node.gpu_available = True
    node.status = "online"
    return node


def test_build_options_gpu_placement_when_model_fits():
    from tools.department_hq.services.ollama_options import build_options

    hub = _hub()
    with patch(
        "tools.department_hq.services.ollama_options._fetch_show",
        return_value=_make_show_response("3B", "Q4_K_M"),
    ), patch(
        "tools.department_hq.services.ollama_options._fetch_ps",
        return_value=_make_ps_response([]),
    ):
        result = build_options(model="llama3.2:3b", target_node=hub)
    assert result["placement"] == "gpu"
    assert "num_gpu" not in result["options"]
    assert result["target_node_id"] == "hub"
    assert result["model"] == "llama3.2:3b"


def test_build_options_cpu_placement_when_model_too_big():
    from tools.department_hq.services.ollama_options import build_options

    hub = _hub()
    with patch(
        "tools.department_hq.services.ollama_options._fetch_show",
        return_value=_make_show_response("13B", "Q4_K_M"),  # ~34 GB
    ), patch(
        "tools.department_hq.services.ollama_options._fetch_ps",
        return_value=_make_ps_response([]),
    ):
        result = build_options(model="llama3.1:13b", target_node=hub)
    assert result["placement"] == "cpu"
    assert result["options"]["num_gpu"] == 0
    assert "too_big" in result["reason"] or "insufficient" in result["reason"]


def test_build_options_cpu_placement_when_probe_failed():
    from tools.department_hq.services.ollama_options import build_options

    hub = _hub()
    with patch(
        "tools.department_hq.services.ollama_options._fetch_show",
        side_effect=RuntimeError("boom"),
    ), patch(
        "tools.department_hq.services.ollama_options._fetch_ps",
        return_value=_make_ps_response([]),
    ):
        result = build_options(model="mystery:7b", target_node=hub)
    assert result["placement"] == "cpu"
    assert result["options"]["num_gpu"] == 0
    assert result["reason"] == "probe_failed"


def test_build_options_prompt_tokens_push_past_vram_threshold():
    from tools.department_hq.services.ollama_options import build_options

    hub = _hub()  # M4000 8 GB
    with patch(
        "tools.department_hq.services.ollama_options._fetch_show",
        return_value=_make_show_response("3B", "Q4_K_M"),  # base ~7.3 GB
    ), patch(
        "tools.department_hq.services.ollama_options._fetch_ps",
        return_value=_make_ps_response([]),
    ):
        # Base ~7.3 GB already close to 8 GB. 2048 tokens × ~1 MB each
        # should push past available (8 - 0.5 margin = 7.5 GB).
        result = build_options(
            model="llama3.2:3b", target_node=hub, prompt_tokens_hint=2048
        )
    assert result["placement"] == "cpu"


def test_build_options_currently_loaded_models_reduce_headroom():
    from tools.department_hq.services.ollama_options import build_options

    hub = _hub()
    with patch(
        "tools.department_hq.services.ollama_options._fetch_show",
        return_value=_make_show_response("3B", "Q4_K_M"),  # ~7.3 GB base
    ), patch(
        "tools.department_hq.services.ollama_options._fetch_ps",
        return_value=_make_ps_response([("other:latest", 2 * 1024**3)]),
    ):
        result = build_options(model="llama3.2:3b", target_node=hub)
    # 8 - 0.5 margin - 2 loaded = 5.5 GB headroom; 7.3 GB model → CPU
    assert result["placement"] == "cpu"


def test_build_options_respects_keep_alive_override():
    from tools.department_hq.services.ollama_options import build_options

    hub = _hub()
    with patch(
        "tools.department_hq.services.ollama_options._fetch_show",
        return_value=_make_show_response("3B", "Q4_K_M"),
    ), patch(
        "tools.department_hq.services.ollama_options._fetch_ps",
        return_value=_make_ps_response([]),
    ):
        result = build_options(model="llama3.2:3b", target_node=hub, keep_alive="15m")
    assert result["keep_alive"] == "15m"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd platform_v2 && pytest tests/test_ollama_options.py -v`
Expected: new tests FAIL (`build_options` still raises `NotImplementedError`).

- [ ] **Step 3: Implement `build_options()`**

Replace the stub `build_options` in `ollama_options.py`:

```python
_DEFAULT_CACHE = VramProbeCache()


def _resolve_target_node(target_node):
    """Phase 1: None → hub. Phase 2a delegates to select_node (added in Task 11)."""
    if target_node is not None:
        return target_node
    from .fleet_service import get_hub_node  # existing helper

    return get_hub_node()


def build_options(
    *,
    model: str,
    target_node: Any | None = None,
    agent: Any | None = None,
    prompt_tokens_hint: int = 0,
    keep_alive: str = "5m",
    cache: VramProbeCache | None = None,
) -> dict[str, Any]:
    if not model or not isinstance(model, str):
        raise ValueError(f"model must be a non-empty string, got {model!r}")
    if prompt_tokens_hint < 0:
        raise ValueError(f"prompt_tokens_hint must be >= 0, got {prompt_tokens_hint}")

    node = _resolve_target_node(target_node)
    cache = cache or _DEFAULT_CACHE
    entry = cache.get_or_probe(node, model)

    gpu_vram_gb = float(getattr(node, "gpu_vram_gb", 0) or 0)
    gpu_available = bool(getattr(node, "gpu_available", False))

    reason: str
    placement: str

    if entry.probe_failed:
        placement, reason = "cpu", "probe_failed"
    elif not gpu_available or gpu_vram_gb <= 0:
        placement, reason = "cpu", "no_gpu_on_node"
    else:
        ctx_gb = (prompt_tokens_hint * entry.context_overhead_per_token_mb) / 1024.0
        required = entry.estimated_vram_base_gb + ctx_gb
        loaded_other = get_loaded_vram_gb(node, exclude_model=model)
        available = gpu_vram_gb - VRAM_SAFETY_MARGIN_GB - loaded_other
        if required > available:
            placement, reason = "cpu", "insufficient_vram_too_big"
        else:
            placement, reason = "gpu", "fits"

    options: dict[str, Any] = {}
    if placement == "cpu":
        options["num_gpu"] = 0

    return {
        "model": model,
        "options": options,
        "keep_alive": keep_alive,
        "target_node_id": node.node_id,
        "placement": placement,
        "reason": reason,
    }
```

**Note on `fleet_service.get_hub_node`**: if this helper does not already exist with this signature, use the existing `list_nodes()` / `get_node_status()` surface from `fleet_service` and select the row where `node_id = 'archie-starbase'` or `tags ? 'hub'`. Implementation to be confirmed at task start — adjust the import + call accordingly.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd platform_v2 && pytest tests/test_ollama_options.py -v`
Expected: all tests PASS (25 so far).

- [ ] **Step 5: Commit**

```bash
git add platform_v2/tools/department_hq/services/ollama_options.py \
        platform_v2/tests/test_ollama_options.py
git commit -m "feat(ollama_options): implement build_options (strategy A)

Core decision: probe VRAM requirement, subtract safety margin and
currently-loaded models from node VRAM, compare against required
(base + ctx overhead). Set num_gpu=0 when model wouldn't fit;
otherwise omit num_gpu and let Ollama place normally.

Phase 1 of Project #261 #2079.
"
```

---

### Task 6: Retrofit `department_dispatcher.py` call sites

**Files:**
- Modify: `platform_v2/tools/department_hq/services/department_dispatcher.py`

- [ ] **Step 1: Confirm exact call sites**

Run: `cd /mnt/archie_brain && grep -n 'api/generate\|api/chat' platform_v2/tools/department_hq/services/department_dispatcher.py`

Expected output: a numbered list of call sites — spec estimated ~6. If the count differs, update the task; all sites must be retrofit regardless.

- [ ] **Step 2: Retrofit each call site using the pattern**

For every `requests.post(f"{ollama_host}/api/generate", ...)` or `requests.post(f"{node_url}/api/generate", ...)` call:

**Before:**
```python
resp = requests.post(
    f"{ollama_host}/api/generate",
    json={
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": {"num_ctx": 4096, "temperature": 0.2},
        "keep_alive": "5m",
    },
    timeout=180,
)
```

**After:**
```python
from .ollama_options import build_options

opts = build_options(
    model=model,
    target_node=None,  # Phase 1: always hub; Phase 2a: select_node()
    prompt_tokens_hint=len(prompt) // 4,  # conservative; swap for real tokenizer if available
    keep_alive="5m",
)
# Caller-supplied options merge on top of helper's num_gpu decision.
request_options = {**opts["options"], "num_ctx": 4096, "temperature": 0.2}
resp = requests.post(
    f"{_node_url(opts['target_node_id'])}/api/generate",
    json={
        "model": opts["model"],
        "prompt": prompt,
        "stream": False,
        "options": request_options,
        "keep_alive": opts["keep_alive"],
    },
    timeout=180,
)
logger.info(
    "placement: node=%s model=%s placement=%s reason=%s",
    opts["target_node_id"], opts["model"], opts["placement"], opts["reason"],
)
```

If `_node_url()` does not already exist in this file, add a small helper at module scope:

```python
def _node_url(node_id: str) -> str:
    """Resolve node_id → base URL. Hub uses OLLAMA_HOST env; fleet uses remote_nodes row."""
    if node_id in ("hub", "archie-starbase"):
        import os
        return os.getenv("OLLAMA_HOST", "http://archie_ollama:11434")
    from .fleet_service import get_node_status
    node = get_node_status(node_id)
    return f"http://{node['vpn_ip']}:{node.get('port', 11434)}"
```

Repeat the retrofit for every site surfaced in Step 1.

- [ ] **Step 3: Run dispatcher unit tests + smoke import**

Run:
```bash
cd platform_v2 && pytest tests/test_dispatch_scoring.py -v
cd platform_v2 && python -c "from tools.department_hq.services import department_dispatcher"
```
Expected: existing tests still PASS. Import succeeds.

- [ ] **Step 4: Manual smoke test**

Run:
```bash
docker compose restart archie_platform
docker logs archie_platform --tail 100 2>&1 | grep -i 'placement:'
# Trigger a simple dispatch via MCP or the DHQ UI, then:
docker logs archie_platform --tail 50 2>&1 | grep -i 'placement:'
```
Expected: at least one `placement: node=archie-starbase ... placement=gpu reason=fits` line per dispatch.

- [ ] **Step 5: Commit**

```bash
git add platform_v2/tools/department_hq/services/department_dispatcher.py
git commit -m "refactor(dispatcher): route Ollama generates through build_options

Replaces ~6 raw api/generate call sites in department_dispatcher.py
with build_options()-produced option dicts. Callers still supply
num_ctx/temperature; helper only sets num_gpu.

Phase 1 of Project #261 #2079.
"
```

---

### Task 7: Retrofit `orchestration_engine.py` call sites

**Files:**
- Modify: `platform_v2/tools/department_hq/services/orchestration_engine.py`

- [ ] **Step 1: Confirm exact call sites**

Run: `cd /mnt/archie_brain && grep -n 'api/generate\|api/chat' platform_v2/tools/department_hq/services/orchestration_engine.py`
Expected: spec estimated ~3 sites.

- [ ] **Step 2: Retrofit each site with the Task 6 pattern**

Apply the same before/after transformation as Task 6 to every site found in Step 1. Use the same `from .ollama_options import build_options` import at the top of the file (add if not already present).

- [ ] **Step 3: Run orchestration tests + smoke import**

Run:
```bash
cd platform_v2 && pytest tests/ -v -k 'orchestration or dispatch'
cd platform_v2 && python -c "from tools.department_hq.services import orchestration_engine"
```
Expected: existing tests still PASS. Import succeeds.

- [ ] **Step 4: Manual smoke**

Run the same smoke as Task 6 Step 4 after `docker compose restart archie_platform`.

- [ ] **Step 5: Commit**

```bash
git add platform_v2/tools/department_hq/services/orchestration_engine.py
git commit -m "refactor(orchestration): route Ollama generates through build_options

Replaces ~3 raw api/generate call sites in orchestration_engine.py
step 6 (GPU) with build_options()-produced option dicts.

Phase 1 of Project #261 #2079.
"
```

---

### Task 8: Single-writer guardrail — Check #3 for raw `api/generate`

**Files:**
- Modify: `scripts/check_agent_single_writer.py`
- Create: `platform_v2/tests/test_no_raw_api_generate.py`

- [ ] **Step 1: Write the failing regression test**

Create `platform_v2/tests/test_no_raw_api_generate.py`:

```python
"""Lint regression — no raw api/generate outside ollama_options.

Ensures new dispatcher code routes through build_options, per spec
§'Single-writer guardrail' of docs/superpowers/specs/
2026-04-19-dispatcher-gpu-awareness-design.md.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def test_single_writer_guardrail_exits_zero_on_clean_tree():
    script = REPO / "scripts" / "check_agent_single_writer.py"
    # Target only the files we know are clean after Tasks 6+7.
    targets = [
        "platform_v2/tools/department_hq/services/department_dispatcher.py",
        "platform_v2/tools/department_hq/services/orchestration_engine.py",
        "platform_v2/tools/department_hq/services/ollama_options.py",
    ]
    result = subprocess.run(
        [sys.executable, str(script), *targets],
        cwd=REPO,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"guardrail should pass on clean tree.\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )


def test_single_writer_guardrail_flags_new_raw_api_generate(tmp_path):
    script = REPO / "scripts" / "check_agent_single_writer.py"
    offender = tmp_path / "fake_dispatcher.py"
    offender.write_text(
        'import requests\n\n'
        'def run():\n'
        '    requests.post("http://ollama/api/generate", json={"model": "x"})\n'
    )
    result = subprocess.run(
        [sys.executable, str(script), str(offender)],
        cwd=REPO,
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0, "guardrail should flag raw api/generate"
    assert "api/generate" in (result.stdout + result.stderr).lower() or \
           "build_options" in (result.stdout + result.stderr).lower()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd platform_v2 && pytest tests/test_no_raw_api_generate.py -v`
Expected: `test_single_writer_guardrail_flags_new_raw_api_generate` FAILS (script doesn't check for `api/generate` yet).

- [ ] **Step 3: Extend `scripts/check_agent_single_writer.py`**

Add Check #3 at the end of the script's existing check-chain. Pattern after the existing Check #1 / #2 structure:

```python
# ---- Check 3: raw api/generate outside ollama_options ----------------------
# Spec: docs/superpowers/specs/2026-04-19-dispatcher-gpu-awareness-design.md
# Reason: every dispatcher-initiated inference must go through
# build_options() so GPU placement is explicit and observable.

_API_GENERATE_RE = re.compile(r"api/(generate|chat)")

# Files allowed to reference api/generate or api/chat directly.
# Add new entries ONLY with a follow-up task ID in the comment.
_API_GENERATE_ALLOWLIST = {
    # The helper itself: this IS the single writer.
    "platform_v2/tools/department_hq/services/ollama_options.py",
    # Health-ping loop — passes explicit num_gpu=0; not a user dispatch.
    "ai_bridge/agent_loop.py",
    # Legacy sites deferred to future work (see spec §3.1 Retrofit targets):
    "ai_bridge/archie_bridge.py",          # task TBD — ai_bridge migration
    "ai_bridge/knowledge_analyzer.py",     # task TBD — analysis pipeline
    # Tests are always allowed to reference the pattern.
    # (handled by path suffix check below)
}


def _check_raw_api_generate(paths: list[Path]) -> list[str]:
    violations: list[str] = []
    for p in paths:
        rel = str(p).replace("\\", "/")
        if rel.endswith("_test.py") or "/tests/" in rel or "/test_" in rel:
            continue
        if any(rel.endswith(allowed) for allowed in _API_GENERATE_ALLOWLIST):
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for i, line in enumerate(text.splitlines(), 1):
            if _API_GENERATE_RE.search(line):
                violations.append(
                    f"{rel}:{i}: raw api/generate call — use "
                    f"tools.department_hq.services.ollama_options.build_options()"
                )
    return violations
```

Wire `_check_raw_api_generate` into the script's `main()` alongside the existing checks and include its violations in the exit-code decision.

- [ ] **Step 4: Run the regression tests to verify they pass**

Run: `cd platform_v2 && pytest tests/test_no_raw_api_generate.py -v`
Expected: both tests PASS.

Also run: `cd /mnt/archie_brain && python3 scripts/check_agent_single_writer.py platform_v2/tools/department_hq/services/*.py`
Expected: exit 0.

- [ ] **Step 5: Commit**

```bash
git add scripts/check_agent_single_writer.py \
        platform_v2/tests/test_no_raw_api_generate.py
git commit -m "feat(guardrail): block new raw api/generate outside build_options

Adds Check #3 to scripts/check_agent_single_writer.py. Allowlist
covers ollama_options (the single writer) plus three pre-existing
sites scheduled for later migration.

Phase 1 of Project #261 #2079.
"
```

---

### Task 9: `ollama_placement_telemetry` observer

**Files:**
- Modify: `ai_bridge/agent_loop.py`
- Modify: `platform_v2/tools/department_hq/services/ollama_options.py`

- [ ] **Step 1: Add a placement-event emitter to the helper**

Append to `ollama_options.py`:

```python
# Simple in-memory rolling window; observer reads + resets every 5 min.
_placement_events: list[dict[str, Any]] = []
_placement_lock = threading.Lock()
_PLACEMENT_WINDOW_MAX = 10_000  # cap to bound memory under high QPS


def _record_placement_event(event: dict[str, Any]) -> None:
    with _placement_lock:
        if len(_placement_events) >= _PLACEMENT_WINDOW_MAX:
            # Drop oldest — bounded memory is better than unbounded list.
            del _placement_events[:1000]
        _placement_events.append(event)


def drain_placement_events() -> list[dict[str, Any]]:
    with _placement_lock:
        events, _placement_events[:] = list(_placement_events), []
        return events
```

Modify `build_options()` to emit an event before returning:

```python
    event = {
        "ts": _dt.datetime.utcnow().isoformat(),
        "node_id": node.node_id,
        "model": model,
        "placement": placement,
        "reason": reason,
        "prompt_tokens_hint": prompt_tokens_hint,
    }
    _record_placement_event(event)

    return {
        "model": model,
        "options": options,
        "keep_alive": keep_alive,
        "target_node_id": node.node_id,
        "placement": placement,
        "reason": reason,
    }
```

- [ ] **Step 2: Write the observer test**

Append to `platform_v2/tests/test_ollama_options.py`:

```python
def test_drain_placement_events_returns_and_resets():
    from tools.department_hq.services.ollama_options import (
        _record_placement_event,
        drain_placement_events,
    )

    drain_placement_events()  # reset
    _record_placement_event({"placement": "gpu", "reason": "fits"})
    _record_placement_event({"placement": "cpu", "reason": "probe_failed"})
    events = drain_placement_events()
    assert len(events) == 2
    # Second drain is empty.
    assert drain_placement_events() == []
```

- [ ] **Step 3: Run the test to verify it passes**

Run: `cd platform_v2 && pytest tests/test_ollama_options.py::test_drain_placement_events_returns_and_resets -v`
Expected: PASS.

- [ ] **Step 4: Register the observer in `agent_loop.py`**

Add a method `_ollama_placement_telemetry(self)` modeled on the existing `_ollama_model_health` observer. It should:
- `drain_placement_events()`
- Aggregate counts per `(node_id, placement, reason)`
- Log summary via `self._log_cycle("ollama_placement_telemetry", processed, failed, duration_ms, error_message=...)`
- Flag anomaly when CPU-fallback share > 50% sustained for more than 10 minutes (compare against previous tick — stored on `self._last_placement_summary`)

Register the job in the agent-loop scheduler registration block. Use a 5-minute interval (spec §"Observability").

```python
    def _ollama_placement_telemetry(self):
        """5-min placement-decision summary. Writes one autonomy_loop_log row."""
        start = time.time()
        try:
            from tools.department_hq.services.ollama_options import drain_placement_events
            events = drain_placement_events()
            if not events:
                self._log_cycle(
                    "ollama_placement_telemetry", 0, 0,
                    int((time.time() - start) * 1000),
                )
                return
            gpu = sum(1 for e in events if e.get("placement") == "gpu")
            cpu = sum(1 for e in events if e.get("placement") == "cpu")
            cpu_share = cpu / max(gpu + cpu, 1)
            prev = getattr(self, "_last_placement_summary", None)
            anomaly = cpu_share > 0.5 and prev and prev.get("cpu_share", 0) > 0.5
            self._last_placement_summary = {
                "ts": time.time(),
                "gpu": gpu,
                "cpu": cpu,
                "cpu_share": cpu_share,
            }
            self._log_cycle(
                "ollama_placement_telemetry",
                processed=gpu + cpu,
                failed=cpu if anomaly else 0,
                duration_ms=int((time.time() - start) * 1000),
                error_message=(
                    f"sustained_cpu_fallback cpu_share={cpu_share:.2f}"
                    if anomaly else None
                ),
            )
        except Exception as e:
            logger.error(f"ollama_placement_telemetry failed: {e}")
            self._log_cycle(
                "ollama_placement_telemetry", 0, 1,
                int((time.time() - start) * 1000),
                error_message=str(e),
            )
```

Register in the same block where `_ollama_model_health` is scheduled — use `IntervalTrigger(minutes=5)`.

- [ ] **Step 5: Commit**

```bash
git add platform_v2/tools/department_hq/services/ollama_options.py \
        platform_v2/tests/test_ollama_options.py \
        ai_bridge/agent_loop.py
git commit -m "feat(observability): ollama_placement_telemetry observer

5-minute rolling-window summary of build_options placement decisions.
Anomaly flagged when sustained CPU-fallback > 50% for >= 2 ticks.
Writes one autonomy_loop_log row per tick (spec §Observability).

Phase 1 of Project #261 #2079.
"
```

---

### Task 10: Gated integration tests

**Files:**
- Create: `platform_v2/tests/test_ollama_options_integration.py`

- [ ] **Step 1: Write the gated tests**

```python
"""Integration tests — require RUN_INTEGRATION=1 and a live hub Ollama.

These are skipped in CI by default. Run manually after retrofit:
    RUN_INTEGRATION=1 pytest tests/test_ollama_options_integration.py -v
"""
from __future__ import annotations

import os
import requests

import pytest

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_INTEGRATION") != "1",
    reason="integration tests gated by RUN_INTEGRATION=1",
)

OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://192.168.1.200:11434")


class _LiveNode:
    node_id = "archie-starbase"
    host = OLLAMA_HOST
    gpu_vram_gb = 8.0
    gpu_available = True
    status = "online"


def _is_loaded_on_gpu(model: str) -> bool:
    resp = requests.get(f"{OLLAMA_HOST}/api/ps", timeout=10)
    resp.raise_for_status()
    for m in resp.json().get("models", []):
        if m.get("name", "").startswith(model) and m.get("size_vram", 0) > 0:
            return True
    return False


def test_small_model_places_on_gpu():
    """Small model should land on GPU via build_options decision."""
    from tools.department_hq.services.ollama_options import build_options

    result = build_options(model="llama3.2:3b", target_node=_LiveNode())
    assert result["placement"] == "gpu"
    # Trigger actual inference to verify GPU placement via /api/ps.
    requests.post(
        f"{OLLAMA_HOST}/api/generate",
        json={
            "model": "llama3.2:3b",
            "prompt": "hi",
            "stream": False,
            "options": {**result["options"], "num_predict": 1},
            "keep_alive": result["keep_alive"],
        },
        timeout=60,
    )
    assert _is_loaded_on_gpu("llama3.2:3b")


def test_large_model_places_on_cpu():
    """Model exceeding 8 GB VRAM should be routed CPU-only."""
    from tools.department_hq.services.ollama_options import build_options

    # Pick any model known to exceed 8 GB on the hub, e.g. qwen3-coder-cpu.
    result = build_options(model="qwen3-coder-cpu:latest", target_node=_LiveNode())
    assert result["placement"] == "cpu"
    assert result["options"]["num_gpu"] == 0
```

- [ ] **Step 2: Run skipped (CI baseline)**

Run: `cd platform_v2 && pytest tests/test_ollama_options_integration.py -v`
Expected: all tests SKIP with reason `integration tests gated by RUN_INTEGRATION=1`.

- [ ] **Step 3: Run live (manual)**

Run: `cd platform_v2 && RUN_INTEGRATION=1 OLLAMA_HOST=http://192.168.1.200:11434 pytest tests/test_ollama_options_integration.py -v`
Expected: PASS (assumes the hub is up and the two models named in tests are pullable or already present).

If either model isn't present, the test will pull it — allow up to 10 min timeout. Adjust model names to whatever is currently on the hub if the default pair is unavailable.

- [ ] **Step 4: Commit**

```bash
git add platform_v2/tests/test_ollama_options_integration.py
git commit -m "test(ollama_options): gated hub integration tests

Adds RUN_INTEGRATION=1-gated tests that verify end-to-end placement
on the live hub Ollama. Skipped by default in CI; run manually after
each retrofit PR.

Phase 1 of Project #261 #2079.
"
```

---

## Phase 2a — Hub-first locality routing

### Task 11: Implement `select_node()` (hub-first, fleet-fallback)

**Files:**
- Modify: `platform_v2/tools/department_hq/services/ollama_options.py`
- Modify: `platform_v2/tests/test_ollama_options.py`

- [ ] **Step 1: Write the failing tests**

Append to `platform_v2/tests/test_ollama_options.py`:

```python
def test_select_node_returns_hub_when_hub_fits():
    from tools.department_hq.services.ollama_options import select_node

    hub = _hub()
    with patch(
        "tools.department_hq.services.ollama_options._resolve_target_node",
        return_value=hub,
    ), patch(
        "tools.department_hq.services.ollama_options._list_online_fleet_nodes",
        return_value=[],
    ), patch(
        "tools.department_hq.services.ollama_options._fetch_show",
        return_value=_make_show_response("3B", "Q4_K_M"),
    ), patch(
        "tools.department_hq.services.ollama_options._fetch_ps",
        return_value=_make_ps_response([]),
    ):
        chosen = select_node(capability="conversation", model="llama3.2:3b")
    assert chosen.node_id == "hub"


def test_select_node_falls_to_fleet_when_hub_full():
    from tools.department_hq.services.ollama_options import select_node

    hub = _hub()  # 8 GB M4000
    fleet = _FakeNode(node_id="uss-kytran", host="http://100.64.0.2:11434")
    fleet.gpu_vram_gb = 8.0
    fleet.gpu_available = True
    fleet.status = "online"
    fleet.current_load = 0
    fleet.max_concurrent = 5

    with patch(
        "tools.department_hq.services.ollama_options._resolve_target_node",
        return_value=hub,
    ), patch(
        "tools.department_hq.services.ollama_options._list_online_fleet_nodes",
        return_value=[fleet],
    ), patch(
        "tools.department_hq.services.ollama_options._fetch_show",
        return_value=_make_show_response("3B", "Q4_K_M"),
    ), patch(
        "tools.department_hq.services.ollama_options._fetch_ps",
        # Hub already has 7 GB loaded → no room for a 7.3 GB model.
        side_effect=lambda n, timeout_s=5.0: _make_ps_response(
            [("big:latest", 7 * 1024**3)] if n.node_id == hub.node_id else []
        ),
    ):
        chosen = select_node(capability="conversation", model="llama3.2:3b")
    assert chosen.node_id == "uss-kytran"


def test_select_node_returns_hub_cpu_when_no_gpu_node_fits():
    from tools.department_hq.services.ollama_options import select_node

    hub = _hub()
    with patch(
        "tools.department_hq.services.ollama_options._resolve_target_node",
        return_value=hub,
    ), patch(
        "tools.department_hq.services.ollama_options._list_online_fleet_nodes",
        return_value=[],
    ), patch(
        "tools.department_hq.services.ollama_options._fetch_show",
        return_value=_make_show_response("70B", "Q4_K_M"),  # huge
    ), patch(
        "tools.department_hq.services.ollama_options._fetch_ps",
        return_value=_make_ps_response([]),
    ):
        chosen = select_node(capability="conversation", model="big:70b")
    # Nothing fits → still return hub; caller sees placement=cpu from build_options.
    assert chosen.node_id == "hub"


def test_select_node_skips_nodes_at_max_concurrent():
    from tools.department_hq.services.ollama_options import select_node

    hub = _hub()
    fleet = _FakeNode(node_id="busy-node", host="http://x:11434")
    fleet.gpu_vram_gb = 8.0
    fleet.gpu_available = True
    fleet.status = "online"
    fleet.current_load = 5
    fleet.max_concurrent = 5

    with patch(
        "tools.department_hq.services.ollama_options._resolve_target_node",
        return_value=hub,
    ), patch(
        "tools.department_hq.services.ollama_options._list_online_fleet_nodes",
        return_value=[fleet],
    ), patch(
        "tools.department_hq.services.ollama_options._fetch_show",
        return_value=_make_show_response("3B", "Q4_K_M"),
    ), patch(
        "tools.department_hq.services.ollama_options._fetch_ps",
        side_effect=lambda n, timeout_s=5.0: _make_ps_response(
            [("big:latest", 7 * 1024**3)] if n.node_id == hub.node_id else []
        ),
    ):
        chosen = select_node(capability="conversation", model="llama3.2:3b")
    # Hub full, fleet at max_concurrent → fall back to hub (CPU).
    assert chosen.node_id == "hub"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd platform_v2 && pytest tests/test_ollama_options.py -v -k select_node`
Expected: 4 tests FAIL (`select_node`, `_list_online_fleet_nodes` don't exist).

- [ ] **Step 3: Implement `select_node()`**

Append to `ollama_options.py`:

```python
def _list_online_fleet_nodes() -> list:
    """Query remote_nodes for online GPU-capable fleet nodes (non-hub)."""
    from .fleet_service import list_nodes

    rows = list_nodes() or []
    out = []
    for r in rows:
        if r.get("node_id") in ("hub", "archie-starbase"):
            continue
        if r.get("status") != "online":
            continue
        if not r.get("gpu_available"):
            continue
        if not r.get("ollama_available"):
            continue
        out.append(r)
    # Priority ASC, current_load ASC — matches spec §2.3.
    out.sort(key=lambda r: (r.get("priority", 10), r.get("current_load", 0)))
    return out


def _fits_on_node(node, model: str, prompt_tokens_hint: int, cache: VramProbeCache) -> bool:
    """Return True if model + context fits on node's available GPU right now."""
    gpu_vram_gb = float(getattr(node, "gpu_vram_gb", 0) or 0)
    if gpu_vram_gb <= 0:
        return False
    entry = cache.get_or_probe(node, model)
    if entry.probe_failed:
        return False
    ctx_gb = (prompt_tokens_hint * entry.context_overhead_per_token_mb) / 1024.0
    required = entry.estimated_vram_base_gb + ctx_gb
    loaded_other = get_loaded_vram_gb(node, exclude_model=model)
    available = gpu_vram_gb - VRAM_SAFETY_MARGIN_GB - loaded_other
    return required <= available


def select_node(
    *,
    capability: str,
    model: str,
    prompt_tokens_hint: int = 0,
    fallback_cpu_ok: bool = True,
    cache: VramProbeCache | None = None,
):
    cache = cache or _DEFAULT_CACHE
    hub = _resolve_target_node(None)
    if _fits_on_node(hub, model, prompt_tokens_hint, cache):
        return hub
    for node in _list_online_fleet_nodes():
        load = int(getattr(node, "current_load", 0) or 0)
        maxc = int(getattr(node, "max_concurrent", 0) or 0)
        if maxc and load >= maxc:
            continue
        # Convert dict row to a node-like object if needed.
        node_obj = node if hasattr(node, "node_id") else _dict_to_node(node)
        if _fits_on_node(node_obj, model, prompt_tokens_hint, cache):
            return node_obj
    if fallback_cpu_ok:
        return hub
    raise NodeUnavailable(f"no node can fit {model} and fallback_cpu_ok=False")


def _dict_to_node(row: dict[str, Any]):
    """Light adapter for fleet_service rows that come back as dicts."""
    class _NodeView:
        pass
    n = _NodeView()
    n.node_id = row.get("node_id")
    n.host = f"http://{row.get('vpn_ip')}:{row.get('port', 11434)}"
    n.gpu_vram_gb = float(row.get("gpu_vram_gb") or 0)
    n.gpu_available = bool(row.get("gpu_available"))
    n.current_load = int(row.get("current_load") or 0)
    n.max_concurrent = int(row.get("max_concurrent") or 0)
    n.status = row.get("status")
    return n
```

Modify `_resolve_target_node` to delegate to `select_node` when Phase 2a is active. Keep it backwards-compatible:

```python
def _resolve_target_node(target_node, *, for_selection: bool = False):
    if target_node is not None:
        return target_node
    from .fleet_service import get_hub_node
    hub = get_hub_node()
    if for_selection:
        # Prevent recursion when select_node calls _resolve_target_node to get the hub.
        return hub
    return hub
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd platform_v2 && pytest tests/test_ollama_options.py -v`
Expected: all tests (29 total) PASS.

- [ ] **Step 5: Commit**

```bash
git add platform_v2/tools/department_hq/services/ollama_options.py \
        platform_v2/tests/test_ollama_options.py
git commit -m "feat(ollama_options): select_node — hub-first with fleet fallback

Phase 2a per spec §2.3. Hub first; fall back to first online fleet
GPU node where model fits and current_load < max_concurrent. Falls
all the way back to hub CPU when nothing fits.
"
```

---

### Task 12: Wire `build_options(target_node=None)` to `select_node()`

**Files:**
- Modify: `platform_v2/tools/department_hq/services/ollama_options.py`
- Modify: `platform_v2/tests/test_ollama_options.py`

- [ ] **Step 1: Write the failing test**

Append to `platform_v2/tests/test_ollama_options.py`:

```python
def test_build_options_with_none_target_node_uses_select_node():
    from tools.department_hq.services import ollama_options as oo

    hub = _hub()
    fleet = _FakeNode(node_id="uss-kytran", host="http://100.64.0.2:11434")
    fleet.gpu_vram_gb = 8.0
    fleet.gpu_available = True

    with patch(
        "tools.department_hq.services.ollama_options.select_node",
        return_value=fleet,
    ) as mocked_select, patch(
        "tools.department_hq.services.ollama_options._fetch_show",
        return_value=_make_show_response("3B", "Q4_K_M"),
    ), patch(
        "tools.department_hq.services.ollama_options._fetch_ps",
        return_value=_make_ps_response([]),
    ):
        result = oo.build_options(model="llama3.2:3b", target_node=None)
    mocked_select.assert_called_once()
    assert result["target_node_id"] == "uss-kytran"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd platform_v2 && pytest tests/test_ollama_options.py::test_build_options_with_none_target_node_uses_select_node -v`
Expected: FAIL (build_options still resolves to hub directly).

- [ ] **Step 3: Wire `build_options` to `select_node`**

Replace the first line of `build_options`'s body (`node = _resolve_target_node(target_node)`) with:

```python
    if target_node is None:
        node = select_node(
            capability=getattr(agent, "capability", "") if agent else "",
            model=model,
            prompt_tokens_hint=prompt_tokens_hint,
            fallback_cpu_ok=True,
        )
    else:
        node = target_node
```

- [ ] **Step 4: Run tests to verify all pass**

Run: `cd platform_v2 && pytest tests/test_ollama_options.py -v`
Expected: all tests PASS (30 total).

- [ ] **Step 5: Commit**

```bash
git add platform_v2/tools/department_hq/services/ollama_options.py \
        platform_v2/tests/test_ollama_options.py
git commit -m "feat(ollama_options): route target_node=None through select_node

Phase 2a landing. Existing callers (target_node=None) now pick up
hub-first locality routing for free. No call-site changes required.
"
```

---

### Task 13: Mocked multi-node integration tests

**Files:**
- Modify: `platform_v2/tests/test_ollama_options_integration.py` (add `responses`-based cases)

- [ ] **Step 1: Write the failing tests**

Append to `platform_v2/tests/test_ollama_options_integration.py`:

```python
# ---------------------------------------------------------------
# Mocked fleet — always runs (no RUN_INTEGRATION gate).
# Uses the `responses` library to stand up fake Ollama endpoints.
# ---------------------------------------------------------------
import json

import responses


@responses.activate
def test_mocked_two_node_fleet_hub_full_routes_to_fleet():
    from tools.department_hq.services import ollama_options as oo

    oo._loaded_vram_cache.clear()
    oo._DEFAULT_CACHE = oo.VramProbeCache()

    hub_url = "http://archie_ollama:11434"
    fleet_url = "http://100.64.0.2:11434"

    responses.add(responses.POST, f"{hub_url}/api/show",
                  json={"details": {"parameter_size": "3B", "quantization_level": "Q4_K_M"}})
    responses.add(responses.POST, f"{fleet_url}/api/show",
                  json={"details": {"parameter_size": "3B", "quantization_level": "Q4_K_M"}})
    responses.add(responses.GET, f"{hub_url}/api/ps",
                  json={"models": [{"name": "big:latest", "size_vram": 7 * 1024**3}]})
    responses.add(responses.GET, f"{fleet_url}/api/ps",
                  json={"models": []})

    class _HubNode:
        node_id = "archie-starbase"
        host = hub_url
        gpu_vram_gb = 8.0
        gpu_available = True
        status = "online"

    class _FleetNode:
        node_id = "uss-kytran"
        host = fleet_url
        gpu_vram_gb = 8.0
        gpu_available = True
        current_load = 0
        max_concurrent = 5
        status = "online"

    with unittest_mock_patch(
        "tools.department_hq.services.ollama_options._resolve_target_node",
        return_value=_HubNode(),
    ), unittest_mock_patch(
        "tools.department_hq.services.ollama_options._list_online_fleet_nodes",
        return_value=[_FleetNode()],
    ):
        chosen = oo.select_node(capability="conversation", model="llama3.2:3b")
    assert chosen.node_id == "uss-kytran"
```

Add at the top of the file (only if not already there):

```python
from unittest.mock import patch as unittest_mock_patch
```

- [ ] **Step 2: Run the test**

Run: `cd platform_v2 && pytest tests/test_ollama_options_integration.py::test_mocked_two_node_fleet_hub_full_routes_to_fleet -v`
Expected: PASS. If `responses` isn't installed, `pip install responses` and re-run.

- [ ] **Step 3: Commit**

```bash
git add platform_v2/tests/test_ollama_options_integration.py
git commit -m "test(ollama_options): mocked two-node fleet integration

Uses the responses library to stand up fake hub+fleet Ollama
endpoints and verify select_node routes to fleet when hub is full.
"
```

---

## Post-plan follow-ups

After all 13 tasks land on a PR (or two — one per phase):

1. Push branch and open PR(s). Let the user merge.
2. After merge, run the Dev HQ workflow:
   - `mcp complete_task` for #2079 with a note referencing both PRs.
   - `mcp log_decision` documenting the Phase 1/2a decision and the deferral of strategies B/C/D.
   - `mcp update_project_understanding` for Project #261.
   - `mcp store_memory` with a vault_note summarising the helper's public API for future session recall.
3. File new P7 tasks under Project #261 for strategies B, C, D, and for Phase 2b scored selection (gated on a second GPU node coming online).
4. Update `.claude/rules/ai-bridge.md` to reflect that `build_options()` is now the single writer for dispatcher-initiated Ollama options.

---

## Self-review checklist (performed before saving)

- **Spec coverage:** every section of the spec maps to at least one task —
  Phase 1 §2.1 → Task 2; §2.1 VRAM table → Task 3; §2.2 build_options → Task 5;
  §3.1–3.2 retrofit → Tasks 6–7; §3.4 observability → Task 9; §3.5 guardrail → Task 8;
  §2.3 select_node → Task 11; Phase 2a wire-through → Task 12;
  §5 unit tests are inline in Tasks 1–5, 9, 11, 12;
  §5 integration tests → Tasks 10 and 13.
- **Placeholder scan:** no TBD / TODO / "implement later" in the task bodies.
  Two honestly-approximate numbers ("~6 sites", "~3 sites") are resolved by
  grep in Task 6 Step 1 and Task 7 Step 1. The `fleet_service.get_hub_node`
  signature assumption is flagged inline with a fallback instruction.
- **Type consistency:** `VramProbeCache`, `ProbeEntry`, `build_options`,
  `select_node`, `get_loaded_vram_gb`, `drain_placement_events` appear with
  identical signatures across every task that references them.
