"""Merge ORDER for the open PRs of one repo — pure, no DB, no Flask, no GitHub.

Why this exists (2026-09-11, owner: "PR review should show somehow order to merge").
GitHub's ``mergeable`` answers ONE question: does this branch conflict with ``main``
right now? It says nothing about two OPEN PRs against each other, and nothing about a
PR that *semantically* needs another one first (calls a function the other adds) with
no file in common. The tab therefore rendered four green Merge buttons and no order.

Three signals, computed only among OPEN PRs of the SAME repo:

1. **Declared dependency** — ``Depends on #N`` / ``Blocked by #N`` / ``Merge after #N``
   in the PR body. HARD order. ``merge_pr`` refuses a PR whose declared dependency is
   still open (see ``github_service._dependency_refusal``): that is a safety property,
   so it binds every actor, including the human click.
2. **File overlap** — two open PRs touching the same path. SOFT order: the OLDER PR
   goes first and the newer one says "shares N files with #X". Merging in the other
   order is not refused (GitHub will surface the conflict) — the badge is a warning.
3. **Stacked branches** — not computed here (phase 2; needs a compare call per pair).

The result is stamped onto each row as ``merge_order`` beside ``merge_state`` — the
same server-side contract (#5853): the JS renders a decision it did not make.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Iterable

# "Depends on #12", "depends-on #12", "Blocked by #12", "Merge after #12", "Requires #12".
# Deliberately NOT a bare "#12" or "after #12": PR bodies cite issues and PRs constantly
# ("fixes #12", "see #12"), and a false hard dependency BLOCKS a merge.
_DEP_RE = re.compile(
    r"\b(?:depends?[\s-]+on|blocked[\s-]+by|merge[\s-]+after|requires)\s*:?\s*#(\d+)",
    re.IGNORECASE,
)

_CIRCLED = "①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳"


def declared_dependencies(body: str | None) -> set[int]:
    """PR numbers the body declares this PR must merge AFTER. Empty for no body."""
    if not body:
        return set()
    return {int(m) for m in _DEP_RE.findall(body)}


def _num(pr: dict) -> int:
    return int(pr.get("pr_number") or pr.get("number") or 0)


def _created(pr: dict):
    v = pr.get("created_at")
    if isinstance(v, datetime):
        return v.timestamp()
    if isinstance(v, str) and v:
        try:
            return datetime.fromisoformat(v.replace("Z", "+00:00")).timestamp()
        except ValueError:
            return 0.0
    return 0.0


def _older_first(a: dict, b: dict) -> tuple[dict, dict]:
    """The PR that should merge first between two overlapping ones: earlier created_at,
    then lower number. Deterministic, and it never depends on which was reviewed last."""
    ka = (_created(a) or float("inf"), _num(a))
    kb = (_created(b) or float("inf"), _num(b))
    return (a, b) if ka <= kb else (b, a)


def compute_merge_order(open_prs: Iterable[dict]) -> dict[int, dict]:
    """Rank the OPEN PRs of one repo.

    Each input dict: ``pr_number`` (or ``number``), ``body`` (str|None),
    ``files`` (iterable of paths|None), ``created_at`` (datetime|ISO str|None).
    Rows from different repos must be passed in separate calls — PR numbers are only
    unique within a repo.

    Returns ``{pr_number: {rank, label, after, declared_after, shares_files_with,
    blocked, reason, cycle}}`` for every input PR. ``rank`` is 1-based and unique;
    ``after`` is the ordered list of open PRs that should land first (hard deps first,
    then overlap-older PRs); ``blocked`` is True only for a HARD dependency that is
    still open — the gate's input; overlap never blocks.
    """
    prs = [dict(p) for p in open_prs if _num(p)]
    by_num = {_num(p): p for p in prs}
    numbers = set(by_num)

    hard: dict[int, set[int]] = {n: set() for n in numbers}
    soft: dict[int, set[int]] = {n: set() for n in numbers}
    shares: dict[int, dict[int, list[str]]] = {n: {} for n in numbers}

    for n, p in by_num.items():
        # Only an OPEN dependency orders anything; a merged/absent one is satisfied or
        # unknowable from here, and a self-reference is a typo.
        hard[n] = {d for d in declared_dependencies(p.get("body")) if d in numbers and d != n}

    ordered = sorted(prs, key=lambda p: (_created(p) or float("inf"), _num(p)))
    for i, a in enumerate(ordered):
        fa = set(a.get("files") or ())
        if not fa:
            continue
        for b in ordered[i + 1 :]:
            common = sorted(fa & set(b.get("files") or ()))
            if not common:
                continue
            first, second = _older_first(a, b)
            shares[_num(first)][_num(second)] = common
            shares[_num(second)][_num(first)] = common
            soft[_num(second)].add(_num(first))

    # Kahn's algorithm over hard ∪ soft edges; ties by (created_at, number) so the
    # ranking is stable across refreshes. A cycle (A depends on B, B on A) cannot be
    # ordered — those PRs are ranked by number at the end and flagged.
    edges = {n: hard[n] | soft[n] for n in numbers}
    indeg = {n: len(edges[n]) for n in numbers}
    ready = sorted((n for n in numbers if indeg[n] == 0), key=lambda n: (_created(by_num[n]) or float("inf"), n))
    rank_of: dict[int, int] = {}
    while ready:
        n = ready.pop(0)
        rank_of[n] = len(rank_of) + 1
        for m in numbers:
            if n in edges[m] and m not in rank_of:
                indeg[m] -= 1
                if indeg[m] == 0:
                    ready.append(m)
                    ready.sort(key=lambda x: (_created(by_num[x]) or float("inf"), x))
    cyclic = sorted(numbers - set(rank_of))
    for n in cyclic:
        rank_of[n] = len(rank_of) + 1

    out: dict[int, dict] = {}
    for n in numbers:
        declared_after = sorted(hard[n])
        overlap_after = sorted(soft[n] - hard[n])
        after = declared_after + overlap_after
        blocked = bool(declared_after)
        cycle = n in cyclic
        if cycle:
            reason = f"circular dependency with #{', #'.join(str(d) for d in declared_after)} — fix the PR bodies"
            blocked = True
        elif declared_after:
            reason = f"declares it depends on #{', #'.join(str(d) for d in declared_after)}, still open"
        elif overlap_after:
            bits = [
                f"#{d} ({len(shares[n][d])} shared file{'s' if len(shares[n][d]) != 1 else ''})" for d in overlap_after
            ]
            reason = f"shares files with {', '.join(bits)} — merge those first, then re-check mergeability"
        else:
            reason = "no ordering constraint with the other open PRs"
        r = rank_of[n]
        circ = _CIRCLED[r - 1] if r <= len(_CIRCLED) else f"{r}."
        if declared_after:
            label = f"{circ} after #{', #'.join(str(d) for d in declared_after)}"
        elif overlap_after:
            label = f"{circ} shares files with #{', #'.join(str(d) for d in overlap_after)}"
        else:
            label = circ
        out[n] = {
            "rank": r,
            "label": label,
            "after": after,
            "declared_after": declared_after,
            "shares_files_with": {d: shares[n][d] for d in sorted(shares[n])},
            "blocked": blocked,
            "reason": reason,
            "cycle": cycle,
        }
    return out
