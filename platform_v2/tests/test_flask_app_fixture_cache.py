"""The Flask app must be built ONCE per process, not once per test (#5998).

Background. `_conftest()._load_flask_app()` calls `spec.loader.exec_module()`, which executes
the whole of app.py — every blueprint across all 36 modules, the Jinja environment, the
extensions. Nothing releases the result: registrations and module-level globals in the
imported route modules keep each app reachable for the life of the process.

The `app` fixture is function-scoped, so before the cache that cost was paid ONCE PER TEST.
Measured 2026-08-24 with a per-test cgroup probe: single tests in test_coo_actions.py,
test_coo_consult.py and test_dhq_chat_routing.py each added 0.5-1.2 GB, and a full run was
OOM-killed at a 16 GiB ceiling around 57%. Doubling the ceiling from 8 GiB moved only where
it died, never whether — the growth is unbounded, so no ceiling is a fix.

After caching: 3,885 tests complete in a 8 GiB container, peak ~4.7 GB.

⚠️ These tests pin the CACHE, not the fixture's scope. The `app` fixture is deliberately
still function-scoped so it re-applies the test config every time; only the rebuild is
shared. Do not "simplify" this by making the fixture session-scoped — that would let a test
that mutates app.config leak into the next one.
"""

import os
import sys


def _conftest():
    """pytest loads tests/conftest.py as a plugin under a mangled name, so a plain
    `import conftest` raises ModuleNotFoundError. Find it by file instead."""
    for mod in list(sys.modules.values()):
        if mod is not None and str(getattr(mod, "__file__", "")).endswith("/tests/conftest.py"):
            return mod
    raise AssertionError("tests/conftest.py is not loaded — cannot verify the cache")


def test_the_app_is_built_once_not_rebuilt_per_call():
    """The defect: two calls returned two different multi-hundred-MB app objects."""
    first = _conftest()._load_flask_app()
    second = _conftest()._load_flask_app()
    assert first is second, "app.py was re-executed — the ~1 GB per-test leak is back"


def test_the_fixture_hands_out_that_same_cached_app(app):
    """Guards the wiring, not just the helper: a fixture that stopped calling the cached
    loader would pass the test above while still leaking."""
    assert app is _conftest()._load_flask_app()


def test_the_app_fixture_is_still_FUNCTION_scoped():
    """Caching must not cost per-test config isolation.

    The obvious "fix" for this leak is scope="session" on the fixture. That would also
    share every config mutation between tests — a test flipping TESTING or CSRF would
    silently change the next one. Only the rebuild is shared; the fixture body still
    re-applies the test config on every use. This pins that choice.

    Asserted against the SOURCE rather than a pytest internal: pytest 9 no longer exposes
    _pytestfixturefunction on the decorated function, and a guard that silently stops
    checking is worse than no guard (it reads as a pass forever)."""
    import re

    src = open(_conftest().__file__).read()
    m = re.search(r"(@pytest\.fixture[^\n]*)\ndef app\(\):", src)
    assert m, "the app fixture was renamed or restructured — update this guard"
    assert m.group(1).strip() == "@pytest.fixture", (
        "the app fixture gained a scope (%r) — config now leaks between tests; "
        "cache the BUILD (_FLASK_APP_CACHE), not the fixture" % m.group(1).strip()
    )


def test_the_cache_is_keyed_by_path_so_a_worktree_run_gets_its_own_app():
    """ARCHIE_APP_PY lets a bundle/worktree test its OWN app.py. A cache keyed on anything
    coarser (a bare module-level global) would hand it the /app build instead — silently
    testing the wrong tree, which is worse than the leak it replaced."""
    key = os.environ.get("ARCHIE_APP_PY", "/app/app.py")
    _conftest()._load_flask_app()
    assert key in _conftest()._FLASK_APP_CACHE


def test_sys_modules_shadow_survives_a_cache_hit():
    """`from app import User` inside platform code must resolve to the module this app was
    built from. A cache hit that skipped re-asserting the shadow would break that as soon as
    any other test replaced sys.modules['app']."""
    import sys

    _conftest()._load_flask_app()
    sys.modules["app"] = object()  # simulate another test clobbering it
    _conftest()._load_flask_app()
    assert sys.modules["app"] is _conftest()._FLASK_APP_CACHE[os.environ.get("ARCHIE_APP_PY", "/app/app.py")][0]
