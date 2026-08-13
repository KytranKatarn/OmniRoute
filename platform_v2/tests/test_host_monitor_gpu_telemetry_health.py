"""GPU telemetry-health reporting for scripts/host_monitor.py::get_gpu_info.

REAL INCIDENT THIS PINS (task #5595, 2026-08-04 → 2026-08-12):
Both hub GPUs hit NVRM Xid 79 ("GPU has fallen off the bus"). `lspci` still
listed both cards -- it reads cached enumeration data -- so get_gpu_info kept
returning two device dicts, but with every telemetry field None because
nvidia-smi could not get a device handle.

The KSO collector records a metric ONLY when utilization is non-None:

    if util_pct is not None:
        record_metric(f"gpu_{idx}", util_pct)

So "present but unreadable" wrote NO ROWS AT ALL. In the metrics history that is
byte-identical to "no GPU installed" and to "collector not running". Both cards
sat dead for 8 days while every dashboard reported the platform healthy.

These tests are about the SECOND failure, not the first. A card falling off the
bus is hardware. A monitor that cannot tell "blind" apart from "absent" is ours:
in that state it is indistinguishable from a monitor with nothing to report.

The contract:
    telemetry_ok is True  -> an nvidia-smi row was joined; values are trustworthy
    telemetry_ok is False -> nvidia GPU present in lspci, nvidia-smi has no row
    telemetry_ok is None  -> not applicable (non-nvidia vendor; never alarm)
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "scripts"))

import host_monitor as hm  # noqa: E402

_LSPCI_TWO_NVIDIA = (
    "04:00.0 VGA compatible controller: NVIDIA Corporation GM204GL [Quadro M4000] (rev a1)\n"
    "05:00.0 VGA compatible controller: NVIDIA Corporation GP102 [TITAN X] (rev a1)"
)

# nvidia-smi --query-gpu=index,pci.bus_id,name,memory.total,memory.used,
#                        utilization.gpu,temperature.gpu,driver_version,gpu_uuid
_SMI_BOTH = (
    "0, 00000000:04:00.0, Quadro M4000, 8192, 512, 3, 44, 535.309.01, GPU-e20b1ba4\n"
    "1, 00000000:05:00.0, NVIDIA TITAN X (Pascal), 12288, 4096, 82, 61, 535.309.01, GPU-93e51659"
)

_SMI_ONLY_QUADRO = "0, 00000000:04:00.0, Quadro M4000, 8192, 512, 3, 44, 535.309.01, GPU-e20b1ba4"


def _patch_commands(monkeypatch, lspci_out, smi_out):
    """Route get_gpu_info's two run_command calls by inspecting the command."""

    def fake_run_command(cmd, *a, **kw):
        if "lspci" in cmd:
            return lspci_out
        if "nvidia-smi" in cmd:
            return smi_out
        return ""

    monkeypatch.setattr(hm, "run_command", fake_run_command)
    # Deterministic: never let a real hwmon read leak into the assertions.
    monkeypatch.setattr(hm, "_read_hwmon_gpu_temp", lambda *a, **kw: None)


def test_healthy_gpus_report_telemetry_ok_true(monkeypatch):
    """Both cards readable -> both flagged trustworthy, real values joined."""
    _patch_commands(monkeypatch, _LSPCI_TWO_NVIDIA, _SMI_BOTH)

    gpus = hm.get_gpu_info()

    assert len(gpus) == 2
    assert [g["telemetry_ok"] for g in gpus] == [True, True]
    # Sanity: the join is BY PCI ADDRESS, so the 12GB card must not inherit 8192.
    by_pci = {g["pci_address"]: g for g in gpus}
    assert by_pci["05:00.0"]["vram_total_mb"] == 12288
    assert by_pci["04:00.0"]["vram_total_mb"] == 8192


def test_present_but_unreadable_reports_false_not_silence(monkeypatch):
    """THE #5595 CASE: lspci sees the cards, nvidia-smi returns nothing.

    Before the fix this produced two dicts of all-None with no way to tell them
    apart from a machine that simply has no GPU.
    """
    _patch_commands(monkeypatch, _LSPCI_TWO_NVIDIA, "")

    gpus = hm.get_gpu_info()

    assert len(gpus) == 2, "dead cards must still be ENUMERATED, not dropped"
    assert [g["telemetry_ok"] for g in gpus] == [False, False]
    # The telemetry really is absent -- the flag is what makes that legible.
    assert all(g["utilization_percent"] is None for g in gpus)


def test_partial_failure_flags_only_the_dead_card(monkeypatch):
    """One card readable, one not.

    nvidia-smi exits non-zero when ANY device errors, so the naive
    `if returncode == 0` guard blinds you to the HEALTHY card too. Per-device
    flagging is what keeps the survivor observable -- and on 2026-08-04 the two
    hub cards died 12 minutes apart, so this state was real for 12 minutes.
    """
    _patch_commands(monkeypatch, _LSPCI_TWO_NVIDIA, _SMI_ONLY_QUADRO)

    by_pci = {g["pci_address"]: g for g in hm.get_gpu_info()}

    assert by_pci["04:00.0"]["telemetry_ok"] is True
    assert by_pci["04:00.0"]["utilization_percent"] == 3
    assert by_pci["05:00.0"]["telemetry_ok"] is False
    assert by_pci["05:00.0"]["utilization_percent"] is None


def test_non_nvidia_gpu_is_not_flagged_unreadable(monkeypatch):
    """A non-nvidia card was never going to have an nvidia-smi row.

    Flagging it False would manufacture a permanent false alarm on any box with
    integrated graphics -- the failure mode that gets alerting switched off.
    """
    _patch_commands(
        monkeypatch,
        "07:00.0 VGA compatible controller: Advanced Micro Devices, Inc. [AMD/ATI] Cezanne",
        "",
    )

    gpus = hm.get_gpu_info()

    assert len(gpus) == 1
    assert gpus[0]["vendor"] != "nvidia"
    assert gpus[0]["telemetry_ok"] is None, "None = not applicable, NOT False"


def test_no_gpu_at_all_is_still_distinguishable(monkeypatch):
    """No lspci display device -> None. Absent must stay absent."""
    _patch_commands(monkeypatch, "", "")

    assert hm.get_gpu_info() is None


@pytest.mark.parametrize("smi_out", ["", "   ", "\n"])
def test_blank_smi_variants_all_flag_false(monkeypatch, smi_out):
    """Whitespace-only nvidia-smi output must not be mistaken for a reading."""
    _patch_commands(monkeypatch, _LSPCI_TWO_NVIDIA, smi_out)

    assert all(g["telemetry_ok"] is False for g in hm.get_gpu_info())
