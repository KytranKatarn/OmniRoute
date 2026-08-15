#!/usr/bin/env python3
"""Pre-commit gate: touching a registry SOURCE without regenerating its doc (#5230).

WHY A GATE AND NOT A REMINDER
The generated index is only trustworthy if it is regenerated. Phases 1–3 make
regeneration possible; nothing yet makes it HAPPEN. Every hand-maintained doc on
this platform rotted the same way — not because anyone decided to let it, but
because updating it was a separate step that was easy to forget and invisible
when skipped. This makes skipping it visible at the only moment it is cheap to
fix: before the commit lands.

WHAT IT CHECKS
If a commit touches a file that FEEDS the registry (module_registry.py, rbac.py,
a blueprint, a compose file, a skills/commands dir) but does NOT touch the
generated doc, it fails with the exact command to run.

DELIBERATELY A HEURISTIC, AND DELIBERATELY CHEAP. It does NOT run the collector
— that needs a database and a docker socket, neither of which belongs in a
pre-commit hook (a gate that needs prod to be up is a gate that gets bypassed).
It compares the two file SETS, nothing more. False positives are possible and
cheap: regenerate, or pass SKIP_REGISTRY_DRIFT=1 with a reason in the commit
message.

SOURCES come from argv (what pre-commit passed) but the DOC side is always
checked against the full staged set — pre-commit's `files:` regex selects
sources only, so a generated doc can never arrive in argv. See #5602 and
tests/test_registry_drift_hook.py; getting this wrong makes the gate
unpassable, which is worse than having no gate at all.

Exit 0 = fine, 1 = regenerate first.
"""

from __future__ import annotations

import os
import subprocess
import sys

# Sources whose change should be reflected in the generated docs.
_MODULE_SOURCES = (
    "platform_v2/module_registry.py",
    "platform_v2/rbac.py",
)
# NOT "platform_v2/tools/" — that matches every blueprint edit, and a route
# change does not alter a module's REGISTRY entry. Firing on all of them would
# demand a doc regen (which restamps the generated_at line) on routine commits,
# so the gate would be skipped as a matter of habit — and a gate that is
# routinely skipped is worse than no gate, because it trains the reflex.
# Only the files that actually define module FACTS gate the module doc.
_MODULE_SOURCE_PREFIXES = ()
_SERVICE_SOURCE_HINTS = ("docker-compose", "scripts/deploy_drift_check.py")
_SKILL_SOURCE_PREFIXES = (".claude/skills/", ".claude/commands/")

_MODULE_DOC = ".claude/rules/module-capability-index.md"
_SERVICE_DOC = ".claude/rules/service-registry.md"

_CMD = "docker exec archie_platform python3 /mnt/archie_brain/scripts/generate_registry_docs.py"


def _staged() -> list[str]:
    try:
        out = subprocess.run(
            ["git", "diff", "--cached", "--name-only"],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except Exception:  # pragma: no cover - git unavailable
        return []
    return [ln.strip() for ln in out.stdout.splitlines() if ln.strip()]


def main(argv: list[str]) -> int:
    if os.environ.get("SKIP_REGISTRY_DRIFT"):
        return 0

    staged = _staged()
    files = argv[1:] or staged
    if not files:
        return 0

    # The generated docs can NEVER appear in argv. .pre-commit-config.yaml runs
    # this hook with `pass_filenames: true` and a `files:` regex that selects
    # registry SOURCES; neither doc matches it (it allows `.claude/skills|
    # commands/`, not `.claude/rules/`). So asking `_DOC not in files` made the
    # gate UNPASSABLE for a docker-compose or module_registry change — the doc
    # was regenerated correctly and the hook still failed (hit live on PR #2577),
    # forcing SKIP_REGISTRY_DRIFT=1 and teaching exactly the skip-reflex this
    # gate exists to prevent. Ask the full staged set instead. #5602.
    regenerated = set(files) | set(staged)

    touched_module_src = any(f in _MODULE_SOURCES for f in files) or any(
        f.startswith(p) for f in files for p in _MODULE_SOURCE_PREFIXES
    )
    touched_service_src = any(h in f for f in files for h in _SERVICE_SOURCE_HINTS)
    touched_skill_src = any(f.startswith(p) for f in files for p in _SKILL_SOURCE_PREFIXES)

    problems: list[str] = []
    if touched_module_src and _MODULE_DOC not in regenerated:
        problems.append(f"  • a MODULE source changed but {_MODULE_DOC} was not regenerated\n" f"      {_CMD}")
    # NOTE: touched_skill_src is deliberately NOT part of this condition.
    # Skills/commands/capabilities are collected into platform_registry_skill but
    # have NO document renderer yet — service-registry.md renders containers and
    # products only. Gating a skill change on regenerating a doc that would not
    # change is a gate that can NEVER be satisfied, so every author would have to
    # pass SKIP_REGISTRY_DRIFT=1 and the habit of skipping would be learned. A
    # gate that is routinely skipped is worse than no gate. The nightly collector
    # still picks skill changes up; re-add this when a skills doc exists.
    if touched_service_src and _SERVICE_DOC not in regenerated:
        problems.append(
            f"  • a SERVICE source changed but {_SERVICE_DOC} was not regenerated\n" f"      {_CMD} --services"
        )

    if not problems:
        return 0

    sys.stderr.write(
        "\nREGISTRY DRIFT — a generated doc is about to fall behind its source (#5230):\n\n"
        + "\n".join(problems)
        + "\n\nThe generated docs are what a new session reads FIRST and then acts on. "
        "The hand-maintained\npredecessor asserted two tables that did not exist, which left "
        "backups unmonitored while\nappearing monitored. Regenerate, or set SKIP_REGISTRY_DRIFT=1 "
        "if this genuinely does not\naffect the registry.\n\n"
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
