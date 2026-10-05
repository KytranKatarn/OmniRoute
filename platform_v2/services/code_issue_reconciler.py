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

import ast
import io
import logging
import re

from database import get_db_cursor

logger = logging.getLogger(__name__)

RESOLVED_STALE = "resolved_stale"

# "Line exceeds 120 characters (124)" / "line exceeds 120 chars"
_LINE_LEN_RE = re.compile(r"line\s+exceeds\s+(\d+)\s+char", re.IGNORECASE)

# The three detectors that dominate this table after line-length.
_PRINT_RE = re.compile(r"print statement found", re.IGNORECASE)
_TODO_RE = re.compile(r"todo\s*/\s*fixme", re.IGNORECASE)
_BARE_EXCEPT_RE = re.compile(r"bare except", re.IGNORECASE)

# flake8-style code Repair Bay stores on a pyflakes finding ("F401 'os' imported but unused").
_PYFLAKES_CODE_RE = re.compile(r"\b(?:F\d{3}|PYFLAKES)\b", re.IGNORECASE)


def _parse(file_text: str):
    """AST for the source, or None when it does not parse.

    None means "cannot verify" — never "the finding is gone". A file that fails to parse
    must leave its findings open rather than have them silently closed.
    """
    try:
        return ast.parse(file_text or "")
    except (SyntaxError, ValueError):
        return None


# Findings sometimes arrive without a code — recognise pyflakes' own wording too.
_PYFLAKES_PHRASES = (
    "imported but unused",
    "assigned to but never used",
    "undefined name",
    "redefinition of unused",
    "f-string is missing placeholders",
    "unable to detect undefined names",
)


def _pyflakes_findings(file_text: str):
    """(messages, ok) — pyflakes' own text for this source.

    ok is False when the source could not be analysed at all (pyflakes missing, or the file
    does not parse). A syntax error must NEVER read as "the finding is gone": pyflakes emits
    nothing but the syntax error itself, which would otherwise look like a clean file and
    close a finding that is still very much there.
    """
    try:
        from pyflakes.api import check as pyflakes_check
        from pyflakes.reporter import Reporter
    except ImportError:
        return [], False

    out, err = io.StringIO(), io.StringIO()
    try:
        pyflakes_check(file_text or "", "target", Reporter(out, err))
    except Exception:
        return [], False
    if err.getvalue().strip():  # syntax error / unparseable
        return [], False
    return out.getvalue().splitlines(), True


def _needle_from_message(message: str) -> str:
    """Strip the flake8 code prefix, leaving pyflakes' own wording.

    Repair Bay stores "F401 'os' imported but unused"; pyflakes itself emits
    "target:1:1 'os' imported but unused" — no code. Comparing the descriptive tail is what
    makes the two comparable.
    """
    text = _PYFLAKES_CODE_RE.sub("", (message or "").strip(), count=1).strip()
    # ruff quotes names with BACKTICKS (`os`); pyflakes emits 'os'. Without unifying the
    # quoting, every ruff-sourced row read as "provably gone" while still present — the
    # reconciler archived it daily and the next audit recreated it (2026-08-27 oscillator).
    text = text.replace("`", "'")
    return text.strip(" -:")


def finding_still_reproduces(message: str, file_text: str, line_number=None):
    """Does the finding described by ``message`` still hold for ``file_text``?

    Returns True (still present), False (provably gone), or None (no deterministic checker).
    None must never be treated as "gone" — this function decides whether a row gets CLOSED.

    ``line_number`` (optional) makes the line-length check precise instead of whole-file.
    Omitting it preserves the original whole-file behaviour.

    Mirrors archie_engine/fix_efficacy.py (#5003). The platform cannot import from the
    archie-code repo, so the rules are restated. KEEP THE TWO IN STEP.
    """
    if (message or "").startswith("LARGE_FILE "):
        # Match the Python-module scanner's threshold and newline counting.
        # The stored detail is a historical size, not the current threshold.
        return (file_text or "").count("\n") + 1 > 600

    if (message or "").startswith(("DIRECT_OLLAMA", "DIRECT_CLOUD")):
        from services.code_health_checks import direct_call_present

        names = ("call_ollama",) if message.startswith("DIRECT_OLLAMA") else ("call_claude_api", "call_openai_api")
        return direct_call_present(file_text, names)

    # Interface-sweep proposals often survive a corrected import because the
    # generic checker cannot recognize them. Only prove REMOVAL here: keeping
    # the same import means unknown, not a claim that runtime resolution works.
    import_match = re.match(
        r"^(?:WRONG_ROOT_IMPORT|WRONG_SUBMODULE_IMPORT) import (?:from )?'([^']+)'",
        message or "",
    )
    symbol_match = re.match(r"^MISSING_SYMBOL '([^']+)' is not exported by '([^']+)'", message or "")
    if import_match or symbol_match:
        tree = _parse(file_text)
        if tree is None:
            return None
        module = import_match.group(1) if import_match else symbol_match.group(2)
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.level == 0 and node.module == module:
                if import_match or any(alias.name == symbol_match.group(1) for alias in node.names):
                    return None
            if import_match and isinstance(node, ast.Import):
                if any(alias.name == module for alias in node.names):
                    return None
        return False

    m = _LINE_LEN_RE.search(message or "")
    if m:
        try:
            limit = int(m.group(1))
        except ValueError:
            return None
        lines = (file_text or "").splitlines()

        # LINE-PRECISE when we have a usable line number.
        #
        # The whole-file rule ("does this file violate the limit ANYWHERE?") is safe but
        # wildly imprecise on clustered findings: ai_bridge/agent_loop.py carries 422
        # line-length findings while the file actually has FIFTEEN long lines. One survivor
        # kept all 422 open, so the backlog reported 28x its real debt and its size meant
        # nothing — which defeats the point of reconciling at all.
        #
        # TRADE-OFF, stated plainly: if a file was reformatted and the long line MOVED, the
        # cited line is now short and this closes the finding while the problem persists
        # elsewhere. That is acceptable because the scanner re-files it at its new line on the
        # next run, whereas the inflation is permanent and silent. Falls back to the whole-file
        # rule whenever the line number is missing or out of range.
        if line_number and 1 <= int(line_number) <= len(lines):
            return len(lines[int(line_number) - 1]) > limit
        return any(len(ln) > limit for ln in lines)

    msg = message or ""

    # --- the detectors that actually dominate this table (measured 2026-07-20) -------------
    # print 1129 · line-length 725 · SQL injection 275 · TODO/FIXME 31 · secret 10 · bare-except 6
    # Each ignores the stored line NUMBER for the same reason line-length does: unrelated edits
    # shift lines, so the honest question is whether the FILE still exhibits the problem. That
    # biases toward KEEPING findings open, the safe direction for something that closes rows.
    if _PRINT_RE.search(msg):
        tree = _parse(file_text)
        if tree is None:
            return None
        return any(
            isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "print" for n in ast.walk(tree)
        )

    if _BARE_EXCEPT_RE.search(msg):
        tree = _parse(file_text)
        if tree is None:
            return None
        return any(isinstance(n, ast.ExceptHandler) and n.type is None for n in ast.walk(tree))

    if _TODO_RE.search(msg):
        # Deliberately a plain substring scan, not a comment-aware parse: a TODO inside a
        # string still reads as "the marker is present", which keeps the finding open.
        text = file_text or ""
        return ("TODO" in text) or ("FIXME" in text)

    if _PYFLAKES_CODE_RE.search(msg) or any(p in msg.lower() for p in _PYFLAKES_PHRASES):
        needle = _needle_from_message(msg)
        if len(needle) < 8:  # nothing distinctive left to compare
            return None
        findings, ok = _pyflakes_findings(file_text)
        if not ok:
            return None
        # Per-finding match: an unrelated warning elsewhere in the file must not mask a
        # genuine fix, and must not keep a dead finding alive.
        return any(needle in line for line in findings)

    # #6054 -- LAST resort, deliberately scoped to messages NO checker recognised.
    # code_issues #8393 ('performance' prose at line 25847 of a 744-line file) had no
    # deterministic checker, so it returned None here and stayed open forever -- until
    # the engine pulled it and answered with a destructive rewrite (PR #2861). For an
    # unrecognised message the cited line is the ONLY evidence we have, and a line
    # beyond EOF is proof the anchor is dead (the caller skips unreadable files before
    # calling, so file_text is a real read). Recognised classes keep their own
    # fallbacks -- the line-length whole-file rule above stays authoritative, per
    # test_out_of_range_line_falls_back_to_whole_file.
    if line_number:
        try:
            _ln = int(line_number)
        except (TypeError, ValueError):
            _ln = 0
        if _ln > 0 and _ln > len((file_text or "").splitlines()):
            return False

    return None


# --- proposal-side reconciliation (#5004) --------------------------------------------------
# The Consciousness > Code Health tab's Department Orchestration panel reads
# improvement_proposals (source='code_health_audit'), NOT code_issues. Reconciling only
# code_issues therefore never moved the number anyone actually looks at.

# Proposal `detail` carries the finding text WITH a trailing "(line 1008)" that the tool
# itself never emits. Leaving it on makes every pyflakes needle fail to match, so every such
# proposal reads as "gone". Measured: stripping it moved the tally from 385-gone/0-present
# (impossible) to 331-gone/281-present. A 0-present result is the tell that a matcher is
# broken, not that a queue is clean.
_TRAILING_LINE_RE = re.compile(r"\s*\(line \d+\)\s*$")

PROPOSAL_STALE_REASON = "stale:finding_resolved"


def proposal_message(issue_code: str, detail: str) -> str:
    """Finding text for a proposal, normalised for the checkers."""
    joined = " ".join(x for x in (issue_code or "", detail or "") if x).strip()
    return _TRAILING_LINE_RE.sub("", joined).strip()


def finding_fingerprint(issue_code: str, detail: str) -> str:
    """Detector-neutral identity for a finding: code prefix stripped, quoting unified,
    trailing '(line N)' removed. Equal fingerprints mean the SAME defect reported by
    different detectors (ruff F401 vs the static PYFLAKES tier) — the identity that
    creation-time dedup in audit_pipeline keys on, so twin rows for one finding can
    no longer be minted (the 11235/11259 double, 2026-08-27)."""
    return _needle_from_message(proposal_message(issue_code, detail))


def _read_proposal_file(runtime_file: str, file_path: str):
    """Source for a proposal. ``runtime_file`` is the absolute path the scanner already
    resolved, so it is tried first; ``file_path`` falls back through the pipeline's shared
    resolver. Returns None when neither can be read — which never closes anything."""
    import os

    if runtime_file and os.path.isfile(runtime_file):
        try:
            with open(runtime_file, "r", encoding="utf-8", errors="replace") as fh:
                return fh.read()
        except OSError:
            pass
    text, _reason = _read_source(file_path)
    return text


def reconcile_open_proposals(limit: int = 3000, dry_run: bool = True, statuses=("approved",), module_name=None) -> dict:
    """Archive code-health proposals whose finding provably no longer reproduces.

    Same conservative contract as reconcile_open_issues: a proposal is archived ONLY when the
    file can be read AND the finding disproved. Unreadable, unparseable, or no-checker all
    leave the row untouched. dry_run=True by default.

    Archives rather than inventing a status — it matches the existing sweep convention
    (metadata archived_by / archive_reason / archived_at), so provenance stays uniform with
    the #2333 unfixable-path archiver.
    """
    stats = {
        "examined": 0,
        "stale": 0,
        "still_present": 0,
        "unverifiable": 0,
        "unreadable": 0,
        "archived": 0,
        "cards_cancelled": 0,
        "dry_run": dry_run,
        "samples": [],
    }

    module_filter = ""
    params = [list(statuses)]
    if module_name:
        module_filter = """AND (module_name = %s OR metadata->>'module_name' = %s
                            OR metadata->>'file_path' LIKE %s
                            OR metadata->>'file_path' LIKE %s)"""
        # Escape LIKE metacharacters in module keys (e.g. family_tree).
        escaped = module_name.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        params.extend([module_name, module_name, f"platform_v2/tools/{escaped}/%", f"[APP_CORE]/tools/{escaped}/%"])
    params.append(limit)
    with get_db_cursor(commit=False) as (conn, cur):
        cur.execute(
            f"""SELECT id,
                      metadata->>'issue_code'   AS issue_code,
                      metadata->>'detail'       AS detail,
                      metadata->>'runtime_file' AS runtime_file,
                      metadata->>'file_path'    AS file_path,
                      metadata->>'line'         AS line
               FROM improvement_proposals
               WHERE status = ANY(%s)
                 AND metadata->>'source' = 'code_health_audit'
                 {module_filter}
               ORDER BY id
               LIMIT %s""",
            tuple(params),
        )
        rows = cur.fetchall()

    cache: dict = {}
    to_archive: list = []

    for row in rows:
        stats["examined"] += 1
        key = row["runtime_file"] or row["file_path"]
        if key not in cache:
            cache[key] = _read_proposal_file(row["runtime_file"], row["file_path"])
        text = cache[key]
        if text is None:
            stats["unreadable"] += 1
            continue

        line_no = None
        raw_line = (row["line"] or "").strip()
        if raw_line.isdigit():
            line_no = int(raw_line)

        verdict = finding_still_reproduces(proposal_message(row["issue_code"], row["detail"]), text, line_no)
        if verdict is None:
            stats["unverifiable"] += 1
        elif verdict:
            stats["still_present"] += 1
        else:
            stats["stale"] += 1
            to_archive.append(row["id"])
            if len(stats["samples"]) < 5:
                stats["samples"].append(
                    {"id": row["id"], "code": row["issue_code"], "detail": (row["detail"] or "")[:70]}
                )

    if to_archive and not dry_run:
        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                """UPDATE improvement_proposals
                   SET status = 'archived',
                       metadata = COALESCE(metadata, '{}'::jsonb) || jsonb_build_object(
                           'archived_by',   'reconciler_5004',
                           'archive_reason', %s,
                           'archived_at',    NOW()::text)
                   WHERE id = ANY(%s) AND status = ANY(%s)""",
                (PROPOSAL_STALE_REASON, to_archive, list(statuses)),
            )
            stats["archived"] = cur.rowcount
            # An archived proposal's approval cards die WITH it — otherwise a
            # stale ready_for_review twin keeps a live deploy_approve card that
            # the owner can tap only to hit the sandbox gate's "patch does not
            # apply" (6 taps burned on already-fixed findings, 2026-08-28).
            cur.execute(
                """UPDATE autonomy_approval_queue
                   SET status = 'cancelled',
                       rejected_reason = 'proposal archived: finding no longer reproduces (reconciler_5004)',
                       updated_at = NOW()
                   WHERE status = 'pending'
                     AND action_type IN ('deploy_approve', 'improvement_approve_red')
                     AND action_data->>'proposal_id' = ANY(%s)""",
                ([str(pid) for pid in to_archive],),
            )
            stats["cards_cancelled"] = cur.rowcount
        logger.info(
            "[proposal-reconciler] archived %d stale proposal(s) of %d (%d approval card(s) cancelled)",
            stats["archived"],
            stats["examined"],
            stats["cards_cancelled"],
        )
    else:
        logger.info(
            "[proposal-reconciler] dry-run: %d stale / %d examined (%d present, %d unverifiable, %d unreadable)",
            stats["stale"],
            stats["examined"],
            stats["still_present"],
            stats["unverifiable"],
            stats["unreadable"],
        )
    return stats


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
        verdict = finding_still_reproduces(row["message"] or "", text, row.get("line_number"))
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
