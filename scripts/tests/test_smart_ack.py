"""Acknowledged-disk policy for scripts/smart_posture_monitor.py (task #6803).

The monitor is loaded from the SHIPPED script and driven with injected scan/read/push functions: no smartctl, docker or Telegram.
"""

import importlib.util
import json
import time
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "smart_posture_monitor.py"
spec = importlib.util.spec_from_file_location("smart_posture_monitor", SCRIPT)
mon = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mon)

SERIAL = "Z504K0DJ"
DAY = 86400


def disk(pending=1784, realloc=0, crc=0, health=True, serial=SERIAL, unreadable=False):
    if unreadable:
        return None, {}, "ST3000DM008", serial
    return health, {197: pending, 198: pending, 5: realloc, 199: crc}, "ST3000DM008", serial


class Harness:
    def __init__(self, tmp_path):
        self.path = str(tmp_path / "ack.json")
        self.state_path = str(tmp_path / "state.json")
        self.pushed = []
        self.now = 1_800_000_000.0
        self.kerr = (
            {}
        )  # injected kernel-error counts per short device name; the real journal and /var/lib are never touched

    def run(self, state, dev="/dev/sdb"):
        mon.main(
            scan=lambda: [dev],
            read=lambda d: state,
            push=lambda title, msg, sev, cd: self.pushed.append((title, msg, sev)) or True,
            ack_path=self.path,
            now=self.now,
            kernel=lambda: dict(self.kerr),
            state_path=self.state_path,
        )

    def ack(self, state, note="awaiting swap", dev="/dev/sdb"):
        assert (
            mon.cmd_ack(
                dev, note, ack_path=self.path, read=lambda d: state, now=self.now, kernel=lambda: dict(self.kerr)
            )
            == 0
        )


@pytest.fixture
def h(tmp_path):
    return Harness(tmp_path)


def test_an_unacknowledged_failing_disk_pages_critical_exactly_as_before(h):
    h.run(disk())
    assert len(h.pushed) == 1 and h.pushed[0][2] == "critical"


def test_an_acknowledged_disk_at_the_same_counters_stays_silent(h):
    h.ack(disk())
    h.now += 3 * 3600
    h.run(disk())
    assert h.pushed == []


def test_small_growth_inside_the_band_does_not_page(h):
    h.ack(disk(pending=1784))
    h.run(disk(pending=1830))  # +46 but only 2.6%
    assert h.pushed == []


def test_crossing_the_band_pages_once_then_the_baseline_moves_up(h):
    h.ack(disk(pending=1784))
    h.run(disk(pending=2300))  # +29%, +516
    assert len(h.pushed) == 1 and "WORSENED since acknowledgement" in h.pushed[0][1] and h.pushed[0][2] == "critical"
    h.pushed.clear()
    h.run(disk(pending=2300))  # unchanged -> silent
    h.run(disk(pending=2800))  # +21.7% of the NEW baseline -> still inside the band
    assert h.pushed == []
    h.run(disk(pending=2900))  # +26% of 2300 -> next band
    assert len(h.pushed) == 1


def test_a_counter_that_was_zero_becoming_nonzero_pages(h):
    h.ack(disk(pending=1784, realloc=0))
    h.run(disk(pending=1784, realloc=3))
    assert len(h.pushed) == 1 and "realloc 0 -> 3" in h.pushed[0][1]


def test_a_new_crc_fault_class_pages_on_an_acknowledged_disk(h):
    h.ack(disk(crc=0))
    h.run(disk(crc=4))
    assert any("WORSENED" in m for _, m, _ in h.pushed)


def test_health_flipping_to_failed_pages_even_with_unchanged_counters(h):
    h.ack(disk(health=True))
    h.run(disk(health=False))
    assert h.pushed and "now FAILED" in h.pushed[0][1]


def test_an_unreadable_acknowledged_disk_is_never_suppressed(h):
    h.ack(disk())
    h.run(disk(unreadable=True))
    assert len(h.pushed) == 1 and "UNKNOWN" in h.pushed[0][0]


def test_a_weekly_reminder_is_sent_once_at_warning_level_then_stops(h):
    h.ack(disk())
    h.now += (mon.REMINDER_DAYS + 1) * DAY
    h.run(disk())
    assert len(h.pushed) == 1 and h.pushed[0][2] == "warning" and "ACKNOWLEDGED" in h.pushed[0][0]
    h.pushed.clear()
    h.now += 3600
    h.run(disk())
    assert h.pushed == [], "one reminder per week, not one per cooldown"


def test_acknowledgement_is_keyed_by_serial_so_a_device_rename_stays_acknowledged(h):
    h.ack(disk(), dev="/dev/sdb")
    h.run(disk(), dev="/dev/sdx")
    assert h.pushed == []


def test_a_different_disk_is_not_silenced_by_anothers_acknowledgement(h):
    h.ack(disk(serial=SERIAL))
    h.run(disk(serial="OTHER-SERIAL"))
    assert len(h.pushed) == 1, "an ack on one drive must never mute another (the #5094 per-tier trap)"


def test_a_corrupt_ack_file_fails_open_and_pages(h, capsys):
    Path(h.path).write_text("{not json")
    h.run(disk())
    assert len(h.pushed) == 1
    assert "ACK FILE UNREADABLE" in capsys.readouterr().err


def test_ack_refuses_a_disk_with_no_serial_or_unreadable_smart(h):
    assert mon.cmd_ack("/dev/sdb", ack_path=h.path, read=lambda d: disk(serial=""), now=h.now, kernel=dict) == 1
    assert mon.cmd_ack("/dev/sdb", ack_path=h.path, read=lambda d: disk(unreadable=True), now=h.now, kernel=dict) == 1
    assert mon.load_acks(h.path) == {}


def test_unack_restores_paging(h):
    h.ack(disk())
    assert mon.cmd_unack("/dev/sdb", ack_path=h.path, read=lambda d: disk()) == 0
    h.run(disk())
    assert len(h.pushed) == 1


def test_the_ack_file_is_valid_json_and_records_the_baseline(h):
    h.ack(disk(pending=1784), note="awaiting swap")
    data = json.loads(Path(h.path).read_text())
    assert data[SERIAL]["counters"]["pending"] == 1784 and data[SERIAL]["note"] == "awaiting swap"
    assert abs(data[SERIAL]["acked_at"] - h.now) < 1 and time.time() > 0


def test_evaluate_disk_severity_model_is_untouched():
    f = mon.evaluate_disk(True, {197: 1760, 198: 1736, 5: 0})
    assert [lvl for lvl, _ in f] == ["critical"]


# --- kernel I/O errors (ported from the host-only smart_watch.py) ---------------------------------------------------------------------------


def test_parse_kernel_errors_counts_per_disk_and_ignores_unrelated_lines():
    text = "\n".join(
        [
            "kernel: blk_update_request: I/O error, dev sdb, sector 123 op 0x0:(READ)",
            "kernel: sd 1:0:0:0: [sdb] tag#5 Sense Key : Medium Error [current]",
            "kernel: critical medium error, dev sdc, sector 9",
            "kernel: EXT4-fs (sda1): mounted filesystem",
            "kernel: Buffer I/O error on dev sdb1, logical block 5",
        ]
    )
    assert mon.parse_kernel_errors(text) == {"sdb": 3, "sdc": 1}
    assert mon.parse_kernel_errors("") == {} and mon.parse_kernel_errors(None) == {}


def test_a_rising_kernel_error_count_pages_critical_on_an_unacknowledged_disk(h):
    h.kerr = {"sde": 2}
    h.run(disk(pending=0, serial="HEALTHY-1"), dev="/dev/sde")  # SMART clean, but the kernel is erroring
    assert (
        len(h.pushed) == 1
        and h.pushed[0][2] == "critical"
        and "kernel medium/I-O errors" in h.pushed[0][1]
        and "0 -> 2" in h.pushed[0][1]
    )
    assert h.pushed[0][0].startswith("SMART KERNEL I/O:")


def test_a_steady_nonzero_kernel_count_does_not_repage_every_run(h):
    h.kerr = {"sde": 2}
    h.run(disk(pending=0, serial="HEALTHY-1"), dev="/dev/sde")
    h.pushed.clear()
    h.run(disk(pending=0, serial="HEALTHY-1"), dev="/dev/sde")  # rolling hourly count, same value: not a rise
    assert h.pushed == []
    h.kerr = {"sde": 5}
    h.run(disk(pending=0, serial="HEALTHY-1"), dev="/dev/sde")
    assert len(h.pushed) == 1 and "2 -> 5" in h.pushed[0][1]


def test_a_clean_kernel_log_pages_nothing_on_a_healthy_disk(h):
    h.run(disk(pending=0, serial="HEALTHY-1"), dev="/dev/sde")
    assert h.pushed == []


def test_an_acknowledged_disk_pages_on_kernel_errors_only_when_they_cross_the_band(h):
    h.kerr = {"sdb": 0}
    h.ack(disk())
    h.kerr = {"sdb": 3}  # 0 -> nonzero on an acknowledged disk: a new failure signal
    h.run(disk())
    kernel = [p for p in h.pushed if "kernel medium/I-O errors" in p[1]]
    assert len(kernel) == 1 and "WORSENED" in kernel[0][1]
    assert kernel[0][0].startswith(
        "SMART KERNEL I/O:"
    ), "needs its own title or send_system dedups it behind the sector alert"
    assert len({t for t, _, _ in h.pushed}) == len(h.pushed), "every push in one run must have a distinct title"
    h.pushed.clear()
    h.kerr = {"sdb": 5}  # inside the new band (3 -> 5 is +67% but only +2 units)
    h.run(disk())
    assert h.pushed == []
    h.kerr = {"sdb": 40}
    h.run(disk())
    assert len([p for p in h.pushed if p[0].startswith("SMART KERNEL I/O:")]) == 1


def test_an_acknowledged_disk_with_a_steady_kernel_baseline_stays_silent(h):
    h.kerr = {"sdb": 12}
    h.ack(disk())  # baselines kerr=12
    h.run(disk())
    assert h.pushed == []


def test_an_unreadable_journal_is_loud_and_does_not_crash_the_sweep(monkeypatch, capsys):
    monkeypatch.setattr(mon, "_run", lambda cmd, timeout=30: (1, ""))
    assert mon.kernel_errors() == {}
    assert "kernel journal unreadable" in capsys.readouterr().err


def test_the_real_journal_and_var_lib_are_never_touched_by_the_harness(h, monkeypatch):
    def boom(*a, **k):
        raise AssertionError("the harness must inject kernel/state_path")

    monkeypatch.setattr(mon, "kernel_errors", boom)
    monkeypatch.setattr(mon, "STATE_PATH", "/nonexistent/forbidden/state.json")
    h.run(disk())  # would raise if main() fell back to the real journal
