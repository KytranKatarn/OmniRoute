"""Per-card GPU telemetry drives the fit budget; worst-case is the FALLBACK (#5273/#6106).

The old budget assumed every resident byte sat on the largest card (Ollama's
/api/ps never says which card holds a model). With ~13 GB resident anywhere it
read a 1.3 GB budget and sent every 7B to CPU while the TITAN held 5.7 GB free
(measured 2026-08-28: mistral on GPU 10.5s avg vs qwen2.5:7b on CPU 61s avg,
85 failures/6h). The host exporter now writes real per-card numbers; a missing
or STALE file must fall back to the conservative guess, never to garbage.
"""

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tests.repo_root import repo_root  # noqa: E402

sys.path.insert(0, str(repo_root()))

from services import model_service as ms  # noqa: E402

PLATFORM = Path(__file__).resolve().parents[1]


def _write_state(tmp_path, cards, ts=None, extra=None):
    payload = {"ts": ts if ts is not None else time.time(), "cards": cards, "xid_recent": 0}
    payload.update(extra or {})
    p = tmp_path / "gpu_state.json"
    p.write_text(json.dumps(payload), encoding="utf-8")
    return p


class _FakeService:
    """Only what get_gpu_fit_budget touches: the aggregate-free method."""

    def __init__(self, aggregate_free_gb):
        self._agg = aggregate_free_gb

    def get_available_vram(self):
        return self._agg


def _budget(fake, tmp_path, monkeypatch, path=None):
    monkeypatch.setattr(ms, "_GPU_STATE_PATHS", (str(path or (tmp_path / "gpu_state.json")),))
    return ms.ModelService.get_gpu_fit_budget(fake)


def test_fresh_telemetry_uses_the_freest_card(tmp_path, monkeypatch):
    """TITAN 5700 MB free + Quadro 1300 MB free -> budget is the TITAN's free,
    not the worst-case 1.3 GB that sent 7Bs to CPU."""
    _write_state(tmp_path, [{"index": 0, "mem_free_mb": 1300}, {"index": 1, "mem_free_mb": 5700}])
    got = _budget(_FakeService(aggregate_free_gb=10.0), tmp_path, monkeypatch)
    assert abs(got - 5700 / 1024.0) < 0.01


def test_aggregate_still_caps_the_budget(tmp_path, monkeypatch):
    """A model mid-load in the 30s /api/ps cache window must not be
    double-counted as free: the aggregate stays a ceiling."""
    _write_state(tmp_path, [{"index": 1, "mem_free_mb": 11000}])
    got = _budget(_FakeService(aggregate_free_gb=2.0), tmp_path, monkeypatch)
    assert got == 2.0


def test_stale_telemetry_falls_back_to_worst_case(tmp_path, monkeypatch):
    """A dead exporter makes placement MORE conservative, never wrong."""
    _write_state(tmp_path, [{"index": 1, "mem_free_mb": 11000}], ts=time.time() - 3600)
    fake = _FakeService(aggregate_free_gb=6.6)
    got = _budget(fake, tmp_path, monkeypatch)
    # worst case: used = 20 - 6.6 = 13.4 -> largest_card_free = max(0, 12 - 13.4) = 0
    assert got == 0.0


def test_missing_and_garbage_files_fall_back(tmp_path, monkeypatch):
    fake = _FakeService(aggregate_free_gb=6.6)
    got = _budget(fake, tmp_path, monkeypatch, path=tmp_path / "nope.json")
    assert got == 0.0
    bad = tmp_path / "gpu_state.json"
    bad.write_text("{not json", encoding="utf-8")
    assert _budget(fake, tmp_path, monkeypatch) == 0.0


def test_empty_cards_is_not_trustworthy(tmp_path, monkeypatch):
    """cards=[] (nvidia-smi failed on the host) must read as NO telemetry —
    a budget of max(empty) would crash or hand out 0 for the wrong reason."""
    _write_state(tmp_path, [])
    monkeypatch.setattr(ms, "_GPU_STATE_PATHS", (str(tmp_path / "gpu_state.json"),))
    assert ms.read_gpu_state() is None


def test_watchdog_job_is_registered_every_5_minutes():
    jobs = (PLATFORM / "tools" / "department_hq" / "jobs.py").read_text(encoding="utf-8")
    assert 'id="gpu_state_monitor"' in jobs
    block = jobs.split('id="gpu_state_monitor"')[0][-300:]
    assert "IntervalTrigger(minutes=5)" in block
