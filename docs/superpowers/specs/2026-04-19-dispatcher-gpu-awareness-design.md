# Dispatcher GPU Awareness + Fleet GPU Orchestration — Design

**Project**: #261 LLM Resource Management
**Task**: #2079 Dispatcher-level GPU awareness + fleet GPU orchestration
**Date**: 2026-04-19
**Status**: draft — awaiting user review
**Author**: Claude Code session 9c6d7590
**Branch**: `feat/dispatcher-gpu-awareness-spec`

## Background

`OLLAMA_NUM_PARALLEL=1` is set via systemd; Ollama auto-places models on the hub's Quadro M4000 (8GB VRAM) when they fit. First inference on `llama3.2:3b` measured at 27.3 tps, 100% GPU offload.

However, no dispatcher code passes `num_gpu` explicitly. The only place today that touches it is `ai_bridge/agent_loop.py:_ollama_model_health` (forces `num_gpu=0` for health pings of non-GPU models). The ~11 `api/generate` call sites across `department_dispatcher.py`, `orchestration_engine.py`, and `archie_bridge.py` rely entirely on Ollama's implicit auto-placement. Implicit placement silently spills to RAM when a model doesn't fit, causing load-average spikes (the root cause behind Project #240) without telling the dispatcher.

As the fleet grows (home GPU → fleet GPU → cloud), the dispatcher needs to:

1. Know each node's GPU availability, VRAM, CPU cores, and current load — **schema already exists** (`remote_nodes.gpu_available`, `gpu_vram_gb`, `current_load`, `max_concurrent`, `ollama_available`).
2. Route each inference to the best node (home first, fleet second, cloud last — already coded in smart_router's 11-tier escalation, but **not GPU-topology-aware**).
3. Pass `num_gpu` / partial-offload hints based on the target node's VRAM vs model size.
4. Fall back gracefully if the chosen node is under load or GPU-full.

## Scope

This spec covers **Phase 1** and **Phase 2**. Subsequent fallback-strategy phases (B partial offload, C tier escalation, D hybrid heuristic) are filed as follow-up tasks and not in scope here.

| Phase | Scope | Fallback strategy |
|---|---|---|
| **Phase 1** | Hub-only `build_options()` helper + retrofit 11 call sites | A (binary CPU fallback) |
| **Phase 2a** | Hub-first locality routing with fleet fallback when hub GPU full | A |
| **Phase 2b** | Scored node-selection layer on top of Phase 2a | A |
| Phase 3 (future) | Partial-offload `num_gpu` layer-count | B |
| Phase 4 (future) | Tier-escalation on fit failure via smart_router | C |
| Phase 5 (future) | Hybrid heuristic consolidating A/B/C by capability | D |

## Goals

- Stop relying on Ollama's implicit GPU auto-placement for dispatcher-initiated inference.
- Make every GPU-placement decision observable (one log line per dispatch).
- Lay the foundation for fleet-topology-aware routing without requiring a second online GPU node today.
- Preserve today's dispatch outcomes when behavior is already correct (no surprise regressions for small-model traffic on the hub).

## Non-goals

- Partial GPU offload (`num_gpu=N` layer splitting) — deferred to Phase 3.
- Escalation to cloud on GPU-fit failure — deferred to Phase 4; smart_router keeps its existing 11-tier logic unchanged.
- Per-agent GPU budgets — orthogonal concern, not in scope.
- Dynamic GPU pricing / cost optimization — orthogonal.
- Cross-fleet load balancing with scoring — Phase 2b lays the score field; fine-tuning is out of scope.

## Architecture

```
                ┌──────────────────────────────────────┐
                │ department_dispatcher.request_work() │
                └────────────────┬─────────────────────┘
                                 │
                                 ▼
                ┌──────────────────────────────────────┐
                │ orchestration_engine.run()           │
                │  step 6 "GPU" now calls:             │
                │                                      │
                │  ollama_options.build_options(       │
                │      model, target_node, agent,      │
                │      prompt_tokens)                  │
                └────────────────┬─────────────────────┘
                                 │ returns:
                                 │  {model, options{num_gpu,num_ctx,...},
                                 │   keep_alive, target_node_id,
                                 │   placement, reason}
                                 ▼
              ┌──────────────────────────────────────────┐
              │ model_service.ensure_model_ready()       │
              │   (loads model on target_node if needed) │
              └────────────────┬─────────────────────────┘
                               │
                               ▼
              ┌──────────────────────────────────────────┐
              │ POST {node}/api/generate                 │
              │   body includes options + keep_alive     │
              └──────────────────────────────────────────┘
```

### New module

`platform_v2/tools/department_hq/services/ollama_options.py` — follows the post-Project #244 Phase 2 rule that dispatcher-adjacent infra lives under `department_hq/services/`, not `ai_bridge/`. Task #2079's original description specified `ai_bridge/ollama_options.py`; that pre-dates the rename, and `scripts/check_agent_single_writer.py` now blocks new imports from `ai_bridge.bridge_dispatcher`. Co-locating with callers is consistent with `department_dispatcher.py`, `orchestration_engine.py`, `smart_router.py`.

### Retrofit targets

| File | Call sites | Phase 1 retrofit | Notes |
|---|---|---|---|
| `department_dispatcher.py` | ~6 | ✅ | Exact count verified at implementation time |
| `orchestration_engine.py` | ~3 | ✅ | |
| `archie_bridge.py` | ~2 | ❌ defer | Part of ongoing `ai_bridge/` → `services/` migration, out of scope |
| `ai_bridge/agent_loop.py::_ollama_model_health` | 1 | ❌ | Health ping with explicit `num_gpu=0`; unchanged |
| `ai_bridge/knowledge_analyzer.py` | 1 | ❌ defer | Analysis job; separate dispatcher path |

Exact site count confirmed by grep during implementation — helper interface is stable regardless.

### Back-compat

`build_options()` is a new module with no existing imports to break. `target_node=None` defaults to the hub, so Phase 1 callers that pass nothing keep today's topology. When Phase 2a lands, `target_node=None` starts delegating to `select_node()` internally — still no caller signature change.

## Components

### `VramProbeCache` (Phase 1)

Per-node, in-memory, heartbeat-invalidated. Keyed by `(node_id, model_name)`.

```python
class VramProbeCache:
    # In-memory dict guarded by a threading.Lock; no DB persistence.
    _entries: dict[tuple[str, str], ProbeEntry]

    def get_or_probe(self, node: Node, model: str) -> ProbeEntry: ...
    def invalidate_node(self, node_id: str) -> None: ...  # on heartbeat state change
    def invalidate(self, node_id: str, model: str) -> None: ...  # on model pull
```

`ProbeEntry` fields:
- `parameter_count: int` — from `/api/show` `details.parameter_size` parsed (e.g. `"8B"` → 8_000_000_000)
- `quantization: str` — `/api/show` `details.quantization_level` (e.g. `"Q4_K_M"`)
- `estimated_vram_base_gb: float` — `parameter_count * bytes_per_param(quant) * 1.3`
- `context_overhead_per_token_mb: float` — conservative per-Ollama-docs estimate
- `probed_at: datetime`
- `probe_failed: bool` — if `/api/show` errored; helper returns CPU placement conservatively
- `raw_show_response: dict` — archived for debugging

**Quantization → bytes-per-param table**: Q2→1 byte, Q3→1.25, Q4→2, Q5→2.5, Q6→3, Q8→4, fp16→6 (per Ollama docs + empirical measurement). Unknown quant → 4 (worst-case fp32). Refined by telemetry later.

**Cache invalidation triggers**:
- Node heartbeat transition `online → offline` or `offline → online`
- Model-pull job completion (existing lifecycle event)
- Explicit call from ops tooling (`/api/model/refresh` endpoint — out of scope, nice-to-have)
- Soft TTL of 24h as safety net

**No cache size limit** in Phase 1 — cardinality is bounded (~6 nodes × ~30 models = 180 entries max, each <2KB).

### `build_options()` (Phase 1)

```python
def build_options(
    *,
    model: str,
    target_node: Node | None = None,      # None → hub in Phase 1; delegates to select_node() in Phase 2a
    agent: Agent | None = None,           # reserved for per-agent overrides (future)
    prompt_tokens_hint: int = 0,          # caller-estimated input-token count
    keep_alive: str = "5m",               # Decision #440 default
) -> dict:
    """
    Returns:
      {
        "model": str,
        "options": {"num_gpu": int, ...},   # only sets num_gpu; caller merges its own
        "keep_alive": str,
        "target_node_id": str,
        "placement": "gpu" | "cpu",
        "reason": str,
      }
    """
```

**Decision logic (Phase 1, strategy A):**
1. Resolve `target_node` (None → hub).
2. Look up cached `ProbeEntry` (or probe synchronously with 5-second timeout).
3. Compute `required_vram = estimated_vram_base_gb + (prompt_tokens_hint * context_overhead_per_token_mb / 1024)`.
4. Compute `available_vram = node.gpu_vram_gb - VRAM_SAFETY_MARGIN_GB - currently_loaded_other_models_gb`.
   - `VRAM_SAFETY_MARGIN_GB = 0.5` (module-level constant; headroom for Ollama internal buffers; promoted to config later if tuning needed).
   - `currently_loaded_other_models_gb` derived from `/api/ps` `size_vram` field; cached for 5 seconds to avoid per-dispatch HTTP.
5. **If** `probe_failed` **or** `required_vram > available_vram` → set `"num_gpu": 0`, `placement="cpu"`.
6. **Else** → omit `num_gpu` (let Ollama place normally), `placement="gpu"`.

The helper always returns a decision. It never raises for fit questions; raises only on malformed inputs (`ValueError`).

### `select_node()` (Phase 2a — hub-first locality)

```python
def select_node(
    *, capability: str, model: str, fallback_cpu_ok: bool = True
) -> Node:
    """
    Phase 2a: hub-first, fleet-fallback-when-hub-full.
    - Probe hub via build_options(target_node=hub). If placement=="gpu" → return hub.
    - Else scan online fleet nodes (status='online', gpu_available=true,
      ollama_available=true, current_load < max_concurrent) where the model
      is already available OR ensure_model_ready can pull it. First fit wins.
    - If no GPU node fits and fallback_cpu_ok → return hub (CPU placement, flagged).
    - If no GPU node fits and NOT fallback_cpu_ok → raise NoNodeAvailable.
    """
```

Fleet scan order: `ORDER BY priority ASC, current_load ASC`.

### `select_node()` scoring layer (Phase 2b)

Replaces first-fit with a scored selection:

```
score = 0.5 * gpu_fit_ratio                          # 1.0 if exact fit, >1 with headroom
      + 0.3 * (1 - current_load / max_concurrent)
      + 0.2 * latency_bonus(node.avg_latency_ms)     # normalized: 0=bad, 1=good
      + 0.1 * locality_bonus(node == hub)
```

Cache `remote_nodes` state reads for 5 seconds to avoid hammering DB on rapid dispatches.

## Data flow (retrofit pattern)

**Before** (today):
```python
resp = requests.post(
    f"{ollama_host}/api/generate",
    json={"model": model, "prompt": prompt, "stream": False,
          "options": {"num_ctx": 4096, "temperature": 0.2},
          "keep_alive": "5m"},
    timeout=180,
)
```

**After** (Phase 1):
```python
from .ollama_options import build_options

opts = build_options(
    model=model,
    target_node=None,                       # None → hub in Phase 1
    prompt_tokens_hint=_estimate_tokens(prompt),
    keep_alive="5m",
)
resp = requests.post(
    f"{_node_url(opts['target_node_id'])}/api/generate",
    json={
        "model": opts["model"],
        "prompt": prompt,
        "stream": False,
        "options": {**opts["options"], "num_ctx": 4096, "temperature": 0.2},
        "keep_alive": opts["keep_alive"],
    },
    timeout=180,
)
_log_placement(opts, model=model)
```

Caller-supplied `num_ctx`/`temperature`/etc. merge on top of the helper's `options` dict. Caller wins on collisions; helper only sets `num_gpu`.

When Phase 2a lands, `target_node=None` routes through `select_node()` internally — no call-site signature change.

## Observability

### Per-dispatch log line
Every `build_options()` call emits one INFO-level log:
```
placement: node=<node_id> model=<model> placement=<gpu|cpu>
           required_vram=<float>GB available_vram=<float>GB
           reason="<short code>" probe_age_s=<int>
```

### `ollama_placement_telemetry` observer
New observer under the Project #272 5-pillar pattern (planner/runner/verifier/writer/observer). Fires every 5 minutes:
- Counts placements by node × placement bucket
- Flags anomalies (sustained CPU-fallback >50% for >10 min — indicates VRAM pressure or stale probe cache)
- Writes to `autonomy_loop_log` like other observers

### Metrics
Extend `remote_nodes` telemetry read-out in Department HQ Fleet tab: show per-node "GPU utilization %" and "last placement" fields (UI work deferred; data is available).

## Single-writer guardrail

Extend `scripts/check_agent_single_writer.py`:
- **Rule**: Any new `api/generate` or `api/chat` string literal in `tools/department_hq/` or `platform_v2/services/` outside `ollama_options.py` fails lint.
- **Allowlist**: existing deferred sites (`archie_bridge.py` lines X, `knowledge_analyzer.py` line Y, `agent_loop.py::_ollama_model_health`) added with comment referencing their follow-up task IDs.
- **Regression test**: `tests/test_no_raw_api_generate_in_new_code.py` scans the tree and fails if allowlist drifts.

## Error handling

| Failure mode | Helper behavior | Caller sees |
|---|---|---|
| `/api/show` timeout (5s) | `probe_failed=True`, cache with 60s failed-probe TTL, return CPU placement | `placement="cpu"`, `reason="probe_timeout"` |
| `/api/show` malformed JSON | Log ERROR with raw body, cache failed probe 60s, return CPU | `placement="cpu"`, `reason="probe_malformed"` |
| Node offline between dispatch and call | Helper detects `status!='online'`, raises `NodeUnavailable` | Dispatcher catches, falls back (Phase 1: to hub; Phase 2: next-fit node) |
| Model not on node | `ensure_model_ready()` pulls it (existing path); helper returns CPU conservatively for first dispatch | Slow first dispatch, warm thereafter |
| Unknown quantization | Use worst-case `bytes_per_param=4`; CPU fallback likely | `placement="cpu"`, `reason="unknown_quant"` |
| All fleet nodes offline AND hub GPU full (Phase 2) | CPU fallback on hub | `placement="cpu"`, `reason="all_full"` |

**No retry in helper** — pure decision function. Retry remains the dispatcher's concern; smart_router's existing escalation is unchanged.

## Testing

### Phase 1 unit tests (`tests/test_ollama_options.py`)
- `test_build_options_hub_fits` — small model + M4000 fixture → `placement="gpu"`, no `num_gpu` key
- `test_build_options_hub_too_big` — 13B q4 model vs 8GB VRAM → `placement="cpu"`, `num_gpu=0`
- `test_probe_failed_falls_back_to_cpu`
- `test_probe_cache_reuses_entry_within_ttl`
- `test_probe_cache_invalidates_on_node_offline_transition`
- `test_prompt_tokens_hint_pushes_past_vram_threshold`
- `test_unknown_quantization_conservative_fallback`
- `test_caller_supplied_options_override_helper_defaults`
- `test_currently_loaded_models_reduce_available_vram`

### Phase 1 integration tests (gated by `RUN_INTEGRATION=1` env flag)
- Dispatch via retrofitted `department_dispatcher` to small model → verify GPU placement via `/api/ps` (`size_vram > 0`)
- Dispatch via retrofitted dispatcher to model > VRAM → verify CPU placement (`size_vram == 0`)
- End-to-end `dispatch(capability="conversation")` completes and observer log shows correct `reason`

### Phase 2a tests
- `test_select_node_hub_first_when_hub_fits`
- `test_select_node_falls_to_fleet_when_hub_full`
- `test_select_node_returns_hub_cpu_when_no_gpu_node_fits`
- `test_select_node_respects_current_load_against_max_concurrent`
- `test_select_node_raises_when_fallback_cpu_ok_false`

### Phase 2a integration
Two-node test harness using the `responses` library (sync HTTP mock — matches the codebase's `requests`-based I/O) to simulate fleet Ollama endpoints. Real integration deferred until USS-Kytran (RTX 3070) is back online.

### Single-writer guardrail regression
`tests/test_no_raw_api_generate_in_new_code.py` — scans `tools/department_hq/` and `platform_v2/services/` for `api/generate` / `api/chat` string literals outside helper; fails if allowlist drifts.

### Out of scope
- Load / perf tests — helper is O(nodes) per call, not a hot path.
- Failure injection / chaos tests — deferred until Phase 3+.

## Delivery plan

Deliverables split across two PRs, both on this branch family:

### PR 1 — Phase 1 (hub-only helper + retrofit)
- `platform_v2/tools/department_hq/services/ollama_options.py` (new)
- Retrofit `department_dispatcher.py` + `orchestration_engine.py` call sites
- `ollama_placement_telemetry` observer
- Single-writer guardrail + regression test
- `tests/test_ollama_options.py`
- Gated integration tests

### PR 2 — Phase 2a (hub-first locality)
- `select_node()` implementation in `ollama_options.py`
- `build_options(target_node=None)` delegates to `select_node()`
- Additional unit tests + mocked fleet integration tests

Phase 2b (scored selection) files as a separate task after Phase 2a lands — decision gated on having ≥2 online GPU nodes.

## Open questions (to resolve during implementation)

1. **Exact call-site count** in `department_dispatcher.py` and `orchestration_engine.py` — spec says "~6 and ~3", implementation PR will confirm via grep.
2. **Token-estimator for `prompt_tokens_hint`** — is there an existing tokenizer in the codebase, or add a lightweight one? If not, use `len(prompt) // 4` conservative heuristic for Phase 1.
3. **`Node` type source** — is there an existing `Node` dataclass, or use raw dict from `remote_nodes`? Align with fleet_service's convention at implementation time.
4. **Model-pull event hook** — does `model_service.ensure_model_ready()` expose a post-pull hook the cache can listen on, or does the helper poll? Implementation preference.

None are scope-changing; all resolved by reading existing code during PR 1.

## Decisions logged (via `mcp log_decision` after approval)

- Phase 1 + Phase 2 bundled in a single spec; B/C/D fallback strategies deferred to follow-up projects.
- Model VRAM discovered via `/api/show` probe-and-cache, not DB-backed or static config.
- Fallback strategy in scope = A (binary CPU); partial offload and tier-escalation deferred.
- Helper module location: `platform_v2/tools/department_hq/services/ollama_options.py` (not `ai_bridge/`).
- Phase 2a uses hub-first-with-fleet-fallback; Phase 2b adds scoring only once ≥2 GPU nodes online.

## References

- Task #2079 — Dispatcher-level GPU awareness + fleet GPU orchestration
- Project #261 — LLM Resource Management
- Decision #440 — KEEP_ALIVE=5m (Ollama lifecycle default)
- Decision #441 — `bridge_dispatcher` → `department_dispatcher` rename
- `.claude/rules/ai-bridge.md` — current dispatch rules
- `.claude/rules/department-hq-dispatch.md` — post-rename import rules
- `scripts/check_agent_single_writer.py` — guardrail script to extend
