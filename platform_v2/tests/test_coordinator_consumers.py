"""Source-level test: lightweight classify/detect_language consumers route
through the coordinator lane (services.coordinator_lane.coordinator_dispatch).

These modules import db/dispatcher singletons at module scope and can't be
unit-booted outside the container, so this test asserts on source text
rather than importing the modules.
"""

from pathlib import Path
from tests.repo_root import repo_root

FILES = [
    "ai_bridge/emotional_intelligence.py",
    "ai_bridge/auto_tagger.py",
    "ai_bridge/translation_service.py",
    "scripts/wtf_beat_classifier.py",
]

# In the archie_platform container, platform_v2/ is bind-mounted at /app while
# ai_bridge/ and scripts/ are bind-mounted separately at /mnt/archie_brain/* —
# so this test file is NOT nested under the repo root there. On a normal
# checkout (host, CI), platform_v2/tests/<this file> IS nested 2 levels under
# the repo root. Try the container-shaped absolute path first, then fall back
# to the nested-checkout shape.
_CANDIDATE_ROOTS = [
    Path("/mnt/archie_brain"),
    repo_root(),
]


def _repo_root() -> Path:
    for root in _CANDIDATE_ROOTS:
        if (root / "ai_bridge" / "emotional_intelligence.py").is_file():
            return root
    raise FileNotFoundError(f"Could not locate repo root containing ai_bridge/ among {_CANDIDATE_ROOTS}")


REPO_ROOT = _repo_root()


def test_consumers_use_coordinator_dispatch():
    for f in FILES:
        src = (REPO_ROOT / f).read_text()
        assert "coordinator_dispatch" in src, f"{f} should route classify via coordinator_dispatch"
