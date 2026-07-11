"""Deterministic AST interface-sweeps — the checks that found 28/35 latent bugs
in the 2026-07-11 audit session (wrong-root/submodule imports, missing symbols,
wrong kwargs, arity mismatches).

Pure over (parsed module, SymbolResolver) — no I/O beyond reading the file.
The resolver is what makes results faithful: production binds a RuntimeResolver
against the real container sys.path (see run_sweeps.py); tests inject a fake.
Every detail string ends with "(line N)" because audit_pipeline's fix-prompt
excerpt parser keys on the last "line <digits>" occurrence.
"""

from __future__ import annotations

import ast
import inspect
from typing import Optional


class SymbolResolver:
    """Interface only — concrete resolvers live with their runtimes."""

    def module_exists(self, dotted: str) -> bool:  # pragma: no cover - interface
        raise NotImplementedError

    def symbol_exists(self, dotted: str, name: str) -> bool:  # pragma: no cover - interface
        raise NotImplementedError

    def signature_of(self, dotted: str, name: str) -> Optional[inspect.Signature]:  # pragma: no cover
        raise NotImplementedError


def _finding(code, severity, path, line, detail):
    return {"code": code, "severity": severity, "file": path, "line": line, "detail": detail}


def _missing_module_code(resolver: SymbolResolver, dotted: str) -> str:
    """Wrong submodule (the root package exists) vs wrong root (nothing resolves)."""
    root = dotted.split(".")[0]
    return "WRONG_SUBMODULE_IMPORT" if resolver.module_exists(root) else "WRONG_ROOT_IMPORT"


def sweep_module(path: str, resolver: SymbolResolver) -> list[dict]:
    """Run all interface sweeps over one file. Returns Code Health issue dicts."""
    with open(path, "r", encoding="utf-8", errors="ignore") as fh:
        source = fh.read()
    try:
        tree = ast.parse(source, filename=path)
    except SyntaxError as exc:
        return [_finding("SYNTAX_ERROR", "red", path, getattr(exc, "lineno", 0) or 0, f"{exc.msg} (line {exc.lineno})")]

    findings: list[dict] = []
    imported: dict[str, tuple[str, str]] = {}  # local name -> (module, original name)

    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            mod = node.module
            if not resolver.module_exists(mod):
                findings.append(
                    _finding(
                        _missing_module_code(resolver, mod),
                        "red",
                        path,
                        node.lineno,
                        f"import from '{mod}' does not resolve in the runtime (line {node.lineno})",
                    )
                )
                continue
            for alias in node.names:
                if alias.name == "*":
                    continue
                if not resolver.symbol_exists(mod, alias.name):
                    findings.append(
                        _finding(
                            "MISSING_SYMBOL",
                            "red",
                            path,
                            node.lineno,
                            f"'{alias.name}' is not exported by '{mod}' (line {node.lineno})",
                        )
                    )
                else:
                    imported[alias.asname or alias.name] = (mod, alias.name)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if not resolver.module_exists(alias.name):
                    findings.append(
                        _finding(
                            _missing_module_code(resolver, alias.name),
                            "red",
                            path,
                            node.lineno,
                            f"import '{alias.name}' does not resolve in the runtime (line {node.lineno})",
                        )
                    )

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
    """Validate one call site against the resolved runtime signature."""
    out: list[dict] = []
    params = sig.parameters
    has_var_kw = any(p.kind == p.VAR_KEYWORD for p in params.values())
    has_var_pos = any(p.kind == p.VAR_POSITIONAL for p in params.values())

    if not has_var_kw:
        valid = {n for n, p in params.items() if p.kind in (p.POSITIONAL_OR_KEYWORD, p.KEYWORD_ONLY)}
        for kw in node.keywords:
            if kw.arg and kw.arg not in valid:  # kw.arg None == **spread, unknowable statically
                out.append(
                    _finding(
                        "WRONG_KWARG",
                        "red",
                        path,
                        node.lineno,
                        f"{name}() has no parameter '{kw.arg}' (line {node.lineno})",
                    )
                )

    if not has_var_pos:
        positional_slots = [n for n, p in params.items() if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD)]
        if len(node.args) > len(positional_slots):
            out.append(
                _finding(
                    "ARITY_MISMATCH",
                    "red",
                    path,
                    node.lineno,
                    f"{name}() takes {len(positional_slots)} positional args, "
                    f"{len(node.args)} given (line {node.lineno})",
                )
            )
    return out
