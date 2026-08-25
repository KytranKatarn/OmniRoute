"""ONE way to find the repo root from a test (#5994).

`Path(__file__).resolve().parents[2]` is correct on the HOST — this file sits at
`/mnt/archie_brain/platform_v2/tests/`, so two levels up is the repo. Inside the test
container `platform_v2` is bind-mounted AS `/app`, so the same expression resolves one
level too shallow: to the **filesystem root**. Every path built from it becomes
`/scripts/...` or `/standalone/...`, which exist nowhere.

⚠️ THE DAMAGE IS SKIPS, NOT FAILURES. Files hitting this did not fail loudly — they
guarded with `pytest.mark.skipif(not path.exists())` and skipped. Measured 2026-08-25,
before this module existed:

    SKIPPED tests/test_retention_predeploy_prune.py — "retention_prune.py not reachable" (x6)
    SKIPPED tests/test_media_hub_probe_honesty.py   — ".../health_observer.py (not mounted)"

Seven tests reported green while testing nothing, and the skip reason blamed a missing
mount rather than the wrong path. That is why this recurred: #5916 fixed one file, #5994
fixed another, and each left the next one to be rediscovered. Four files still carry
comments explaining the bug instead of a fix.

Import this instead of counting parents:

    from tests.repo_root import repo_root, repo_path

    RETENTION = repo_path("scripts", "backup", "retention_prune.py")
"""

from pathlib import Path

# Files that exist at the repo root and nowhere else. `scripts/backup/retention_prune.py`
# is deliberately specific: a bare `scripts` directory also exists under other trees, and
# matching it would let the search stop somewhere plausible but wrong.
_MARKERS = (
    Path("scripts") / "backup" / "retention_prune.py",
    Path("ai_bridge") / "agent_loop.py",
    Path("docker-compose.yml"),
)

# The container mounts the repo here while __file__ lives under /app, so NO ancestor of
# this file is the repo root — the ancestor walk alone cannot succeed there.
_CONTAINER_REPO = Path("/mnt/archie_brain")


def repo_root() -> Path:
    """The repository root, on the host and inside the test container alike."""
    for base in list(Path(__file__).resolve().parents) + [_CONTAINER_REPO]:
        if any((base / m).exists() for m in _MARKERS):
            return base
    # Deliberately NOT an exception: callers guard on `.exists()` and skip, and raising
    # here would turn a missing file into a collection error for the whole module.
    return _CONTAINER_REPO


def platform_root() -> Path:
    """The platform_v2 root — `/app` in the container, `<repo>/platform_v2` on the host.

    Distinct from repo_root(): this is the tree that is bind-mounted, so a path under it is
    reachable in BOTH environments without a mount. Prefer it over an absolute host path
    like "/mnt/archie_brain/platform_v2/..." which simply does not exist in the container.
    """
    return Path(__file__).resolve().parents[1]


def repo_path(*parts: str) -> Path:
    """`repo_root()` joined with `parts` — the shape almost every caller wants."""
    return repo_root().joinpath(*parts)
