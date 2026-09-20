"""Does the patched file actually RUN? (#6770 / #6771)

WHY THIS EXISTS
---------------
On 2026-09-15, 33 of 33 sampled auto-fix PRs were broken or no-ops (~97%). Four of them
carried a stored F.O.R.G.E. **APPROVE**. The failures were not subtle:

    #3375  removes `Dict` from a typing import while `Dict` is used 9x   -> NameError
    #3362  malformed try/except indentation                              -> SyntaxError
    #3363  imports invented module `agent_clarification`                 -> ImportError
    #3366  imports invented package `core.database`                      -> ImportError
    #3355  deletes `omniroute_telemetry_collect()` while claiming an import fix
    #3357  deletes the `connect_chaplain` route while claiming an import fix
    #3364  rewrites 2 of 4 call sites, leaving the file inconsistent

Every one of those is mechanically detectable from the patched text alone. Nothing here
needs a language model, and that is the whole point — the same reasoning
``deterministic_fixer`` already applies to mechanical pyflakes edits ("there is nothing for
a language model to decide").

WHY IT IS ONE MODULE AND NOT TWO
--------------------------------
#6770 wants this at the GENERATOR (never emit a patch that cannot run). #6771 wants it at
the REVIEW (never approve a patch that cannot run). That is the SAME predicate at two
choke points, and this codebase has repeatedly paid for writing such a guard once and
wiring it in only one place (#5194, #5862, #2738 — "the fix is to WIRE it, not write it").
So the predicate lives here, pure, and each caller imports it.

WHAT THIS IS NOT
----------------
This does not judge whether a fix is CORRECT — only whether it is *executable and
self-consistent*. A patch can pass every check here and still be a bad idea. It is a floor,
not a verdict.
"""

from __future__ import annotations

import ast
import sys

# Modules the self-heal generator hallucinated, measured on the 2026-09-15 sample. Kept as
# documentation of the failure mode; the resolver below rejects them on their own merits,
# so this list is never consulted as a blocklist (a blocklist would only catch the ones we
# have already seen).
KNOWN_HALLUCINATED = (
    "core.database",
    "app_core.tools.database",
    "ai_bridge.platform_v2.database",
    "starbase.tools.helpers",
    "app_builder.tools.database",
    "fleet.helpers",
    "agent_clarification",
    "agents.test_agent",
)


def _imported_modules(tree: ast.Module) -> set:
    """Top-level module names introduced by import statements."""
    out = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                out.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            # A relative import (level > 0) resolves against the package, which we cannot
            # evaluate from text alone — skip rather than guess.
            if node.level == 0 and node.module:
                out.add(node.module)
    return out


def _imported_names(tree: ast.Module) -> set:
    """Bound names an import makes available (the `Dict` in `from typing import Dict`)."""
    out = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                if alias.name == "*":
                    continue
                out.add(alias.asname or alias.name.split(".")[0])
    return out


def _referenced_names(tree: ast.Module) -> set:
    """Every bare name and attribute root used anywhere in the body."""
    out = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            out.add(node.id)
        elif isinstance(node, ast.Attribute):
            cur = node
            while isinstance(cur, ast.Attribute):
                cur = cur.value
            if isinstance(cur, ast.Name):
                out.add(cur.id)
    # A name can also appear only inside a string annotation; treat those as referenced by
    # scanning nothing here (handled by the caller's raw-text fallback) — see
    # `removed_import_still_used`, which re-checks the raw text before failing.
    return out


def _top_level_defs(tree: ast.Module) -> set:
    """Top-level function/class names — what a patch must not silently delete."""
    out = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            out.add(node.name)
    return out


def module_resolves(module: str) -> bool:
    """Can the REAL interpreter find this module?

    ⚠️ Deliberately uses find_spec rather than a curated allowlist: the generator invents
    *new* wrong paths, so anything enumerable is already out of date. find_spec consults
    sys.path exactly as an import would.

    ⚠️ ROOT-ONLY PROBING IS NOT ENOUGH, and assuming it was let a real failure through.
    Measured in this container: ``core`` resolves (``/app/core/__init__.py``) while
    ``core.database`` does not, so a root-only check PASSED #3366 — one of the four broken
    patches that carried an APPROVE. ``fleet`` is a namespace package and would pass
    ``fleet.helpers`` the same way.

    ⚠️ But we also cannot hand the full dotted path to ``find_spec``: resolving ``a.b.c``
    IMPORTS ``a`` and ``a.b``, running arbitrary package side effects inside a validator.
    So the root is probed via ``find_spec`` (which imports nothing for a top-level name)
    and every remaining segment is resolved against the package's ``__path__`` on the
    FILESYSTEM — full-depth accuracy, zero submodule imports.
    """
    parts = [p for p in (module or "").split(".") if p]
    if not parts:
        return False
    # Already-imported names resolve by definition. This is not just a fast path: it is the
    # ONLY way some real modules can be seen. ``os.path`` is an ALIAS (os assigns it to
    # posixpath at import), so there is no os/path.py to find on disk and the filesystem
    # walk below returns False for it — a FALSE REJECT, which is the costlier direction
    # here because it blocks a legitimate fix. Measured: without this, `import os.path`
    # was rejected.
    if module in sys.modules:
        return True
    root = parts[0]
    if root in sys.builtin_module_names:
        return True
    try:
        import importlib.machinery
        import importlib.util
        import os

        spec = importlib.util.find_spec(root)
        if spec is None:
            return False
        if len(parts) == 1:
            return True

        search = list(spec.submodule_search_locations or [])
        if not search:
            # A plain module (foo.py) cannot have submodules.
            return False

        suffixes = tuple(importlib.machinery.SOURCE_SUFFIXES) + tuple(importlib.machinery.EXTENSION_SUFFIXES)
        for i, seg in enumerate(parts[1:], start=1):
            found_pkg = None
            found_mod = False
            for d in search:
                pkg_init = os.path.join(d, seg, "__init__.py")
                if os.path.isfile(pkg_init):
                    found_pkg = os.path.join(d, seg)
                    break
                if any(os.path.isfile(os.path.join(d, seg + sfx)) for sfx in suffixes):
                    found_mod = True
                    break
                # PEP 420 namespace package: a bare directory with no __init__.py.
                if os.path.isdir(os.path.join(d, seg)):
                    found_pkg = os.path.join(d, seg)
                    break
            if found_pkg is not None:
                search = [found_pkg]
                continue
            if found_mod:
                # Terminal module — anything deeper cannot exist.
                return i == len(parts) - 1
            return False
        return True
    except Exception:  # noqa: BLE001 — any finder blowup means "cannot vouch for it"
        return False


def check_syntax(patched: str) -> tuple:
    """(ok, detail). A SyntaxError is an automatic refusal — #3362."""
    try:
        ast.parse(patched)
        return True, ""
    except SyntaxError as exc:
        return False, f"SyntaxError line {exc.lineno}: {exc.msg}"
    except Exception as exc:  # noqa: BLE001
        return False, f"unparseable: {type(exc).__name__}: {exc}"


def check_new_imports_resolve(original: str, patched: str) -> tuple:
    """Every module the patch ADDS must resolve — #3363, #3366.

    Only NEW imports are probed. A pre-existing unresolvable import is not this patch's
    fault, and failing it would block unrelated fixes to the same file.
    """
    try:
        before = _imported_modules(ast.parse(original))
        after = _imported_modules(ast.parse(patched))
    except SyntaxError:
        return True, ""  # syntax check owns this failure; don't double-report
    added = sorted(after - before)
    bad = [m for m in added if not module_resolves(m)]
    if bad:
        return False, "unresolvable import(s) added: " + ", ".join(bad)
    return True, ""


def check_removed_import_still_used(original: str, patched: str) -> tuple:
    """A name dropped from an import must not still be referenced — #3375 (NameError).

    Re-checks the RAW patched text before failing, because a name can legitimately survive
    only inside a string annotation or a docstring-typed signature, which the AST walk
    above does not see as a Name node. Better to miss a rare case than to block a correct
    patch on one.
    """
    try:
        before_tree, after_tree = ast.parse(original), ast.parse(patched)
    except SyntaxError:
        return True, ""
    removed = _imported_names(before_tree) - _imported_names(after_tree)
    if not removed:
        return True, ""
    used = _referenced_names(after_tree)
    still = sorted(n for n in removed if n in used)
    if still:
        return False, "import removed but name still used: " + ", ".join(still)
    return True, ""


def check_no_unrelated_deletions(original: str, patched: str) -> tuple:
    """A patch must not delete top-level functions/classes — #3355, #3357.

    Both of those claimed to be import fixes while removing live code
    (``omniroute_telemetry_collect``, the ``connect_chaplain`` route). Renames are rare in
    a mechanical fix and would surface here as a deletion — which is the correct outcome:
    a rename is not a mechanical import fix and deserves a human.
    """
    try:
        before, after = _top_level_defs(ast.parse(original)), _top_level_defs(ast.parse(patched))
    except SyntaxError:
        return True, ""
    gone = sorted(before - after)
    if gone:
        return False, "top-level definition(s) deleted: " + ", ".join(gone)
    return True, ""


def _pyflakes_messages(text: str) -> tuple:
    """(set_of_messages, ok). Line numbers stripped — a patch shifts every line below it,
    so comparing raw output would report the whole file as "new". ok=False means pyflakes
    could not run, and the caller must then SKIP this check rather than infer a pass.
    """
    try:
        import io

        from pyflakes.api import check
        from pyflakes.reporter import Reporter
    except ImportError:
        return set(), False
    out, err = io.StringIO(), io.StringIO()
    try:
        check(text or "", "t", Reporter(out, err))
    except Exception:  # noqa: BLE001
        return set(), False
    if err.getvalue().strip():
        return set(), False  # syntax error — the syntax check owns that failure
    msgs = set()
    for line in out.getvalue().splitlines():
        # "t:12:5: 'os' imported but unused" -> "'os' imported but unused"
        msgs.add(line.split(":", 3)[-1].strip())
    return msgs, True


def check_no_new_pyflakes_findings(original: str, patched: str) -> tuple:
    """A patch must not INTRODUCE new static findings — #3348 (used a name it never imported).

    This is the check that caught the long tail. The AST checks above catch a patch that
    deletes something needed; this catches one that ADDS a reference to something that was
    never defined — measured as the single biggest remaining hole (undefined names, plus
    redefinitions and imports the patch added and did not use).

    Compares SETS of messages, not counts: a fix that removes one finding and adds none is
    the whole point, so only genuinely NEW message text fails. Pre-existing findings are
    ignored — this patch is not responsible for them.
    """
    before, ok_b = _pyflakes_messages(original)
    after, ok_a = _pyflakes_messages(patched)
    if not (ok_b and ok_a):
        # CANNOT MEASURE. This returns ok=True — it must, because failing closed on a
        # missing linter would block every patch the moment pyflakes went away — but it
        # says so out loud (F.O.R.G.E. review of #3390: "may lead to false negatives").
        # A gate that quietly drops a check is how "it passed" stops meaning anything.
        # The caller sees checks['no_new_pyflakes_findings']['detail'] naming the skip;
        # the other four checks are unaffected, so the gate degrades, never opens.
        return True, "SKIPPED — pyflakes unavailable or source unparseable; this check did not run"
    introduced = sorted(after - before)
    if introduced:
        shown = "; ".join(introduced[:4])
        more = f" (+{len(introduced)-4} more)" if len(introduced) > 4 else ""
        return False, f"patch introduces new static findings: {shown}{more}"
    return True, ""


def check_no_orphaned_module_refs(original: str, patched: str) -> tuple:
    """A patch that re-points an import must re-point EVERY use of it — #3364.

    #3364 removed `import sqlalchemy` while updating only 2 of its 4 call sites, leaving a
    file that imports one thing and calls another. `removed_import_still_used` catches the
    bare-name case; this catches the DOTTED case, where the old module path survives inside
    an attribute chain or a string that the Name walk never sees.

    Deliberately literal: it looks for the removed module's own text still present in the
    patched source. A false positive is possible (the name appearing in an unrelated
    comment), which is why it reports the module rather than asserting a specific line —
    a human reading the refusal can see immediately whether it is real.
    """
    import re as _re

    try:
        before, after = _imported_modules(ast.parse(original)), _imported_modules(ast.parse(patched))
    except SyntaxError:
        return True, ""
    removed = before - after
    if not removed:
        return True, ""
    orphaned = []
    for mod in sorted(removed):
        # Only meaningful for dotted/attribute-style use; a bare name is already covered.
        if _re.search(r"\b" + _re.escape(mod) + r"\s*\.", patched):
            orphaned.append(mod)
    if orphaned:
        return False, "import re-pointed but old module still referenced: " + ", ".join(orphaned)
    return True, ""


def check_not_semantically_identical(original: str, patched: str) -> tuple:
    """A patch whose parsed form is unchanged did nothing — #3371.

    The plain text comparison in ``validate_patch`` catches a byte-identical patch. This
    catches the subtler one: whitespace, comment or formatting churn that leaves the ACTUAL
    code identical. #3371 rewrote a try/except fallback into something that parsed to the
    same thing. Such a patch still costs a branch, a PR and a review cycle.

    Compares ``ast.dump`` WITHOUT attributes, so line/column shifts do not register as
    change — only structure does.
    """
    try:
        a = ast.dump(ast.parse(original), annotate_fields=True, include_attributes=False)
        b = ast.dump(ast.parse(patched), annotate_fields=True, include_attributes=False)
    except SyntaxError:
        return True, ""
    if a == b:
        return False, "patch is a no-op: the parsed code is identical (formatting/comments only)"
    return True, ""


def validate_patch(original: str, patched: str, file_path: str = "") -> dict:
    """THE predicate. Returns {ok, failures, checks}.

    ``ok`` is True only when every check passes. ``failures`` is a list of human-readable
    reasons suitable for a PR comment or a refusal message. Fails CLOSED: an unexpected
    error in any check is reported as a failure, never swallowed into a pass — this gate
    exists precisely because things that could not run were being approved.
    """
    results = {}
    failures = []

    def run(name, fn, *args):
        try:
            ok, detail = fn(*args)
        except Exception as exc:  # noqa: BLE001
            ok, detail = False, f"check errored: {type(exc).__name__}: {exc}"
        results[name] = {"ok": bool(ok), "detail": detail}
        if not ok:
            failures.append(f"[{name}] {detail}")

    # Order matters only for readability; every check runs so the report is complete
    # rather than stopping at the first problem.
    run("syntax", check_syntax, patched)
    run("new_imports_resolve", check_new_imports_resolve, original, patched)
    run("removed_import_still_used", check_removed_import_still_used, original, patched)
    run("no_unrelated_deletions", check_no_unrelated_deletions, original, patched)
    run("no_new_pyflakes_findings", check_no_new_pyflakes_findings, original, patched)
    run("no_orphaned_module_refs", check_no_orphaned_module_refs, original, patched)
    run("not_semantically_identical", check_not_semantically_identical, original, patched)

    if patched.strip() == (original or "").strip():
        failures.append("[no_op] patch changes nothing")
        results["no_op"] = {"ok": False, "detail": "patched text is identical to the original"}

    return {
        "ok": not failures,
        "failures": failures,
        "checks": results,
        "file_path": file_path,
    }
