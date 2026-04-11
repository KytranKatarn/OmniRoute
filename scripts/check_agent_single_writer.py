#!/usr/bin/env python3
"""K.I.N. Single-Writer Guardrail for the ``agents`` table.

Fails if any staged Python file introduces a raw ``UPDATE agents``,
``INSERT INTO agents``, or ``DELETE FROM agents WHERE`` statement
outside of the canonical single-writer module
(``platform_v2/services/agent_service.py``) and the test fixtures.

Part of Project #241 Track C.4 — locks in the Tracks A-C.3 lifecycle
consolidation so new code can't quietly reintroduce raw mutations.

Usage:
    python3 scripts/check_agent_single_writer.py file1.py file2.py ...

Exits 0 with no output if clean, exits 1 with violation details if
dirty. Used by:
    - .pre-commit-config.yaml  (runs on changed files)
    - .github/workflows/single-writer-guardrail.yml  (runs on PR diff)
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

# Regex matches the three classes of raw write the Track A audit targeted.
# Kept intentionally permissive (case-insensitive, whitespace-tolerant) so
# that multi-line and indented forms are caught — the original audit missed
# three such sites during Tracks C.1-C.3.
VIOLATION_RE = re.compile(
    r"(?ix)"
    r"(?:"
    r"  UPDATE\s+agents\s+SET"
    r"| INSERT\s+INTO\s+agents\s*\("
    r"| DELETE\s+FROM\s+agents\s+WHERE"
    r")"
)

# Allow-list: files that are permitted to hold raw mutations. The canonical
# single-writer module owns the agents table, and test fixtures need an
# independent path to set up/tear down test agents.
ALLOWED_PATHS = (
    "platform_v2/services/agent_service.py",
    "scripts/check_agent_single_writer.py",
    "/tests/",
)


def _is_allowed(path: str) -> bool:
    """True if the path is on the allow-list (canonical writer or tests)."""
    normalized = str(path).replace("\\", "/")
    return any(allowed in normalized for allowed in ALLOWED_PATHS)


def _check_file(path: Path) -> list[tuple[int, str]]:
    """Return a list of (line_number, line_content) violations for one file."""
    if _is_allowed(str(path)):
        return []
    if not path.exists() or path.suffix != ".py":
        return []
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return []
    hits: list[tuple[int, str]] = []
    for idx, line in enumerate(text.splitlines(), start=1):
        if VIOLATION_RE.search(line):
            hits.append((idx, line.strip()))
    return hits


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        # Nothing staged — nothing to check.
        return 0

    total_violations = 0
    report: list[str] = []

    for arg in argv[1:]:
        path = Path(arg)
        violations = _check_file(path)
        if not violations:
            continue
        report.append(f"\n  \033[1;31m{path}\033[0m")
        for lineno, line in violations:
            snippet = line[:120]
            report.append(f"    line {lineno}: {snippet}")
            total_violations += 1

    if total_violations == 0:
        return 0

    sys.stderr.write(
        "\n\033[1;31m"
        "K.I.N. single-writer guardrail: raw agents-table mutation detected"
        "\033[0m\n"
    )
    sys.stderr.write("".join(f"{line}\n" for line in report))
    sys.stderr.write(
        "\n\033[1;33m"
        "The agents table has a single canonical writer: "
        "platform_v2/services/agent_service.py\n"
        "Use one of these helpers instead of raw SQL:\n"
        "    agent_service.create_agent(name, display_name, department, model, **kwargs)\n"
        "    agent_service.update_agent(agent_id, **fields)\n"
        "    agent_service.delete_agent(agent_id, hard=False)\n"
        "    agent_service.barracks(agent_id) / activate(agent_id) / deploy_to_node(...)\n"
        "    agent_service.increment_usage(agent_id, tier)\n"
        "    agent_service.update_performance_metrics(agent_id, success)\n"
        "\n"
        "If you need a new atomic pattern that these helpers don't cover, add\n"
        "a new helper to agent_service.py rather than writing raw SQL in a\n"
        "caller. See Project #241 Tracks A-C.3 for context.\n"
        "\033[0m"
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
