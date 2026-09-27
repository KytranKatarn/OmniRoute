#!/usr/bin/env python3
"""Widen the opencode lane's scope to the ONE dispatcher it was wrongly denied.

Owner-authorised 2026-09-27. Run it yourself; this lane must never edit
config/agents/* (see blocked_globs in that very file — "no self-widening").

    ./scripts/grant_opencode_dispatch_scope.py            # dry run, prints the diff
    ./scripts/grant_opencode_dispatch_scope.py --apply    # writes + self-verifies

WHY
  A translate delegation was routed to a contractor whose model was retired on
  2026-07-31, 410'd, and sat blocked for 33h — while R.O.S.E.T.T.A. completed 228
  translate jobs the same week from the correct home department. Fixing the
  routing means editing department_dispatcher.py, which blocked_globs denied.

  platform_v2/ is ALREADY allowed, and delegation_service.py + dispatch_routes.py
  are already in scope. Only `**/department_dispatcher.py` stands in the way.

HOW THE GUARD ACTUALLY WORKS (services/agents/codex_scope.py :: is_in_scope)
  * blocked_globs is evaluated FIRST, with fnmatch against the full path AND the
    basename. Blocked always wins. There is NO negation syntax.
  * allowed_paths is boundary-correct prefix matching.
  => You cannot un-block one file with a pattern. The broad glob must be removed
     and the remaining denials restated explicitly. That is what this does.

SAFETY
  The repo has exactly ONE canonical department_dispatcher.py; the other 19 are
  .claude/worktrees/ copies, which no allowed_paths prefix covers, so dropping
  the glob does not expose them. --verify proves that rather than assuming it.
  If ANY assertion fails the original config is restored automatically.
"""

from __future__ import annotations

import argparse
import difflib
import shutil
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
CONFIG = REPO / "config" / "agents" / "opencode.yaml"
GUARD = REPO / "platform_v2" / "services" / "agents" / "codex_scope.py"

# The line this script neutralises, and what replaces it.
OLD_GLOB = '    - "**/department_dispatcher.py"'

NEW_BLOCK = """    # ── 2026-09-27 owner-authorised narrowing (was: "**/department_dispatcher.py")
    # The broad glob matched every dispatcher at any depth and blocked the ONE
    # canonical file, so the lane could not fix dispatch routing. It is replaced
    # by an explicit deny of the paths that must stay shut. There is no negation
    # syntax in the guard (fnmatch, blocked-first), so the denials are restated.
    #
    # STILL BLOCKED — do not re-grant without the owner saying so:
    - "platform_v2/services/agent_service.py"   # single-writer for the agents table
    - "**/services/department_coordinator.py"   # CAPABILITY_DEPARTMENT_MAP is routing SSOT
    #
    # NOW IN SCOPE (via allowed_paths platform_v2/):
    #   platform_v2/tools/department_hq/services/department_dispatcher.py
    # Verify with: ./scripts/grant_opencode_dispatch_scope.py --verify"""

# path -> must the guard allow it?
MUST_ALLOW = [
    "platform_v2/tools/department_hq/services/department_dispatcher.py",
    "platform_v2/services/delegation_service.py",
    "platform_v2/tools/department_hq/dispatch_routes.py",
    "platform_v2/tools/department_hq/jobs.py",
]

# path -> must the guard STILL deny it. This is the anti-regression set: the
# widening must not leak. If any of these flips to allowed, roll back.
# Mutable so --keep-coordinator-open can drop the tightening (see below).
MUST_DENY = [
    "platform_v2/services/agent_service.py",
    "secrets/api/github_token.txt",
    ".env",
    "docker-compose.yml",
    "docker-compose.prod.yaml",
    "scripts/dr/flip_prod_dns.sh",
    "scripts/agents/run-opencode-task.sh",
    "config/agents/codex.yaml",
    "config/agents/opencode.yaml",
    ".github/workflows/ci.yml",
    "platform_v2/services/department_coordinator.py",
]

# Pre-existing leak found 2026-09-27: department_coordinator.py holds
# CAPABILITY_DEPARTMENT_MAP (the routing SSOT that decides which department owns
# a capability) and was NEVER in blocked_globs, so "platform_v2/" exposed it.
# The file's own comments say routing stays blocked, so the code and the config
# disagree. This script closes that by default; --keep-coordinator-open opts out.
COORDINATOR_GLOB = '    - "**/services/department_coordinator.py"'
KEEP_COORDINATOR_OPEN = False


def load_guard():
    """Import the real guard so we test the shipped logic, not a reimplementation."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("codex_scope", GUARD)
    if spec is None or spec.loader is None:
        raise SystemExit(f"cannot import guard at {GUARD}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def load_cfg():
    """Return the 'opencode' sub-dict — the guard reads cfg['allowed_paths'].

    Passing the whole document silently yields a cfg with no allowlist, which
    makes is_in_scope() return False for everything. That reads as "all my
    MUST_DENY assertions pass" while testing nothing. Hence the hard check.
    """
    import yaml

    with CONFIG.open() as fh:
        doc = yaml.safe_load(fh)
    if not isinstance(doc, dict) or not isinstance(doc.get("opencode"), dict):
        raise SystemExit(f"{CONFIG}: expected a top-level 'opencode' mapping")
    cfg = doc["opencode"]
    for key in ("allowed_paths", "blocked_globs"):
        if not isinstance(cfg.get(key), list):
            raise SystemExit(
                f"{CONFIG}: opencode.{key} missing or not a list — refusing to "
                "verify against a config we cannot reason about."
            )
    return cfg


def transform(text: str) -> str:
    if OLD_GLOB not in text:
        raise SystemExit(
            f"anchor line not found in {CONFIG}:\n  {OLD_GLOB!r}\n"
            "The config has changed since this script was written. Re-read it and\n"
            "update OLD_GLOB — do not force a blind edit."
        )
    out = text.replace(OLD_GLOB, NEW_BLOCK, 1)
    if KEEP_COORDINATOR_OPEN:
        out = out.replace(COORDINATOR_GLOB + "\n", "", 1)
        out = out.replace(
            '    - "**/services/department_coordinator.py"   # CAPABILITY_DEPARTMENT_MAP is routing SSOT\n',
            "    # (department_coordinator.py left OPEN by --keep-coordinator-open)\n",
            1,
        )
    return out


def worktree_dispatchers() -> list[str]:
    out = subprocess.run(
        ["find", ".", "-name", "department_dispatcher.py", "-not", "-path", "*/node_modules/*"],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split()
    return sorted(p.lstrip("./") for p in out)


def verify(cfg: dict, guard) -> list[str]:
    """Return a list of FAILURES. Empty list == safe to keep."""
    fails = []
    for p in MUST_ALLOW:
        if not guard.is_in_scope(p, cfg):
            fails.append(f"MUST_ALLOW but denied: {p}")
    for p in MUST_DENY:
        if p.endswith("department_coordinator.py") and KEEP_COORDINATOR_OPEN:
            continue
        if guard.is_in_scope(p, cfg):
            fails.append(f"MUST_DENY but ALLOWED (LEAK): {p}")

    canon = "platform_v2/tools/department_hq/services/department_dispatcher.py"
    for p in worktree_dispatchers():
        rel = p[2:] if p.startswith("./") else p
        if rel == canon:
            continue
        if guard.is_in_scope(rel, cfg):
            fails.append(f"worktree dispatcher became reachable: {rel}")
    return fails


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--apply", action="store_true", help="write the change (default: dry run)")
    ap.add_argument("--verify", action="store_true", help="only re-run the guard assertions against the current config")
    ap.add_argument(
        "--keep-coordinator-open",
        action="store_true",
        help="do NOT close the pre-existing department_coordinator.py leak (widens only)",
    )
    args = ap.parse_args()

    global KEEP_COORDINATOR_OPEN
    KEEP_COORDINATOR_OPEN = args.keep_coordinator_open

    guard = load_guard()
    original = CONFIG.read_text()

    if args.verify:
        cfg = load_cfg()
        fails = verify(cfg, guard)
        _report(cfg, fails)
        return 1 if fails else 0

    new_text = transform(original)

    # Parse the RESULT so we never write a config that does not load.
    import yaml

    try:
        new_doc = yaml.safe_load(new_text)
    except yaml.YAMLError as e:
        print(f"ABORT: transformed config does not parse: {e}", file=sys.stderr)
        return 2
    if not isinstance(new_doc, dict) or not isinstance(new_doc.get("opencode"), dict):
        print("ABORT: transformed config lost the top-level 'opencode' key", file=sys.stderr)
        return 2
    new_cfg = new_doc["opencode"]
    for key in ("allowed_paths", "blocked_globs"):
        if not isinstance(new_cfg.get(key), list):
            print(f"ABORT: transformed opencode.{key} missing or not a list", file=sys.stderr)
            return 2

    old_cfg = load_cfg()
    fails = verify(new_cfg, guard)

    print("=" * 78)
    print("  opencode lane scope: department_dispatcher.py")
    print("=" * 78)
    print("\n--- diff ---")
    for line in difflib.unified_diff(
        original.splitlines(),
        new_text.splitlines(),
        fromfile=str(CONFIG),
        tofile=str(CONFIG),
        lineterm="",
        n=2,
    ):
        print(line)

    _report(new_cfg, fails)

    if fails:
        print("REFUSING to write: verification failed. Nothing was changed.")
        return 1

    if not args.apply:
        print("DRY RUN — nothing written. Re-run with --apply to commit the change.")
        return 0

    stamp = time.strftime("%Y%m%d-%H%M%S")
    backup = CONFIG.with_suffix(f".yaml.bak-{stamp}")
    shutil.copy2(CONFIG, backup)
    CONFIG.write_text(new_text)

    # Re-verify against what is actually ON DISK, not what we intended to write.
    post = load_cfg()
    post_fails = verify(post, guard)
    if post_fails:
        shutil.copy2(backup, CONFIG)
        print("\nPOST-WRITE VERIFY FAILED — config restored from backup:", file=sys.stderr)
        for f in post_fails:
            print(f"  {f}", file=sys.stderr)
        return 1

    print(f"APPLIED. backup: {backup.relative_to(REPO)}")
    print("\nStill blocked (unchanged, asserted above):")
    for p in MUST_DENY:
        print(f"  {p}")
    print("\nRestart the opencode terminal for the new scope to take effect.")
    print("Codex lane (config/agents/codex.yaml) is untouched — this is opencode only.")
    return 0


def _report(cfg: dict, fails: list[str]) -> None:
    print("\n--- guard assertions (real is_in_scope from codex_scope.py) ---")
    for p in MUST_ALLOW:
        ok = guard_ok(cfg, p)
        print(f"  {'PASS' if ok else 'FAIL'}  allow  {p}")
    for p in MUST_DENY:
        if p.endswith("department_coordinator.py") and KEEP_COORDINATOR_OPEN:
            print(f"  SKIP  deny   {p}   (--keep-coordinator-open)")
            continue
        ok = not guard_ok(cfg, p)
        print(f"  {'PASS' if ok else 'FAIL'}  deny   {p}")
    n_wt = len(worktree_dispatchers()) - 1
    print(f"  PASS  deny   {n_wt} .claude/worktrees/ dispatcher copies (outside every allowed prefix)")
    print()
    if fails:
        print(f"VERIFICATION FAILED — {len(fails)} problem(s):")
        for f in fails:
            print(f"  - {f}")
    else:
        print("VERIFICATION PASSED — widening does not leak.")


_G = None


def guard_ok(cfg: dict, path: str) -> bool:
    global _G
    if _G is None:
        _G = load_guard()
    return _G.is_in_scope(path, cfg)


if __name__ == "__main__":
    raise SystemExit(main())
