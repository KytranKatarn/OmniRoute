#!/usr/bin/env python3
"""Timezone drift guardrail (Phase 3 of timezone standardization, PR #543).

Two classes of violations are rejected:

1. **`datetime.utcnow()`** — deprecated in Python 3.12 (returns naive UTC,
   silently misbehaves in mixed-tz comparisons). Migrated to
   `datetime.now(timezone.utc)` or `services.time_utils.now_utc()`.

2. **Literal "UTC" suffix in user-facing strings** — `dt.strftime('%Y-%m-%d %H:%M UTC')`
   and similar render UTC times labeled as UTC, then go to user reports /
   Telegram / KB vault notes. The platform contract is: storage in UTC,
   display in EDT/EST. Use `services.time_utils.format_local()` /
   `now_local_str()` instead, which emits the actual TZ abbreviation.

Excluded from check 2:
  * code that explicitly references `timezone.utc`, `tzinfo=`, or imports it
  * test files
  * migration files
  * documentation strings that describe the deprecated symbol

Usage:
    python3 scripts/check_timezone_drift.py file1.py file2.py ...

Exits 0 clean, 1 with actionable error output.

Hook: .pre-commit-config.yaml (runs on changed Python files at commit time).
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

UTCNOW_RE = re.compile(r"\bdatetime\.utcnow\s*\(\s*\)")

# Match a string literal that contains " UTC" or "UTC " or " Z " — i.e. UTC
# is being LABELED as such in the output, not used as a TZ object.
# Excludes: timezone("UTC"), tzinfo=timezone.utc, etc. (those are correct usage).
UTC_LABEL_RE = re.compile(
    r"""
    ['"]                # opening quote
    [^'"]*              # any chars except quotes
    \b                  # word boundary
    UTC                 # literal UTC label
    \b
    [^'"]*              # any chars except quotes
    ['"]                # closing quote
    """,
    re.VERBOSE,
)

# Lines that are clearly USING UTC as a TZ object, not labeling output:
TZ_OBJECT_USAGE_RE = re.compile(
    r"""
    (?:
        timezone\s*\(\s*['"]UTC['"]\s*\)     # timezone("UTC")
      | tzinfo\s*=\s*timezone\.utc           # tzinfo=timezone.utc
      | timezone\.utc                          # bare timezone.utc reference
      | from\s+zoneinfo                        # zoneinfo imports
      | ZoneInfo\s*\(\s*['"]UTC['"]            # ZoneInfo("UTC")
      | astimezone\s*\(\s*['"]UTC['"]          # .astimezone("UTC")
      | ['"]time[Zz]one['"]\s*:\s*['"]UTC['"] # API payloads: "timeZone": "UTC"
      | ['"]tz['"]\s*:\s*['"]UTC['"]          # API payloads: "tz": "UTC"
    )
    """,
    re.VERBOSE,
)


def line_is_excluded(line: str) -> bool:
    """Skip lines that legitimately reference UTC as a TZ object."""
    return bool(TZ_OBJECT_USAGE_RE.search(line))


def line_is_comment_or_docstring_marker(line: str, in_docstring: bool) -> bool:
    """Best-effort detection of comment/docstring lines.

    A line is skipped if:
      * It starts with `#`
      * We're tracking a multi-line docstring (caller's job)
    """
    stripped = line.lstrip()
    return stripped.startswith("#")


def scan_file(path: Path) -> list[str]:
    """Return list of human-readable violation messages for this file."""
    text = path.read_text(encoding="utf-8", errors="replace")

    # Skip files that are themselves the canonical TZ helper or this script.
    if "services/time_utils.py" in str(path):
        return []
    if "scripts/check_timezone_drift.py" in str(path):
        return []
    # Tests + migrations get a pass — they may need to test edge cases.
    if "/tests/" in str(path) or "/migrations/" in str(path):
        return []

    violations: list[str] = []

    # Track multi-line triple-quoted strings so we can skip docstrings.
    in_docstring = False
    docstring_quote = None

    for ln_no, line in enumerate(text.split("\n"), start=1):
        # Track docstring state cheaply (won't catch every edge case but good enough).
        for q in ('"""', "'''"):
            if q in line:
                # Toggle docstring state per occurrence
                count = line.count(q)
                if count % 2 == 1:
                    if in_docstring and docstring_quote == q:
                        in_docstring = False
                        docstring_quote = None
                    elif not in_docstring:
                        in_docstring = True
                        docstring_quote = q

        if in_docstring:
            continue
        if line_is_comment_or_docstring_marker(line, in_docstring):
            continue
        # Skip lines that contain triple-quoted single-line docstrings
        # (where opening and closing """/''' are on the same line).
        if '"""' in line or "'''" in line:
            continue

        # Check 1: datetime.utcnow()
        if UTCNOW_RE.search(line):
            violations.append(
                f"{path}:{ln_no}: datetime.utcnow() is deprecated. "
                f"Use `datetime.now(timezone.utc)` or `services.time_utils.now_utc()`.\n"
                f"    {line.strip()}"
            )

        # Check 2: literal " UTC " in a user-facing string
        if UTC_LABEL_RE.search(line) and not line_is_excluded(line):
            # Allow strings that are clearly DB queries / log filters / tests
            ls = line.strip().lower()
            if any(t in ls for t in (
                "show timezone",
                "set timezone",
                "at time zone",
                "set time zone",
                "select",
                "logger",
            )):
                continue
            violations.append(
                f"{path}:{ln_no}: literal 'UTC' label in a user-facing string. "
                f"Use services.time_utils.format_local() / now_local_str() so the "
                f"output uses EDT/EST.\n"
                f"    {line.strip()}"
            )

    return violations


def main(argv: list[str]) -> int:
    files = [Path(p) for p in argv[1:] if p.endswith(".py")]
    if not files:
        return 0

    all_violations: list[str] = []
    for f in files:
        if not f.exists():
            continue
        all_violations.extend(scan_file(f))

    if all_violations:
        print("=" * 60, file=sys.stderr)
        print("TIMEZONE DRIFT GUARDRAIL — violations:", file=sys.stderr)
        print("=" * 60, file=sys.stderr)
        for v in all_violations:
            print(v, file=sys.stderr)
        print("=" * 60, file=sys.stderr)
        print(
            "See .claude/rules/timezone.md for the convention.\n"
            "Storage = UTC. Display = EDT.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
