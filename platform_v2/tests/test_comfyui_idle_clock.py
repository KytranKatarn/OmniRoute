"""ComfyUI idle-clock regression tests (task #5277).

THE BUG (measured on the hub 2026-07-27 07:27-07:33):

    07:27:53  [ComfyUI] Waiting up to 90s for health
    07:29:23  Timed out waiting for health after wake
    07:29:53  media_generation_worker: ComfyUI stopped - P.I.X.E.L. warming up container
    07:30:21  ComfyUI idle for 2995874s > 1800s - stopping      <-- 34.7 DAYS
    07:31:53  [ComfyUI] Container archie_comfyui (exited) - starting

`ensure_running()` stamped `last_used` on two paths (already-running, and a
cold-start whose health check answered) but NOT on the path where the container
was STARTED and the health wait then timed out. ComfyUI is currently broken and
never answers /system_stats, so every wake took that third path.

Result: the warmer starts the container, `last_used` still reads 2026-06-22, and
the idle reaper - which correctly sees `idle_for` = 34.7 days > 1800s - stops the
container roughly 28 seconds after it was started. The warmer starts it again.
Livelock, ~2 minute period, indefinitely.

Each wake fires the ComfyUI VRAM swap, which unloads the Ollama GPU models to
make room for an SDXL load that never arrives - so the agent 7Bs get evicted to
CPU repeatedly, for an image queue that is EMPTY (89 failed / 3 completed /
0 pending). That is what erased the benefit of PR #2500 within 3 minutes of
deploying it.

THE FIX: starting the container IS use. Stamp `last_used` immediately after a
successful `container.start()`, before the health wait, so a container that was
just started on demand is never judged idle.
"""

from __future__ import annotations

import sys
import types
from pathlib import Path
from unittest import mock

import pytest

# Import the module directly, without dragging in the package conftest's DB deps.
_SERVICES = Path(__file__).resolve().parents[1] / "services"
sys.path.insert(0, str(_SERVICES.parent))

from services import comfyui_lifecycle as cl  # noqa: E402


class _FakeContainer:
    """Minimal docker-py container stand-in."""

    def __init__(self, status: str = "exited", start_raises: bool = False):
        self.status = status
        self._start_raises = start_raises
        self.started = False
        self.stopped = False
        self.restart_policies: list = []

    def reload(self):
        pass

    def update(self, restart_policy=None, **_):
        self.restart_policies.append(restart_policy)

    def start(self):
        if self._start_raises:
            raise RuntimeError("boom")
        self.started = True
        self.status = "running"

    def stop(self, timeout=None):
        self.stopped = True
        self.status = "exited"


class _Clock:
    """A fake clock where sleeping ADVANCES time.

    Freezing time.time() while stubbing time.sleep() to a no-op deadlocks
    `ensure_running`: its `while time.time() < deadline` can never terminate and
    it spins at 100% CPU. Sleep must move the clock, exactly as it does in
    reality.
    """

    def __init__(self, start: float = 1_800_000_000.0):
        self.now = float(start)

    def time(self) -> float:
        return self.now

    def sleep(self, seconds: float = 0.0) -> None:
        self.now += float(seconds) or 0.01

    def advance(self, seconds: float) -> None:
        self.now += float(seconds)


@pytest.fixture
def clock():
    c = _Clock()
    with mock.patch.object(cl.time, "time", c.time), mock.patch.object(cl.time, "sleep", c.sleep):
        yield c


@pytest.fixture
def never_answers(clock):
    """ComfyUI never responds to /system_stats - the live hub condition."""
    fake_requests = types.SimpleNamespace(get=mock.Mock(side_effect=ConnectionError("refused")))
    with mock.patch.dict(sys.modules, {"requests": fake_requests}):
        yield fake_requests


@pytest.fixture
def answers_ok(clock):
    ok = types.SimpleNamespace(status_code=200)
    fake_requests = types.SimpleNamespace(get=mock.Mock(return_value=ok))
    with mock.patch.dict(sys.modules, {"requests": fake_requests}):
        yield fake_requests


# ---------------------------------------------------------------------------
# ensure_running - the stamping contract
# ---------------------------------------------------------------------------


def test_failed_health_wait_still_stamps_last_used(never_answers):
    """THE REGRESSION. Container started but health timed out -> must still stamp.

    Without this, the reaper reads a month-old timestamp and kills the container
    the warmer just started, ~28s in, forever.
    """
    container = _FakeContainer(status="exited")
    with mock.patch.object(cl, "_get_container", return_value=container), mock.patch.object(
        cl, "record_last_used"
    ) as rec:
        result = cl.ensure_running(timeout=0.05)

    assert result is False, "health never answered, so ensure_running must report failure"
    assert container.started is True, "the container should still have been started"
    assert rec.called, (
        "last_used MUST be stamped when the container is started, even if the "
        "health wait then fails - otherwise the idle reaper kills a container "
        "that was just started on demand (task #5277 livelock)"
    )


def test_start_failure_does_not_stamp(never_answers):
    """If we could not even start it, nothing was used - do not stamp."""
    container = _FakeContainer(status="exited", start_raises=True)
    with mock.patch.object(cl, "_get_container", return_value=container), mock.patch.object(
        cl, "record_last_used"
    ) as rec:
        result = cl.ensure_running(timeout=0.05)

    assert result is False
    assert not rec.called, "a container that never started was not used"


def test_already_running_stamps(answers_ok):
    container = _FakeContainer(status="running")
    with mock.patch.object(cl, "_get_container", return_value=container), mock.patch.object(
        cl, "record_last_used"
    ) as rec:
        assert cl.ensure_running(timeout=0.05) is True
    assert rec.called


def test_successful_cold_start_stamps(answers_ok):
    container = _FakeContainer(status="exited")
    with mock.patch.object(cl, "_get_container", return_value=container), mock.patch.object(
        cl, "record_last_used"
    ) as rec:
        assert cl.ensure_running(timeout=5) is True
    assert container.started is True
    assert rec.called


def test_no_container_returns_false_without_stamping(never_answers):
    with mock.patch.object(cl, "_get_container", return_value=None), mock.patch.object(cl, "record_last_used") as rec:
        assert cl.ensure_running(timeout=0.05) is False
    assert not rec.called


# ---------------------------------------------------------------------------
# The livelock itself - the two functions in sequence
# ---------------------------------------------------------------------------


def test_reaper_spares_a_container_the_warmer_just_started(never_answers, clock):
    """End-to-end shape of the outage: wake (health fails) then reap must NOT stop it.

    This is the assertion that actually encodes the incident. Before the fix the
    reaper stopped the container ~28s after the warmer started it, forever.
    """
    container = _FakeContainer(status="exited")

    # Production state: last_used is STALE-BUT-PRESENT (the hub read 2026-06-22,
    # ~34.7 days back). This matters - with NO timestamp at all the reaper takes
    # its benign "seed and skip" branch and the bug does not reproduce. The
    # livelock needs an old timestamp so the reaper takes the idle_for > max path.
    stamped = {"at": clock.now - 2_995_874}

    with mock.patch.object(cl, "_get_container", return_value=container), mock.patch.object(
        cl, "record_last_used", side_effect=lambda: stamped.__setitem__("at", clock.now)
    ), mock.patch.object(cl, "get_last_used", side_effect=lambda: stamped.get("at")):
        # Warmer wakes it; ComfyUI never becomes healthy.
        cl.ensure_running(timeout=1)
        assert container.started is True

        # Reaper runs 28 seconds later, exactly as observed on the hub.
        clock.advance(28)
        outcome = cl.idle_stop_if_needed(max_idle_seconds=1800)

    assert container.stopped is False, (
        "the reaper must not stop a container that was started 28s ago " "(task #5277 livelock)"
    )
    assert outcome["action"] == "skip", f"expected skip, got {outcome}"


def test_reaper_still_stops_a_genuinely_idle_container(never_answers, clock):
    """The fix must not disable the reaper - a real idle container still stops."""
    container = _FakeContainer(status="running")
    stamped = {"at": clock.now}

    with mock.patch.object(cl, "_get_container", return_value=container), mock.patch.object(
        cl, "record_last_used", side_effect=lambda: stamped.__setitem__("at", clock.now)
    ), mock.patch.object(cl, "get_last_used", side_effect=lambda: stamped.get("at")):
        clock.advance(3600)  # an hour of genuine idleness
        outcome = cl.idle_stop_if_needed(max_idle_seconds=1800)

    assert container.stopped is True, "a genuinely idle container must still be stopped"
    assert outcome["action"] == "stopped", f"expected stopped, got {outcome}"
