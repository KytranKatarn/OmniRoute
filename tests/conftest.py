"""
Pytest configuration for the archie test suite.

Problem: test_dispatch_service.py calls sys.modules.setdefault() at import
time to stub out heavy platform modules (department_coordinator,
agent_service, model_service).  Because setdefault() runs once at collection
time, those stubs remain in sys.modules for the rest of the process —
corrupting any test that later tries to import the *real* implementations.

Fix: an autouse function-scoped fixture that restores the real modules before
each test in the coordinator / integration test files, and re-instates the
stubs after each test so the dispatch tests are unaffected.
"""

import importlib
import sys

import pytest

# Modules that test_dispatch_service stubs out at collection time.
_STUBBED = [
    "services.department_coordinator",
    "services.agent_service",
    "services.model_service",
]


def _is_mock(module) -> bool:
    """Return True if the module object is a MagicMock stub."""
    return type(module).__name__ == "MagicMock"


@pytest.fixture(autouse=True)
def restore_real_coordinator_modules(request):
    """For coordinator/integration tests, reload the real service modules."""
    # Only activate for the test files that need real imports.
    needs_real = any(
        name in request.fspath.basename
        for name in ("test_department_coordinator", "test_consciousness_integration")
    )

    if not needs_real:
        yield
        return

    # Save whatever is currently in sys.modules (may be stubs or real).
    saved = {key: sys.modules.get(key) for key in _STUBBED}

    # Remove stubs so importlib.import_module loads the real files.
    for key in _STUBBED:
        sys.modules.pop(key, None)

    # Force-reload the real implementations in dependency order.
    import sys as _sys
    sys.path.insert(0, "platform_v2")
    for mod_name in _STUBBED:
        try:
            importlib.import_module(mod_name)
        except Exception:
            pass  # If a transitive dep fails, the test will surface it clearly.

    yield

    # Restore previous state so dispatch tests still see their stubs.
    for key, mod in saved.items():
        if mod is None:
            sys.modules.pop(key, None)
        else:
            sys.modules[key] = mod
