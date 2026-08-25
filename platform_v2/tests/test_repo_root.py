"""The repo-root resolver, and a sweep that stops #5994 recurring a fifth time.

History: #5916 fixed one file. #5994 fixed another. Three more had grown their own
hand-rolled two-candidate workaround, and two had no workaround at all — those two SKIPPED,
silently, reporting green while testing nothing:

    SKIPPED tests/test_retention_predeploy_prune.py — "retention_prune.py not reachable" (x6)
    SKIPPED tests/test_media_hub_probe_honesty.py   — "...not mounted in this container"

The summary said "7 skipped". It was really **19 tests** not running: the media_hub guard is
a MODULE-level skip, which pytest counts as ONE line however many tests it hides (13 here).
A skip count is a floor, not a measure.

The second skip message is the instructive one: "not mounted" was TRUE, but the path being
probed was `/standalone/...` — the wrong path named the wrong cause, so it read as an
infrastructure gap rather than arithmetic.

The rule this file enforces: inside the test container `platform_v2` is mounted AS `/app`,
so `parents[N]` counted from a test file means one level LESS than it does on the host.
Anything that walks past the platform_v2 root lands on `/`.
"""

import ast
from pathlib import Path

from tests.repo_root import repo_path, repo_root

_TESTS_DIR = Path(__file__).resolve().parent


# ----------------------------------------------------------------- the resolver itself


def test_repo_root_finds_a_real_repo():
    root = repo_root()
    assert (root / "ai_bridge" / "agent_loop.py").exists(), f"not a repo root: {root}"


def test_repo_root_is_not_the_filesystem_root():
    """The exact failure being eliminated."""
    assert repo_root() != Path("/"), "resolver returned the filesystem root — this is #5994"


def test_repo_path_joins_from_the_root():
    p = repo_path("scripts", "backup", "retention_prune.py")
    assert p.exists(), f"{p} does not exist — the resolver picked the wrong root"


def test_the_two_files_that_used_to_skip_are_reachable():
    """Pins the actual win. If either regresses, 19 tests go back to skipping green."""
    assert repo_path("scripts", "backup", "retention_prune.py").exists()
    assert repo_path("standalone", "media_hub", "health_observer.py").exists(), (
        "needs the standalone mount in scripts/run_tests.sh — without it " "test_media_hub_probe_honesty skips"
    )


# ------------------------------------------------------------------------- the sweep


def _escaping_parents(source: str, depth_under_platform_v2: int):
    """Return [(lineno, index)] for `.parents[N]` that walks past the platform_v2 root.

    A file at `tests/x.py` has depth 1: parents[1] IS platform_v2 (== /app in the
    container), so parents[2] is already `/`. At `tests/services/x.py` depth is 2 and
    parents[2] is still fine. The threshold is therefore depth + 1, NOT a fixed number —
    which is why `tests/services/test_doc_service.py` legitimately uses parents[2].
    """
    out = []
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return out
    for n in ast.walk(tree):
        if (
            isinstance(n, ast.Subscript)
            and isinstance(n.value, ast.Attribute)
            and n.value.attr == "parents"
            and isinstance(n.slice, ast.Constant)
            and isinstance(n.slice.value, int)
            and n.slice.value > depth_under_platform_v2
        ):
            out.append((n.lineno, n.slice.value))
    return out


def test_the_sweep_flags_an_escaping_index():
    """Negative control — a guard that cannot fail is worse than no guard."""
    src = "from pathlib import Path\nROOT = Path(__file__).resolve().parents[2]\n"
    assert _escaping_parents(src, 1) == [(2, 2)]


def test_the_sweep_allows_a_legitimate_deeper_file():
    """`tests/services/test_doc_service.py` uses parents[2] CORRECTLY — depth 2 means
    parents[2] is platform_v2, not the filesystem root. A fixed threshold would have
    produced a false positive here and invited an allowlist entry for correct code."""
    src = "from pathlib import Path\nROOT = Path(__file__).resolve().parents[2]\n"
    assert _escaping_parents(src, 2) == []


def test_no_test_file_walks_past_the_platform_root():
    violations = []
    scanned = 0
    for p in sorted(_TESTS_DIR.rglob("*.py")):
        if "__pycache__" in p.parts:
            continue
        scanned += 1
        depth = len(p.relative_to(_TESTS_DIR.parent).parts) - 1  # tests/x.py -> 1
        for lineno, idx in _escaping_parents(p.read_text(errors="replace"), depth):
            violations.append(f"{p.name}:{lineno} — parents[{idx}] at depth {depth} resolves to '/'")

    # An empty sweep is not a pass.
    assert scanned > 50, f"sweep only reached {scanned} files"

    assert not violations, (
        "These resolve to the FILESYSTEM ROOT inside the test container, where platform_v2\n"
        "is mounted as /app. Use `from tests.repo_root import repo_path` instead.\n"
        "Note the damage is usually a silent SKIP, not a failure (#5994).\n\n" + "\n".join(violations)
    )
