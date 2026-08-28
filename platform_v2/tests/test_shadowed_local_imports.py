"""A local `import X` nested in a branch makes X function-LOCAL everywhere (#6022).

Python binds a name assigned anywhere in a function as local for the ENTIRE function body,
and an `import` is an assignment. So this is an UnboundLocalError waiting to happen:

    def handle(action):
        if action == "proposal":
            import threading                 # <- binds `threading` LOCAL to handle()
            threading.Thread(...).start()
        if action == "linkedin":
            threading.Thread(...).start()    # <- UnboundLocalError on this path

Measured live on 2026-08-25: `ai_bridge/agent_loop.py::_execute_approved_action` did exactly
this. The import sat in an `else:` branch for non-audit proposals; the LinkedIn first-comment
path 536 lines below never passed through it. Result:

    INFO  LinkedIn post approved and executed: success=True
    WARN  First comment thread failed: cannot access local variable 'threading' ...

7 occurrences in a 20-minute window. The post succeeded and the first comment silently did
not, because the failure was swallowed by `except Exception as fc_err: logger.warning(...)`.
Same "best-effort except hides a dead feature" family as the skill_failure_alerts bug in
PR #2812.

⚠️ THE PREDICATE IS NESTING, NOT LINE ORDER. The first instinct — "flag a use whose lineno is
below the local import" — finds NOTHING here: both uses (6394, 6917) are lexically AFTER the
import (6381). What matters is whether the use can be REACHED without executing the import,
i.e. whether the import is nested inside a branch the use sits outside of. A line-order check
would have passed this file while the bug was live.
"""

import ast
from pathlib import Path


# Repo root: search for a marker rather than counting parents — inside the test container
# platform_v2 is mounted AS /app, so parents[N] does not mean what it means on the host
# (the #5994 trap).
_MARKER = Path("ai_bridge") / "agent_loop.py"


def _find_repo() -> Path:
    for base in list(Path(__file__).resolve().parents) + [Path("/mnt/archie_brain")]:
        if (base / _MARKER).exists():
            return base
    return Path("/mnt/archie_brain")


REPO = _find_repo()

# Scanned trees. Kept explicit so adding a tree is a deliberate act.
_SCAN = [REPO / "ai_bridge", REPO / "platform_v2" / "services"]

_SKIP_PARTS = {"__pycache__", "tests", "migrations", ".venv", "node_modules"}


def _imported_names(node: ast.AST):
    """Names an import statement BINDS in the enclosing scope."""
    out = []
    if isinstance(node, ast.Import):
        for a in node.names:
            # `import a.b.c` binds `a`; `import a.b as ab` binds `ab`
            out.append(a.asname or a.name.split(".")[0])
    elif isinstance(node, ast.ImportFrom):
        for a in node.names:
            if a.name != "*":
                out.append(a.asname or a.name)
    return out


def _own_nodes(fn):
    """Walk a function WITHOUT descending into nested function/class scopes.

    An import inside an inner def binds in the INNER scope, so attributing it to the outer
    function would be a false positive — and agent_loop.py is full of inner `_run_*` helpers.
    """
    for child in ast.iter_child_nodes(fn):
        stack = [child]
        while stack:
            n = stack.pop()
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)):
                continue
            yield n
            stack.extend(ast.iter_child_nodes(n))


def _guarded_regions(fn):
    """Yield (node, field, stmt_list) for every conditionally-executed statement list.

    A BRANCH, not a statement: `if:` and `else:` are separate regions, and the span of one
    must never be credited to the other.
    """
    _BLOCKS = {
        ast.If: ("body", "orelse"),
        ast.Try: ("body", "orelse", "finalbody"),
        ast.For: ("body", "orelse"),
        ast.AsyncFor: ("body", "orelse"),
        ast.While: ("body", "orelse"),
        ast.With: ("body",),
        ast.AsyncWith: ("body",),
    }
    for node in _own_nodes(fn):
        fields = _BLOCKS.get(type(node))
        if not fields:
            continue
        for field in fields:
            body = getattr(node, field, None)
            if body:
                yield node, field, body
        # except-handler bodies are conditional too
        for h in getattr(node, "handlers", []) or []:
            if h.body:
                yield node, "handler", h.body


def _try_guarantees_binding(node, names):
    """True when reaching code AFTER this `try` proves the import ran.

    Two correct, extremely common idioms — neither is a defect, and both dominate the
    codebase's optional-dependency handling:

        try:                                    try:
            from database import get_db_cursor      import ujson
        except Exception:                       except ImportError:
            return {"error": ...}    <- exits       ujson = None      <- rebinds

    In the first, control cannot reach the rest of the function unless the import
    succeeded. In the second the name is bound on every path. Treating either as a
    violation is what took the sweep from 3 real findings to 41.
    """
    if not isinstance(node, ast.Try):
        return False
    if not node.handlers:
        return False
    for h in node.handlers:
        rebinds = any(
            (isinstance(s, ast.Name) and isinstance(s.ctx, ast.Store) and s.id in names)
            or (isinstance(s, (ast.Import, ast.ImportFrom)) and set(_imported_names(s)) & names)
            # a fallback `def claude_request(...)` in the handler binds the name too
            or (isinstance(s, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and s.name in names)
            for s in ast.walk(h)
        )
        # A handler that falls through leaves the name unbound for the code below.
        terminates = bool(h.body) and isinstance(h.body[-1], (ast.Return, ast.Raise, ast.Continue, ast.Break))
        if not (rebinds or terminates):
            return False
    return True


def find_shadowed_local_imports(source: str, filename: str = "<src>"):
    """Return [(function, name, import_line, use_line)] for reachable-without-import uses."""
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:  # a parse failure is a different problem; report, don't mask
        return [("<syntax-error>", str(exc), 0, 0)]

    findings = []
    for fn in ast.walk(tree):
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue

        # Statements directly in the function body are on EVERY path through it.
        top_level = {id(s) for s in fn.body}
        # Imports belonging to THIS function's own scope (not an inner def's).
        own_import_ids = {id(n) for n in _own_nodes(fn) if isinstance(n, (ast.Import, ast.ImportFrom))}
        guaranteed: set = set()

        nested_imports = []  # (names, block_start, block_end, import_line)
        for parent, field, body in _guarded_regions(fn):
            for n in body:
                if not isinstance(n, (ast.Import, ast.ImportFrom)):
                    continue
                if id(n) in top_level:
                    continue
                names = set(_imported_names(n))
                if not names:
                    continue
                # An import inside an INNER def belongs to that def's scope. ast.walk(parent)
                # descends into nested functions, so without this the `import time` inside
                # loop_service's `_backoff_trigger`/`_delayed_trigger` closures was attributed
                # to the enclosing function — a pure false positive.
                if id(n) not in own_import_ids:
                    continue
                if _try_guarantees_binding(parent, names):
                    # Binding IS guaranteed past this try, so the name is safe for the whole
                    # rest of the function. Merely skipping the block (the first version) left
                    # later uses matched against NO block and reported them as unbound.
                    guaranteed.update(names)
                    continue
                # Span of the BRANCH the import sits in, NOT of the whole statement.
                # Using the ast.If node's span covers if AND else, so an import in the
                # `else:` looked like it guarded uses in the `if:` — and, fatally, an
                # `if/else` spanning 600 lines swallowed a use 536 lines below. That made
                # the guard BLIND to #6022, the exact bug it was written for.
                blk_start = body[0].lineno
                blk_end = getattr(body[-1], "end_lineno", None) or body[-1].lineno
                nested_imports.append((names, blk_start, blk_end, n.lineno))

        if not nested_imports:
            continue

        # Names bound on EVERY path through the function:
        #   - imported at the function's top level
        #   - PARAMETERS (already bound at call time)
        #   - assigned by an unconditional top-level statement
        # The last two are the "lazy default" idiom, which is correct and common:
        #     if dispatch_fn is None:
        #         from ... import dispatch as dispatch_fn   # rebinds a PARAMETER
        # `dispatch_fn` can never be unbound there, so flagging it is a false positive.
        safe = set()
        a = fn.args
        for arg in [*getattr(a, "posonlyargs", []), *a.args, *a.kwonlyargs]:
            safe.add(arg.arg)
        for extra in (a.vararg, a.kwarg):
            if extra:
                safe.add(extra.arg)
        for s in fn.body:
            if isinstance(s, (ast.Import, ast.ImportFrom)):
                safe.update(_imported_names(s))
            elif isinstance(s, ast.Assign):
                for t in s.targets:
                    if isinstance(t, ast.Name):
                        safe.add(t.id)
            elif isinstance(s, (ast.AnnAssign, ast.AugAssign)) and isinstance(s.target, ast.Name):
                safe.add(s.target.id)
        # The lazy-default idiom is frequently wrapped in a try:, so the guarding assignment
        # is not a top-level statement:
        #     try:
        #         _dispatch = dispatch            <- binds unconditionally
        #         if _dispatch is None:
        #             from ... import dispatch as _dispatch
        # Any plain `name = ...` in this function's own scope is therefore treated as binding.
        # This trades some sensitivity for precision; it does NOT weaken the #6022 case, where
        # `threading` is never assigned outside the import (pinned by the negative control).
        for s in _own_nodes(fn):
            if isinstance(s, ast.Assign):
                for t in s.targets:
                    if isinstance(t, ast.Name):
                        safe.add(t.id)

        # Group guarding blocks BY NAME. A name is frequently imported in SEVERAL branches
        # (agent_loop.py imports `sys` in a dozen of them), and a use sitting in branch B is
        # protected by B's own import — it does not care that branch A also imports the name.
        # Checking a use against ONE block instead of ALL blocks for that name reported 80
        # findings where there were 3: every additional import of a name turned every other
        # branch's legitimate use into a false positive.
        blocks_by_name: dict = {}
        first_import_line: dict = {}
        for names, blk_start, blk_end, imp_line in nested_imports:
            for nm in names:
                blocks_by_name.setdefault(nm, []).append((blk_start, blk_end))
                first_import_line.setdefault(nm, imp_line)

        for nm, blocks in blocks_by_name.items():
            if nm in safe or nm in guaranteed:
                continue
            for use in ast.walk(fn):
                if not (isinstance(use, ast.Name) and isinstance(use.ctx, ast.Load)):
                    continue
                if use.id != nm:
                    continue
                if any(s <= use.lineno <= e for s, e in blocks):
                    continue
                findings.append((fn.name, nm, first_import_line[nm], use.lineno))
    return findings


# --------------------------------------------------------------------------- predicate tests
# Negative controls first: a guard that cannot fail is worse than no guard.


def test_detects_the_exact_6022_shape():
    """The real bug: import in one branch, use in a sibling branch."""
    src = (
        "def handle(action):\n"
        "    if action == 'proposal':\n"
        "        import threading\n"
        "        threading.Thread(target=None).start()\n"
        "    if action == 'linkedin':\n"
        "        threading.Thread(target=None).start()\n"
    )
    found = find_shadowed_local_imports(src)
    assert found, "the #6022 shape MUST be detected"
    assert found[0][1] == "threading"


def test_line_order_alone_would_miss_it():
    """Pins the lesson: every use is lexically AFTER the import, and it is still a bug."""
    src = (
        "def handle(a):\n" "    if a == 1:\n" "        import threading\n" "    threading.Thread(target=None).start()\n"
    )
    found = find_shadowed_local_imports(src)
    assert found, "a use after the import line is still unreachable-safe only if nesting allows"


def test_top_level_local_import_is_fine():
    """Imported directly in the function body = bound on every path."""
    src = "def handle(a):\n    import threading\n    if a:\n        threading.Thread(target=None)\n"
    assert find_shadowed_local_imports(src) == []


def test_use_confined_to_the_guarding_block_is_fine():
    src = (
        "def handle(a):\n" "    if a:\n" "        import threading\n" "        threading.Thread(target=None).start()\n"
    )
    assert find_shadowed_local_imports(src) == []


def test_try_except_importerror_fallback_is_not_flagged():
    """`try: import x / except ImportError: x = None` binds on every path."""
    src = (
        "def handle(a):\n"
        "    try:\n"
        "        import ujson\n"
        "    except ImportError:\n"
        "        ujson = None\n"
        "    return ujson\n"
    )
    assert find_shadowed_local_imports(src) == []


def test_import_inside_a_NESTED_function_is_not_attributed_to_the_outer():
    """An inner def has its own scope — flagging it would be a false positive, and
    agent_loop.py is full of inner `_run_*` helpers that import locally on purpose."""
    src = (
        "def outer(a):\n"
        "    if a:\n"
        "        def inner():\n"
        "            import threading\n"
        "            return threading\n"
        "        return inner\n"
    )
    assert find_shadowed_local_imports(src) == []


def test_module_level_import_shadowed_by_a_nested_one_is_still_flagged():
    """The module-level import does NOT save you: the local binding wins for the whole
    function. This is precisely why the #6022 fix had to REMOVE the nested import, not
    merely add a module-level one."""
    src = (
        "import threading\n"
        "def handle(a):\n"
        "    if a:\n"
        "        import threading\n"
        "    threading.Thread(target=None).start()\n"
    )
    assert find_shadowed_local_imports(src), "a nested import shadows the module-level one"


def test_a_name_imported_in_EVERY_branch_that_uses_it_is_not_flagged():
    """The false-positive that made the first sweep report 80 findings instead of 3.

    agent_loop.py imports `sys` inside a dozen different branches. Checking a use against
    only ONE of those blocks made every other branch's perfectly-guarded use look unbound.
    A use is safe if it falls inside ANY block importing that name.
    """
    src = (
        "def handle(a):\n"
        "    if a == 1:\n"
        "        import sys\n"
        "        print(sys.path)\n"
        "    if a == 2:\n"
        "        import sys\n"
        "        print(sys.argv)\n"
    )
    assert find_shadowed_local_imports(src) == []


def test_but_a_use_outside_EVERY_importing_branch_is_still_flagged():
    """The complement — proves the fix above did not simply disable the check."""
    src = (
        "def handle(a):\n"
        "    if a == 1:\n"
        "        import sys\n"
        "        print(sys.path)\n"
        "    if a == 2:\n"
        "        import sys\n"
        "        print(sys.argv)\n"
        "    print(sys.version)\n"
    )
    assert find_shadowed_local_imports(src), "a use outside all importing branches is unbound"


# ------------------------------------------------------------------------------- repo sweep


# Findings the AST cannot prove safe. EMPTY, and it should stay that way.
#
# It briefly held two "flag-guarded optional import" entries — an import in a try whose
# handler set a BOOLEAN (or a sentinel string), with every use wrapped in `if <flag>:`.
# Correct at runtime, unprovable statically. Both were fixed instead of tolerated, by
# binding the name to None on the failure path:
#
#     except Exception:
#         execute_tool = None          <- now bound on EVERY path
#         tools_enabled = False
#
# That is strictly better than an allowlist entry. The flag stays the real control, the
# UnboundLocalError class is gone, and nothing has to remember why an exception was fine.
#
# ⚠️ Before adding an entry here, try that two-line fix first. An allowlist entry says
# "known safe" to every future reader, and stays saying it long after the code moves —
# which is exactly how the class this file guards against survives.
#
# Entries are (file_suffix, function, name). test_the_allowlist_only_shrinks fails if one
# stops firing, so a fixed entry cannot linger.
_ALLOWED: set = set()


def _py_files():
    for root in _SCAN:
        if not root.exists():
            continue
        for p in root.rglob("*.py"):
            if _SKIP_PARTS & set(p.parts):
                continue
            yield p


def test_no_shadowed_local_imports_in_the_scanned_trees():
    violations = []
    scanned = 0
    for p in _py_files():
        scanned += 1
        rel = str(p.relative_to(REPO))
        for fn, name, imp, use in find_shadowed_local_imports(p.read_text(errors="replace"), str(p)):
            if (rel, fn, name) in _ALLOWED:
                continue
            violations.append(
                f"{p.relative_to(REPO)}::{fn} — '{name}' imported at line {imp} inside a branch, used at line {use}"
            )

    # Guard the guard: if the sweep silently scanned nothing, an empty result is not a pass.
    assert scanned > 20, f"sweep only reached {scanned} files — check _SCAN paths"

    assert not violations, (
        "Nested local import(s) that shadow a name used outside the guarding block.\n"
        "This raises UnboundLocalError on any path that skips the import — see #6022.\n"
        "Fix: import at MODULE level and delete the nested import.\n\n" + "\n".join(violations)
    )


def test_the_allowlist_only_shrinks():
    """An allowlist entry that no longer fires must be REMOVED, not left to rot.

    Same lesson as #2811's stub-leak allowlist: an entry annotated "known safe" outlives the
    condition it described, and the next reader trusts it. If one of these gets fixed, this
    test fails and the entry comes out.
    """
    live = set()
    for p in _py_files():
        rel = str(p.relative_to(REPO))
        for fn, name, _imp, _use in find_shadowed_local_imports(p.read_text(errors="replace")):
            live.add((rel, fn, name))

    stale = _ALLOWED - live
    assert not stale, "These _ALLOWED entries no longer produce a finding — delete them:\n" + "\n".join(
        f"  {e}" for e in sorted(stale)
    )


# --------------------------------------------------- runtime proof of the chosen fix shape
# The sweep above is static. These two execute the actual Python semantics, so the claim
# "binding the name in the handler removes the failure mode" is demonstrated, not asserted.


def _run(src):
    """exec a snippet and call handle(); return the exception type or None."""
    ns: dict = {}
    exec(compile(src, "<shape>", "exec"), ns)
    try:
        ns["handle"]()
    except Exception as exc:  # noqa: BLE001 — the exception IS the result here
        return type(exc).__name__
    return None


_UNFIXED = (
    "def handle():\n"
    "    try:\n"
    "        from nonexistent_module_xyz import helper\n"
    "        enabled = True\n"
    "    except Exception:\n"
    "        enabled = False\n"
    "    if not enabled:\n"
    "        return None\n"
    "    return helper()\n"
)

_FIXED = (
    "def handle():\n"
    "    try:\n"
    "        from nonexistent_module_xyz import helper\n"
    "        enabled = True\n"
    "    except Exception:\n"
    "        helper = None\n"
    "        enabled = False\n"
    "    if not enabled:\n"
    "        return None\n"
    "    return helper()\n"
)


def test_the_flag_guard_alone_survives_only_while_the_guard_is_correct():
    """With the flag checked, the UNFIXED shape does not raise — which is exactly why the
    two allowlisted cases were 'safe'. It is a property of the GUARD, not of the code."""
    assert _run(_UNFIXED) is None


def test_removing_the_guard_from_the_UNFIXED_shape_raises_NameError():
    """The failure mode the fix eliminates. Drop the `if not enabled: return` line — as any
    future refactor might — and the unfixed shape is an UnboundLocalError."""
    unguarded = _UNFIXED.replace("    if not enabled:\n        return None\n", "")
    # UnboundLocalError subclasses NameError, but type(exc).__name__ is the SUBCLASS name.
    assert _run(unguarded) == "UnboundLocalError"


def test_the_FIXED_shape_survives_losing_its_guard():
    """The point of binding in the handler: the code is correct even if the guard is later
    removed or bypassed. This is what took both entries off the allowlist."""
    unguarded = _FIXED.replace("    if not enabled:\n        return None\n", "")
    assert _run(unguarded) == "TypeError", "None is not callable — a clear error, not an unbound name"
