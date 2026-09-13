"""AGENTS.md's pointers must resolve (#6736 follow-up).

AGENTS.md is the ONLY instruction file the coder lanes actually read — opencode loads it
from its checkout, and Codex reads it too. This pass added a table pointing at the
platform's procedure playbooks (.claude/commands, .claude/skills), which is worth
something only while the paths are real.

A rotted pointer is worse than no pointer: the lane burns a turn looking for a file that
moved, and the instruction silently stops being followed with nothing going red. Renaming
a skill is fine -- this test just makes you update the map in the same commit.

Deliberately NOT asserted: the file's prose. This pins the REFERENCES, so the guide can be
rewritten freely without a test fighting the author.
"""

import os
import re

import pytest


def _repo_root() -> str:
    """Walk up to the checkout root. The container mounts only platform_v2 at /app, so a
    fixed ../.. lands outside the repo -- the same trap that made every case in
    test_opencode_scope.py raise FileNotFoundError before it walked up instead."""
    here = os.path.abspath(os.path.dirname(__file__))
    while True:
        if os.path.exists(os.path.join(here, "AGENTS.md")):
            return here
        parent = os.path.dirname(here)
        if parent == here:
            break
        here = parent
    fallback = "/mnt/archie_brain"
    if os.path.exists(os.path.join(fallback, "AGENTS.md")):
        return fallback
    raise FileNotFoundError(
        "AGENTS.md not found by walking up from the tests dir. Run where the repo ROOT "
        "is available -- the platform container mounts only platform_v2 at /app."
    )


@pytest.fixture(scope="module")
def agents_md() -> str:
    with open(os.path.join(_repo_root(), "AGENTS.md"), encoding="utf-8") as fh:
        return fh.read()


# Backtick-quoted things that look like repo paths under .claude/ or config/ or scripts/.
_PATH_RE = re.compile(r"`((?:\.claude|config|scripts|platform_v2)/[A-Za-z0-9._/*-]+)`")


def _referenced_paths(text: str) -> set:
    out = set()
    for raw in _PATH_RE.findall(text):
        # A glob describes a SET of files; assert the fixed prefix before the first '*'
        # instead. Taking dirname() is not enough -- `.claude/skills/*/SKILL.md` has the
        # star mid-path, so dirname leaves `.claude/skills/*`, which exists nowhere.
        # (This test caught exactly that in its own first draft.)
        if "*" in raw:
            raw = raw.split("*", 1)[0].rstrip("/")
        out.add(raw)
    return {p for p in out if p}


def test_every_referenced_path_exists(agents_md):
    root = _repo_root()
    missing = sorted(p for p in _referenced_paths(agents_md) if not os.path.exists(os.path.join(root, p)))
    assert not missing, (
        "AGENTS.md points at paths that do not exist: "
        + ", ".join(missing)
        + " -- update the reference in the same commit that moved the file."
    )


def test_it_actually_references_the_playbooks(agents_md):
    """Non-vacuity: the scanner above passes trivially on a file with no paths at all.
    This is the thing the pass was FOR."""
    assert ".claude/commands/" in agents_md
    assert ".claude/skills/" in agents_md


def test_both_lanes_are_pointed_at_their_own_scope(agents_md):
    """The bug this pass fixed: the guide named codex.yaml as 'your scope' while opencode
    read the same file. The two allowlists are NOT identical, so a lane sent to the wrong
    one is told it may edit paths its own guard will refuse."""
    assert "config/agents/codex.yaml" in agents_md
    assert "config/agents/opencode.yaml" in agents_md


def test_opencode_is_not_told_to_push(agents_md):
    """opencode holds no git credential by design (see opencode.yaml). Telling it to run
    `codex-pr` -- which is installed only in the codex terminal -- sends it at a command
    it does not have and a push that cannot succeed."""
    assert (
        "you do not push" in agents_md or "do not ship" in agents_md
    ), "AGENTS.md must state that opencode does not push; the host runner ships its work"
