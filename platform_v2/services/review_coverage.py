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

    ``complete`` is True when nothing was dropped AND nothing was cut short — including
    the degenerate case of a diff with no parseable file headers, where we cannot tell and
    must not cry wolf. A diff that yields zero files also yields zero dropped files, so an
    unparseable diff behaves exactly as it does today rather than blocking every review.

    ⚠️ PRESENCE IS NOT COVERAGE (#5910). This compared file PATHS only until 2026-08-22,
    which made it BLIND to the single-file case: a PR whose diff exceeds the window but
    contains ONE file loses no whole file, so ``dropped`` was empty, ``complete`` was True,
    and it recorded a clean APPROVE while the reviewer had seen only part of the change.
    Measured on PR #2749: 8,135 of 13,379 chars shown — **60%** — reported as full
    coverage and merged on that basis. That is #5836's own failure mode in a shape #5836
    could not see. So we now also compare BYTES PER FILE: a file present but SHORTER than
    in the full diff was truncated mid-way and is reported ``partial``.
    """
    full = diff_files(full_diff)
    full_blocks = {p: b for p, b in split_blocks(full_diff) if p}
    shown_blocks = {p: b for p, b in split_blocks(shown_diff) if p}
    dropped = [f for f in full if f not in shown_blocks]
    partial = []
    for f in full:
        if f in dropped:
            continue
        have = len(full_blocks.get(f, ""))
        saw = len(shown_blocks.get(f, ""))
        if have and saw < have:
            partial.append({"path": f, "shown_pct": max(1, round(100.0 * saw / have))})
    return {
        "total": len(full),
        # A partially-read file is NOT a reviewed file — counting it as one is exactly
        # the overstatement this function exists to prevent.
        "reviewed": len(full) - len(dropped) - len(partial),
        "dropped": dropped,
        "partial": partial,
        "complete": not dropped and not partial,
    }


def coverage_note(cov: dict, *, max_listed: int = 12) -> str:
    """Human-readable coverage block. Lists the dropped paths — a count alone does not
    tell a reviewer whether the missing file was a README or the deploy path."""
    dropped = list(cov.get("dropped") or [])
    partial = list(cov.get("partial") or [])
    shown = dropped[:max_listed]
    more = len(dropped) - len(shown)
    lines = [
        f"{MARKER} COVERAGE: {cov.get('reviewed', 0)} of {cov.get('total', 0)} files were "
        "read IN FULL by this review.",
    ]
    if dropped:
        lines.append("NOT REVIEWED (truncated away before the model saw them):")
        lines += [f"  - {p}" for p in shown]
        if more > 0:
            lines.append(f"  - ...and {more} more")
    # ⚠️ The blank line below TERMINATES the dropped-path listing that
    # pr_review_service.coverage_dropped_paths() parses, and the partial entries use a
    # "*" bullet rather than "- " so that parser can never mistake a partially-read file
    # for a wholly-dropped one — it keys on a leading "- ". Do not switch these to "-".
    lines.append("")
    if partial:
        lines.append("READ ONLY IN PART (the window cut mid-file — #5910):")
        for e in partial[:max_listed]:
            lines.append(f"  * {e.get('path')} — about {e.get('shown_pct')}% shown")
        if len(partial) > max_listed:
            lines.append(f"  * ...and {len(partial) - max_listed} more")
        lines.append("")
    lines += [
        "A verdict cannot cover code the reviewer never read — whether a whole file was "
        "dropped or one was cut short — so this review is recorded as NEEDS REVIEW rather "
        "than an approval (#5836/#5910). The findings above still stand for what WAS read.",
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
    return "PARTIAL: %d/%d files read in full; dropped=%s; part-read=%s" % (
        cov.get("reviewed", 0),
        cov.get("total", 0),
        ",".join(cov.get("dropped") or []) or "-",
        ",".join("%s@%s%%" % (e.get("path"), e.get("shown_pct")) for e in (cov.get("partial") or [])) or "-",
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


def file_plan(diff: str | None, max_files: int) -> list:
    """One review pass per FILE, each with the whole window to itself (#6779).

    ``chunk_plan`` PACKS files into bins of <= cap. That is the right question when the
    goal is "fit this diff into N windows", and the wrong one when a SINGLE file is larger
    than the cap: that file takes a bin alone and ``_truncate_diff`` then cuts it at its
    only boundary. For a NEWLY ADDED file the only boundary is the ``@@`` header near the
    top, so the reviewer sees the header and nothing else.

    Measured 2026-09-15 on PR #3339, ``omniroute_telemetry.py`` (a new 342-line file):
    **15,950 chars in, 214 chars out** — 1.3%. The review then flagged an import as unused
    whose only use sat in the truncated-away region. A false blocking finding, from a file
    the reviewer had effectively never seen.

    Per-file planning removes the packing decision entirely. Each file is judged on its own,
    which also means a finding can no longer be attributed to the wrong file — with packed
    bins the model sees several files at once and nothing binds a finding to one of them.

    TRADE-OFF, deliberately taken: small files no longer share a pass, so a 9-file PR costs
    9 serial dispatches instead of 1-3. Reviewing is slower; it is not truncated. Bound the
    cost with ``max_files`` rather than by re-packing — a packed bin is what this exists to
    avoid. Files beyond the bound are DROPPED, and ``coverage`` reports them as dropped, so
    the cost of the bound is visible rather than silent.

    ``max_files <= 1`` returns the diff UNCHANGED — the same killswitch property
    ``chunk_plan`` has, so the mode is inert until switched on. Blocks are banded with
    ``file_band`` (code before tests before docs) so a truncating bound spends its passes on
    the files that matter; see the note in the body on why this does not go through
    ``prioritize``.
    """
    if not diff:
        return []
    if max_files <= 1:
        return [diff]
    blocks = [pb for pb in split_blocks(diff) if pb[0] != ""]
    if not blocks:
        # An unparseable diff must still be reviewable — fall back to one whole-diff pass
        # rather than returning [] (which the caller would read as "nothing to review").
        return [diff]
    # Band the blocks DIRECTLY rather than via `prioritize`: that helper is deliberately
    # gated on `len(diff) > cap` (reordering a diff the model sees in full buys nothing),
    # and there is no single cap here — each file gets its own window. For per-file
    # planning the order decides which files get a pass AT ALL when `max_files` truncates,
    # so it has to hold unconditionally. Stable, so ties keep GitHub's ordering.
    blocks.sort(key=lambda pb: file_band(pb[0]))
    return [block for _path, block in blocks[:max_files]]


def chunk_plan(diff: str | None, cap: int, max_chunks: int) -> list:
    """Pack whole diff blocks into at most ``max_chunks`` bins of <= ``cap`` chars (#5848).

    A block is NEVER split. Splitting mid-hunk reintroduces the exact mid-statement cut
    ``_truncate_diff`` was written to avoid — the one that produced false 'no tests added'
    and 'unclosed loop' flags. A single block larger than ``cap`` takes its own bin and is
    truncated downstream by the existing ``_truncate_diff``.

    ``max_chunks <= 1`` returns the diff UNCHANGED, so the killswitch path is byte-identical
    to the pre-chunking behaviour. That property is pinned by a test; do not "optimise" it
    into an early truncation.

    Ordering comes from ``prioritize`` (#2715) — code before tests before docs — so chunk 1
    is the code. That ordering is also why tests were the thing being truncated away: five of
    six consecutive truncations on 2026-08-20 were the test file.
    """
    if not diff:
        return []
    if max_chunks <= 1:
        return [diff]

    ordered = prioritize(diff, cap) or diff
    bins: list = []
    current = ""
    for _path, block in split_blocks(ordered):
        if current and len(current) + len(block) > cap:
            bins.append(current)
            current = ""
            if len(bins) >= max_chunks:
                break
        current += block
    if current and len(bins) < max_chunks:
        bins.append(current)
    return bins[:max_chunks]
