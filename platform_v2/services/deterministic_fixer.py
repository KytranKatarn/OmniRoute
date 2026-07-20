"""Deterministic fixes for mechanical pyflakes findings (#4989 drain yield).

WHY THIS EXISTS
The Code-Health drain asks a 7B model to emit FIND/REPLACE text for fixes that are
single-line and mechanical. Measured 2026-07-20, every attempt that day failed:

    07-20 08:27  F401        -> find_not_located
    07-20 03:38  BARE_EXCEPT -> find_not_located
    07-20 03:38  BARE_EXCEPT -> no_change
    07-20 03:37  WRONG_KWARG -> find_ambiguous (x2)

Nothing has reached ready_for_review since 07-19 11:30. The dominant failure is
`find_not_located`: the model's FIND string does not match the file. But look at what these
fixes actually require —

    "'datetime.datetime' imported but unused (line 10)"    -> delete that import line
    "f-string is missing placeholders (line 410)"          -> drop the f prefix

— there is nothing for a language model to decide. This module performs those edits directly
and verifies them with pyflakes, taking the LLM out of the loop entirely.

SCOPE — deliberately the two provably-safe classes only (measured pool of 273):
    unused import on a SINGLE-name line   124   -> delete the line
    f-string missing placeholders          11   -> drop the f prefix

EXPLICITLY EXCLUDED, and these exclusions are the point:
  * __init__.py re-exports (30) — pyflakes flags deliberate re-exports; deleting them breaks
    the public API of a package.
  * multi-name imports (79) — `from x import a, b` needs an edit WITHIN the line; a different
    and more error-prone operation.
  * unused locals (29) — `y = do_thing()` may exist for its SIDE EFFECT. Deleting the
    assignment silently removes the call. Not worth the risk for 29 findings.

EVERY fix is verified before it is offered:
    1. the ORIGINAL finding must be gone from pyflakes output
    2. NO NEW pyflakes finding may appear (catches a delete that broke something)
    3. the file must still parse
Any failure -> the proposal is left untouched. Deploy remains human-gated: a successful fix
lands as `ready_for_review` with a unified diff for review in Repair Bay's Repairs tab.
Nothing here writes to a source file on disk.
"""

import ast
import io
import logging
import re

from database import get_db_cursor

logger = logging.getLogger(__name__)

# "'datetime.datetime' imported but unused" / "`os` imported but unused"
_UNUSED_IMPORT_RE = re.compile(r"[`'\"]([\w.]+)[`'\"]\s+imported but unused", re.IGNORECASE)
_FSTRING_RE = re.compile(r"f-string is missing placeholders", re.IGNORECASE)
_TRAILING_LINE_RE = re.compile(r"\s*\(line \d+\)\s*$")

FIX_KINDS = ("unused_import_single", "fstring_no_placeholder")


def _pyflakes_lines(text: str):
    """(messages, ok). ok is False when pyflakes is unavailable or the source won't parse."""
    try:
        from pyflakes.api import check
        from pyflakes.reporter import Reporter
    except ImportError:
        return [], False
    out, err = io.StringIO(), io.StringIO()
    try:
        check(text or "", "t", Reporter(out, err))
    except Exception:
        return [], False
    if err.getvalue().strip():
        return [], False
    return [ln.split(":", 3)[-1].strip() for ln in out.getvalue().splitlines()], True


def _needle(detail: str) -> str:
    return _TRAILING_LINE_RE.sub("", (detail or "").strip()).strip()


def plan_fix(detail: str, file_text: str, line_number, file_path: str = ""):
    """Return (new_text, kind, description) for a mechanical finding, else None.

    Pure: takes and returns text, touches no disk and no database.
    """
    if not file_text or not line_number:
        return None
    try:
        idx = int(line_number) - 1
    except (TypeError, ValueError):
        return None
    lines = file_text.splitlines(keepends=True)
    if idx < 0 or idx >= len(lines):
        return None
    line = lines[idx]
    detail = detail or ""

    # --- unused import on a single-name line -> delete the line ---------------------------
    m = _UNUSED_IMPORT_RE.search(detail)
    if m:
        if file_path.endswith("__init__.py"):
            return None  # re-export, very likely deliberate
        stripped = line.strip()
        if not (stripped.startswith("import ") or stripped.startswith("from ")):
            return None  # the cited line isn't the import — refuse to guess
        after_import = stripped.split("import", 1)[-1]
        if "," in after_import or "(" in after_import or stripped.endswith("\\"):
            return None  # multi-name / parenthesised / continued — out of scope
        new_lines = lines[:idx] + lines[idx + 1 :]
        return "".join(new_lines), "unused_import_single", f"remove unused import: {stripped}"

    # --- f-string with no placeholders -> drop the f prefix -------------------------------
    if _FSTRING_RE.search(detail):
        # Only the simple, unambiguous case: exactly one f-quote on the line and no braces
        # in the literal (a brace means the placeholder analysis is not this simple).
        if "{" in line or line.count('f"') + line.count("f'") != 1:
            return None
        new_line = re.sub(r"(?<![\w])f(['\"])", r"\1", line, count=1)
        if new_line == line:
            return None
        new_lines = lines[:idx] + [new_line] + lines[idx + 1 :]
        return "".join(new_lines), "fstring_no_placeholder", "drop f prefix from placeholder-less f-string"

    return None


def verify_fix(detail: str, old_text: str, new_text: str):
    """(ok, reason). A fix is accepted only when it removes the finding and adds nothing."""
    try:
        ast.parse(new_text)
    except (SyntaxError, ValueError) as exc:
        return False, f"result does not parse: {exc}"

    before, ok_b = _pyflakes_lines(old_text)
    after, ok_a = _pyflakes_lines(new_text)
    if not (ok_b and ok_a):
        return False, "pyflakes unavailable or source unparseable"

    needle = _needle(detail)
    if any(needle in ln for ln in after):
        return False, "finding still reported after the fix"

    # No NEW finding may appear — catches a delete that broke something else.
    introduced = [ln for ln in after if ln not in before]
    if introduced:
        return False, f"fix introduced a new finding: {introduced[0][:90]}"
    return True, "finding removed, nothing introduced"


def run_deterministic_fixes(limit: int = 200, dry_run: bool = True) -> dict:
    """Generate + verify mechanical fixes and offer them as ready_for_review proposals.

    dry_run=True (default) computes and verifies everything but writes nothing.
    """
    from services.audit_pipeline import _build_fix_diff, resolve_proposal_source

    stats = {"examined": 0, "planned": 0, "verified": 0, "rejected": 0, "offered": 0, "dry_run": dry_run, "samples": []}
    accepted = []

    with get_db_cursor(commit=False) as (conn, cur):
        cur.execute(
            """SELECT id, metadata->>'detail' AS detail, metadata->>'line' AS line,
                      COALESCE(NULLIF(metadata->>'file_path',''), metadata->>'runtime_file') AS file_path,
                      metadata
               FROM improvement_proposals
               WHERE status = 'approved'
                 AND metadata->>'source' = 'code_health_audit'
                 AND metadata->>'dispatch_attempted' IS NULL
                 AND metadata->>'issue_code' IN ('PYFLAKES','F401','F541')
               ORDER BY id
               LIMIT %s""",
            (limit,),
        )
        rows = cur.fetchall()

    for row in rows:
        stats["examined"] += 1
        abs_path, rel_path, status = resolve_proposal_source(row["file_path"])
        if status != "ok" or not abs_path:
            continue
        try:
            with open(abs_path, "r", encoding="utf-8", errors="replace") as fh:
                old_text = fh.read()
        except OSError:
            continue

        planned = plan_fix(row["detail"], old_text, row["line"], abs_path)
        if not planned:
            continue
        new_text, kind, description = planned
        stats["planned"] += 1

        ok, reason = verify_fix(row["detail"], old_text, new_text)
        if not ok:
            stats["rejected"] += 1
            continue
        stats["verified"] += 1

        diff_text, _diff_stats = _build_fix_diff(old_text, new_text, rel_path)
        accepted.append((row["id"], diff_text, kind, description))
        if len(stats["samples"]) < 5:
            stats["samples"].append({"id": row["id"], "kind": kind, "what": description[:70], "file": rel_path})

    if accepted and not dry_run:
        import json as _json

        with get_db_cursor(commit=True) as (conn, cur):
            for pid, diff_text, kind, description in accepted:
                cur.execute(
                    """UPDATE improvement_proposals
                       SET code_changes = %s,
                           status = 'ready_for_review',
                           metadata = COALESCE(metadata,'{}'::jsonb) || %s::jsonb
                       WHERE id = %s AND status = 'approved'""",
                    (
                        diff_text,
                        _json.dumps(
                            {
                                "fixed_by": "deterministic_fixer",
                                "fix_kind": kind,
                                "fix_description": description,
                                "dispatch_attempted": "deterministic",
                            }
                        ),
                        pid,
                    ),
                )
                stats["offered"] += cur.rowcount
        logger.info("[deterministic-fixer] offered %d verified fix(es) for review", stats["offered"])
    else:
        logger.info(
            "[deterministic-fixer] dry-run: %d planned, %d verified, %d rejected of %d examined",
            stats["planned"],
            stats["verified"],
            stats["rejected"],
            stats["examined"],
        )
    return stats
