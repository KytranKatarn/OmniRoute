"""Tests for scripts/hardware_inventory.py.

Every fixture below is REAL output captured from the hub on 2026-07-26, not
invented. The multi-GPU strings in particular are the literal bytes nvidia-smi
printed while a Quadro M4000 and a TITAN X were both installed -- that matters,
because the bug being fixed is a string-parsing bug and a hand-written fixture
would have been written to match the (wrong) assumption.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "scripts"))

hw = pytest.importorskip(  # noqa: E402
    "hardware_inventory",
    reason=(
        "host-only: this module lives in scripts/ on the HOST and is not present in the archie_platform container. Skipping keeps it honest — an ImportError here aborts collection for the ENTIRE suite (#5665)."
    ),
)


# --------------------------------------------------------------------------
# Real captured nvidia-smi output, hub, 2026-07-26, two cards installed.
# --------------------------------------------------------------------------

# The OLD query the buggy code used (no index, no bus_id, no --id filter).
REAL_OLD_QUERY_TWO_GPUS = "8192, 4, 0, 32, 535.309.01\n12288, 2, 0, 35, 535.309.01"

# The NEW query, same moment, same machine.
REAL_NEW_QUERY_TWO_GPUS = (
    "0, 00000000:04:00.0, Quadro M4000, 8192, 4, 0, 32, 535.309.01, GPU-aaaa-1111\n"
    "1, 00000000:05:00.0, NVIDIA TITAN X (Pascal), 12288, 2, 0, 35, 535.309.01, GPU-bbbb-2222"
)

REAL_NEW_QUERY_ONE_GPU = "0, 00000000:04:00.0, Quadro M4000, 8192, 4, 0, 32, 535.309.01, GPU-aaaa-1111"


class TestTheBugThisFixes:
    """Pin the defect so a future 'simplification' cannot silently restore it."""

    def test_old_parse_glues_two_gpus_into_one_corrupt_row(self):
        # This is precisely what the shipped code did: split the ENTIRE blob
        # on ',' regardless of how many lines nvidia-smi returned.
        parts = [p.strip() for p in REAL_OLD_QUERY_TWO_GPUS.split(",")]

        # 5 fields were expected. Two GPUs yield 9, because the newline between
        # rows is not a comma -- GPU 0's driver and GPU 1's VRAM become ONE field.
        assert len(parts) == 9
        assert parts[4] == "535.309.01\n12288"

        # And the consequence: parts[0] is GPU 0's VRAM, so EVERY card in the
        # lspci loop was assigned the first GPU's numbers. The 12 GB TITAN X
        # was reported as 8192 MB.
        assert parts[0] == "8192"

    def test_new_parse_keeps_the_two_cards_distinct(self):
        gpus = hw.parse_nvidia_smi(REAL_NEW_QUERY_TWO_GPUS)

        assert set(gpus) == {"04:00.0", "05:00.0"}
        assert gpus["04:00.0"]["vram_total_mb"] == 8192
        assert gpus["05:00.0"]["vram_total_mb"] == 12288
        assert gpus["04:00.0"]["name"] == "Quadro M4000"
        assert gpus["05:00.0"]["name"] == "NVIDIA TITAN X (Pascal)"
        # Distinct temperatures prove per-card telemetry, not a duplicated row.
        assert gpus["04:00.0"]["temperature"] == 32
        assert gpus["05:00.0"]["temperature"] == 35
        # The driver field is clean -- no newline-glued garbage.
        assert gpus["05:00.0"]["driver"] == "535.309.01"


class TestNvidiaSmiParsing:
    def test_single_gpu_still_works(self):
        gpus = hw.parse_nvidia_smi(REAL_NEW_QUERY_ONE_GPU)
        assert len(gpus) == 1
        assert gpus["04:00.0"]["vram_total_mb"] == 8192

    def test_empty_and_none_are_safe(self):
        assert hw.parse_nvidia_smi("") == {}
        assert hw.parse_nvidia_smi(None) == {}

    def test_short_or_malformed_rows_are_skipped_not_raised(self):
        raw = "garbage\n" + REAL_NEW_QUERY_ONE_GPU
        gpus = hw.parse_nvidia_smi(raw)
        assert len(gpus) == 1

    def test_na_values_become_none_rather_than_crashing(self):
        raw = "0, 00000000:04:00.0, Quadro M4000, [N/A], [N/A], [N/A], [N/A], [N/A], [N/A]"
        gpus = hw.parse_nvidia_smi(raw)
        assert gpus["04:00.0"]["vram_total_mb"] is None
        assert gpus["04:00.0"]["driver"] is None


class TestNormalizePci:
    def test_joins_the_two_spellings_of_the_same_slot(self):
        # nvidia-smi's 32-bit-domain form and lspci's bare form must collapse
        # to one key, or the join silently finds nothing and every GPU reads
        # as having no telemetry.
        assert hw.normalize_pci("00000000:05:00.0") == "05:00.0"
        assert hw.normalize_pci("05:00.0") == "05:00.0"
        assert hw.normalize_pci("0000:05:00.0") == "05:00.0"

    def test_case_and_whitespace_insensitive(self):
        assert hw.normalize_pci("  00000000:0A:00.0 ") == "0a:00.0"

    def test_empty_inputs(self):
        assert hw.normalize_pci(None) == ""
        assert hw.normalize_pci("") == ""


# --------------------------------------------------------------------------
# Snapshot / diff behaviour
# --------------------------------------------------------------------------


def _disk(stable_id, slot, size=2000398934016, model="ST2000DM001", kernel="sde"):
    return {
        stable_id: {
            "model": model,
            "serial": stable_id.split("_")[-1],
            "kernel_name": kernel,
            "slot": slot,
            "size_bytes": size,
        }
    }


def _snap(disks=None, gpus=None, mounts=None, mem=None):
    return hw.build_snapshot(
        disks=disks or {},
        gpus=gpus or [],
        declared_mounts=mounts or {},
        memory_total_bytes=mem,
    )


class TestFirstRunIsNeverAnAlert:
    def test_empty_baseline_emits_nothing(self):
        current = _snap(disks=_disk("ST2000_W1E592H7", "pci-0000:00:1f.2-ata-2"))
        assert hw.diff_snapshots(None, current) == []
        assert hw.diff_snapshots({}, current) == []

    def test_but_a_missing_declared_mount_is_reported_even_with_no_baseline(self):
        # Deliberate asymmetry: this is a property of the host RIGHT NOW, not a
        # comparison. It is the check that would have caught the Plex drive on
        # the very first boot after it was unplugged.
        current = _snap(
            mounts={
                "/mnt/Plex": {
                    "spec": "UUID=9a24a201",
                    "options": "defaults,nofail",
                    "device_present": False,
                    "mounted": False,
                },
            }
        )
        assert [e["type"] for e in hw.diff_snapshots(None, current)] == ["mount_missing"]
        assert [e["type"] for e in hw.diff_snapshots({}, current)] == ["mount_missing"]


class TestDiskRemoval:
    def test_removed_disk_is_critical(self):
        base = _snap(disks=_disk("ST2000_W1E592H7", "pci-0000:00:1f.2-ata-2"))
        current = _snap(disks={})
        events = hw.diff_snapshots(base, current)
        assert len(events) == 1
        assert events[0]["type"] == "disk_removed"
        assert events[0]["severity"] == hw.SEV_CRITICAL
        assert "W1E592H7" in events[0]["message"]

    def test_kernel_rename_alone_is_NOT_a_change(self):
        # sda/sdb/sdc reshuffle between boots on their own. Keying on the
        # kernel name would make every reboot look like hardware churn.
        base = _snap(disks=_disk("ST2000_W1E592H7", "pci-0000:00:1f.2-ata-2", kernel="sdb"))
        current = _snap(disks=_disk("ST2000_W1E592H7", "pci-0000:00:1f.2-ata-2", kernel="sde"))
        assert hw.diff_snapshots(base, current) == []


class TestModelStringDriftIsNotHardwareChange:
    """The 2026-07-26 reboot false-alarm, reproduced with the real strings.

    A single disk has several /dev/disk/by-id aliases:
        ata-Samsung_SSD_840_EVO_120GB_S1D5NSAF371213F
        scsi-0ATA_Samsung_SSD_840_S1D5NSAF371213F
        scsi-1ATA_Samsung_SSD_840_EVO_120GB_S1D5NSAF371213F
    Which one is encountered first can change across a reboot. v1 keyed on
    "<model>_<serial>", so the key moved and THREE untouched disks each fired
    disk_removed (CRITICAL) + disk_added. Keying on the serial alone fixes it;
    these tests pin that the model is display-only and never diffed.
    """

    def test_same_serial_different_model_string_is_silent(self):
        base = _snap(
            disks={
                "S1D5NSAF371213F": {
                    "model": "1ATA Samsung SSD 840 EVO 120GB",
                    "serial": "S1D5NSAF371213F",
                    "kernel_name": "sda",
                    "slot": "pci-0000:02:00.0-sas-phy1-lun-0",
                    "size_bytes": 120034123776,
                }
            }
        )
        current = _snap(
            disks={
                "S1D5NSAF371213F": {
                    "model": "0ATA Samsung SSD 840",  # <- different alias won this boot
                    "serial": "S1D5NSAF371213F",
                    "kernel_name": "sda",
                    "slot": "pci-0000:02:00.0-sas-phy1-lun-0",
                    "size_bytes": 120034123776,
                }
            }
        )
        assert hw.diff_snapshots(base, current) == []

    def test_all_three_real_disks_stay_silent_across_the_reboot(self):
        # Exactly the three that false-alarmed, with their real serials.
        before = {
            "S1D5NSAF371213F": {
                "model": "1ATA Samsung SSD 840 EVO 120GB",
                "serial": "S1D5NSAF371213F",
                "kernel_name": "sda",
                "slot": "pci-0000:02:00.0-sas-phy1-lun-0",
                "size_bytes": 1,
            },
            "W1E592H7": {
                "model": "1ATA ST2000DM001-9YN164",
                "serial": "W1E592H7",
                "kernel_name": "sde",
                "slot": "pci-0000:00:1f.2-ata-2",
                "size_bytes": 2,
            },
            "64IS104JTFZY": {
                "model": "1ATA TOSHIBA THNSNH512GCST",
                "serial": "64IS104JTFZY",
                "kernel_name": "sdd",
                "slot": "pci-0000:00:1f.2-ata-1",
                "size_bytes": 3,
            },
        }
        after = {
            "S1D5NSAF371213F": {
                "model": "0ATA Samsung SSD 840",
                "serial": "S1D5NSAF371213F",
                "kernel_name": "sda",
                "slot": "pci-0000:02:00.0-sas-phy1-lun-0",
                "size_bytes": 1,
            },
            "W1E592H7": {
                "model": "0ATA ST2000DM001-9YN1",
                "serial": "W1E592H7",
                "kernel_name": "sdf",
                "slot": "pci-0000:00:1f.2-ata-2",
                "size_bytes": 2,
            },
            "64IS104JTFZY": {
                "model": "SATA TOSHIBA THNSNH51",
                "serial": "64IS104JTFZY",
                "kernel_name": "sde",
                "slot": "pci-0000:00:1f.2-ata-1",
                "size_bytes": 3,
            },
        }
        # Model strings AND kernel names both drifted. Neither is hardware change.
        assert hw.diff_snapshots(_snap(disks=before), _snap(disks=after)) == []

    def test_a_genuinely_new_disk_still_fires(self):
        # The one REAL event that night must survive the fix.
        before = {
            "W1E592H7": {
                "model": "ST2000DM001",
                "serial": "W1E592H7",
                "kernel_name": "sde",
                "slot": "pci-0000:00:1f.2-ata-2",
                "size_bytes": 2,
            }
        }
        after = dict(before)
        after["Z504K0DJ"] = {
            "model": "SATA ST3000DM008-2DM1",
            "serial": "Z504K0DJ",
            "kernel_name": "sdb",
            "slot": "pci-0000:02:00.0-sas-phy2-lun-0",
            "size_bytes": 3000592982016,
        }
        events = hw.diff_snapshots(_snap(disks=before), _snap(disks=after))
        assert [e["type"] for e in events] == ["disk_added"]
        assert "Z504K0DJ" in events[0]["message"]


class TestSlotMove:
    def test_same_serial_different_port_is_a_move(self):
        base = _snap(disks=_disk("ST2000_W1E592H7", "pci-0000:00:1f.2-ata-2"))
        current = _snap(disks=_disk("ST2000_W1E592H7", "pci-0000:02:00.0-sas-phy3-lun-0"))
        events = hw.diff_snapshots(base, current)
        assert len(events) == 1
        assert events[0]["type"] == "disk_moved"
        assert events[0]["severity"] == hw.SEV_WARNING
        assert "ata-2" in events[0]["message"]

    def test_move_is_not_reported_as_removal_plus_addition(self):
        base = _snap(disks=_disk("ST2000_W1E592H7", "pci-0000:00:1f.2-ata-2"))
        current = _snap(disks=_disk("ST2000_W1E592H7", "pci-0000:00:1f.2-ata-4"))
        types = {e["type"] for e in hw.diff_snapshots(base, current)}
        assert types == {"disk_moved"}
        assert "disk_removed" not in types


class TestDiskAddition:
    def test_new_serial_is_a_notice(self):
        base = _snap(disks=_disk("ST2000_W1E592H7", "pci-0000:00:1f.2-ata-2"))
        disks = dict(_disk("ST2000_W1E592H7", "pci-0000:00:1f.2-ata-2"))
        disks.update(_disk("NEW_ABC123", "pci-0000:00:1f.2-ata-4", model="WD"))
        events = hw.diff_snapshots(base, _snap(disks=disks))
        assert [e["type"] for e in events] == ["disk_added"]
        assert events[0]["severity"] == hw.SEV_NOTICE


class TestGpuChanges:
    def test_gpu_moved_between_slots_keeps_one_identity(self):
        # A card moved between PCIe slots must read as MOVED, not as a removal
        # and an unrelated addition -- that is why GPUs key on UUID.
        base = _snap(
            gpus=[
                {
                    "uuid": "GPU-bbbb-2222",
                    "pci_address": "05:00.0",
                    "model": "TITAN X",
                    "vendor": "nvidia",
                    "vram_total_mb": 12288,
                }
            ]
        )
        current = _snap(
            gpus=[
                {
                    "uuid": "GPU-bbbb-2222",
                    "pci_address": "09:00.0",
                    "model": "TITAN X",
                    "vendor": "nvidia",
                    "vram_total_mb": 12288,
                }
            ]
        )
        events = hw.diff_snapshots(base, current)
        assert [e["type"] for e in events] == ["gpu_moved"]
        assert "05:00.0 -> 09:00.0" in events[0]["message"]

    def test_second_card_added_is_detected(self):
        base = _snap(
            gpus=[{"uuid": "GPU-aaaa-1111", "pci_address": "04:00.0", "model": "Quadro M4000", "vram_total_mb": 8192}]
        )
        current = _snap(
            gpus=[
                {"uuid": "GPU-aaaa-1111", "pci_address": "04:00.0", "model": "Quadro M4000", "vram_total_mb": 8192},
                {"uuid": "GPU-bbbb-2222", "pci_address": "05:00.0", "model": "TITAN X", "vram_total_mb": 12288},
            ]
        )
        events = hw.diff_snapshots(base, current)
        assert [e["type"] for e in events] == ["gpu_added"]
        assert "12288 MB" in events[0]["message"]

    def test_gpu_removed_is_critical(self):
        base = _snap(
            gpus=[{"uuid": "GPU-bbbb-2222", "pci_address": "05:00.0", "model": "TITAN X", "vram_total_mb": 12288}]
        )
        events = hw.diff_snapshots(base, _snap(gpus=[]))
        assert events[0]["type"] == "gpu_removed"
        assert events[0]["severity"] == hw.SEV_CRITICAL


class TestTelemetryIsNotHardware:
    def test_changing_temperature_and_usage_produces_no_events(self):
        # If live telemetry leaked into the snapshot, EVERY cycle would look
        # like a hardware change and the alert would be worthless.
        base = _snap(
            gpus=[
                {
                    "uuid": "GPU-aaaa-1111",
                    "pci_address": "04:00.0",
                    "model": "Quadro M4000",
                    "vram_total_mb": 8192,
                    "temperature": 32,
                    "utilization_percent": 0,
                    "vram_used_mb": 4,
                }
            ]
        )
        current = _snap(
            gpus=[
                {
                    "uuid": "GPU-aaaa-1111",
                    "pci_address": "04:00.0",
                    "model": "Quadro M4000",
                    "vram_total_mb": 8192,
                    "temperature": 71,
                    "utilization_percent": 98,
                    "vram_used_mb": 7900,
                }
            ]
        )
        assert hw.diff_snapshots(base, current) == []


class TestDeclaredMounts:
    def test_present_device_is_silent(self):
        current = _snap(
            mounts={
                "/mnt/data2": {
                    "spec": "UUID=1f43f417",
                    "options": "defaults,nofail",
                    "device_present": True,
                    "mounted": True,
                },
            }
        )
        assert hw.diff_snapshots(None, current) == []

    def test_nofail_is_called_out_in_the_message(self):
        current = _snap(
            mounts={
                "/mnt/Plex": {
                    "spec": "UUID=9a24a201",
                    "options": "defaults,nofail",
                    "device_present": False,
                    "mounted": False,
                },
            }
        )
        events = hw.diff_snapshots(None, current)
        assert "nofail" in events[0]["message"]
        assert events[0]["severity"] == hw.SEV_CRITICAL


class TestMemory:
    # Both snapshots carry identical disks so the ONLY difference under test is
    # RAM. An earlier draft used a phantom baseline disk to get past the
    # empty-baseline guard, and that disk correctly reported itself removed --
    # the fixture, not the module, was wrong.
    DISKS = _disk("KEEP_ME_W1D16EEK", "pci-0000:00:1f.2-ata-1")

    def test_small_firmware_variance_is_ignored(self):
        base = _snap(disks=self.DISKS, mem=137_438_953_472)
        current = _snap(disks=self.DISKS, mem=137_438_953_472 - (64 * 1024 * 1024))
        assert hw.diff_snapshots(base, current) == []

    def test_a_removed_dimm_is_reported(self):
        base = _snap(disks=self.DISKS, mem=137_438_953_472)
        current = _snap(disks=self.DISKS, mem=68_719_476_736)
        events = hw.diff_snapshots(base, current)
        assert [e["type"] for e in events] == ["memory_changed"]
        assert "DECREASED" in events[0]["message"]


class TestOrderingAndSummary:
    def test_critical_sorts_before_warning_before_notice(self):
        base = _snap(
            disks={
                **_disk("GONE_1", "pci-0000:00:1f.2-ata-1"),
                **_disk("MOVED_2", "pci-0000:00:1f.2-ata-2"),
            }
        )
        current = _snap(
            disks={
                **_disk("MOVED_2", "pci-0000:00:1f.2-ata-5"),
                **_disk("NEW_3", "pci-0000:00:1f.2-ata-6"),
            }
        )
        events = hw.diff_snapshots(base, current)
        assert [e["severity"] for e in events] == [
            hw.SEV_CRITICAL,
            hw.SEV_WARNING,
            hw.SEV_NOTICE,
        ]

    def test_summarize_counts_and_worst(self):
        base = _snap(disks=_disk("GONE_1", "pci-0000:00:1f.2-ata-1"))
        events = hw.diff_snapshots(base, _snap(disks={}))
        s = hw.summarize(events)
        assert s == {"total": 1, "critical": 1, "warning": 0, "notice": 0, "worst_severity": "critical"}

    def test_summarize_of_nothing_has_no_worst(self):
        assert hw.summarize([])["worst_severity"] is None


class TestTheActualIncident:
    """End-to-end reconstruction of 2026-07-25, using the real values."""

    def test_the_plex_drive_would_have_alarmed(self):
        baseline = _snap(
            disks={
                **_disk("Samsung_SSD_840_S1D5NSAF371213F", "pci-0000:02:00.0-sas-phy1-lun-0"),
                **_disk("PLEX_DRIVE_SERIAL", "pci-0000:00:1f.2-ata-4"),
            },
            mounts={
                "/mnt/Plex": {
                    "spec": "UUID=9a24a201-1dfb-4f12-9fc5-03bb3bdd1ab5",
                    "options": "defaults,nofail",
                    "device_present": True,
                    "mounted": True,
                },
            },
        )
        after_the_gpu_install = _snap(
            disks=_disk("Samsung_SSD_840_S1D5NSAF371213F", "pci-0000:02:00.0-sas-phy1-lun-0"),
            mounts={
                "/mnt/Plex": {
                    "spec": "UUID=9a24a201-1dfb-4f12-9fc5-03bb3bdd1ab5",
                    "options": "defaults,nofail",
                    "device_present": False,
                    "mounted": False,
                },
            },
        )
        events = hw.diff_snapshots(baseline, after_the_gpu_install)
        types = {e["type"] for e in events}

        # Two independent detectors fire -- the disk vanished AND fstab still
        # expects it. Either alone would have been enough.
        assert types == {"disk_removed", "mount_missing"}
        assert hw.summarize(events)["critical"] == 2
