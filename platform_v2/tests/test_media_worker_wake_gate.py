"""Regression test — the media_generation_worker's hub ComfyUI wake is gated on
a real pending ComfyUI-bound queue row (task #5277, defect 3).

With an EMPTY queue the worker used to wake the hub container anyway whenever
fleet ComfyUI was unreachable (e.g. the 8PM–6AM hardware-rest window). Each
start claims GPU VRAM (compose reserves an nvidia device), so agent inference
lost the card to an SDXL load that never arrives; #2503 bounded the wake/reap
churn to once per 30-min idle window but did not remove the needless wake.

Source-level check: the worker can't be unit-booted (APScheduler + Flask app
context + a live DB), so this asserts on the source text directly — same
pattern and repo-root resolution as test_warm_keep_coordinator.py.
"""

from __future__ import annotations

from pathlib import Path


def _find_repo_root() -> Path:
    candidate = Path(__file__).resolve()
    for parent in candidate.parents:
        if (parent / "ai_bridge" / "agent_loop.py").exists():
            return parent
    # Absolute fallback for the container mount point
    return Path("/mnt/archie_brain")


REPO = _find_repo_root()
SRC = (REPO / "ai_bridge" / "agent_loop.py").read_text()

WAKE_GATE = "if _comfyui_pending and not _fleet_available:"


def test_hub_wake_is_gated_on_pending_comfyui_work():
    assert WAKE_GATE in SRC, "hub ComfyUI wake must require a pending ComfyUI-bound queue row (#5277)"


def test_pending_peek_runs_before_the_wake_gate():
    peek = "_comfyui_pending = False"
    assert peek in SRC
    assert SRC.index(peek) < SRC.index(WAKE_GATE), "the pending peek must be evaluated before the wake gate reads it"


def test_bare_fleet_fallback_wake_is_gone():
    # The old gate woke the hub whenever fleet was unavailable, queue or no queue.
    assert "if not _fleet_available:\n            # Fall back to hub ComfyUI" not in SRC


def test_idle_stop_path_survives():
    # The empty-queue tick must still reap an idle container so the GPUs return
    # to agent inference — gating the wake must not have removed the reap.
    assert "stop_if_idle" in SRC
