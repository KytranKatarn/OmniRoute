"""Review COVERAGE — a verdict may not out-run what the model actually read (#5836).

ADR-001 (#947) built four review-integrity gates: GROUNDING (is the cited line real?),
POLARITY (is it an ADDED line?), CLAIM (is the assertion checkable from a diff?), and
SEVERITY (does the label match the content?). All four ask whether a finding ABOUT the
diff is sound. **None of them asks whether the model SAW the diff.**

Measured 2026-08-19 on PR #2713 — 35,621 chars, 5 files, cap 18,768:

    kept    .claude/rules/module-capability-index.md, services/predeploy_scope.py
    dropped services/proposal_service.py  (the actual behaviour change)
            tests/test_predeploy_scope.py (17 tests)
            tools/backup_manager/routes_restore.py

    F.O.R.G.E.: "The diff shows no relevant changes to the codebase, only a markdown
                 file update which does not impact the functionality. ... VERDICT: APPROVE"

A confident approval of 49% of a PR that changes a pre-deploy BACKUP path — and the
model's own words show it believed it had seen everything.

WHY THE EXISTING GATES CANNOT CATCH IT
The #5009 ungrounded-APPROVE floor counts `evidence_not_in_diff`. A dropped file produces
NO finding at all — there is nothing to be ungrounded about. Silence reads as clean.

THE AMPLIFIER (why this is not a rare edge case)
A ONE-LINE edit to `.claude/rules/module-capability-index.md` produced a 10,837-char diff
— 58% of the whole budget — because that file has single multi-KB lines, so a one-line
change emits the entire old line plus the entire new line. And `.claude/...` sorts FIRST
in a GitHub diff, so it consumes the budget BEFORE any code is reached. Every PR that
touches a rules file is therefore at risk of having its CODE go unreviewed.

THE FIX, AND WHY IT IS SHAPED THIS WAY
`annotate` APPENDS a coverage block ending in `VERDICT: NEEDS REVIEW`. It does NOT rewrite
the model's text:

  * `parse_verdict` tests NEEDS **before** APPROVE, so the canonical verdict flips and
    `verdict_is_approved()` -> False, which makes `_automerge_governance_ok` fail closed
    with no change needed there. Gate the CHOKE POINT, never per-caller.
  * NEEDS REVIEW is already in the vocabulary — no new state to plumb through five call
    sites, and every consumer already handles it.
  * It is deliberately NOT REQUEST CHANGES. The model found nothing wrong with what it
    DID read; manufacturing a blocking finding would be its own failure mode (the exact
    thing ADR-001's four gates exist to prevent). "I could not see all of it" is an
    honest third answer.
  * The model's original words survive verbatim, because a human reading the review needs
    to know what WAS examined, not just what was not.
"""

from __future__ import annotations

import re
from typing import Iterable

# A GitHub unified diff starts each file with `diff --git a/<path> b/<path>`.
_FILE_RE = re.compile(r"^diff --git a/(\S+)", re.MULTILINE)

# Marker so an already-annotated summary is never annotated twice (a review can be
# re-driven, and `_obtain_review_summary` may return a retried summary).
MARKER = "[review-coverage]"


def diff_files(diff: str | None) -> list:
    """File paths in a unified diff, in the order GitHub emits them."""
    if not diff:
        return []
    return _FILE_RE.findall(diff)


def coverage(full_diff: str | None, shown_diff: str | None) -> dict:
    """What the reviewer actually saw.

    Returns ``{total, reviewed, dropped: [paths], complete: bool}``.

    ``complete`` is True when nothing was dropped — including the degenerate case of a
    diff with no parseable file headers, where we cannot tell and must not cry wolf. A
    diff that yields zero files also yields zero dropped files, so an unparseable diff
    behaves exactly as it does today rather than blocking every review.
    """
    full = diff_files(full_diff)
    shown = set(diff_files(shown_diff))
    dropped = [f for f in full if f not in shown]
    return {
        "total": len(full),
        "reviewed": len(full) - len(dropped),
        "dropped": dropped,
        "complete": not dropped,
    }


def coverage_note(cov: dict, *, max_listed: int = 12) -> str:
    """Human-readable coverage block. Lists the dropped paths — a count alone does not
    tell a reviewer whether the missing file was a README or the deploy path."""
    dropped = list(cov.get("dropped") or [])
    shown = dropped[:max_listed]
    more = len(dropped) - len(shown)
    lines = [
        f"{MARKER} COVERAGE: {cov.get('reviewed', 0)} of {cov.get('total', 0)} files were "
        "in the diff window this review actually read.",
        "NOT REVIEWED (truncated away before the model saw them):",
    ]
    lines += [f"  - {p}" for p in shown]
    if more > 0:
        lines.append(f"  - ...and {more} more")
    lines += [
        "",
        "A verdict cannot cover a file the reviewer never read, so this review is recorded "
        "as NEEDS REVIEW rather than an approval (#5836). The findings above still stand "
        "for the files that WERE read.",
        "VERDICT: NEEDS REVIEW",
    ]
    return "\n".join(lines)


def annotate(summary: str | None, cov: dict) -> str | None:
    """Append the coverage block when files were dropped; otherwise return unchanged.

    Idempotent — an already-annotated summary is returned as-is, so re-driving a review
    or a structured retry cannot stack blocks.
    """
    if not summary or cov.get("complete", True):
        return summary
    if MARKER in summary:
        return summary
    return f"{summary}\n\n{coverage_note(cov)}"


def dropped_files_for(full_diff: str | None, shown_diff: str | None) -> list:
    """Convenience for callers that only need the dropped list (logging/telemetry)."""
    return coverage(full_diff, shown_diff)["dropped"]


def summarize(cov: dict) -> str:
    """One-line form for logs."""
    if cov.get("complete", True):
        return f"full coverage ({cov.get('total', 0)} files)"
    return "PARTIAL: %d/%d files reviewed; dropped=%s" % (
        cov.get("reviewed", 0),
        cov.get("total", 0),
        ",".join(cov.get("dropped") or []),
    )


def is_low_signal_path(path: str, patterns: Iterable[str] = ()) -> bool:
    """True when a path is documentation/config noise rather than reviewable code.

    Provided so a caller can DE-PRIORITISE such files in the diff window. Deliberately
    NOT used to hide them from the coverage count: a dropped file is still a file the
    reviewer did not read, whatever it contains, and the honest number is the point.
    """
    p = (path or "").lower()
    for pat in patterns:
        if pat and re.search(pat, p):
            return True
    return False


# ---------------------------------------------------------------------------
# ORDERING — spend a limited diff window on CODE first (#5836 follow-up)
#
# Coverage (above) makes a partial review honest. Ordering makes it RARER, by deciding
# WHICH files survive truncation instead of leaving it to alphabetical accident.
#
# GitHub emits diff files alphabetically, so `.claude/rules/...` sorts FIRST — ahead of
# everything. Measured 2026-08-19 on PR #2713: a ONE-LINE edit to
# .claude/rules/module-capability-index.md produced a 10,837-char diff (58% of an 18,768
# budget) because that file's lines are multi-KB, so a one-line change emits the whole old
# line plus the whole new line. It consumed the window before any code was reached, and the
# review that came back described the PR as "only a markdown file update" — while approving
# a change to a pre-deploy BACKUP path.
#
# BANDS, and why tests are NOT last:
#   0 code   — the behaviour under review
#   1 tests  — a sliced-off test file is the documented cause of the false "no tests added"
#              flag (see _truncate_diff's docstring). Demoting tests BELOW docs would
#              manufacture that false finding on exactly the PRs that do add tests.
#   2 docs / generated / lockfiles — real changes, but the least reviewable per byte.
#
# Ordering is applied ONLY when the diff would actually truncate. A diff that fits is passed
# through byte-identical, so the overwhelming majority of reviews see no behaviour change at
# all — the change is confined to the case it exists to fix.
#
# Reordering is safe because a unified diff is a concatenation of INDEPENDENT per-file
# blocks, each carrying its own `diff --git` header. Nothing is added or removed, so
# `coverage()` (a set comparison) stays exactly as honest either way.

_TEST_RE = re.compile(r"(^|/)(tests?|spec)/|(^|/)test_[^/]*$|_test\.[^/]+$|\.spec\.[^/]+$")
_DOC_RE = re.compile(
    r"\.(md|rst|txt|adoc)$"
    r"|^\.claude/"
    r"|(^|/)docs?/"
    r"|(^|/)(changelog|license|notice|authors|codeowners)"
    r"|(-|\.)lock$|lock\.json$|\.min\.(js|css)$|\.snap$",
    re.IGNORECASE,
)


def file_band(path: str) -> int:
    """0 = code, 1 = tests, 2 = docs/generated. Lower is reviewed first."""
    p = (path or "").strip()
    if _DOC_RE.search(p):
        return 2
    if _TEST_RE.search(p):
        return 1
    return 0


def split_blocks(diff: str | None) -> list:
    """Split a unified diff into (path, block) pairs, preserving each block verbatim.

    Anything before the first `diff --git` (rare preamble) is returned under the path
    ``""`` so it is never silently dropped.
    """
    if not diff:
        return []
    marks = [(m.start(), m.group(1)) for m in _FILE_RE.finditer(diff)]
    if not marks:
        return [("", diff)]
    blocks = []
    if marks[0][0] > 0:
        blocks.append(("", diff[: marks[0][0]]))
    for i, (start, path) in enumerate(marks):
        end = marks[i + 1][0] if i + 1 < len(marks) else len(diff)
        blocks.append((path, diff[start:end]))
    return blocks


def prioritize(diff: str | None, cap: int | None = None) -> str | None:
    """Reorder a diff so code precedes tests precedes docs — only when it would truncate.

    ``cap`` is the truncation budget. When it is None, or the diff already fits, the diff is
    returned UNCHANGED (byte-identical), because reordering a diff the model will see in
    full changes presentation for no benefit.

    The sort is STABLE, so within a band GitHub's original ordering is preserved.
    """
    if not diff or cap is None or len(diff) <= cap:
        return diff
    blocks = split_blocks(diff)
    if len(blocks) < 2:
        return diff
    # A leading preamble (path "") must stay at the front — it is not a file block.
    preamble = [b for b in blocks if b[0] == ""]
    files = [b for b in blocks if b[0] != ""]
    files.sort(key=lambda pb: file_band(pb[0]))  # stable: ties keep original order
    return "".join(b for _, b in preamble + files)
