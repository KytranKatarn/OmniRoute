"""Reconcile stale code_issues against the current source (#5004).

WHY THIS EXISTS
`code_issues.status` has not been reconciled in over two months. Measured 2026-07-20:

    open   2230   (growing)
    resolved 142  newest row 2026-04-21   <- set only by a manual UI action
    fixed     72  newest row 2026-05-12

Nothing re-checks whether an open finding still exists, so the queue keeps serving findings
that were fixed long ago by unrelated work. Issue #7846 is the proof: it claims
"doc/routes.py line 178 exceeds 120 characters", was created 2026-05-12, and line 178 is now
49 characters. The engine still picked it up on 2026-07-19 and burned an autonomous build
cycle discovering there was nothing to fix.

That also makes the backlog SIZE meaningless, which in turn makes the #4989 drain-yield
numbers meaningless: you cannot compute a fix rate against a denominator full of ghosts.

WHAT IT DOES
Re-validates open findings against the file on disk and marks the provably-gone ones
``resolved_stale``. Deliberately conservative — a finding is only closed when we can READ
the file and DISPROVE the finding. Anything else is left strictly alone:

    verdict False (provably gone)  -> resolved_stale
    verdict True  (still there)    -> untouched
    verdict None  (no checker)     -> untouched, counted as unverifiable
    file missing / synthetic label -> untouched, counted separately

A missing file is NOT treated as "resolved": path resolution can fail for reasons that have
nothing to do with the finding, and silently closing findings on an unreadable path would
hide real work. Deleting a file is handled by the scanner, not here.

NOTE ON DUPLICATION: the equivalent checker in the engine is archie_engine/fix_efficacy.py
(#5003). The platform cannot import from the archie-code repo, so the line-length rule is
restated here. Keep the two in step — both are deliberately tiny and dependency-free.
"""

import logging
import re

from database import get_db_cursor

logger = logging.getLogger(__name__)

RESOLVED_STALE = "resolved_stale"

# "Line exceeds 120 characters (124)" / "line exceeds 120 chars"
_LINE_LEN_RE = re.compile(r"line\s+exceeds\s+(\d+)\s+char", re.IGNORECASE)


def finding_still_reproduces(message: str, file_text: str):
    """Does the finding described by ``message`` still hold for ``file_text``?

    Returns True (still present), False (provably gone), or None (no deterministic checker).
    None is the common case and must never be treated as "gone".
    """
    m = _LINE_LEN_RE.search(message or "")
    if m:
        try:
            limit = int(m.group(1))
        except ValueError:
            return None
        # The stored line NUMBER is ignored: unrelated edits shift lines, so the honest
        # question is whether the file still violates the limit anywhere. Biases toward
        # KEEPING the finding open, which is the safe direction for a closer.
        return any(len(ln) > limit for ln in (file_text or "").splitlines())
    return None


def _read_source(file_path: str):
    """(text, reason) — text is None when the file can't be read. Reuses the pipeline's
    single source of truth for path resolution + #4979 path containment."""
    try:
        from services.audit_pipeline import resolve_proposal_source
    except Exception as exc:  # pragma: no cover - import guard
        return None, f"resolver unavailable: {exc}"

    abs_path, _display, status = resolve_proposal_source(file_path)
    if status != "ok" or not abs_path:
        return None, status
    try:
        with open(abs_path, "r", encoding="utf-8", errors="replace") as fh:
            return fh.read(), "ok"
    except OSError as exc:
        return None, f"unreadable: {exc}"


def reconcile_open_issues(limit: int = 500, dry_run: bool = True) -> dict:
    """Re-validate open findings; close the provably-gone ones.

    ``dry_run=True`` (the default) changes nothing and reports what WOULD be closed, so the
    job can be inspected before it is ever allowed to write.
    """
    stats = {
        "examined": 0,
        "stale": 0,
        "still_present": 0,
        "unverifiable": 0,
        "unreadable": 0,
        "closed": 0,
        "dry_run": dry_run,
        "samples": [],
    }

    with get_db_cursor(commit=False) as (conn, cur):
        cur.execute(
            """SELECT id, file_path, message, line_number
               FROM code_issues
               WHERE status = 'open' AND file_path IS NOT NULL
               ORDER BY id
               LIMIT %s""",
            (limit,),
        )
        rows = cur.fetchall()

    # Cache per file: one read serves every finding in that file (agent_loop.py alone has 485).
    cache: dict = {}
    to_close: list = []

    for row in rows:
        stats["examined"] += 1
        fp = row["file_path"]
        if fp not in cache:
            cache[fp] = _read_source(fp)
        text, reason = cache[fp]
        if text is None:
            stats["unreadable"] += 1
            continue
        verdict = finding_still_reproduces(row["message"] or "", text)
        if verdict is None:
            stats["unverifiable"] += 1
        elif verdict:
            stats["still_present"] += 1
        else:
            stats["stale"] += 1
            to_close.append(row["id"])
            if len(stats["samples"]) < 5:
                stats["samples"].append(
                    {"id": row["id"], "file": fp, "line": row["line_number"], "message": (row["message"] or "")[:70]}
                )

    if to_close and not dry_run:
        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                """UPDATE code_issues
                   SET status = %s, fixed_by = 'reconciler', fixed_at = NOW()
                   WHERE id = ANY(%s) AND status = 'open'""",
                (RESOLVED_STALE, to_close),
            )
            stats["closed"] = cur.rowcount
        logger.info(
            "[code-issue-reconciler] closed %d stale finding(s) of %d examined", stats["closed"], stats["examined"]
        )
    else:
        logger.info(
            "[code-issue-reconciler] dry-run: %d stale / %d examined (%d still present, %d unverifiable)",
            stats["stale"],
            stats["examined"],
            stats["still_present"],
            stats["unverifiable"],
        )
    return stats
