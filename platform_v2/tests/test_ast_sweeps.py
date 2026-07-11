"""Unit tests for the deterministic AST interface-sweeps (Code Health static tier).

These encode the exact bug classes the 2026-07-11 audit session found by hand:
wrong-root / wrong-submodule imports, missing symbols, wrong kwargs, arity.
The resolver is injected, so the checks are pure and hermetic here; production
binds a RuntimeResolver against the faithful container sys.path.
"""

import inspect
import textwrap

from services.code_analysis.ast_sweeps import sweep_module


class FakeResolver:
    """Deterministic stand-in for the runtime resolver."""

    def __init__(self, modules=(), symbols=(), sigs=None):
        self._m = set(modules)
        self._s = set(symbols)
        self._sig = sigs or {}

    def module_exists(self, dotted):
        return dotted in self._m

    def symbol_exists(self, dotted, name):
        return (dotted, name) in self._s

    def signature_of(self, dotted, name):
        return self._sig.get((dotted, name))


def _write(tmp_path, src):
    p = tmp_path / "sample.py"
    p.write_text(textwrap.dedent(src))
    return str(p)


def test_flags_wrong_root_import(tmp_path):
    path = _write(tmp_path, "from toolz.dev_hq.routes import thing\n")
    r = FakeResolver(modules={"tools"})
    findings = sweep_module(path, r)
    assert [f["code"] for f in findings] == ["WRONG_ROOT_IMPORT"]
    assert findings[0]["severity"] == "red"


def test_flags_wrong_submodule_import(tmp_path):
    path = _write(tmp_path, "from tools.dev_hq.routes import thing\n")
    r = FakeResolver(modules={"tools"})  # root exists, submodule does not
    findings = sweep_module(path, r)
    assert [f["code"] for f in findings] == ["WRONG_SUBMODULE_IMPORT"]


def test_does_not_flag_real_import(tmp_path):
    path = _write(tmp_path, "from tools.consciousness.devhq_routes import thing\n")
    r = FakeResolver(
        modules={"tools", "tools.consciousness.devhq_routes"},
        symbols={("tools.consciousness.devhq_routes", "thing")},
    )
    assert sweep_module(path, r) == []


def test_flags_missing_symbol(tmp_path):
    path = _write(tmp_path, "from services.telegram_service import store_knowledge\n")
    r = FakeResolver(modules={"services", "services.telegram_service"})
    findings = sweep_module(path, r)
    assert [f["code"] for f in findings] == ["MISSING_SYMBOL"]
    assert "store_knowledge" in findings[0]["detail"]


def test_flags_wrong_kwarg_on_known_call(tmp_path):
    src = """
        from services.telegram_service import send_info

        send_info(subject="x", body="y")
    """
    path = _write(tmp_path, src)

    def send_info(title="", message="", severity="info"):
        pass

    r = FakeResolver(
        modules={"services", "services.telegram_service"},
        symbols={("services.telegram_service", "send_info")},
        sigs={("services.telegram_service", "send_info"): inspect.signature(send_info)},
    )
    findings = sweep_module(path, r)
    codes = [f["code"] for f in findings]
    assert codes.count("WRONG_KWARG") == 2  # subject AND body are both invalid
    assert all("line" in f["detail"] for f in findings)  # fix-excerpt parser needs it


def test_flags_arity_mismatch(tmp_path):
    src = """
        from services.telegram_service import send_info

        send_info("a", "b", "c", "d")
    """
    path = _write(tmp_path, src)

    def send_info(title="", message=""):
        pass

    r = FakeResolver(
        modules={"services", "services.telegram_service"},
        symbols={("services.telegram_service", "send_info")},
        sigs={("services.telegram_service", "send_info"): inspect.signature(send_info)},
    )
    findings = sweep_module(path, r)
    assert [f["code"] for f in findings] == ["ARITY_MISMATCH"]


def test_var_positional_and_var_keyword_are_not_flagged(tmp_path):
    src = """
        from services.telegram_service import send_info

        send_info("a", "b", "c", extra=True)
    """
    path = _write(tmp_path, src)

    def send_info(*args, **kwargs):
        pass

    r = FakeResolver(
        modules={"services", "services.telegram_service"},
        symbols={("services.telegram_service", "send_info")},
        sigs={("services.telegram_service", "send_info"): inspect.signature(send_info)},
    )
    assert sweep_module(path, r) == []


def test_relative_and_star_imports_are_skipped(tmp_path):
    src = """
        from . import sibling
        from .relative_mod import helper
        from services.telegram_service import *
    """
    path = _write(tmp_path, src)
    r = FakeResolver(modules={"services", "services.telegram_service"})
    assert sweep_module(path, r) == []


def test_syntax_error_is_reported_not_raised(tmp_path):
    path = _write(tmp_path, "def broken(:\n")
    findings = sweep_module(path, FakeResolver())
    assert [f["code"] for f in findings] == ["SYNTAX_ERROR"]
