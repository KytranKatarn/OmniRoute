# Code Health Autonomous Self-Healing (via Department HQ) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the Consciousness → Code Health module real static-analysis "eyes," gate the findings for trust, and run the whole scan → fix → re-scan loop autonomously with every fix routed through the Department HQ dispatcher, orchestration engine, and agent fleet — while the deploy/merge gate stays human.

**Architecture:** Two new services (`code_static_analyzer.py`, `finding_gate.py`) plus a thin orchestrator (`code_health_autoheal.py`) sit *in front of* the existing Repair Bay pipeline. The scanner runs the proven toolchain (AST interface-sweeps + pyflakes/ruff/mypy/pylint/bandit) inside the target's **real container** (faithful runtime). The gate auto-confirms deterministic findings and adversarially verifies judgment findings **through DHQ dispatch**. Confirmed findings enter the *unchanged* pipeline (`process_audit_findings` → `improvement_proposals` → `dispatch_proposal_fix`/`forge_self_heal` → **human deploy** → `reverify_deployed_findings`). A welfare-gated scheduled job drives it nightly.

**Tech Stack:** Python 3.11, Flask, APScheduler (`archie_scheduler` sidecar), psycopg2/Postgres, `docker exec` for faithful runtime, pinned linter virtualenv, the DHQ dispatcher (`tools.department_hq.services.department_dispatcher`).

## Global Constraints

*(Every task's requirements implicitly include this section. Values copied verbatim from CLAUDE.md + `.claude/rules/`.)*

- **All LLM inference goes through the DHQ dispatcher** — `from tools.department_hq.services.department_dispatcher import dispatch, dispatch_json`. NEVER call Ollama directly from a module (ADR-013). The scanner itself is deterministic tooling (no LLM); only the verify + fix-gen steps dispatch.
- **Human deploy/merge gate is unchanged.** Autonomy stops at `fix_generated`/`ready_for_review` and PR creation. Never auto-deploy, never auto-merge, never push to `main`.
- **Faithful runtime only.** Static tools run inside the target container via `docker exec` with the correct `sys.path`. NEVER fall back to a wrong-path host run (that reproduces the false positives this design exists to avoid).
- **Scheduled jobs are welfare-gated + EDT.** New jobs guard on `services.work_control_service.is_enabled(key, default=True)` and use `CronTrigger(..., timezone="America/Toronto")`.
- **Finding dict shape is fixed** (data-shape driven): `{"code": str, "severity": "red"|"yellow"|"info", "file": str, "detail": str}` — this is what `process_audit_findings` consumes.
- **Fail-closed on the gate:** a verify dispatch that errors/times out leaves the finding **advisory**, never auto-CONFIRMED.
- **Mesh IPs only** for any inter-cluster call (`100.64.0.4`), never public hostnames.
- **Feature branch + PR** for every task; commit frequently. `docker compose ... restart archie_scheduler` picks up scheduler changes; `restart archie_platform` picks up route changes.
- **Tests run in the platform container:** `docker exec archie_platform python3 -m pytest ...` with `sys.path` at `/app`.

---

## File Structure

| File | Responsibility |
|---|---|
| `platform_v2/services/code_analysis/__init__.py` | package marker |
| `platform_v2/services/code_analysis/ast_sweeps.py` | the 5 AST interface-sweep checks as pure functions (highest-yield, deterministic) |
| `platform_v2/services/code_static_analyzer.py` | faithful-runtime toolchain runner + per-product runtime registry; emits normalized findings |
| `platform_v2/services/finding_gate.py` | auto-verify trust gate — deterministic auto-confirm; judgment set adversarial-verify via DHQ; routes confirmed→pipeline, else advisory |
| `platform_v2/services/code_health_autoheal.py` | orchestrator: scan → gate → process_audit_findings → dispatch fixes (DHQ) → reverify; the autonomous cycle |
| `platform_v2/services/audit_pipeline.py` | **modify** — add new issue codes to `_ISSUE_CAPABILITY_MAP` + severity to `_TIER_CONFIG` |
| `platform_v2/tools/consciousness/code_health_routes.py` | **modify** — add `POST /api/code-health/deep-scan` |
| `platform_v2/tools/department_hq/jobs.py` | **modify** — register the welfare-gated `code_health_autoheal` scheduled job |
| `platform_v2/tools/department_hq/services/job_registry.py` | **modify** — add the job's catalog entry |
| `platform_v2/tests/test_ast_sweeps.py` | AST-sweep unit tests |
| `platform_v2/tests/test_finding_gate.py` | gate routing/verify tests (stubbed dispatcher) |
| `platform_v2/tests/test_code_static_analyzer.py` | runner tests (fake `docker exec`) + one live integration test |
| `platform_v2/tests/test_code_health_autoheal.py` | cycle orchestration tests (stubbed pipeline) |

---

## Task 1: AST interface-sweep checks

The 5 checks that found 28 of 35 bugs, as pure functions over a parsed module + a resolvable symbol table. Deterministic → these feed the gate's auto-confirm allowlist.

**Files:**
- Create: `platform_v2/services/code_analysis/__init__.py`
- Create: `platform_v2/services/code_analysis/ast_sweeps.py`
- Test: `platform_v2/tests/test_ast_sweeps.py`

**Interfaces:**
- Produces: `sweep_module(path: str, resolver: "SymbolResolver") -> list[dict]` where each dict is `{"code", "severity", "file", "detail", "line"}` with `code` ∈ `{WRONG_ROOT_IMPORT, WRONG_SUBMODULE_IMPORT, MISSING_SYMBOL, WRONG_KWARG, ARITY_MISMATCH}`.
- Produces: `class SymbolResolver` with `module_exists(dotted: str) -> bool`, `symbol_exists(dotted: str, name: str) -> bool`, `signature_of(dotted: str, name: str) -> inspect.Signature | None`. Slice-1 impl resolves against the faithful-runtime import root(s); tests inject a fake.

- [ ] **Step 1: Write the failing tests**

```python
# platform_v2/tests/test_ast_sweeps.py
import textwrap
from services.code_analysis.ast_sweeps import sweep_module, SymbolResolver


class FakeResolver:
    """Deterministic stand-in for the runtime resolver."""
    def __init__(self, modules, symbols, sigs):
        self._m, self._s, self._sig = set(modules), set(symbols), sigs
    def module_exists(self, dotted): return dotted in self._m
    def symbol_exists(self, dotted, name): return (dotted, name) in self._s
    def signature_of(self, dotted, name): return self._sig.get((dotted, name))


def _write(tmp_path, src):
    p = tmp_path / "sample.py"
    p.write_text(textwrap.dedent(src))
    return str(p)


def test_flags_wrong_submodule_import(tmp_path):
    src = "from tools.dev_hq.routes import thing\n"
    path = _write(tmp_path, src)
    r = FakeResolver(modules={"tools.consciousness.devhq_routes"}, symbols=set(), sigs={})
    findings = sweep_module(path, r)
    assert any(f["code"] == "WRONG_SUBMODULE_IMPORT" for f in findings)


def test_does_not_flag_real_submodule_import(tmp_path):
    src = "from tools.consciousness.devhq_routes import thing\n"
    path = _write(tmp_path, src)
    r = FakeResolver(modules={"tools.consciousness.devhq_routes"},
                     symbols={("tools.consciousness.devhq_routes", "thing")}, sigs={})
    findings = sweep_module(path, r)
    assert not any(f["code"] in ("WRONG_SUBMODULE_IMPORT", "MISSING_SYMBOL") for f in findings)


def test_flags_missing_symbol(tmp_path):
    src = "from services.telegram_service import store_knowledge\n"
    path = _write(tmp_path, src)
    r = FakeResolver(modules={"services.telegram_service"}, symbols=set(), sigs={})
    findings = sweep_module(path, r)
    assert any(f["code"] == "MISSING_SYMBOL" for f in findings)


def test_flags_wrong_kwarg_on_known_call(tmp_path):
    src = textwrap.dedent("""
        from services.telegram_service import send_info
        send_info(subject="x", body="y")
    """)
    path = _write(tmp_path, src)
    import inspect
    def send_info(title="", message="", severity="info"): ...
    r = FakeResolver(modules={"services.telegram_service"},
                     symbols={("services.telegram_service", "send_info")},
                     sigs={("services.telegram_service", "send_info"): inspect.signature(send_info)})
    findings = sweep_module(path, r)
    assert any(f["code"] == "WRONG_KWARG" for f in findings)


def test_flags_arity_mismatch(tmp_path):
    src = textwrap.dedent("""
        from services.telegram_service import send_info
        send_info("a", "b", "c", "d")
    """)
    path = _write(tmp_path, src)
    import inspect
    def send_info(title="", message=""): ...
    r = FakeResolver(modules={"services.telegram_service"},
                     symbols={("services.telegram_service", "send_info")},
                     sigs={("services.telegram_service", "send_info"): inspect.signature(send_info)})
    findings = sweep_module(path, r)
    assert any(f["code"] == "ARITY_MISMATCH" for f in findings)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `docker exec archie_platform python3 -m pytest platform_v2/tests/test_ast_sweeps.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'services.code_analysis'`

- [ ] **Step 3: Implement `ast_sweeps.py`**

```python
# platform_v2/services/code_analysis/ast_sweeps.py
"""Deterministic AST interface-sweeps — the checks that found 28/35 bugs
(2026-07-11 session). Pure over (parsed module, SymbolResolver); no I/O here.
The resolver is what makes results faithful — inject the runtime resolver in
production, a fake in tests."""
from __future__ import annotations

import ast
import inspect
from typing import Optional


class SymbolResolver:  # pragma: no cover - production impl lives in code_static_analyzer
    """Interface only; concrete resolver built against the faithful runtime."""
    def module_exists(self, dotted: str) -> bool: raise NotImplementedError
    def symbol_exists(self, dotted: str, name: str) -> bool: raise NotImplementedError
    def signature_of(self, dotted: str, name: str) -> Optional[inspect.Signature]: raise NotImplementedError


def _f(code, sev, path, line, detail):
    return {"code": code, "severity": sev, "file": path, "line": line, "detail": detail}


def sweep_module(path: str, resolver: SymbolResolver) -> list[dict]:
    with open(path, "r", encoding="utf-8") as fh:
        source = fh.read()
    try:
        tree = ast.parse(source, filename=path)
    except SyntaxError as exc:
        return [_f("SYNTAX_ERROR", "red", path, getattr(exc, "lineno", 0), str(exc))]

    findings: list[dict] = []
    imported: dict[str, tuple[str, str]] = {}  # local name -> (module, orig name)

    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            mod = node.module
            if not resolver.module_exists(mod):
                # Wrong submodule (root exists) vs wrong root (nothing resolves)
                root = mod.split(".")[0]
                code = "WRONG_SUBMODULE_IMPORT" if resolver.module_exists(root) else "WRONG_ROOT_IMPORT"
                findings.append(_f(code, "red", path, node.lineno,
                                   f"import from '{mod}' does not resolve in the runtime"))
                continue
            for alias in node.names:
                if alias.name == "*":
                    continue
                if not resolver.symbol_exists(mod, alias.name):
                    findings.append(_f("MISSING_SYMBOL", "red", path, node.lineno,
                                       f"'{alias.name}' is not exported by '{mod}'"))
                else:
                    imported[alias.asname or alias.name] = (mod, alias.name)

    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            ref = imported.get(node.func.id)
            if not ref:
                continue
            sig = resolver.signature_of(*ref)
            if sig is None:
                continue
            findings.extend(_check_call(node, sig, path, node.func.id))

    return findings


def _check_call(node: ast.Call, sig: inspect.Signature, path: str, name: str) -> list[dict]:
    out: list[dict] = []
    params = sig.parameters
    has_var_kw = any(p.kind == p.VAR_KEYWORD for p in params.values())
    has_var_pos = any(p.kind == p.VAR_POSITIONAL for p in params.values())

    if not has_var_kw:
        valid = {n for n, p in params.items()
                 if p.kind in (p.POSITIONAL_OR_KEYWORD, p.KEYWORD_ONLY)}
        for kw in node.keywords:
            if kw.arg and kw.arg not in valid:
                out.append(_f("WRONG_KWARG", "red", path, node.lineno,
                              f"{name}() has no parameter '{kw.arg}'"))

    if not has_var_pos:
        positional_slots = [n for n, p in params.items()
                            if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD)]
        if len(node.args) > len(positional_slots):
            out.append(_f("ARITY_MISMATCH", "red", path, node.lineno,
                          f"{name}() takes {len(positional_slots)} positional args, "
                          f"{len(node.args)} given"))
    return out
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `docker exec archie_platform python3 -m pytest platform_v2/tests/test_ast_sweeps.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: Commit**

```bash
git add platform_v2/services/code_analysis/__init__.py \
        platform_v2/services/code_analysis/ast_sweeps.py \
        platform_v2/tests/test_ast_sweeps.py
git commit -m "feat(code-health): AST interface-sweep checks (wrong-import/symbol/kwarg/arity)"
```

---

## Task 2: Faithful-runtime toolchain runner

Runs the AST sweeps + external linters inside the target's real container and normalizes everything to one finding shape. The runtime registry (a dict for Slice 1) holds the platform target only.

**Files:**
- Create: `platform_v2/services/code_static_analyzer.py`
- Test: `platform_v2/tests/test_code_static_analyzer.py`

**Interfaces:**
- Consumes: `sweep_module`, `SymbolResolver` from Task 1.
- Produces: `run(target: str = "platform", files: list[str] | None = None) -> dict` returning `{"target", "findings": [Finding...], "coverage": {"tools_run": [...], "tools_skipped": [...]}}`. Finding = `{"target","file","line","tool","code","severity","confidence","message","module","capability"}`.
- Produces: `RUNTIME_REGISTRY: dict[str, dict]` — `{target: {"container","app_root","extra_sys_path":[...],"py_version"}}`.
- Produces: `_run_in_runtime(target: str, argv: list[str]) -> subprocess.CompletedProcess` (the single seam mocked in tests).

- [ ] **Step 1: Write the failing tests**

```python
# platform_v2/tests/test_code_static_analyzer.py
import json
import types
import services.code_static_analyzer as csa


def test_registry_has_platform_target():
    t = csa.RUNTIME_REGISTRY["platform"]
    assert t["container"] == "archie_scheduler"
    assert "/app" in t["app_root"] or t["app_root"] == "/app"


def test_run_normalizes_pyflakes(monkeypatch):
    # pyflakes text output -> normalized finding
    def fake_exec(target, argv):
        if "pyflakes" in argv:
            out = "/app/x.py:3:1 undefined name 'foo'\n"
            return types.SimpleNamespace(returncode=1, stdout=out, stderr="")
        return types.SimpleNamespace(returncode=0, stdout="", stderr="")
    monkeypatch.setattr(csa, "_run_in_runtime", fake_exec)
    monkeypatch.setattr(csa, "_run_ast_sweeps", lambda target, files: [])
    res = csa.run("platform", files=["/app/x.py"])
    codes = [f["code"] for f in res["findings"]]
    assert "F821" in codes or "UNDEFINED_NAME" in codes
    assert all(f["target"] == "platform" for f in res["findings"])


def test_tool_crash_is_skipped_not_fatal(monkeypatch):
    def boom(target, argv):
        raise RuntimeError("container down")
    monkeypatch.setattr(csa, "_run_in_runtime", boom)
    monkeypatch.setattr(csa, "_run_ast_sweeps", lambda target, files: [])
    res = csa.run("platform", files=["/app/x.py"])
    assert res["findings"] == []
    assert set(res["coverage"]["tools_skipped"])  # non-empty; nothing raised


def test_ast_sweep_findings_are_tagged(monkeypatch):
    monkeypatch.setattr(csa, "_run_in_runtime",
                        lambda t, a: types.SimpleNamespace(returncode=0, stdout="", stderr=""))
    monkeypatch.setattr(csa, "_run_ast_sweeps", lambda target, files: [
        {"code": "WRONG_KWARG", "severity": "red", "file": "/app/x.py", "line": 2,
         "detail": "send_info() has no parameter 'subject'"}])
    res = csa.run("platform", files=["/app/x.py"])
    f = res["findings"][0]
    assert f["tool"] == "ast_sweep" and f["confidence"] == "high"
    assert f["module"] and f["capability"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `docker exec archie_platform python3 -m pytest platform_v2/tests/test_code_static_analyzer.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'services.code_static_analyzer'`

- [ ] **Step 3: Implement `code_static_analyzer.py`**

```python
# platform_v2/services/code_static_analyzer.py
"""Faithful-runtime static-analysis runner. Runs the AST sweeps + linters INSIDE
the target's real container (correct sys.path) and normalizes findings to the
Code Health shape. Deterministic tooling only — NO LLM here (ADR-013 not engaged).
See docs/superpowers/specs/2026-07-11-code-health-static-analysis-scanner-tier-design.md
"""
from __future__ import annotations

import re
import subprocess
from services.code_analysis.ast_sweeps import sweep_module  # noqa: F401 (used by _run_ast_sweeps)

# --- per-product runtime registry (Slice 1: platform only) --------------------
RUNTIME_REGISTRY: dict[str, dict] = {
    "platform": {
        "container": "archie_scheduler",   # the sidecar that runs the jobs
        "app_root": "/app",                # == platform_v2 inside the container
        "extra_sys_path": ["/mnt/archie_brain/ai_bridge"],  # bare `db`/`external_providers`
        "py_version": "3.11",
    },
}

# Tools whose findings are near-zero false-positive (gate auto-confirms these).
_DETERMINISTIC_TOOLS = {"ast_sweep", "pyflakes", "ruff"}

# path -> (module, capability). Reuse the platform's ownership map if importable.
try:
    from services.code_ownership import resolve_owner  # type: ignore
except Exception:  # pragma: no cover
    def resolve_owner(path: str) -> tuple[str, str]:
        return (_module_from_path(path), _capability_from_path(path))


def _module_from_path(path: str) -> str:
    parts = path.split("/tools/")
    if len(parts) > 1:
        return parts[1].split("/")[0]
    return path.rsplit("/", 1)[-1].replace(".py", "")


def _capability_from_path(path: str) -> str:
    if "/security" in path or "vigil" in path.lower():
        return "security"
    return "code"


def _run_in_runtime(target: str, argv: list[str]) -> subprocess.CompletedProcess:
    """The one seam. Executes `argv` inside the target container. Mocked in tests."""
    cfg = RUNTIME_REGISTRY[target]
    full = ["docker", "exec", cfg["container"]] + argv
    return subprocess.run(full, capture_output=True, text=True, timeout=900)


def _pyflakes(target: str, files: list[str]) -> list[dict]:
    cp = _run_in_runtime(target, ["python3", "-m", "pyflakes", *files])
    out: list[dict] = []
    for line in (cp.stdout or "").splitlines():
        m = re.match(r"(?P<file>[^:]+):(?P<line>\d+):\d*\s*(?P<msg>.+)", line)
        if not m:
            continue
        msg = m.group("msg")
        code = "F821" if "undefined name" in msg else "PYFLAKES"
        out.append({"file": m.group("file"), "line": int(m.group("line")),
                    "tool": "pyflakes", "code": code, "severity": "red",
                    "confidence": "high", "message": msg})
    return out


def _ruff(target: str, files: list[str]) -> list[dict]:
    cp = _run_in_runtime(target, ["python3", "-m", "ruff", "check",
                                  "--select=F", "--output-format=json", *files])
    import json
    out: list[dict] = []
    try:
        rows = json.loads(cp.stdout or "[]")
    except ValueError:
        return out
    for r in rows:
        out.append({"file": r.get("filename", ""), "line": (r.get("location") or {}).get("row", 0),
                    "tool": "ruff", "code": r.get("code", "F"), "severity": "yellow",
                    "confidence": "high", "message": r.get("message", "")})
    return out


def _mypy(target: str, files: list[str]) -> list[dict]:
    cfg = RUNTIME_REGISTRY[target]
    mypypath = ":".join([cfg["app_root"], *cfg["extra_sys_path"]])
    cp = _run_in_runtime(target, [
        "sh", "-c",
        f"MYPYPATH={mypypath} python3 -m mypy --check-untyped-defs "
        f"--follow-imports=silent --explicit-package-bases --ignore-missing-imports "
        f"--python-version={cfg['py_version']} --no-color-output " + " ".join(files)])
    out: list[dict] = []
    for line in (cp.stdout or "").splitlines():
        m = re.match(r"(?P<file>[^:]+):(?P<line>\d+):\s*error:\s*(?P<msg>.+?)\s*\[(?P<code>[\w-]+)\]", line)
        if not m:
            continue
        out.append({"file": m.group("file"), "line": int(m.group("line")),
                    "tool": "mypy", "code": "TYPE_ERROR", "severity": "yellow",
                    "confidence": "medium", "message": f"[{m.group('code')}] {m.group('msg')}"})
    return out


def _pylint(target: str, files: list[str]) -> list[dict]:
    cp = _run_in_runtime(target, ["python3", "-m", "pylint", "-E",
                                  "--disable=import-error", "--output-format=json", *files])
    import json
    out: list[dict] = []
    try:
        rows = json.loads(cp.stdout or "[]")
    except ValueError:
        return out
    for r in rows:
        sym = r.get("symbol", "")
        code = "MISSING_METHOD" if r.get("message-id") == "E1101" else "PYLINT_ERROR"
        out.append({"file": r.get("path", ""), "line": r.get("line", 0),
                    "tool": "pylint", "code": code, "severity": "red",
                    "confidence": "medium", "message": f"{sym}: {r.get('message','')}"})
    return out


def _bandit(target: str, files: list[str]) -> list[dict]:
    cp = _run_in_runtime(target, ["python3", "-m", "bandit", "-f", "json",
                                  "--severity-level", "medium",
                                  "--confidence-level", "medium", *files])
    import json
    out: list[dict] = []
    try:
        rows = json.loads(cp.stdout or "{}").get("results", [])
    except ValueError:
        return out
    for r in rows:
        out.append({"file": r.get("filename", ""), "line": r.get("line_number", 0),
                    "tool": "bandit", "code": "SECURITY_STATIC", "severity": "yellow",
                    "confidence": "medium", "message": r.get("issue_text", "")})
    return out


def _run_ast_sweeps(target: str, files: list[str]) -> list[dict]:
    """Runs the AST sweeps inside the runtime (resolver built against real sys.path).
    Implemented via a small in-container helper the runner ships; returns finding
    dicts with keys {code,severity,file,detail,line}. See Task 2b note below."""
    import json
    cfg = RUNTIME_REGISTRY[target]
    roots = ",".join([cfg["app_root"], *cfg["extra_sys_path"]])
    cp = _run_in_runtime(target, ["python3", "-m", "services.code_analysis.run_sweeps",
                                  "--roots", roots, *files])
    try:
        raw = json.loads(cp.stdout or "[]")
    except ValueError:
        return []
    for f in raw:
        f["tool"] = "ast_sweep"
        f["confidence"] = "high"
    return raw


_TOOLS = [("ast_sweep", _run_ast_sweeps), ("pyflakes", _pyflakes), ("ruff", _ruff),
          ("mypy", _mypy), ("pylint", _pylint), ("bandit", _bandit)]


def run(target: str = "platform", files: list[str] | None = None) -> dict:
    if target not in RUNTIME_REGISTRY:
        raise ValueError(f"unknown scan target: {target}")
    files = files or _discover_files(target)
    findings: list[dict] = []
    ran, skipped = [], []
    for name, fn in _TOOLS:
        try:
            for f in fn(target, files):
                f.setdefault("tool", name)
                f["target"] = target
                mod, cap = resolve_owner(f["file"])
                f["module"], f["capability"] = mod, cap
                findings.append(f)
            ran.append(name)
        except Exception as exc:  # tool crash never fails the whole scan
            skipped.append(f"{name}: {exc}")
    return {"target": target, "findings": findings,
            "coverage": {"tools_run": ran, "tools_skipped": skipped}}


def _discover_files(target: str) -> list[str]:
    """List .py files in the target app_root (in-runtime). Slice 1 keeps it simple."""
    cfg = RUNTIME_REGISTRY[target]
    cp = _run_in_runtime(target, ["sh", "-c",
                                  f"find {cfg['app_root']} -name '*.py' -not -path '*/__pycache__/*'"])
    return [ln for ln in (cp.stdout or "").splitlines() if ln.strip()]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `docker exec archie_platform python3 -m pytest platform_v2/tests/test_code_static_analyzer.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Add the in-runtime sweep helper (`run_sweeps.py`)**

The runner shells `python3 -m services.code_analysis.run_sweeps` inside the target so the resolver binds to the real `sys.path`. Create it:

```python
# platform_v2/services/code_analysis/run_sweeps.py
"""In-runtime entrypoint: builds a SymbolResolver against the live sys.path and
runs the AST sweeps. Prints JSON findings to stdout. Runs INSIDE the target
container (correct import environment) — that is what makes results faithful."""
import argparse, importlib, inspect, json, sys
from services.code_analysis.ast_sweeps import sweep_module, SymbolResolver


class RuntimeResolver(SymbolResolver):
    def module_exists(self, dotted):
        try:
            importlib.import_module(dotted); return True
        except Exception:
            return False
    def symbol_exists(self, dotted, name):
        try:
            return hasattr(importlib.import_module(dotted), name)
        except Exception:
            return False
    def signature_of(self, dotted, name):
        try:
            obj = getattr(importlib.import_module(dotted), name)
            return inspect.signature(obj)
        except (ValueError, TypeError, Exception):
            return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--roots", default="")
    ap.add_argument("files", nargs="*")
    ns = ap.parse_args()
    for root in filter(None, ns.roots.split(",")):
        if root not in sys.path:
            sys.path.insert(0, root)
    resolver = RuntimeResolver()
    out = []
    for path in ns.files:
        try:
            out.extend(sweep_module(path, resolver))
        except Exception as exc:  # a bad file never kills the batch
            out.append({"code": "SWEEP_ERROR", "severity": "info",
                        "file": path, "line": 0, "detail": str(exc)})
    print(json.dumps(out))


if __name__ == "__main__":
    main()
```

- [ ] **Step 6: Live integration smoke (faithful runtime)**

Run: `docker exec archie_scheduler python3 -m services.code_analysis.run_sweeps --roots /app,/mnt/archie_brain/ai_bridge /app/tools/department_hq/jobs.py`
Expected: prints `[]` or a JSON list (proves the in-container resolver + import roots work). If it errors with `No module named services.code_analysis`, the scheduler image needs the new package — note it for Task 8's deploy step.

- [ ] **Step 7: Commit**

```bash
git add platform_v2/services/code_static_analyzer.py \
        platform_v2/services/code_analysis/run_sweeps.py \
        platform_v2/tests/test_code_static_analyzer.py
git commit -m "feat(code-health): faithful-runtime static-analysis toolchain runner"
```

---

## Task 3: Auto-verify finding gate

Encodes the session's triage discipline: deterministic tools auto-confirm; judgment tools are adversarially verified **through DHQ dispatch**; unverified stays advisory (fail-closed).

**Files:**
- Create: `platform_v2/services/finding_gate.py`
- Test: `platform_v2/tests/test_finding_gate.py`

**Interfaces:**
- Consumes: normalized findings from `code_static_analyzer.run(...)["findings"]`; the DHQ `dispatch` function.
- Produces: `gate(findings: list[dict], dispatcher=None) -> {"confirmed": [...], "advisory": [...]}`. `dispatcher` defaults to the real DHQ `dispatch`; tests inject a stub.

- [ ] **Step 1: Write the failing tests**

```python
# platform_v2/tests/test_finding_gate.py
import services.finding_gate as fg


def _find(tool, code, conf="high"):
    return {"tool": tool, "code": code, "confidence": conf, "file": "/app/x.py",
            "line": 1, "severity": "red", "message": "m", "module": "dept",
            "capability": "code", "target": "platform"}


def test_deterministic_findings_auto_confirm_without_dispatch():
    called = {"n": 0}
    def stub_dispatch(**kw):
        called["n"] += 1
        raise AssertionError("should not dispatch for deterministic findings")
    res = fg.gate([_find("ast_sweep", "WRONG_KWARG"), _find("pyflakes", "F821"),
                   _find("ruff", "F401")], dispatcher=stub_dispatch)
    assert len(res["confirmed"]) == 3
    assert called["n"] == 0


def test_judgment_finding_confirmed_when_verifier_says_real():
    class R:  # mimics DispatchResult
        success = True
        response = "CONFIRMED: send_info is called with 4 positional args but takes 2"
    res = fg.gate([_find("bandit", "SECURITY_STATIC", conf="medium")],
                  dispatcher=lambda **kw: R())
    assert len(res["confirmed"]) == 1 and not res["advisory"]


def test_judgment_finding_advisory_when_verifier_says_false_positive():
    class R:
        success = True
        response = "FALSE-POSITIVE: parameterized query, not injectable"
    res = fg.gate([_find("bandit", "SECURITY_STATIC", conf="medium")],
                  dispatcher=lambda **kw: R())
    assert not res["confirmed"] and len(res["advisory"]) == 1


def test_verify_error_is_fail_closed_advisory():
    def boom(**kw):
        raise RuntimeError("dispatch down")
    res = fg.gate([_find("mypy", "TYPE_ERROR", conf="medium")], dispatcher=boom)
    assert not res["confirmed"] and len(res["advisory"]) == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `docker exec archie_platform python3 -m pytest platform_v2/tests/test_finding_gate.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'services.finding_gate'`

- [ ] **Step 3: Implement `finding_gate.py`**

```python
# platform_v2/services/finding_gate.py
"""Auto-verify trust gate for static-analysis findings. Deterministic tools
auto-confirm; judgment findings are adversarially verified THROUGH DHQ dispatch
(the owning agent must NAME the concrete failure or it stays advisory). Fail-closed:
any verify error leaves the finding advisory, never auto-confirmed."""
from __future__ import annotations

import logging

log = logging.getLogger(__name__)

# Near-zero false-positive tools/codes -> auto-confirm (no LLM).
_DETERMINISTIC_TOOLS = {"ast_sweep", "pyflakes", "ruff"}
_DETERMINISTIC_CODES = {"F821", "WRONG_ROOT_IMPORT", "WRONG_SUBMODULE_IMPORT",
                        "MISSING_SYMBOL", "WRONG_KWARG", "ARITY_MISMATCH"}

_VERIFY_SYSTEM = (
    "You are verifying a static-analysis finding. Decide if it is a REAL runtime "
    "bug. Default to FALSE-POSITIVE unless you can name the concrete failure "
    "(inputs -> wrong output/crash). Reply starting with exactly 'CONFIRMED:' or "
    "'FALSE-POSITIVE:' then one sentence.")


def _is_deterministic(f: dict) -> bool:
    return f.get("tool") in _DETERMINISTIC_TOOLS or f.get("code") in _DETERMINISTIC_CODES


def _default_dispatcher(**kwargs):
    from tools.department_hq.services.department_dispatcher import dispatch
    return dispatch(**kwargs)


def _verify(f: dict, dispatcher) -> bool:
    prompt = (f"Finding from {f['tool']} [{f['code']}] at {f['file']}:{f.get('line')}\n"
              f"{f.get('message') or f.get('detail','')}\n\n"
              "Is this a real runtime bug? Prove it or reject it.")
    try:
        result = dispatcher(capability=f.get("capability", "code"),
                            prompt=prompt, module_id="finding_gate",
                            system_prompt=_VERIFY_SYSTEM)
        if not getattr(result, "success", False):
            return False
        return (getattr(result, "response", "") or "").strip().upper().startswith("CONFIRMED")
    except Exception as exc:  # fail-closed
        log.warning("finding_gate verify error (advisory): %s", exc)
        return False


def gate(findings: list[dict], dispatcher=None) -> dict:
    dispatcher = dispatcher or _default_dispatcher
    confirmed, advisory = [], []
    for f in findings:
        if _is_deterministic(f):
            confirmed.append({**f, "verified_by": "deterministic"})
        elif _verify(f, dispatcher):
            confirmed.append({**f, "verified_by": "dhq_adversarial"})
        else:
            advisory.append({**f, "advisory": True})
    return {"confirmed": confirmed, "advisory": advisory}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `docker exec archie_platform python3 -m pytest platform_v2/tests/test_finding_gate.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add platform_v2/services/finding_gate.py platform_v2/tests/test_finding_gate.py
git commit -m "feat(code-health): auto-verify finding gate (deterministic + DHQ adversarial verify)"
```

---

## Task 4: Register new issue codes in the pipeline

Map the new codes to owning capability + severity tier so confirmed findings become correctly-routed Repair Bay proposals.

**Files:**
- Modify: `platform_v2/services/audit_pipeline.py` (`_ISSUE_CAPABILITY_MAP` ~L573, `_TIER_CONFIG` ~L277)
- Test: `platform_v2/tests/test_audit_pipeline_codes.py`

**Interfaces:**
- Consumes: the confirmed finding's `code` (`WRONG_ROOT_IMPORT`, `WRONG_SUBMODULE_IMPORT`, `MISSING_SYMBOL`, `MISSING_METHOD`, `WRONG_KWARG`, `ARITY_MISMATCH`, `TYPE_ERROR`, `SECURITY_STATIC`).
- Produces: pipeline routes imports/symbols/arity/type → `code` (F.O.R.G.E.), security → `vulnerability_scan` (V.I.G.I.L.).

- [ ] **Step 1: Write the failing test**

```python
# platform_v2/tests/test_audit_pipeline_codes.py
from services.audit_pipeline import _ISSUE_CAPABILITY_MAP


def test_new_static_codes_are_mapped():
    assert _ISSUE_CAPABILITY_MAP["WRONG_SUBMODULE_IMPORT"] == "code"
    assert _ISSUE_CAPABILITY_MAP["MISSING_SYMBOL"] == "code"
    assert _ISSUE_CAPABILITY_MAP["WRONG_KWARG"] == "code"
    assert _ISSUE_CAPABILITY_MAP["ARITY_MISMATCH"] == "code"
    assert _ISSUE_CAPABILITY_MAP["MISSING_METHOD"] == "code"
    assert _ISSUE_CAPABILITY_MAP["TYPE_ERROR"] == "code"
    assert _ISSUE_CAPABILITY_MAP["SECURITY_STATIC"] == "vulnerability_scan"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker exec archie_platform python3 -m pytest platform_v2/tests/test_audit_pipeline_codes.py -v`
Expected: FAIL — `KeyError: 'WRONG_SUBMODULE_IMPORT'`

- [ ] **Step 3: Read the current maps, then add the entries**

First confirm the exact dict literals:
Run: `docker exec archie_platform python3 -c "import sys; sys.path.insert(0,'/app'); import services.audit_pipeline as a; print(a._ISSUE_CAPABILITY_MAP)"`

Then edit `platform_v2/services/audit_pipeline.py` — extend `_ISSUE_CAPABILITY_MAP` (keep existing entries) with:

```python
    # Static-analysis scanner tier (Slice 1, 2026-07-11)
    "WRONG_ROOT_IMPORT": "code",
    "WRONG_SUBMODULE_IMPORT": "code",
    "MISSING_SYMBOL": "code",
    "MISSING_METHOD": "code",
    "WRONG_KWARG": "code",
    "ARITY_MISMATCH": "code",
    "TYPE_ERROR": "code",
    "SECURITY_STATIC": "vulnerability_scan",
```

If `_TIER_CONFIG` gates which severities create proposals, confirm `red`/`yellow` are both present (they are — `info` is the only skipped tier). No change needed unless the new codes must be forced to a tier; they carry their own `severity` from the finding.

- [ ] **Step 4: Run test to verify it passes**

Run: `docker exec archie_platform python3 -m pytest platform_v2/tests/test_audit_pipeline_codes.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add platform_v2/services/audit_pipeline.py platform_v2/tests/test_audit_pipeline_codes.py
git commit -m "feat(code-health): map static-analysis issue codes to owning capability"
```

---

## Task 5: Deep-Scan endpoint

A manual/MCP trigger for the whole scanner→gate→pipeline path, on the existing async `bridge_jobs` pattern.

**Files:**
- Modify: `platform_v2/tools/consciousness/code_health_routes.py` (add route inside `register_code_health_routes`, ~L302; reuse `_ch_async_job` ~L19)
- Test: `platform_v2/tests/test_deep_scan_route.py`

**Interfaces:**
- Consumes: `code_static_analyzer.run`, `finding_gate.gate`, `audit_pipeline.process_audit_findings`.
- Produces: `POST /api/code-health/deep-scan {target?}` → `{job_id}`; poll existing `GET /job-status/<id>`.

- [ ] **Step 1: Write the failing test**

```python
# platform_v2/tests/test_deep_scan_route.py
import importlib


def test_deep_scan_orchestrator_confirms_and_submits(monkeypatch):
    mod = importlib.import_module("tools.consciousness.code_health_routes")
    # the pure worker function the route wraps in _ch_async_job
    monkeypatch.setattr(mod, "_static_run",
                        lambda target: {"findings": [{"code": "WRONG_KWARG", "severity": "red",
                                                       "file": "/app/x.py", "detail": "d",
                                                       "tool": "ast_sweep", "module": "m",
                                                       "capability": "code"}],
                                        "coverage": {"tools_run": ["ast_sweep"], "tools_skipped": []}})
    monkeypatch.setattr(mod, "_gate_findings",
                        lambda findings: {"confirmed": findings, "advisory": []})
    captured = {}
    monkeypatch.setattr(mod, "_submit_confirmed",
                        lambda module_name, issues: captured.setdefault("issues", issues) or
                        {"proposals_created": len(issues)})
    result = mod._deep_scan_worker("platform")
    assert result["confirmed"] == 1
    assert captured["issues"][0]["code"] == "WRONG_KWARG"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker exec archie_platform python3 -m pytest platform_v2/tests/test_deep_scan_route.py -v`
Expected: FAIL — `AttributeError: module ... has no attribute '_deep_scan_worker'`

- [ ] **Step 3: Implement the worker + route**

Add near the top of `code_health_routes.py` (thin seams so the worker is unit-testable):

```python
def _static_run(target):
    from services.code_static_analyzer import run as _run
    return _run(target)

def _gate_findings(findings):
    from services.finding_gate import gate as _gate
    return _gate(findings)

def _submit_confirmed(module_name, issues):
    from services.audit_pipeline import process_audit_findings
    return process_audit_findings(module_name, issues)

def _deep_scan_worker(target="platform"):
    scan = _static_run(target)
    gated = _gate_findings(scan["findings"])
    # group confirmed findings by module -> one process_audit_findings call each
    by_mod = {}
    for f in gated["confirmed"]:
        by_mod.setdefault(f.get("module") or target, []).append(
            {"code": f["code"], "severity": f["severity"], "file": f["file"],
             "detail": f.get("message") or f.get("detail", "")})
    created = 0
    for module_name, issues in by_mod.items():
        created += (_submit_confirmed(module_name, issues) or {}).get("proposals_created", 0)
    return {"confirmed": len(gated["confirmed"]), "advisory": len(gated["advisory"]),
            "proposals_created": created, "coverage": scan["coverage"]}
```

Then register the route inside `register_code_health_routes(bp, admin_required)`:

```python
    @bp.route("/api/code-health/deep-scan", methods=["POST"])
    @login_required
    @admin_required
    def code_health_deep_scan():
        from flask import request, jsonify
        target = (request.get_json(silent=True) or {}).get("target", "platform")
        job_id = _ch_async_job("deep_scan", f"Deep static-analysis scan: {target}",
                               total_steps=4, work_fn=lambda: _deep_scan_worker(target))
        return jsonify({"job_id": job_id}), 202
```

(Confirm `_ch_async_job`'s exact signature at L19 and match it; the `work_fn` returns the worker result which the job records.)

- [ ] **Step 4: Run test to verify it passes**

Run: `docker exec archie_platform python3 -m pytest platform_v2/tests/test_deep_scan_route.py -v`
Expected: PASS

- [ ] **Step 5: Deploy route + live smoke**

```bash
docker compose -f /mnt/archie_brain/docker-compose.yml restart archie_platform
```
Then (admin session or internal alias) POST `/api/code-health/deep-scan {"target":"platform"}` and poll `/job-status/<id>` until it reports `confirmed`/`proposals_created`.

- [ ] **Step 6: Commit**

```bash
git add platform_v2/tools/consciousness/code_health_routes.py platform_v2/tests/test_deep_scan_route.py
git commit -m "feat(code-health): POST /deep-scan (static analysis -> gate -> pipeline)"
```

---

## Task 6: Autonomous heal-cycle orchestrator

One function that runs the full loop and **dispatches every fix through DHQ**, leaving deploy human-gated. This is the object the scheduled job calls.

**Files:**
- Create: `platform_v2/services/code_health_autoheal.py`
- Test: `platform_v2/tests/test_code_health_autoheal.py`

**Interfaces:**
- Consumes: `_deep_scan_worker` (Task 5) OR the same seams; `audit_pipeline.dispatch_audit_proposals`, `audit_pipeline.reverify_deployed_findings`.
- Produces: `run_autoheal_cycle(target="platform", max_fixes=10) -> dict` = `{"scanned","confirmed","advisory","proposals_created","fixes_dispatched","reverified"}`.

- [ ] **Step 1: Write the failing test**

```python
# platform_v2/tests/test_code_health_autoheal.py
import services.code_health_autoheal as ah


def test_cycle_scans_gates_dispatches_and_reverifies(monkeypatch):
    monkeypatch.setattr(ah, "_deep_scan",
                        lambda target: {"confirmed": 2, "advisory": 1, "proposals_created": 2,
                                        "coverage": {"tools_run": ["ast_sweep"], "tools_skipped": []}})
    calls = {"dispatch": 0, "reverify": 0}
    monkeypatch.setattr(ah, "_dispatch_fixes",
                        lambda limit: calls.__setitem__("dispatch", limit) or {"dispatched": limit})
    monkeypatch.setattr(ah, "_reverify",
                        lambda: calls.__setitem__("reverify", 1) or {"fixed": 1, "still_open": 0})
    res = ah.run_autoheal_cycle(target="platform", max_fixes=5)
    assert res["proposals_created"] == 2
    assert res["fixes_dispatched"] == 5      # dispatch_audit_proposals(limit=max_fixes)
    assert res["reverified"]["fixed"] == 1
    assert calls["dispatch"] == 5 and calls["reverify"] == 1


def test_cycle_never_deploys(monkeypatch):
    # guard: the orchestrator must not import/call any deploy function
    import inspect
    src = inspect.getsource(ah)
    assert "deploy_to_production" not in src
    assert "deploy_via_merge" not in src
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker exec archie_platform python3 -m pytest platform_v2/tests/test_code_health_autoheal.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'services.code_health_autoheal'`

- [ ] **Step 3: Implement `code_health_autoheal.py`**

```python
# platform_v2/services/code_health_autoheal.py
"""Autonomous Code Health heal cycle. Chains: deep static scan -> auto-verify gate
-> Repair Bay proposals -> DHQ fix dispatch (F.O.R.G.E./V.I.G.I.L.) -> reverify.
Deploy/merge is DELIBERATELY NOT here — it stays human-gated. Called by the
welfare-gated scheduled job."""
from __future__ import annotations

import logging

log = logging.getLogger(__name__)


def _deep_scan(target: str) -> dict:
    from tools.consciousness.code_health_routes import _deep_scan_worker
    return _deep_scan_worker(target)


def _dispatch_fixes(limit: int) -> dict:
    # dispatch_audit_proposals -> per proposal dispatch_proposal_fix ->
    # get_dispatcher().request_work(...) — the DHQ path. Returns a summary dict.
    from services.audit_pipeline import dispatch_audit_proposals
    return dispatch_audit_proposals(limit=limit)


def _reverify() -> dict:
    from services.audit_pipeline import reverify_deployed_findings
    return reverify_deployed_findings()


def run_autoheal_cycle(target: str = "platform", max_fixes: int = 10) -> dict:
    scan = _deep_scan(target)
    dispatched = {}
    if scan.get("proposals_created", 0) > 0:
        dispatched = _dispatch_fixes(max_fixes)   # DHQ fix generation, human deploy after
    reverified = _reverify()
    result = {"scanned": target,
              "confirmed": scan.get("confirmed", 0),
              "advisory": scan.get("advisory", 0),
              "proposals_created": scan.get("proposals_created", 0),
              "fixes_dispatched": (dispatched or {}).get("dispatched", max_fixes if dispatched else 0),
              "reverified": reverified,
              "coverage": scan.get("coverage", {})}
    log.info("autoheal cycle complete: %s", result)
    return result
```

*(Confirm `dispatch_audit_proposals`'s return shape at `audit_pipeline.py` L870 and adapt the `dispatched` extraction to its real keys — the test pins the contract; match it in the source.)*

- [ ] **Step 4: Run test to verify it passes**

Run: `docker exec archie_platform python3 -m pytest platform_v2/tests/test_code_health_autoheal.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add platform_v2/services/code_health_autoheal.py platform_v2/tests/test_code_health_autoheal.py
git commit -m "feat(code-health): autonomous heal-cycle orchestrator (DHQ fix dispatch, human deploy)"
```

---

## Task 7: Welfare-gated scheduled job

Drive the cycle nightly on the `archie_scheduler` sidecar, off by default until proven, toggleable via work-control.

**Files:**
- Modify: `platform_v2/tools/department_hq/jobs.py` (add handler + register in `register_department_hq_jobs` ~L614)
- Modify: `platform_v2/tools/department_hq/services/job_registry.py` (catalog entry)
- Test: `platform_v2/tests/test_autoheal_job.py`

**Interfaces:**
- Consumes: `code_health_autoheal.run_autoheal_cycle`, `services.work_control_service.is_enabled`.
- Produces: job id `agent_code_health_autoheal`, work-control key `agent_code_health_autoheal` (default OFF).

- [ ] **Step 1: Write the failing test**

```python
# platform_v2/tests/test_autoheal_job.py
import tools.department_hq.jobs as jobs


def test_autoheal_job_respects_work_control(monkeypatch):
    ran = {"n": 0}
    monkeypatch.setattr(jobs, "is_enabled", lambda key, default=True: False)
    monkeypatch.setattr("services.code_health_autoheal.run_autoheal_cycle",
                        lambda **kw: ran.__setitem__("n", ran["n"] + 1))
    jobs.code_health_autoheal_job()
    assert ran["n"] == 0  # disabled -> no run


def test_autoheal_job_runs_when_enabled(monkeypatch):
    ran = {"n": 0}
    monkeypatch.setattr(jobs, "is_enabled", lambda key, default=True: True)
    monkeypatch.setattr("services.code_health_autoheal.run_autoheal_cycle",
                        lambda **kw: ran.__setitem__("n", ran["n"] + 1) or {"ok": True})
    jobs.code_health_autoheal_job()
    assert ran["n"] == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker exec archie_platform python3 -m pytest platform_v2/tests/test_autoheal_job.py -v`
Expected: FAIL — `AttributeError: module ... has no attribute 'code_health_autoheal_job'`

- [ ] **Step 3: Add the handler + registration**

In `jobs.py` (ensure `from services.work_control_service import is_enabled` is imported — it is at L674; move to module top if needed):

```python
def code_health_autoheal_job():
    """Nightly autonomous Code Health heal cycle (scan->gate->DHQ fix->reverify).
    Deploy stays human-gated. OFF by default; toggle via work-control key
    'agent_code_health_autoheal'."""
    if not is_enabled("agent_code_health_autoheal", default=False):
        return
    from services.code_health_autoheal import run_autoheal_cycle
    return run_autoheal_cycle(target="platform", max_fixes=10)
```

In `register_department_hq_jobs(scheduler, flask_app)` (~L614), add beside the existing `agent_code_health_scan` registration:

```python
    scheduler.add_job(
        code_health_autoheal_job,
        trigger=CronTrigger(hour=3, minute=30, timezone="America/Toronto"),  # after the 2AM scan
        id="agent_code_health_autoheal",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
```

In `job_registry.py` add the catalog entry (match the existing dict shape):

```python
    "agent_code_health_autoheal": {
        "department": "Engineering & Technology",
        "director": "F.O.R.G.E.",
        "description": "Autonomous Code Health heal cycle: static scan -> gate -> DHQ fix -> reverify (deploy human-gated)",
        "interval": "daily 03:30 ET",
        "source_file": "tools/department_hq/jobs.py",
    },
```

- [ ] **Step 4: Run test to verify it passes**

Run: `docker exec archie_platform python3 -m pytest platform_v2/tests/test_autoheal_job.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Deploy to the scheduler + verify registration**

```bash
docker compose -f /mnt/archie_brain/docker-compose.yml restart archie_scheduler
docker logs archie_scheduler 2>&1 | grep -i "agent_code_health_autoheal" | tail -3
```
Expected: the job registers with no import error. (It's OFF by default, so it won't run until `set_enabled("agent_code_health_autoheal", True)`.)

- [ ] **Step 6: Commit**

```bash
git add platform_v2/tools/department_hq/jobs.py \
        platform_v2/tools/department_hq/services/job_registry.py \
        platform_v2/tests/test_autoheal_job.py
git commit -m "feat(code-health): welfare-gated nightly autoheal job (off by default)"
```

---

## Task 8: Scanner tool env in the scheduler runtime + end-to-end integration

The runner shells `python3 -m mypy/ruff/...` inside `archie_scheduler`; those must exist there, and the new `services.code_analysis` package must be importable in-runtime.

**Files:**
- Modify: `requirements.txt` (or a scanner requirements file) — pin `mypy`, `pyflakes`, `ruff`, `pylint`, `bandit`
- Modify: the scheduler image build (Dockerfile / compose `archie_scheduler`) — install the pinned scanner deps
- Test: `platform_v2/tests/test_deep_scan_integration.py` (marked slow/live)

**Interfaces:**
- Consumes: everything above.
- Produces: a proven end-to-end path on the live platform target.

- [ ] **Step 1: Pin the linters**

Add to `requirements.txt` (versions matching what the session used; verify current):

```
mypy==1.11.2
pyflakes==3.2.0
ruff==0.6.9
pylint==3.2.7
bandit==1.7.9
```

- [ ] **Step 2: Ensure they're in the scheduler image**

Confirm `archie_scheduler` builds from the same image/requirements as `archie_platform` (it mirrors the platform). If it uses the same Dockerfile, the pin above suffices. If separate, add the install line. Rebuild:

```bash
docker compose -f /mnt/archie_brain/docker-compose.yml up -d --build archie_scheduler
```

- [ ] **Step 3: Verify tools + package resolve in-runtime**

```bash
docker exec archie_scheduler python3 -c "import mypy, pyflakes, ruff, pylint, bandit; print('linters ok')"
docker exec archie_scheduler python3 -c "import services.code_analysis.run_sweeps; print('pkg ok')"
```
Expected: both print ok. If `pkg ok` fails, the new package isn't in the scheduler's `/app` — rebuild (Task 8 Step 2) rather than restart.

- [ ] **Step 4: Write the live integration test**

```python
# platform_v2/tests/test_deep_scan_integration.py
import pytest
from services.code_static_analyzer import run


@pytest.mark.slow
def test_platform_target_scan_returns_coverage():
    res = run("platform", files=["/app/tools/department_hq/jobs.py"])
    assert res["target"] == "platform"
    assert "ast_sweep" in res["coverage"]["tools_run"]
    # jobs.py was cleaned this session -> expect no red import/arity findings
    reds = [f for f in res["findings"]
            if f["code"] in ("WRONG_SUBMODULE_IMPORT", "MISSING_SYMBOL", "ARITY_MISMATCH")]
    assert reds == [], f"unexpected regressions: {reds}"
```

- [ ] **Step 5: Run the live integration test**

Run: `docker exec archie_scheduler python3 -m pytest platform_v2/tests/test_deep_scan_integration.py -v -m slow`
Expected: PASS — proves the faithful runtime works end-to-end and the session's cleanups hold.

- [ ] **Step 6: Seed-a-bug regression proof (optional but recommended)**

Temporarily reintroduce one known session bug in a scratch file, deep-scan, confirm it's flagged + becomes a proposal, then remove it. This is the "the 35 bugs would now be caught" guarantee.

- [ ] **Step 7: Commit**

```bash
git add requirements.txt platform_v2/tests/test_deep_scan_integration.py
git commit -m "chore(code-health): pin scanner linters in scheduler runtime + live integration test"
```

---

## Task 9 (optional deeper autonomy): route heavy fixes through the engine build_loop

For fixes that need a real build+test+PR (not just a diff), hand confirmed proposals to the `archie_engine` `pull_repair_work` path, which already runs coordinate→build→test→PR via DHQ F.O.R.G.E. and **never merges**. This upgrades "fix_generated diff" to "tested PR awaiting human merge" without changing the merge gate.

**Files:**
- Read first: `/mnt/standalone/archie-code/archie_engine/build_loop.py` (`pull_and_build`, `pull_repair_work`), `hub/inbound.py`
- Modify: `platform_v2/services/code_health_autoheal.py` — add an opt-in `engine_build=False` param that, when true, notifies the engine to pull the newly-created proposals
- Test: `platform_v2/tests/test_autoheal_engine_handoff.py`

**Interfaces:**
- Consumes: the engine's inbound `POST /api/dispatch` (port 9091, header `X-Node-API-Key`) OR the existing `pull_repair_work` ws command.
- Produces: `run_autoheal_cycle(..., engine_build=False)`; when true, a fire-and-forget engine trigger after proposals are created. Default keeps current diff-only behavior.

- [ ] **Step 1: Confirm the engine pull contract**

Run: `docker exec archie_engine sh -c "grep -n 'pull_repair_work\|pull_and_build\|def dispatch' /app/archie_engine/build_loop.py /app/archie_engine/hub/inbound.py"` (adjust path to the container's app root).
Read the handler to learn exactly what payload/verb triggers a pull. Record the contract in this task before coding.

- [ ] **Step 2: Write the failing test (stubbed trigger)**

```python
# platform_v2/tests/test_autoheal_engine_handoff.py
import services.code_health_autoheal as ah


def test_engine_build_off_by_default(monkeypatch):
    triggered = {"n": 0}
    monkeypatch.setattr(ah, "_deep_scan", lambda t: {"confirmed": 1, "advisory": 0,
                                                     "proposals_created": 1, "coverage": {}})
    monkeypatch.setattr(ah, "_dispatch_fixes", lambda limit: {"dispatched": limit})
    monkeypatch.setattr(ah, "_reverify", lambda: {"fixed": 0, "still_open": 0})
    monkeypatch.setattr(ah, "_trigger_engine_build",
                        lambda: triggered.__setitem__("n", triggered["n"] + 1))
    ah.run_autoheal_cycle(target="platform")            # default: no engine build
    assert triggered["n"] == 0
    ah.run_autoheal_cycle(target="platform", engine_build=True)
    assert triggered["n"] == 1
```

- [ ] **Step 3: Add `_trigger_engine_build` + param**

```python
def _trigger_engine_build():
    """Fire-and-forget: ask the archie_engine to pull newly-created Repair Bay
    proposals and run build->test->PR (DHQ F.O.R.G.E.; NEVER merges). Engine
    reached over the mesh; failure is non-fatal (diffs already generated)."""
    import logging, requests
    try:
        requests.post("http://archie_engine:9091/api/dispatch",
                      json={"command": "pull_repair_work"},
                      headers={"X-Node-API-Key": _engine_key()}, timeout=5)
    except Exception as exc:  # non-fatal
        logging.getLogger(__name__).warning("engine build trigger failed: %s", exc)
```

Add `engine_build: bool = False` to `run_autoheal_cycle` and call `_trigger_engine_build()` after `_dispatch_fixes` when true. `_engine_key()` reads `os.getenv("NODE_API_KEY")`/`INTERNAL_API_KEY`.
(Match the real verb/payload discovered in Step 1 — the `{"command": "pull_repair_work"}` above is the placeholder to replace with the confirmed contract.)

- [ ] **Step 4: Run test to verify it passes**

Run: `docker exec archie_platform python3 -m pytest platform_v2/tests/test_autoheal_engine_handoff.py -v`
Expected: PASS

- [ ] **Step 5: Verify `ARCHIE_GITHUB_TOKEN` in the live engine (else PRs fail closed)**

```bash
docker inspect archie_engine -f '{{range .Config.Env}}{{println .}}{{end}}' | grep -i ARCHIE_GITHUB_TOKEN
```
If absent, PRs from the build loop fail closed — flag to the owner (secret provisioning is a manual step).

- [ ] **Step 6: Commit**

```bash
git add platform_v2/services/code_health_autoheal.py platform_v2/tests/test_autoheal_engine_handoff.py
git commit -m "feat(code-health): optional engine build_loop handoff for tested-PR fixes (human merge)"
```

---

## Self-Review

**Spec coverage (against `2026-07-11-code-health-static-analysis-scanner-tier-design.md`):**
- §4.1 toolchain runner → Task 2. §4.2 auto-verify gate → Task 3. §4.3 issue codes + Deep-Scan → Tasks 4–5. §4.4 data flow → Tasks 5–6. Autonomy (11a Track A) → Tasks 6–7. Faithful runtime → Tasks 2/8. Error handling (fail-closed, tool-crash-skip) → Tasks 2/3. Testing → every task + Task 8 integration. Engine convergence (11a) → Task 9. **Gap check:** standalone/website runtimes are Slice 1b (spec §9) — intentionally not tasked here; `RUNTIME_REGISTRY` is the extension point.
- **Human deploy gate unchanged** — Task 6 test `test_cycle_never_deploys` enforces it; Task 9 uses the never-merge engine path.

**Placeholder scan:** two spots explicitly flag "confirm the real signature/contract and match it" (Task 6 `dispatch_audit_proposals` return keys; Task 9 engine verb) — these are grounded read-then-match steps, not vague placeholders; the tests pin the contract either way.

**Type consistency:** finding dict `{code,severity,file,detail}` is used identically from Task 1 → `process_audit_findings`. Normalized finding keys (`tool,confidence,module,capability,target`) are added in Task 2 and consumed unchanged in Tasks 3/5. `run_autoheal_cycle` return keys match between Tasks 6 and 7.
