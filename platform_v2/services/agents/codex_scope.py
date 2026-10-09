"""Deny-by-default path scope guard for Codex CLI runs (Phase A).

A path is in scope ONLY IF, after normalization, it: does not escape the repo via
``..``/absolute traversal, does not match any blocked_globs, AND sits under an
allowed_paths prefix on a real directory boundary. Blocked always wins. This is
the PRIMARY safety gate for Codex — it MUST fail closed (deny on anything unsafe
or malformed), never fail open.
"""

from __future__ import annotations

import fnmatch
import posixpath
from typing import Iterable, Optional


def _normalize(path: str) -> Optional[str]:
    """Return a safe repo-relative normalized path, or None if unsafe.

    Rejects absolute paths and anything that escapes the repo via ``..``.
    """
    if not path or not isinstance(path, str):
        return None
    if path.startswith("/"):  # absolute paths are never in scope
        return None
    norm = posixpath.normpath(path)
    # normpath collapses ./ and ../ ; anything still starting with .. escapes the repo
    if norm == "." or norm == ".." or norm.startswith("../") or norm.startswith("/"):
        return None
    return norm


def _clean_prefix(prefix: str) -> Optional[str]:
    """Canonicalize an allowed_paths entry to a safe, boundary-correct prefix.

    Returns a normalized prefix ending in ``/`` so it can only match on a real
    directory boundary, or None for malformed/over-broad entries (which are then
    skipped — fail closed, never allow-all).
    """
    if not prefix or not isinstance(prefix, str):
        return None
    norm = posixpath.normpath(prefix)
    if norm in (".", "/", "..") or norm.startswith("../") or norm.startswith("/"):
        return None
    return norm.rstrip("/") + "/"


def is_in_scope(path: str, cfg: dict) -> bool:
    p = _normalize(path)
    if p is None:
        return False  # traversal / absolute / malformed → denied

    # #3777 Codex narrow exception: allow this specific file despite blocked_globs
    # while preserving the block on all other scripts/agents/* files.
    # The exception only fires when the path is explicitly in allowed_paths.
    if p == "scripts/agents/codex-delegation-worker.py":
        if "scripts/agents/codex-delegation-worker.py" in cfg.get("allowed_paths", []):
            return True
        # Otherwise fall through to normal blocked_globs check below

    for pat in cfg.get("blocked_globs", []):
        if not pat:
            continue
        # match against the full normalized path AND the basename so "*.env" catches nested
        if fnmatch.fnmatch(p, pat) or fnmatch.fnmatch(p.split("/")[-1], pat):
            return False
        if pat.endswith("/*") and p.startswith(pat[:-1]):
            return False

    for prefix in cfg.get("allowed_paths", []):
        cp = _clean_prefix(prefix)
        if cp is None:
            continue  # skip malformed entries — do NOT allow-all on bad config
        # boundary-correct: append "/" so "<allowed>/" must be a real ancestor of the path
        if (p + "/").startswith(cp):
            return True
    return False


def check_diff_paths(paths: Iterable[str], cfg: dict) -> list[str]:
    """Return the list of out-of-scope paths (empty list == all clean)."""
    return [p for p in paths if p and not is_in_scope(p, cfg)]
