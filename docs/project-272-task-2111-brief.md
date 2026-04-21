# Project #272, Task #2111 — Agent-Driven Test Generation for New Service Functions

**Status:** Scoping brief · 2026-04-21 · not yet implemented
**Source of truth on pieces already shipped:** this doc, audited against code on 2026-04-21
**Intended implementor:** next session (fresh context) or a subagent following this brief

## TL;DR

When a new function lands in `platform_v2/services/*.py` without a matching test in `platform_v2/tests/test_<name>.py`, F.O.R.G.E. should auto-draft a pytest scaffold via Bridge dispatch. The scaffold becomes a Tier-2 proposal → Kytran approves → `improvement_proposals` row → F.O.R.G.E. writes the test file → P.R.O.B.E. verifies pytest passes → merged.

**Same pipeline as #2186** (the misroute adapter) just with a different input signal and a different F.O.R.G.E. capability. **The entire downstream chain — `audit_pipeline.process_audit_findings` → C.R.E.E.D. ethics gate → F.O.R.G.E. fix generation → approval queue → apply → verify — already exists.** Phase 1 is one ~120 LOC detector + one ~60 LOC adapter.

Tagged "large" in the DHQ task list because agent-written tests can be brittle (ghost imports, wrong mocks, flaky asserts). Phase 1 delivers the detection + proposal path; Phase 2 iterates on test quality.

## What's already built

### `audit_pipeline.process_audit_findings` (entry point)

Takes `(module_name, issues_list)` with each issue `{code, severity, file, detail}`. Creates `improvement_proposals` row with `metadata.source='code_health_audit'` and routes through `request_approval`. Already proven via PR #240 — the misroute adapter uses this same funnel.

### F.O.R.G.E. Bridge dispatch

F.O.R.G.E. is the Engineering director. `dispatch_audit_proposals` (audit_pipeline.py:739) picks up pending proposals and dispatches fix generation via Bridge. Today it generates code fixes; with a `capability='test_generation'` tag (routable via `smart_router.CAPABILITY_ROUTING`) it can generate pytest scaffolds using the same path.

### P.R.O.B.E. post-apply verification

`audit_pipeline.verify_fix_deployment` (line 802) runs post-apply. Pair it with `pytest path/to/new_test.py -v` in the same function and P.R.O.B.E. becomes the test executor.

### Test conventions to target (already mature)

- Tests live flat in `platform_v2/tests/` (no `tests/services/` subdirectory)
- `pytest.ini`: `testpaths=tests`, `python_files=test_*.py`
- `conftest.py`: loads Flask app from `/app/app.py`; Flask fixture + test client ready
- `unittest.mock.patch` for pipeline-boundary mocking — pattern demonstrated in `test_misroute_to_proposal_adapter.py` (PR #241), `test_propose_hire.py` (PR #243), `test_forge_triage.py`, `test_approvals_multi_source.py`
- `ai_bridge.agent_loop` import requires the sys.modules stub pattern (see `test_propose_hire.py` lines 17–24)

## The gap — detection

No observer exists today that looks for "new function in services/ lacking a test." Two layers needed:

### 1. AST-based detector (`services/untested_function_detector.py`)

```python
def find_untested_functions(services_dir="platform_v2/services") -> list[dict]:
    """Return a list of public functions without matching tests.

    Walks every .py file in services_dir; for each top-level function
    whose name doesn't start with '_', checks whether ANY file in
    platform_v2/tests/ calls it. Uses AST, not regex — avoids false
    matches on comments/docstrings.

    Returns rows shaped for audit_pipeline.process_audit_findings:
        [{
            "code": "SERVICE_FUNCTION_UNTESTED",
            "severity": "yellow",
            "file": "<relative/path>.py:<function_name>",
            "detail": f"Function {name} in {module} has no tests",
        }, ...]
    """
```

Dedup key via `audit_pipeline._has_open_audit_proposal`:
`(file_path='[service_tests]/services/foo.py:bar', issue_code='SERVICE_FUNCTION_UNTESTED')` — survives forever per function.

### 2. Scheduled adapter (`services/untested_function_adapter.py`)

Mirrors `misroute_to_proposal_adapter.py` — calls detector, caps per-run output (default `MAX_PER_RUN=3`; tests are generated serially so flooding the queue is worse than for observers), hands to `process_audit_findings("[service_tests]", issues)`.

Nightly job at **03:00 UTC** — after F.O.R.G.E. dep drift (03:15) would be fine too; sequence doesn't matter.

### 3. F.O.R.G.E. test-generation capability

New `capability='test_generation'` entry in `smart_router.CAPABILITY_ROUTING` mapped to F.O.R.G.E. as primary + cloud models (Claude Sonnet) as fallback. Prompt template:

```
You are F.O.R.G.E. Generate a pytest test file for the function below.
Conventions:
  - Tests live at platform_v2/tests/test_<module>.py
  - Use unittest.mock.patch for DB and Bridge boundaries
  - For ai_bridge imports, use the sys.modules stub at tests/test_propose_hire.py:17-24
  - Required classes: Test<FunctionName>Validation, Test<FunctionName>HappyPath
  - At least: 1 happy path, 1 error path, 1 edge case
Function source: <AST-extracted source>
Module path: <path>
Existing test style reference: <tests/test_propose_hire.py snippet>
```

## Phase 1 MVP scope

| Step | File | Est LOC |
|------|------|---:|
| Detector | `services/untested_function_detector.py` | 120 |
| Adapter | `services/untested_function_adapter.py` | 60 |
| Nightly job wiring | `ai_bridge/agent_loop.py` (follow the misroute pattern exactly) | 45 |
| Router capability | `tools/department_hq/services/smart_router.py` | 10 |
| Prompt template | `services/forge_test_generation_prompts.py` | 80 |
| Unit tests | `tests/test_untested_function_detector.py`, `tests/test_untested_function_adapter.py` | 200 |

**~515 LOC total**, all on the well-worn pattern. No schema changes.

### Verification

1. First run — detector finds N untested functions, adapter files 3 worst proposals
2. Nightly `dispatch_audit_proposals` picks them up; F.O.R.G.E. generates test scaffolds via Bridge
3. `creed_gate_pre_fix` checks (auto-generated tests are low-risk — expect approval)
4. Proposal hits `pending_approval` → `/api/approvals/pending` surfaces
5. Kytran approves → `improvement_approve` action writes test file + runs pytest
6. `verify_fix_deployment` re-runs pytest; if green, proposal marked `deployed`

## Phase 2 extensions (separate follow-up tasks)

| Extension | Lift |
|-----------|-----:|
| Quality scoring — reject tests without at least 1 error-path assertion | small |
| Iteration — if first pytest run fails, dispatch F.O.R.G.E. again with error output (≤2 retries) | medium |
| Coverage tracking — after first N function-level tests, detect untested branches via `pytest --cov` | medium |
| Cross-module — expand beyond `services/` to `tools/<module>/*.py` | small |

## Risks & gotchas

- **Ghost imports in agent-written tests:** F.O.R.G.E. may hallucinate imports that don't exist. Pre-write-back validation must `python3 -c "import ast; ast.parse(open(f).read())"` BEFORE committing to `improvement_proposals.code_changes`. Hard-fail if import resolution fails.
- **Mocking blind spots:** agent-written tests may patch the wrong module path (e.g. patch at definition site instead of use site). Prompt template must include the `test_propose_hire.py` stub pattern explicitly — it was non-obvious and got resolved through one iteration.
- **DB-touching services:** tests for functions that call `get_db_cursor()` need a mocked cursor (see `test_propose_hire.py::_mock_cursor`). Prompt must reference that helper — or lift it into a shared `tests/test_helpers.py` first.
- **Flaky time-based asserts:** if a service function uses `datetime.now()`, agent may assert a literal timestamp. Prompt must emphasize `unittest.mock.patch` on datetime.
- **Wave risk:** first nightly run against ~95% of `platform_v2/services/` will identify dozens of untested functions. Cap strictly (`MAX_PER_RUN=3`) for the first two weeks; otherwise the approval queue drowns.
- **C.R.E.E.D. ethics gate:** test-file-only changes are low-risk by construction but the gate may still flag them. If false positives > 20%, add a bypass path for `issue_code='SERVICE_FUNCTION_UNTESTED'`.
- **_has_open_audit_proposal dedup:** if a proposal is rejected once, the same function can't get another proposal. That's wrong for tests — F.O.R.G.E. should be able to iterate. Consider a re-propose path after N days for rejected test proposals.

## Proposed subtasks under #272 (or spun out as #276)

| # | Title | Est |
|---|------|----:|
| a | Detector: AST walk services/, cross-reference tests/; returns issue list | 3 hr |
| b | Adapter: calls detector → process_audit_findings (mirrors misroute adapter) | 1 hr |
| c | Nightly job wiring in agent_loop.py | 30 min |
| d | smart_router: add `test_generation` capability → F.O.R.G.E. + Claude cloud fallback | 30 min |
| e | Prompt template + test-style reference docs | 2 hr |
| f | Unit tests for detector + adapter | 3 hr |
| g | End-to-end manual test: pick 1 function, let pipeline generate its test | 1 hr |
| h | (Phase 2) Iteration loop, coverage expansion, cross-module | separate |

## Why F.O.R.G.E. (not a new agent)

F.O.R.G.E. already owns code generation + the audit pipeline fix path. Giving it `test_generation` as an additional capability keeps the ownership chain short: one director, one rules file, same proposal-queue surface. Consistent with the pillar-complete observer pattern used by #2186.

## Rough cost signal

If detector finds ~60 untested public service functions in `platform_v2/services/` (likely), cap at 3/run → 20 runs to cover the set. With Claude Sonnet cloud fallback at ~$0.015 per test generation, full coverage costs well under $5 over 3 weeks. Cloud usage only happens when F.O.R.G.E.'s local model fails — usually first-pass Ollama succeeds.

---

**Authored 2026-04-21 alongside #2113 brief. Both extend the observation → proactive-fix pipeline shipped in PR #240 to new input signals. Implementation deferred to a fresh-context session with the `subagent-driven-development` skill.**
