"""Coordinator-lane model_sizes coverage (Task 2, coordinator-lane Phase 1).

The coordinator model (qwen25-classify) must resolve to a small, CPU-preferring
footprint. Without an explicit _TABLE entry, model_sizes.lookup() falls through
to the conservative GPU-leaning default (prefer_gpu=True), which — combined
with the department_dispatcher marker gap — mis-tags it as a heavy 7B and
causes it to be shed by the hub admission gate. See test_dispatch_scoring.py
::TestModelIsGpuClass for the companion dispatcher-side check.
"""

from services import model_sizes


def test_coordinator_model_is_cpu_small():
    fp = model_sizes.lookup("qwen25-classify")
    assert fp.prefer_gpu is False
    assert fp.vram_gb <= 2.0
