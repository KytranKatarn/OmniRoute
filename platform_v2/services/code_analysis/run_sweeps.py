"""In-runtime AST-sweep entrypoint: `python3 -m services.code_analysis.run_sweeps`.

Builds a SymbolResolver against the LIVE sys.path of the runtime it executes in
and runs the interface sweeps over the given files, printing JSON findings to
stdout. Run as a short-lived subprocess by code_static_analyzer so that
resolver imports (which execute module-level code) never contaminate the
calling daemon.
"""

from __future__ import annotations

import argparse
import importlib
import inspect
import json
import sys

from services.code_analysis.ast_sweeps import SymbolResolver, sweep_module


class RuntimeResolver(SymbolResolver):
    """Resolves modules/symbols/signatures against the current interpreter's
    real import environment — the definition of 'faithful'."""

    def module_exists(self, dotted: str) -> bool:
        try:
            importlib.import_module(dotted)
            return True
        except Exception:
            return False

    def symbol_exists(self, dotted: str, name: str) -> bool:
        try:
            if hasattr(importlib.import_module(dotted), name):
                return True
        except Exception:
            return False
        # `from pkg import name` also succeeds when name is a SUBMODULE that
        # hasn't been imported yet — mirror Python's real fallback semantics
        # (this exact case false-positived on `from services import
        # qa_baseline_service` during live verification).
        try:
            importlib.import_module(f"{dotted}.{name}")
            return True
        except Exception:
            return False

    def signature_of(self, dotted: str, name: str):
        try:
            obj = getattr(importlib.import_module(dotted), name)
            return inspect.signature(obj)
        except Exception:
            return None


def main() -> None:
    parser = argparse.ArgumentParser(description="Run AST interface-sweeps in the live runtime")
    parser.add_argument("--roots", default="", help="comma-separated sys.path roots to prepend")
    parser.add_argument("files", nargs="*")
    args = parser.parse_args()

    for root in reversed([r for r in args.roots.split(",") if r]):
        if root not in sys.path:
            sys.path.insert(0, root)

    resolver = RuntimeResolver()
    findings = []
    for path in args.files:
        try:
            findings.extend(sweep_module(path, resolver))
        except Exception as exc:  # one bad file never kills the batch
            findings.append(
                {
                    "code": "SWEEP_ERROR",
                    "severity": "info",
                    "file": path,
                    "line": 0,
                    "detail": f"{exc} (line 0)",
                }
            )
    print(json.dumps(findings))


if __name__ == "__main__":
    main()
