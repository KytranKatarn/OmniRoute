"""Every task the drift guard WATCHES must have something that WRITES it.

This is the generalisation of a failure gov-watch paid for twice, and it is
worth stating plainly because the broken state looks identical to the healthy
one on every dashboard:

    A task listed in _MAX_AGE_DAYS with no heartbeat writer never gets an
    ingest_log row. `_source_freshness` sees zero rows, treats it as "not yet
    tracked", and skips it — quietly, forever. The task is UNMONITORED WHILE
    APPEARING MONITORED.

gov-watch's `entity_graph_push` sat in exactly that state while its feed was
dead for ~7 weeks (#5799); the guard was green the whole time because it had
nothing to measure. Its fix was
`test_every_monitored_job_has_a_heartbeat_writer`. WTF had the same guard and
no such test — only a digest-specific one — so this adds the general form.

The check is deliberately loose: it asks whether the task NAME appears in a
module that also writes parliament.ingest_log. That cannot prove the writer is
reachable, but it does catch the thing that actually happens — a name added to
the watch list and never wired to anything.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from ingest.parliament.drift_guard import _MAX_AGE_DAYS, _REQUIRED_TASKS

ROOT = Path(__file__).resolve().parents[1]
GUARD = ROOT / "ingest" / "parliament" / "drift_guard.py"


def _writer_sources() -> list[tuple[Path, str]]:
    """Every module under ingest/ that writes parliament.ingest_log."""
    out = []
    for p in ROOT.joinpath("ingest").rglob("*.py"):
        if p == GUARD or "__pycache__" in p.parts:
            continue
        try:
            src = p.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        if "parliament.ingest_log" in src:
            out.append((p, src))
    return out


@pytest.mark.parametrize("task", sorted(_MAX_AGE_DAYS))
def test_every_monitored_task_has_a_heartbeat_writer(task):
    writers = [p.name for p, src in _writer_sources() if task in src]
    assert writers, (
        f"'{task}' is watched by drift_guard but no module under ingest/ that "
        f"writes parliament.ingest_log mentions it. It will never log, the "
        f"guard will skip it as 'not yet tracked', and it will report healthy "
        f"forever while doing nothing."
    )


def test_required_tasks_are_all_actually_monitored():
    """A name in _REQUIRED_TASKS but not _MAX_AGE_DAYS is never iterated, so the
    'has NEVER run' branch it was added for cannot fire."""
    orphans = sorted(_REQUIRED_TASKS - set(_MAX_AGE_DAYS))
    assert not orphans, f"required but not watched: {orphans}"


def test_the_new_elections_task_is_wired_end_to_end():
    """Named explicitly rather than relying on the parametrised sweep, so the
    intent survives someone narrowing that sweep later."""
    assert "elections_results" in _MAX_AGE_DAYS
    assert "elections_results" in _REQUIRED_TASKS
    writers = [p.name for p, src in _writer_sources() if "elections_results" in src]
    assert "results.py" in writers, writers
    # and it must actually be scheduled, or the window measures nothing
    run_py = (ROOT / "ingest" / "run.py").read_text(encoding="utf-8")
    assert "run_election_results" in run_py, "registered but never scheduled"
