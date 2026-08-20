"""Pre-deploy backup SCOPE resolution (#5279 / #5835, ADR-009).

`deploy_to_production` must choose between a SCOPED module backup (a few MB) and the
FULL platform snapshot (~2.8 GB). ADR-009: "roll back via a FRESH module backup; full
snapshots become the safety net, not the per-fix default."

The rule that makes scoping safe is CONTAINMENT: a backup only protects what it
contains, so a scope may be chosen ONLY when the file the deploy will overwrite
provably lives inside what `backup_module()` copies. Anything unresolvable falls UP to
the full snapshot — never down to nothing.

WHY THIS MODULE EXISTS SEPARATELY
The resolver used to live inline in `proposal_service` and could not be tested without a
database and a live tree, so its guards were never exercised. Measured 2026-08-19: the
guard that was actually rejecting every ai_bridge proposal was the CHARSET regex, not the
documented policy exclusion below it — the policy line was dead code for those rows and
nobody could tell, because nothing could call the function in isolation.

  improvement_proposals.metadata for proposal 8725:
      module_name  = '[AI_BRIDGE]'                          <- bracketed LABEL, not a name
      file_path    = '[AI_BRIDGE]/translation_service.py'   <- SYNTHETIC, not a repo path
      runtime_file = '/mnt/archie_brain/ai_bridge/translation_service.py'   <- the real one

Two consequences drive the design:

1. `module_name` is a display LABEL and must be normalised before use. `[AI_BRIDGE]` does
   not match `[A-Za-z0-9_-]+`.
2. For the pseudo-modules, `file_path` is SYNTHETIC and must NEVER decide containment.
   Only `runtime_file` names a real location, so containment is decided on its resolved
   realpath being inside a resolved module root. Using the synthetic path here would be a
   containment check that verifies nothing.

FAIL-SAFE DIRECTION
Every uncertain input returns None (=> FULL backup). Wasting 2.8 GB is cheap; deploying
against a restore point that does not contain the file being overwritten is not.
"""

from __future__ import annotations

import os
import re
from typing import Iterable, Mapping, Optional, Sequence

# A normalised module name. Deliberately stricter than the display label.
_NAME_RE = re.compile(r"[a-z0-9_-]+")

# Pseudo-modules are whole TREES outside platform_v2/tools/, copied wholesale by
# backup_module(). Their containment test is "is runtime_file inside this tree", which is
# why they need real roots rather than a path prefix convention.
PSEUDO_MODULES = ("ai_bridge", "services")


def normalize_module_name(raw) -> Optional[str]:
    """`'[AI_BRIDGE]'` -> `'ai_bridge'`. None when it is not a usable module name.

    Strips one layer of surrounding brackets and lowercases. Anything still outside
    `[a-z0-9_-]+` after that is rejected rather than sanitised further — a name we had to
    guess at is a name we should not be scoping a backup on.
    """
    s = str(raw or "").strip()
    if not s:
        return None
    if len(s) >= 2 and s[0] == "[" and s[-1] == "]":
        s = s[1:-1].strip()
    s = s.lower()
    return s if _NAME_RE.fullmatch(s) else None


def _within(child: str, parent: str) -> bool:
    """True when `child` resolves to `parent` itself or something beneath it.

    realpath on BOTH sides so a symlink cannot point out of the tree while the literal
    string still looks contained. `commonpath` rather than `startswith` so `/a/services`
    is not treated as inside `/a/serv`.
    """
    try:
        c = os.path.realpath(child)
        p = os.path.realpath(parent)
        return c == p or os.path.commonpath([c, p]) == p
    except (ValueError, OSError):
        # ValueError: paths on different drives / mixed absolute-relative.
        return False


def resolve_scope(
    metadata: Mapping,
    *,
    tools_root: str,
    pseudo_roots: Mapping[str, Sequence[str]],
    isfile=os.path.isfile,
    isdir=os.path.isdir,
) -> Optional[str]:
    """Return the module name to scope the pre-deploy backup to, or None for FULL.

    Args:
        metadata: the proposal's `metadata` dict (module_name / file_path / runtime_file).
        tools_root: absolute path of `platform_v2/tools`.
        pseudo_roots: {'ai_bridge': [candidate roots...], 'services': [...]} — several
            candidates because the same tree is mounted at different paths inside the
            platform container vs on the host.
        isfile / isdir: injected for tests.
    """
    if not isinstance(metadata, Mapping):
        return None

    module = normalize_module_name(metadata.get("module_name"))
    if not module:
        return None

    file_path = str(metadata.get("file_path") or "")
    runtime_file = str(metadata.get("runtime_file") or "")
    if not file_path or not runtime_file:
        return None
    if ".." in file_path or ".." in runtime_file:
        return None

    # runtime_file is the path the deploy actually overwrites. It must exist NOW — a
    # backup of a file that is not there protects nothing.
    if not os.path.isabs(runtime_file) or not isfile(runtime_file):
        return None

    if module in pseudo_roots:
        # Pseudo-module: containment is decided on the REAL path only. file_path is a
        # synthetic label here ('[AI_BRIDGE]/x.py') and is checked for consistency, not
        # containment — its basename must still name the same file.
        if os.path.basename(file_path) != os.path.basename(runtime_file):
            return None
        for root in pseudo_roots.get(module) or ():
            if isdir(root) and _within(runtime_file, root):
                return module
        return None

    # Ordinary module: the change must be declared inside platform_v2/tools/<module>/ AND
    # the runtime file must really live there. Both, because the declared path and the
    # runtime path have disagreed before.
    if not file_path.lstrip("/").startswith(f"platform_v2/tools/{module}/"):
        return None
    if not _within(runtime_file, os.path.join(tools_root, module)):
        return None
    return module


def default_pseudo_roots(platform_dir: str, ai_bridge_roots: Iterable[str]) -> dict:
    """Roots for the two widened pseudo-modules backup_module() knows how to copy."""
    return {
        "ai_bridge": tuple(ai_bridge_roots),
        "services": (os.path.join(platform_dir, "services"),),
    }
