"""Stamp ``merge_order`` onto PR rows for the Repair Bay surfaces.

Companion to ``merge_order.compute_merge_order`` (pure). This module is the ONLY place
that touches GitHub for it: per open PR it needs the body (declared dependencies) and
the changed paths (overlap), which ``pr_reviews`` does not store. Two read-token calls
per open PR, cached for ``_TTL`` seconds so the tab's refresh cadence (15 s) and the
``/api/forge/pr-reviews`` 30 s cache do not multiply into API quota.

Contract, same as ``merge_state`` (#5853): the server decides, the JS renders.
Display-only here — the HARD half (a declared dependency still open) is enforced in
``github_service.merge_pr`` via ``_dependency_refusal``, which reads GitHub itself at
merge time and never trusts this cache.

Fail-OPEN for display: a fetch failure stamps ``{"unavailable": True, ...}`` (a badge
that says "order unavailable"), never a fabricated rank and never a raise that would
take the listing down. Unknown is reported as unknown (deploy-provenance rule).
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Iterable

from .merge_order import compute_merge_order

logger = logging.getLogger(__name__)

_TTL = 120.0
_cache: dict[tuple[str, int], tuple[float, str | None, list | None]] = {}
_lock = threading.Lock()

_UNAVAILABLE = {
    "rank": None,
    "label": "",
    "after": [],
    "declared_after": [],
    "shares_files_with": {},
    "blocked": False,
    "reason": "merge order unavailable — GitHub could not be read for this PR",
    "cycle": False,
    "unavailable": True,
}


def _fetch(repo: str, number: int) -> tuple[str | None, list | None]:
    """(body, files) for one PR — cached. Either half is None when its read failed."""
    key = (repo, number)
    now = time.time()
    with _lock:
        hit = _cache.get(key)
        if hit and now - hit[0] < _TTL:
            return hit[1], hit[2]
    from . import github_service as gs  # late import: github_service imports requests etc.

    body = gs.pr_body(number, repo)
    files = gs.pr_files(number, repo)
    with _lock:
        _cache[key] = (now, body, files)
    return body, files


def clear_cache() -> None:
    with _lock:
        _cache.clear()


def _is_open(row: dict, state_key: str) -> bool:
    return str(row.get(state_key) or "open").strip().lower() == "open"


def stamp_merge_order(
    rows: Iterable[dict],
    number_key: str = "pr_number",
    repo_key: str = "repo",
    state_key: str = "state",
    default_repo: str | None = None,
) -> list:
    """Stamp ``row["merge_order"]`` on every row. Open rows are ranked per repo;
    closed/merged rows get ``None`` (there is nothing to order).

    ``number_key`` is ``pr_number`` for ``pr_reviews`` rows and ``number`` for the
    GitHub-shaped ``/api/forge/prs`` payload; ``default_repo`` covers rows with no
    repo field (GitHub-shaped rows are all one repo).
    """
    rows = list(rows or [])
    groups: dict[str, list[dict]] = {}
    for row in rows:
        row["merge_order"] = None
        n = row.get(number_key)
        if not isinstance(n, int) or not _is_open(row, state_key):
            continue
        repo = (row.get(repo_key) or default_repo or "").strip()
        if not repo:
            continue
        groups.setdefault(repo, []).append(row)

    for repo, group in groups.items():
        inputs = []
        unavailable: set[int] = set()
        for row in group:
            n = row[number_key]
            try:
                body, files = _fetch(repo, n)
            except Exception as exc:  # noqa: BLE001 — display must never take the listing down
                logger.warning("merge_order: fetch failed for %s#%s: %s", repo, n, exc)
                body, files = None, None
            if body is None and files is None:
                unavailable.add(n)
            inputs.append(
                {
                    "pr_number": n,
                    "body": body or "",
                    "files": files or [],
                    "created_at": row.get("created_at"),
                }
            )
        try:
            order = compute_merge_order(inputs)
        except Exception as exc:  # noqa: BLE001
            logger.warning("merge_order: ranking failed for %s: %s", repo, exc)
            order = {}
        for row in group:
            n = row[number_key]
            if n in unavailable or n not in order:
                row["merge_order"] = dict(_UNAVAILABLE)
            else:
                row["merge_order"] = order[n]
    return rows
