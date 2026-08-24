"""The module stub must win regardless of import order (#5987).

`test_maintenance_window_driver.py` passed alone and failed in a suite for exactly one
reason: `from services import maintenance_schedule_service as mss` reads the PACKAGE
ATTRIBUTE, which Python caches the first time the submodule is imported anywhere, and a
`sys.modules`-only stub never touches that attribute.

These tests pin the fix AND include the negative control, so they cannot pass vacuously.
"""

import importlib
import pathlib
import sys
import types

import pytest

pytest.importorskip("psycopg2")

from tests.modstub import install_module_stub  # noqa: E402

_TARGET = "services.maintenance_schedule_service"


def _force_the_attribute_to_exist():
    """Simulate a neighbouring test file doing a normal `import services.x`."""
    pytest.importorskip(_TARGET)
    importlib.import_module(_TARGET)
    import services

    assert hasattr(services, "maintenance_schedule_service"), "precondition: attribute cached"
    return services


def test_the_stub_wins_even_after_the_real_submodule_was_imported(monkeypatch):
    """THE BUG, pinned: this is the situation in which the old pattern silently failed."""
    _force_the_attribute_to_exist()
    install_module_stub(monkeypatch, _TARGET, list_windows=lambda **kw: ["SENTINEL"])

    from services import maintenance_schedule_service as mss  # the driver's exact import form

    assert mss.list_windows() == ["SENTINEL"]


def test_NEGATIVE_CONTROL_sys_modules_alone_is_not_enough(monkeypatch):
    """Proves the helper does real work.

    This is precisely what the four `_install` helpers used to do, and it is why the driver
    tests emptied out when another file imported the submodule first.
    """
    _force_the_attribute_to_exist()
    stub = types.ModuleType(_TARGET)
    stub.list_windows = lambda **kw: ["SENTINEL"]
    monkeypatch.setitem(sys.modules, _TARGET, stub)

    from services import maintenance_schedule_service as mss

    assert mss.list_windows() != ["SENTINEL"], "sys.modules-only patching must NOT take effect here"


def test_teardown_restores_the_real_module(monkeypatch):
    """A stub that leaked would poison every later test in the session."""
    services = _force_the_attribute_to_exist()
    real = services.maintenance_schedule_service

    mp = pytest.MonkeyPatch()
    install_module_stub(mp, _TARGET, list_windows=lambda **kw: ["SENTINEL"])
    assert services.maintenance_schedule_service is not real
    mp.undo()

    assert services.maintenance_schedule_service is real
    assert sys.modules[_TARGET] is real


def test_no_test_file_reintroduces_the_sys_modules_only_pattern():
    """A grep guard, because the previous mitigation was a COMMENT and comments do not fail.

    Any file stubbing this submodule must go through tests/modstub.py.
    """
    offenders = []
    for path in pathlib.Path(__file__).parent.glob("test_*.py"):
        text = path.read_text(encoding="utf-8")
        if f'setitem(sys.modules, "{_TARGET}"' in text and "install_module_stub" not in text:
            offenders.append(path.name)
    assert not offenders, f"use tests.modstub.install_module_stub in: {offenders}"


def test_uninstall_makes_the_module_genuinely_unimportable(monkeypatch):
    """The mirror-image trap: a test asserting "the service is missing" must really miss it."""
    from tests.modstub import uninstall_module

    _force_the_attribute_to_exist()
    uninstall_module(monkeypatch, _TARGET)

    with pytest.raises(ImportError):
        from services import maintenance_schedule_service  # noqa: F401


def test_NEGATIVE_CONTROL_sys_modules_None_alone_does_not_hide_the_module(monkeypatch):
    """Why uninstall_module exists: this is what test_missing_service_does_not_raise used to do.

    The import SUCCEEDS off the cached package attribute, so the test exercised the healthy
    path while believing it had removed the service.
    """
    _force_the_attribute_to_exist()
    monkeypatch.setitem(sys.modules, _TARGET, None)

    from services import maintenance_schedule_service as mss  # must NOT raise

    assert mss is not None, "sys.modules=None alone should not have hidden it — that is the trap"
