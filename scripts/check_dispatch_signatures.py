#!/usr/bin/env python3
"""V.I.G.I.L. Dispatch Signature Guardrail.

Blocks commits that call the Department HQ dispatcher entry points with
keyword arguments that don't exist in the canonical signature, or that
omit required positional arguments. Catches the class of bug surfaced
during the 2026-04-18 translation-coverage session (Project #272 / Task
#2104): a ``dispatch_json(...)`` call with a typo'd kwarg name that
failed silently at runtime instead of at import time.

Canonical source of truth:
    platform_v2/tools/department_hq/services/department_dispatcher.py

Audited entry points:
    dispatch(capability, prompt, module_id='unknown', system_prompt=None,
             user_id=None, json_mode=False) -> DispatchResult
    dispatch_json(capability, prompt, module_id='unknown',
                  system_prompt=None, user_id=None) -> Optional[Dict]
    request_work(capability, prompt, module_id='unknown',
                 system_prompt=None, context=None, user_id=None,
                 priority='normal', json_mode=False, timeout=300,
                 prefer_gpu=True, job_id=None, prefer_agent=None,
                 local_only=False, project_id=None, images=None)
                 -> DispatchResult

Scope rules:
  * ``dispatch_json`` and ``request_work`` are unique enough that every
    call to a function with that name is considered in-scope.
  * ``dispatch`` is audited only in files that import from the
    dispatcher module (or use ``get_dispatcher``) — avoids false
    positives from unrelated ``.dispatch()`` methods (e.g.
    APScheduler's ``scheduler.dispatch``).

Usage:
    python3 scripts/check_dispatch_signatures.py file1.py file2.py ...

Exits 0 clean, exits 1 with actionable error output listing each bad
call site and the allowed kwarg set for that function.

Hooks:
    - .pre-commit-config.yaml (runs on staged files at commit time)
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CANONICAL = (
    REPO_ROOT
    / "platform_v2"
    / "tools"
    / "department_hq"
    / "services"
    / "department_dispatcher.py"
)

AUDITED_FUNCS = ("dispatch", "dispatch_json", "request_work")

# Files that are the canonical source (signatures live here) or are
# legitimately allowed to drift (e.g. the signature extractor itself
# and tests exercising bad signatures).
ALLOWED_PATHS = (
    "platform_v2/tools/department_hq/services/department_dispatcher.py",
    "scripts/check_dispatch_signatures.py",
    "/tests/",
)

# Substrings that indicate a file imports the dispatcher. Used to scope
# the bare-name ``dispatch(...)`` audit — if the file never imports the
# dispatcher, any ``dispatch()`` it contains is some other function.
DISPATCHER_IMPORT_HINTS = (
    "department_dispatcher",
    "bridge_dispatcher",  # back-compat shim path
    "get_dispatcher",
    "get_router",
)


def _is_allowed(path: str) -> bool:
    normalized = str(path).replace("\\", "/")
    return any(allowed in normalized for allowed in ALLOWED_PATHS)


def _load_canonical_signatures() -> dict[str, dict]:
    """Return ``{func_name: {'required': [...], 'allowed_kwargs': set()}}``
    pulled from the canonical dispatcher module.

    Uses AST to walk top-level function defs and the ``request_work``
    method on ``BridgeDispatcher``. Falls back to an empty allow-list
    if the canonical file is missing — better to accept a commit than
    to wedge the repo when the source of truth moves.
    """
    if not CANONICAL.exists():
        return {}

    try:
        tree = ast.parse(CANONICAL.read_text(encoding="utf-8"))
    except SyntaxError:
        return {}

    sigs: dict[str, dict] = {}

    def _record(node: ast.FunctionDef) -> None:
        args = node.args
        positional = [a.arg for a in args.args if a.arg != "self"]
        kwonly = [a.arg for a in args.kwonlyargs]
        defaults = args.defaults
        # Walk positional args right-to-left pairing with defaults.
        required: list[str] = []
        optional: list[str] = list(positional[-len(defaults):]) if defaults else []
        required_count = len(positional) - len(defaults)
        required = positional[:required_count]
        kwonly_required = [
            a.arg
            for a, d in zip(args.kwonlyargs, args.kw_defaults)
            if d is None
        ]
        allowed = set(positional) | set(kwonly)
        sigs[node.name] = {
            "required": required + kwonly_required,
            "allowed_kwargs": allowed,
            "accepts_kwargs": args.kwarg is not None,
        }

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name in AUDITED_FUNCS:
                _record(node)

    # ``dispatch`` and ``dispatch_json`` carry ``**kwargs`` that forward
    # straight into ``request_work``/``request_json`` — so a typo'd kwarg
    # at the wrapper layer silently forwards and fails late. Treat the
    # wrappers as strict: allowed kwargs = (own sig ∪ request_work sig),
    # and disable ``accepts_kwargs``. This is the exact bug class that
    # motivated Task #2104.
    if "request_work" in sigs:
        forward_allowed = sigs["request_work"]["allowed_kwargs"]
        for wrapper in ("dispatch", "dispatch_json"):
            if wrapper in sigs:
                sigs[wrapper]["allowed_kwargs"] |= forward_allowed
                sigs[wrapper]["accepts_kwargs"] = False

    return sigs


def _file_imports_dispatcher(source: str) -> bool:
    return any(hint in source for hint in DISPATCHER_IMPORT_HINTS)


def _extract_call_name(call: ast.Call) -> str | None:
    """Return the trailing name of the call target (``obj.dispatch`` -> 'dispatch')
    or None if the target can't be resolved to a simple name."""
    func = call.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return None


def _audit_file(
    path: Path,
    sigs: dict[str, dict],
) -> list[tuple[int, str, str]]:
    """Return [(line_no, func_name, problem_description), ...] for one file."""
    if _is_allowed(str(path)):
        return []
    if not path.exists() or path.suffix != ".py":
        return []
    try:
        source = path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return []

    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError:
        # Let other linters complain about syntax; don't double-fail.
        return []

    scope_dispatcher = _file_imports_dispatcher(source)
    hits: list[tuple[int, str, str]] = []

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = _extract_call_name(node)
        if name not in sigs:
            continue
        # Scope the bare ``dispatch`` name to dispatcher-importing files
        # only — too common a method name on other objects to audit blindly.
        if name == "dispatch" and not scope_dispatcher:
            continue

        spec = sigs[name]
        allowed_kwargs = spec["allowed_kwargs"]
        accepts_kwargs = spec["accepts_kwargs"]

        # --- Check 1: unknown kwarg names --------------------------------
        for kw in node.keywords:
            if kw.arg is None:
                # **kwargs splat — can't validate statically.
                continue
            if kw.arg in allowed_kwargs:
                continue
            if accepts_kwargs:
                continue
            hits.append((
                node.lineno,
                name,
                f"unknown kwarg '{kw.arg}' — allowed: "
                f"{sorted(allowed_kwargs)}",
            ))

        # --- Check 2: required args present ------------------------------
        positional_count = len(node.args)
        provided_names = {k.arg for k in node.keywords if k.arg}
        required = spec["required"]
        missing = [
            r
            for i, r in enumerate(required)
            if i >= positional_count and r not in provided_names
        ]
        for miss in missing:
            hits.append((
                node.lineno,
                name,
                f"missing required argument '{miss}'",
            ))

    return hits


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        return 0

    sigs = _load_canonical_signatures()
    if not sigs:
        # Canonical file missing or unparseable — fail open, don't wedge
        # the repo. The K.I.N. single-writer guardrail catches broken
        # imports of the same module.
        return 0

    all_hits: list[tuple[Path, int, str, str]] = []
    for arg in argv[1:]:
        path = Path(arg)
        for lineno, name, msg in _audit_file(path, sigs):
            all_hits.append((path, lineno, name, msg))

    if not all_hits:
        return 0

    sys.stderr.write(
        "\n\033[1;31m"
        "V.I.G.I.L. dispatch-signature guardrail: "
        "call site disagrees with canonical signature"
        "\033[0m\n"
    )
    current_file: Path | None = None
    for path, lineno, name, msg in all_hits:
        if path != current_file:
            sys.stderr.write(f"\n  \033[1;31m{path}\033[0m\n")
            current_file = path
        sys.stderr.write(f"    line {lineno}: {name}() — {msg}\n")

    sys.stderr.write(
        "\n\033[1;33m"
        "The canonical signatures live in:\n"
        "    platform_v2/tools/department_hq/services/"
        "department_dispatcher.py\n"
        "\n"
        "If a new kwarg is genuinely needed, add it to the canonical\n"
        "function first (and any shim), then update call sites. That\n"
        "keeps ADR-013 (Bridge as single dispatch surface) honest.\n"
        "\n"
        "See Project #272 Phase 1 / Task #2104 for context.\n"
        "\033[0m"
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
