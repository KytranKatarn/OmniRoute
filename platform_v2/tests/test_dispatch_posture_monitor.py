"""The #5596 alarm must fire on the incident it was built for — and stay quiet otherwise.

Every number in `test_replays_the_real_incident` is MEASURED from
task_execution_log for the 2026-08-04 GPU failure, not invented. If a future
threshold tweak stops these firing, the alarm has regressed to the state that
let the platform run degraded for eight days unnoticed.

The silence tests matter just as much: an alarm that pages on healthy traffic
gets muted by humans, which is indistinguishable from having no alarm.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


def _find(rel: str) -> Path:
    """Locate a module from either layout (host repo, or /app in-container)."""
    for base in (Path(__file__).resolve().parents[1], Path("/app")):
        p = base / rel
        if p.is_file():
            return p
    raise AssertionError(f"{rel} not found")


_MOD = _find("services/dispatch_posture_monitor.py")


def _load():
    spec = importlib.util.spec_from_file_location("_dpm", _MOD)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _health(total, failed, avg_s, pending=0):
    """Shape a dispatch_health() return from day-level incident figures."""
    success = total - failed
    return {
        "total": total,
        "success": success,
        "failed": failed,
        "failed_real": failed,
        "failed_timeout": 0,
        "pending": pending,
        "decided": total,
        "success_rate": round(success / total * 100, 1) if total else 0.0,
        "success_rate_real": round(success / total * 100, 1) if total else 0.0,
        "avg_duration_ms": avg_s * 1000.0,
        "tokens": 0,
    }


@pytest.fixture
def harness(monkeypatch):
    """Drive check_dispatch_posture with canned windows; capture alerts."""
    mod = _load()
    sent = []

    def _install(by_hours, default=None):
        def fake_health(hours=24.0):
            for h, payload in by_hours.items():
                if abs(float(hours) - h) < 0.01:
                    return payload
            if default is not None:
                return default
            raise AssertionError(f"unexpected window {hours}h")

        monkeypatch.setattr(mod, "_thresholds", lambda cur: dict(mod._DEFAULTS))
        # get_db_cursor is only used to read threshold overrides, stubbed above.
        import contextlib

        @contextlib.contextmanager
        def fake_cursor(*a, **k):
            yield (None, None)

        import sys
        import types

        db_stub = types.ModuleType("database")
        db_stub.get_db_cursor = fake_cursor
        dh_stub = types.ModuleType("services.dispatch_health_service")
        dh_stub.dispatch_health = fake_health
        tg_stub = types.ModuleType("services.telegram_service")
        tg_stub.send_system = lambda **kw: sent.append(kw) or {"ok": True}
        monkeypatch.setitem(sys.modules, "database", db_stub)
        monkeypatch.setitem(sys.modules, "services.dispatch_health_service", dh_stub)
        monkeypatch.setitem(sys.modules, "services.telegram_service", tg_stub)
        return mod

    return _install, sent


# --- THE REGRESSION: the 8-day blind spot ------------------------------------


def test_replays_the_real_incident(harness):
    """2026-08-06 vs the healthy week before it. MUST alert.

    Measured: healthy ~11750 runs/day, 181 failed (1.5%), 24.5s avg.
    Degraded 08-06: 7436 runs/day, 1002 failed (13.5%), 44.9s avg.
    """
    install, sent = harness
    healthy_week = _health(total=11750 * 7, failed=181 * 7, avg_s=24.5)
    degraded_6h = _health(total=int(7436 / 4), failed=int(1002 / 4), avg_s=44.9)
    degraded_24h = _health(total=7436, failed=1002, avg_s=44.9)
    mod = install({6.0: degraded_6h, 168.0: healthy_week, 1.0: degraded_6h, 24.0: degraded_24h})

    res = mod.check_dispatch_posture()
    checks = res["checks"]

    assert checks["failure_rate"]["status"] == "alert", checks["failure_rate"]
    assert checks["latency"]["status"] == "alert", checks["latency"]
    assert res["alerts_sent"] >= 2, sent
    # Distinct titles: send_system dedups on (title, source), so a shared
    # title would let one condition mute the others.
    titles = [a["title"] for a in sent]
    assert len(titles) == len(set(titles)), titles


def test_replays_the_worst_incident_day_including_throughput(harness):
    """2026-08-12: 5528 runs (down from ~11750) — throughput must fire too."""
    install, sent = harness
    healthy_week = _health(total=11750 * 7, failed=181 * 7, avg_s=24.5)
    bad_6h = _health(total=int(5528 / 4), failed=int(362 / 4), avg_s=49.0)
    bad_24h = _health(total=5528, failed=362, avg_s=49.0)
    mod = install({6.0: bad_6h, 168.0: healthy_week, 1.0: bad_6h, 24.0: bad_24h})

    res = mod.check_dispatch_posture()
    assert res["checks"]["throughput"]["status"] == "alert", res["checks"]["throughput"]
    assert res["checks"]["latency"]["status"] == "alert"


# --- SILENCE: an alarm that cries wolf gets muted ----------------------------


def test_healthy_platform_is_silent(harness):
    install, sent = harness
    healthy_week = _health(total=11750 * 7, failed=181 * 7, avg_s=24.5)
    healthy_6h = _health(total=int(11750 / 4), failed=int(181 / 4), avg_s=25.5)
    healthy_24h = _health(total=11750, failed=181, avg_s=24.9)
    mod = install({6.0: healthy_6h, 168.0: healthy_week, 1.0: healthy_6h, 24.0: healthy_24h})

    res = mod.check_dispatch_posture()
    assert res["alerts_sent"] == 0, sent
    assert all(c["status"] == "ok" for c in res["checks"].values()), res["checks"]


def test_normal_daily_variation_is_silent(harness):
    """Healthy days already swing 21->27s and 10.8k->13.1k runs. Not an alert."""
    install, sent = harness
    baseline = _health(total=11750 * 7, failed=181 * 7, avg_s=24.5)
    busy_6h = _health(total=int(13101 / 4), failed=int(416 / 4), avg_s=26.9)
    busy_24h = _health(total=13101, failed=416, avg_s=26.9)
    mod = install({6.0: busy_6h, 168.0: baseline, 1.0: busy_6h, 24.0: busy_24h})

    res = mod.check_dispatch_posture()
    assert res["alerts_sent"] == 0, sent


def test_absolute_ceiling_bites_through_a_poisoned_baseline(harness):
    """A long incident poisons the rolling baseline — the ceiling must still fire.

    MEASURED LIVE 2026-08-15: with the 8-day outage still inside the 7-day
    window, the baseline read 12.2% / 48.1s, pushing the RELATIVE trip points
    to 36.7% / 77.0s. Without an absolute ceiling the alarm would sit silent
    through a fresh recurrence of the exact incident it exists to catch.
    """
    install, sent = harness
    poisoned = _health(total=7000 * 7, failed=int(7000 * 7 * 0.122), avg_s=48.1)
    fresh_6h = _health(total=1800, failed=int(1800 * 0.25), avg_s=75.0)
    fresh_24h = _health(total=7200, failed=int(7200 * 0.25), avg_s=75.0)
    mod = install({6.0: fresh_6h, 168.0: poisoned, 1.0: fresh_6h, 24.0: fresh_24h})

    res = mod.check_dispatch_posture()
    # 25% > the 20% ceiling even though the poisoned ratio trip is ~36.7%.
    assert res["checks"]["failure_rate"]["status"] == "alert", res["checks"]["failure_rate"]
    # 75s > the 70s ceiling even though the poisoned ratio trip is ~77s.
    assert res["checks"]["latency"]["status"] == "alert", res["checks"]["latency"]


# --- FAIL-SAFE: uncertainty must not page, and must not crash ----------------


def test_thin_data_is_unknown_not_alert(harness):
    """A fresh deploy has no baseline. Report it; never page on it."""
    install, sent = harness
    tiny = _health(total=5, failed=4, avg_s=200.0)
    mod = install({6.0: tiny, 168.0: tiny, 1.0: tiny, 24.0: tiny})

    res = mod.check_dispatch_posture()
    assert res["checks"]["failure_rate"]["status"] == "unknown"
    assert res["checks"]["throughput"]["status"] == "unknown"
    assert not any(a["title"].startswith("Dispatch failure") for a in sent)


def test_zero_dispatch_fires_liveness(harness):
    """The 29-minute dead platform on 2026-08-15 — nothing paged."""
    install, sent = harness
    healthy_week = _health(total=11750 * 7, failed=181 * 7, avg_s=24.5)
    dead = _health(total=0, failed=0, avg_s=0)
    mod = install({6.0: dead, 168.0: healthy_week, 1.0: dead, 24.0: dead})

    res = mod.check_dispatch_posture()
    assert res["checks"]["liveness"]["status"] == "alert"
    assert any("STOPPED" in a["title"] for a in sent), sent
    assert any(a.get("severity") == "critical" for a in sent)


def test_never_raises_when_health_source_breaks(harness):
    """A monitor that can crash is a monitor that silently stops monitoring."""
    install, _ = harness
    mod = install({}, default=None)

    import sys
    import types

    boom = types.ModuleType("services.dispatch_health_service")

    def _raise(hours=24.0):
        raise RuntimeError("db gone")

    boom.dispatch_health = _raise
    sys.modules["services.dispatch_health_service"] = boom

    res = mod.check_dispatch_posture()
    assert res["ok"] is False
    assert "error" in res


# --- #5606: the observer must be OBSERVABLE ----------------------------------


def test_heartbeat_records_on_a_healthy_run(harness, monkeypatch):
    """Silent-when-healthy makes 'running' indistinguishable from 'dead'."""
    install, _ = harness
    healthy_week = _health(total=11750 * 7, failed=181 * 7, avg_s=24.5)
    healthy = _health(total=int(11750 / 4), failed=int(181 / 4), avg_s=25.0)
    mod = install({6.0: healthy, 168.0: healthy_week, 1.0: healthy, 24.0: healthy})

    seen = {}
    monkeypatch.setattr(mod, "_record_run", lambda res: seen.update(res))

    res = mod.check_dispatch_posture()
    assert seen, "a healthy run must still leave a trace"
    assert seen.get("ok") is True
    assert set(seen.get("checks", {})) == {"liveness", "failure_rate", "latency", "throughput"}


def test_heartbeat_records_on_the_failure_path(harness, monkeypatch):
    """'Broken' must look different from 'quiet' — crash runs record too."""
    install, _ = harness
    mod = install({}, default=None)

    import sys
    import types

    boom = types.ModuleType("services.dispatch_health_service")

    def _raise(hours=24.0):
        raise RuntimeError("db gone")

    boom.dispatch_health = _raise
    sys.modules["services.dispatch_health_service"] = boom

    seen = {}
    monkeypatch.setattr(mod, "_record_run", lambda res: seen.update(res))

    res = mod.check_dispatch_posture()
    assert res["ok"] is False
    assert seen.get("ok") is False, "a crashing monitor must still record that it ran"


def test_heartbeat_failure_cannot_break_the_check(harness, monkeypatch):
    """A monitor must not die because it could not write its own heartbeat."""
    install, _ = harness
    healthy_week = _health(total=11750 * 7, failed=181 * 7, avg_s=24.5)
    healthy = _health(total=int(11750 / 4), failed=int(181 / 4), avg_s=25.0)
    mod = install({6.0: healthy, 168.0: healthy_week, 1.0: healthy, 24.0: healthy})

    # _record_run swallows its own errors; prove the check still returns.
    res = mod.check_dispatch_posture()
    assert res["ok"] is True
    assert res["checks"]["liveness"]["status"] == "ok"


def test_last_run_key_is_not_mistaken_for_a_threshold(harness):
    """The stamp lives under the same `dispatch:posture:` prefix the threshold
    loader scans with LIKE. It must be ignored there, not parsed as a number."""
    mod = _load()
    assert mod._LAST_RUN_KEY.startswith(mod._SETTING_PREFIX)
    assert mod._LAST_RUN_KEY[len(mod._SETTING_PREFIX) :] not in mod._DEFAULTS


# --- proof the suite bites (repair-bay.md) -----------------------------------


def test_suite_detects_a_disabled_alarm(tmp_path, harness):
    """Neuter the thresholds in a COPY; the incident replay must then FAIL.

    Guards against a future "tuning" commit that quietly raises thresholds
    beyond the incident and leaves the tests passing.
    """
    src = _MOD.read_text()
    broken = src.replace('"fail_floor_pct": 8.0,', '"fail_floor_pct": 99.0,').replace(
        '"latency_ratio": 1.6,', '"latency_ratio": 99.0,'
    )
    assert broken != src, "threshold markers not found — update this test with the module"

    copy = tmp_path / "dpm_broken.py"
    copy.write_text(broken)
    spec = importlib.util.spec_from_file_location("_dpm_broken", copy)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    install, _ = harness
    install({})  # installs the stub modules into sys.modules
    healthy_week = _health(total=11750 * 7, failed=181 * 7, avg_s=24.5)
    degraded = _health(total=int(7436 / 4), failed=int(1002 / 4), avg_s=44.9)

    import sys
    import types

    dh = types.ModuleType("services.dispatch_health_service")
    dh.dispatch_health = lambda hours=24.0: (healthy_week if abs(float(hours) - 168.0) < 0.01 else degraded)
    sys.modules["services.dispatch_health_service"] = dh
    mod._thresholds = lambda cur: dict(mod._DEFAULTS)

    res = mod.check_dispatch_posture()
    assert res["checks"]["failure_rate"]["status"] == "ok", "defect must reproduce in the copy"
    assert res["checks"]["latency"]["status"] == "ok", "defect must reproduce in the copy"
