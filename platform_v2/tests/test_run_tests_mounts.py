"""Every repo-root path the suite reads must be MOUNTED by scripts/run_tests.sh.

THE DEFECT THIS EXISTS FOR. `run_tests.sh` mounted ten repo paths into its test container
and never mounted `config/`. `test_opencode_scope.py` resolves
`config/agents/opencode.yaml`, falling back to exactly
`/mnt/archie_brain/config/agents/opencode.yaml` — the path that mount would create. So all
**21** of its tests errored at collection:

    FileNotFoundError: config/agents/opencode.yaml not found. Run this where the repo ROOT
    is available — the platform container mounts only platform_v2 at /app.

They ERRORED rather than failed, which reads as environment noise, so the file looked like
coverage while never once running — and its own docstring says
"config/agents/opencode.yaml is the ONLY thing standing between a third-party coding agent
and the rest of the repo." A missing `-v` flag silenced that guard, and hid a real policy
divergence for as long as it was silent (#6824).

WHY A GENERAL GUARD, not just a `config` assertion. The same shape recurs whenever a test
learns to read a new repo-root path: the author adds the read, the mount is forgotten, and
the test goes quietly inert. This test makes the mount list and the suite's actual reads
agree, so the next omission is a red test instead of a silent one.

⚠️ A trip here is a PROMPT, not necessarily a bug. If a new path is genuinely not meant to
be mounted, declare it in DELIBERATELY_ABSENT with the reason. What must never happen again
is a path being neither mounted nor declared.
"""

from __future__ import annotations

import os
import re

import pytest

_CANDIDATES = (
    "/mnt/archie_brain/scripts/run_tests.sh",
    os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
        "scripts",
        "run_tests.sh",
    ),
)
_TESTS_DIR = os.path.dirname(os.path.abspath(__file__))


def _runner_source() -> str:
    for path in _CANDIDATES:
        if os.path.exists(path):
            with open(path) as fh:
                return fh.read()
    pytest.skip("scripts/run_tests.sh not reachable from this container")


# Paths the suite references that are deliberately NOT mounted, each with the reason.
# Measured 2026-09-21 by scanning the suite for quoted /mnt/archie_brain/<seg> literals.
DELIBERATELY_ABSENT = {
    ".env": "secrets never enter the test container (compliance-standards.md)",
    "platform_v2": "mounted at /app instead — the tree under test, not a sibling",
    "docker-compose.yml": "referenced in prose about deployment, never opened by a test",
    "mcp-gateway": "referenced in prose; the lane gateway is not exercised here",
}

_MOUNT_TARGET_RE = re.compile(r":/mnt/archie_brain/([A-Za-z0-9_.][A-Za-z0-9_./-]*)")
_REFERENCE_RE = re.compile(r'"/mnt/archie_brain/([A-Za-z0-9_.][A-Za-z0-9_.-]*)')


def _mounted_roots() -> set:
    """Top-level names run_tests.sh makes available under /mnt/archie_brain."""
    return {t.split("/")[0] for t in _MOUNT_TARGET_RE.findall(_runner_source())}


def _referenced_roots() -> set:
    roots = set()
    for name in sorted(os.listdir(_TESTS_DIR)):
        if not name.startswith("test_") or not name.endswith(".py"):
            continue
        with open(os.path.join(_TESTS_DIR, name)) as fh:
            roots.update(_REFERENCE_RE.findall(fh.read()))
    return roots


def test_config_is_mounted():
    """The specific regression: 21 tests inert for want of one -v flag."""
    assert "config" in _mounted_roots(), (
        "scripts/run_tests.sh must mount config/ — test_opencode_scope.py reads "
        "config/agents/opencode.yaml and all 21 of its tests error at collection without it"
    )


def test_every_referenced_repo_root_path_is_mounted_or_declared():
    referenced = _referenced_roots()
    assert referenced, "found no /mnt/archie_brain/ references — the scan itself is broken"
    unaccounted = referenced - _mounted_roots() - set(DELIBERATELY_ABSENT)
    assert not unaccounted, (
        "these repo-root paths are read by tests but neither mounted by run_tests.sh nor "
        "declared in DELIBERATELY_ABSENT: %s. Mount it, or declare it with the reason — "
        "a path that is neither goes silently inert." % sorted(unaccounted)
    )


def test_the_absent_list_does_not_rot():
    """A declared-absent path that IS now mounted should be removed from the list, so the
    list keeps describing reality rather than accumulating stale exemptions."""
    both = set(DELIBERATELY_ABSENT) & _mounted_roots()
    assert not both, "declared absent but actually mounted — drop from DELIBERATELY_ABSENT: %s" % sorted(both)
