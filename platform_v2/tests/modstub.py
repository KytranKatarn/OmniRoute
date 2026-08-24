"""Install a stand-in module so BOTH import forms see it, whatever the import order (#5987).

THE TRAP. `monkeypatch.setitem(sys.modules, "pkg.child", stub)` alone is NOT enough when the
code under test says::

    from pkg import child          # e.g. jobs.py: from services import maintenance_schedule_service as mss

`from pkg import child` resolves `child` as an **attribute of the already-imported `pkg`
package object**, and Python caches the submodule there the first time it is imported
anywhere in the process. Once that attribute exists, the from-import returns it and NEVER
consults ``sys.modules`` — so the stub is silently ignored and the real module runs.

WHY THAT IS WORSE THAN A PLAIN BUG. It depends on IMPORT ORDER, so the same test is green
alone and red in a suite. Measured 2026-08-24 on ``test_maintenance_window_driver.py``:
**10 passed alone, 7 failed** under ``pytest tests/ -k maintenance`` — because ``-k`` still
*collects* (imports) every test module first, and ``test_proposer_service.py`` does a real
``import services.maintenance_schedule_service``, caching the attribute before any test runs.
The driver then called the REAL service, found no windows, and returned empty results.

That suite covers ``maintenance_window_driver``, which ANNOUNCES-THEN-OPENS a maintenance
window — the thing standing between a proposed manifest and automated agents being allowed
to merge. Whichever way CI runs it, one of the two results is a lie.

THE OLD MITIGATION DOES NOT HOLD. Some of these files avoided a real import specifically to
keep the package attribute unset. That is an invariant spanning every test file in a growing
suite, enforced by a comment — and it was broken the day a new file imported the submodule
normally. Patch both bindings instead, and import order stops mattering.

``monkeypatch`` undoes both, including deleting an attribute that did not previously exist.
"""

import contextlib
import importlib
import sys
import types


def install_module_stub(monkeypatch, dotted_name: str, **attrs):
    """Replace ``dotted_name`` with a stub exposing ``attrs``. Returns the stub module.

    Patches BOTH bindings:
      * ``sys.modules[dotted_name]``            — for ``import pkg.child`` / ``from pkg.child import x``
      * ``getattr(pkg, "child")``               — for ``from pkg import child``, which wins when set
    """
    parent_name, _, child = dotted_name.rpartition(".")
    stub = types.ModuleType(dotted_name)
    for name, value in attrs.items():
        setattr(stub, name, value)

    monkeypatch.setitem(sys.modules, dotted_name, stub)
    if parent_name:
        # raising=False: the attribute may legitimately not exist yet (nothing has imported
        # the submodule). monkeypatch then DELETES it on teardown rather than restoring a
        # value, which is exactly right — it leaves the session as it found it.
        monkeypatch.setattr(importlib.import_module(parent_name), child, stub, raising=False)
    return stub


def uninstall_module(monkeypatch, dotted_name: str) -> None:
    """Make ``dotted_name`` genuinely UNIMPORTABLE — both ways (#5987).

    The mirror image of the trap above. ``sys.modules[name] = None`` makes ``import name``
    raise, but ``from pkg import child`` still succeeds off the cached package attribute, so
    a test asserting "the service is missing" silently exercised the HEALTHY path instead.
    Measured: ``test_missing_service_does_not_raise`` expected ``{"ok": False}`` and got a
    normal result dict, because the driver imported the real module after all.

    Used to prove an unattended job degrades gracefully rather than raising into the
    scheduler — so it has to actually be missing.
    """
    parent_name, _, child = dotted_name.rpartition(".")
    monkeypatch.setitem(sys.modules, dotted_name, None)
    parent = sys.modules.get(parent_name) if parent_name else None
    if parent is not None:
        monkeypatch.delattr(parent, child, raising=False)


@contextlib.contextmanager
def stub_module_scoped(dotted_name: str, stub):
    """Install a PREBUILT stub module for the duration of the block, then restore (#6018).

    `install_module_stub` above builds a stub from kwargs and reverts via monkeypatch, which
    needs a fixture. This variant takes an already-constructed module and works anywhere a
    `with` works — including a module-scoped autouse fixture, which is what a test file needs
    when it must stub something for its OWN tests without poisoning the session.

    WHY THIS EXISTS: five modules used to do, at import time and permanently,
        sys.modules["tools.department_hq.services.department_dispatcher"] = _stub
    pytest imports every test module during COLLECTION, so from the earliest such import the
    stub was what the WHOLE session saw. Later modules wanting the real thing got the stub —
    silently, and only when the suite ran as a whole (#6017: 8 tests that passed 8/8 alone).

    Restores BOTH bindings, and the parent attribute is not optional: `from pkg import child`
    reads the PARENT PACKAGE ATTRIBUTE, not sys.modules. Restoring only sys.modules regressed
    6 tests in PR #2805's first attempt. Same trap as #5987.

    Absence is restored as absence — if the name was not in sys.modules (or the attribute did
    not exist), it is removed again rather than left bound to None, which is its own import
    hazard (`None in sys.modules` raises ImportError on the next import).
    """
    parent_name, leaf = dotted_name.rsplit(".", 1)
    parent = sys.modules.get(parent_name)

    had_mod = dotted_name in sys.modules
    prev_mod = sys.modules.get(dotted_name)
    had_attr = parent is not None and hasattr(parent, leaf)
    prev_attr = getattr(parent, leaf, None) if parent is not None else None

    sys.modules[dotted_name] = stub
    if parent is not None:
        setattr(parent, leaf, stub)
    try:
        yield stub
    finally:
        if had_mod:
            sys.modules[dotted_name] = prev_mod
        else:
            sys.modules.pop(dotted_name, None)
        if parent is not None:
            if had_attr:
                setattr(parent, leaf, prev_attr)
            else:
                try:
                    delattr(parent, leaf)
                except AttributeError:
                    pass
