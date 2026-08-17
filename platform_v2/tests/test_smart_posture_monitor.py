"""#5438 — SMART posture severity model: failure MODE over raw counts.

Loads evaluate_disk from the SHIPPED host script (scripts/smart_posture_monitor.py)
so the tests cannot drift from a copy. The decision table encodes the task's core
insight: pending>0 with reallocated==0 is MORE severe than a higher reallocated
count, because the drive is not remapping — sdb (1,760 pending / 0 realloc) is
failing while sdc (152 realloc) is doing its job.
"""

import importlib.util
from pathlib import Path

# Repo-relative like test_dr_silent_success.py — resolves in-container
# (/mnt/archie_brain is mounted) and on the host alike.
_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "smart_posture_monitor.py"
if not _SCRIPT.exists():
    _SCRIPT = Path("/mnt/archie_brain/scripts/smart_posture_monitor.py")

_spec = importlib.util.spec_from_file_location("smart_posture_monitor", str(_SCRIPT))
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)

evaluate_disk = _mod.evaluate_disk
A = {"realloc": 5, "pending": 197, "offline": 198, "crc": 199}


def _levels(findings):
    return [level for level, _ in findings]


def test_sdb_signature_pending_no_realloc_is_critical():
    findings = evaluate_disk(True, {197: 1760, 198: 1736, 5: 0})
    assert "critical" in _levels(findings)
    assert any("NOT remapping" in r for _, r in findings)


def test_sdc_signature_realloc_only_is_warning_not_critical():
    findings = evaluate_disk(True, {5: 152, 197: 0, 198: 0})
    assert _levels(findings) == ["warning"]
    assert any("remapping successfully" in r for _, r in findings)


def test_both_pending_and_realloc_is_critical():
    findings = evaluate_disk(True, {5: 152, 197: 16, 198: 0})
    assert "critical" in _levels(findings)


def test_crc_is_separate_cable_warning():
    findings = evaluate_disk(True, {199: 112})
    assert _levels(findings) == ["warning"]
    assert any("CABLE" in r for _, r in findings)


def test_crc_reported_alongside_sector_findings():
    findings = evaluate_disk(True, {197: 1760, 199: 112})
    assert _levels(findings) == ["critical", "warning"]


def test_overall_health_failed_is_critical_even_with_clean_attrs():
    findings = evaluate_disk(False, {5: 0, 197: 0, 198: 0})
    assert "critical" in _levels(findings)


def test_unreadable_disk_is_unknown_never_healthy():
    findings = evaluate_disk(None, {})
    assert _levels(findings) == ["unknown"]


def test_clean_disk_yields_no_findings():
    assert evaluate_disk(True, {5: 0, 197: 0, 198: 0, 199: 0}) == []
