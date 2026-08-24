"""A test module must not leave a stub in sys.modules for the rest of the session (#6021).

Reported as a normal failing test rather than a collection abort: a hard failure inside
pytest_collection_finish takes down the whole run, and the point is to NAME the offender,
not to hide every other result behind it.

See the block above `_ALLOWED_STUB_LEAKS` in conftest.py for the three incidents that
motivated this, and for why detection keys on `__spec__` rather than `__file__`.
"""

import sys


def _conftest():
    """conftest is loaded as a plugin under a mangled name; find it by file."""
    for mod in list(sys.modules.values()):
        if mod is not None and str(getattr(mod, "__file__", "")).endswith("/tests/conftest.py"):
            return mod
    raise AssertionError("tests/conftest.py is not loaded — cannot check for stub leaks")


def test_no_new_module_stub_outlives_its_test_module():
    cf = _conftest()
    unexpected = sorted(cf._leaked_stubs - set(cf._ALLOWED_STUB_LEAKS))
    assert not unexpected, (
        "these first-party modules are STUBS after collection, so every later test module "
        "importing them gets the stub instead of the real thing — silently, and only in a "
        "full run:\n  " + "\n  ".join(unexpected) + "\n\nFix: install the stub in a module-scoped autouse fixture via "
        "tests/modstub.stub_module_scoped(dotted, stub), which restores BOTH sys.modules "
        "and the parent package attribute. Do NOT add it to _ALLOWED_STUB_LEAKS — that "
        "list may only shrink."
    )


# Below this, a run is a subset and the staleness check cannot mean anything.
_FULL_RUN_MIN_ITEMS = 3000


def test_the_allowlist_only_shrinks():
    """Every allowlisted name must still actually leak.

    A stale entry is worse than none: it silently permits a name nobody stubs any more, so
    a NEW offender reusing that name would be waved through."""
    import pytest

    cf = _conftest()
    if cf._collected_count < _FULL_RUN_MIN_ITEMS:
        pytest.skip(
            "partial run (%d items) — nothing leaks when only some modules are imported, "
            "so every allowlist entry would look stale" % cf._collected_count
        )
    stale = sorted(set(cf._ALLOWED_STUB_LEAKS) - cf._leaked_stubs)
    assert not stale, "allowlisted but no longer leaking — remove from _ALLOWED_STUB_LEAKS: " + ", ".join(stale)
