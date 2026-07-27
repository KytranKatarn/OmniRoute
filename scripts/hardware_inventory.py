"""Hardware inventory + change detection for the A.R.C.H.I.E. hub.

WHY THIS EXISTS
---------------
On 2026-07-25 a drive was disconnected during a GPU/PSU install. fstab carried
`nofail`, so the host booted cleanly, `mnt-Plex.mount` went `inactive (dead)`,
and ten media containers ran for 20 hours against an empty directory on the
root filesystem. Nothing anywhere said a word. The kernel log was clean --
there was no failure to detect, because the drive did not fail, it *left*.

Capacity monitoring cannot catch that: a device that is gone has no capacity.
The only way to notice is to remember what was here before and compare.

DESIGN
------
Every function here is pure. Collectors are injected by the caller. That is
deliberate -- the whole point is to be provable without physically unplugging a
drive or owning a second GPU.

IDENTITY, and why each key was chosen
-------------------------------------
* Disks are keyed by ``stable_id`` (model_serial from /dev/disk/by-id), NOT by
  kernel name. sda/sdb/sdc reshuffle on their own between boots; a serial does
  not. Keying on `sdX` would report a rename as a removal plus an addition.
* Disk *slot* is ``/dev/disk/by-path`` (e.g. ``pci-0000:00:1f.2-ata-2``). That
  is the physical port. Same serial + different by-path == the drive was moved
  to another port, which is exactly the "moved from one slot to another" case.
* GPUs are keyed by ``uuid`` (nvidia-smi gpu_uuid) when available, falling back
  to PCI address. A UUID survives a slot change, so moving a card between PCIe
  slots reports as MOVED rather than as a removal plus an unrelated addition.
* Declared mounts come from fstab. A device that vanishes entirely leaves no
  block device to inspect -- the only surviving evidence is that fstab still
  expects it. This is the check that would have caught the Plex drive at
  18:40:47 on the first boot, instead of never.

FIRST RUN IS NEVER AN ALERT -- WITH ONE DELIBERATE EXCEPTION
------------------------------------------------------------
With no baseline, every device looks new. Emitting on first run would page on
every fresh deploy and train everyone to ignore this, so all COMPARISON checks
(disk/GPU added, removed, moved; RAM change) stay silent until a baseline
exists -- the same "unknown is not an alert" rule the backup freshness monitor
uses.

The fstab check is the exception, and runs unconditionally. It is not a
comparison: it asks whether a filesystem the host is configured to mount has a
device attached RIGHT NOW. That needs no history, and a fresh install whose
drive is unplugged is still broken. Gating it behind a baseline is exactly what
would have kept the lost drive silent.
"""

from __future__ import annotations

# v2 (2026-07-26): disks are keyed by SERIAL alone. v1 keyed on
# "<model>_<serial>", where the model half came from whichever /dev/disk/by-id
# alias sorted first — that changed across a reboot and made three untouched
# disks each report as disk_removed + disk_added with identical serials.
# A version bump is REQUIRED whenever the identity key changes: every v1 key is
# unrecognisable to v2, so diffing across the boundary would emit exactly the
# false storm this fixes. Callers must re-baseline instead (see
# host_monitor.check_hardware_changes).
SNAPSHOT_VERSION = 2

# Severity vocabulary matches host_monitor's existing alert levels so these
# events flow through create_alert() and the health webhooks unchanged.
SEV_CRITICAL = "critical"
SEV_WARNING = "warning"
SEV_NOTICE = "notice"


def normalize_pci(addr: str | None) -> str:
    """Reduce any PCI address spelling to lspci's ``bus:dev.func``.

    nvidia-smi reports ``00000000:05:00.0`` (with a 32-bit domain); lspci
    reports ``05:00.0``. Joining the two sources requires one spelling.
    Anything already domain-less is returned unchanged.
    """
    a = (addr or "").strip().lower()
    if not a:
        return ""
    # domain:bus:dev.func -> bus:dev.func  (a bare bus:dev.func has one colon)
    if a.count(":") >= 2:
        a = a.split(":", 1)[1]
    return a


def parse_nvidia_smi(raw: str | None) -> dict[str, dict]:
    """Parse a multi-GPU ``nvidia-smi --query-gpu`` block, keyed by PCI address.

    THE BUG THIS REPLACES: nvidia-smi with no ``--id`` prints ONE LINE PER GPU.
    The previous code ran ``smi_output.split(",")`` across the entire blob, so
    with two cards it produced 9 fields instead of 5 and glued GPU 0's last
    value to GPU 1's first::

        parts[4] == '535.309.01\\n12288'

    Every card then read parts[0..3] -- GPU 0's numbers. Both GPUs reported
    identical stats and the 12 GB TITAN X was displayed as 8 GB.

    Expected column order::

        index, pci.bus_id, name, memory.total, memory.used,
        utilization.gpu, temperature.gpu, driver_version, gpu_uuid

    Rows that are short or unparseable are skipped rather than raising -- a
    driver hiccup must not take down the whole monitor cycle.
    """
    out: dict[str, dict] = {}
    if not raw:
        return out

    for line in raw.strip().split("\n"):
        line = line.strip()
        if not line:
            continue
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 8:
            continue

        pci = normalize_pci(parts[1])
        if not pci:
            continue

        out[pci] = {
            "index": _as_int(parts[0]),
            "pci_address": pci,
            "name": parts[2] or None,
            "vram_total_mb": _as_int(parts[3]),
            "vram_used_mb": _as_int(parts[4]),
            "utilization_percent": _as_int(parts[5]),
            "temperature": _as_int(parts[6]),
            "driver": parts[7] if parts[7] not in ("", "[N/A]") else None,
            "uuid": parts[8] if len(parts) > 8 and parts[8] != "[N/A]" else None,
        }
    return out


def _as_int(value: str | None):
    """int() that yields None instead of raising. nvidia-smi emits '[N/A]'."""
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def _gpu_key(gpu: dict) -> str:
    """Stable identity for a GPU: UUID if we have one, else its PCI slot.

    Using the UUID is what lets a card moved between slots read as MOVED
    instead of as a removal and an unrelated addition.
    """
    uuid = (gpu.get("uuid") or "").strip()
    if uuid:
        return f"uuid:{uuid}"
    return f"pci:{normalize_pci(gpu.get('pci_address'))}"


def build_snapshot(
    *,
    disks: dict | None = None,
    gpus: list | None = None,
    declared_mounts: dict | None = None,
    memory_total_bytes: int | None = None,
    captured_at: str | None = None,
) -> dict:
    """Assemble a canonical, comparable hardware snapshot.

    Only fields that describe *what hardware is present* belong here. Live
    telemetry (temperature, utilization, VRAM in use) is deliberately excluded
    -- including it would make every single cycle look like a hardware change.
    """
    snap: dict = {
        "version": SNAPSHOT_VERSION,
        "captured_at": captured_at,
        "disks": {},
        "gpus": {},
        "declared_mounts": {},
        "memory": {"total_bytes": memory_total_bytes},
    }

    for stable_id, info in (disks or {}).items():
        if not stable_id:
            continue
        snap["disks"][stable_id] = {
            "stable_id": stable_id,
            "model": info.get("model"),
            "serial": info.get("serial"),
            "kernel_name": info.get("kernel_name"),
            "slot": info.get("slot"),
            "size_bytes": info.get("size_bytes"),
        }

    for gpu in gpus or []:
        key = _gpu_key(gpu)
        snap["gpus"][key] = {
            "key": key,
            "vendor": gpu.get("vendor"),
            "model": gpu.get("model") or gpu.get("name"),
            "pci_address": normalize_pci(gpu.get("pci_address")),
            "vram_total_mb": gpu.get("vram_total_mb"),
            "uuid": gpu.get("uuid"),
        }

    for target, info in (declared_mounts or {}).items():
        snap["declared_mounts"][target] = {
            "target": target,
            "spec": info.get("spec"),
            "options": info.get("options"),
            "device_present": bool(info.get("device_present")),
            "mounted": bool(info.get("mounted")),
        }

    return snap


def diff_snapshots(baseline: dict | None, current: dict) -> list[dict]:
    """Compare two snapshots and return hardware-change events, worst first.

    Returns [] when there is no usable baseline. A fresh install has nothing to
    compare against, and paging on that would make this monitor noise.
    """
    # The declared-mount check is STATELESS and therefore runs unconditionally.
    # It compares fstab against the devices attached right now, so it needs no
    # history -- and a fresh install whose drive is unplugged is still broken.
    # Gating it behind a baseline is what would have kept the Plex drive silent.
    events: list[dict] = list(_diff_declared_mounts(current))

    # Everything below is a genuine comparison and needs prior state.
    has_baseline = bool(baseline) and bool(baseline.get("disks") or baseline.get("gpus"))
    if has_baseline:
        events.extend(_diff_disks(baseline, current))
        events.extend(_diff_gpus(baseline, current))
        events.extend(_diff_memory(baseline, current))

    order = {SEV_CRITICAL: 0, SEV_WARNING: 1, SEV_NOTICE: 2}
    events.sort(key=lambda e: (order.get(e["severity"], 3), e["type"]))
    return events


def _diff_disks(baseline: dict, current: dict) -> list[dict]:
    old = baseline.get("disks") or {}
    new = current.get("disks") or {}
    events = []

    for stable_id, was in old.items():
        now = new.get(stable_id)
        if now is None:
            events.append(
                {
                    "type": "disk_removed",
                    "severity": SEV_CRITICAL,
                    "key": stable_id,
                    "message": (
                        f"Disk no longer present: {was.get('model') or stable_id} "
                        f"(serial {was.get('serial') or 'unknown'}), "
                        f"last seen at slot {was.get('slot') or 'unknown'}"
                    ),
                    "details": {"before": was, "after": None},
                }
            )
            continue

        if was.get("slot") and now.get("slot") and was["slot"] != now["slot"]:
            events.append(
                {
                    "type": "disk_moved",
                    "severity": SEV_WARNING,
                    "key": stable_id,
                    "message": (f"Disk moved slot: {now.get('model') or stable_id} " f"{was['slot']} -> {now['slot']}"),
                    "details": {"before": was, "after": now},
                }
            )

        b_size, n_size = was.get("size_bytes"), now.get("size_bytes")
        if b_size and n_size and b_size != n_size:
            events.append(
                {
                    "type": "disk_resized",
                    "severity": SEV_WARNING,
                    "key": stable_id,
                    "message": (
                        f"Disk capacity changed: {now.get('model') or stable_id} " f"{b_size} -> {n_size} bytes"
                    ),
                    "details": {"before": was, "after": now},
                }
            )

    for stable_id, now in new.items():
        if stable_id not in old:
            events.append(
                {
                    "type": "disk_added",
                    "severity": SEV_NOTICE,
                    "key": stable_id,
                    "message": (
                        f"New disk detected: {now.get('model') or stable_id} "
                        f"(serial {now.get('serial') or 'unknown'}) "
                        f"at slot {now.get('slot') or 'unknown'}"
                    ),
                    "details": {"before": None, "after": now},
                }
            )
    return events


def _diff_gpus(baseline: dict, current: dict) -> list[dict]:
    old = baseline.get("gpus") or {}
    new = current.get("gpus") or {}
    events = []

    for key, was in old.items():
        now = new.get(key)
        if now is None:
            events.append(
                {
                    "type": "gpu_removed",
                    "severity": SEV_CRITICAL,
                    "key": key,
                    "message": (
                        f"GPU no longer present: {was.get('model') or key} "
                        f"(was at PCI {was.get('pci_address') or 'unknown'})"
                    ),
                    "details": {"before": was, "after": None},
                }
            )
            continue

        if was.get("pci_address") and now.get("pci_address") and (was["pci_address"] != now["pci_address"]):
            events.append(
                {
                    "type": "gpu_moved",
                    "severity": SEV_WARNING,
                    "key": key,
                    "message": (
                        f"GPU moved slot: {now.get('model') or key} "
                        f"PCI {was['pci_address']} -> {now['pci_address']}"
                    ),
                    "details": {"before": was, "after": now},
                }
            )

    for key, now in new.items():
        if key not in old:
            events.append(
                {
                    "type": "gpu_added",
                    "severity": SEV_NOTICE,
                    "key": key,
                    "message": (
                        f"New GPU detected: {now.get('model') or key} "
                        f"at PCI {now.get('pci_address') or 'unknown'} "
                        f"({now.get('vram_total_mb') or '?'} MB VRAM)"
                    ),
                    "details": {"before": None, "after": now},
                }
            )
    return events


def _diff_declared_mounts(current: dict) -> list[dict]:
    """Flag fstab entries whose backing device is absent.

    This is stateless on purpose -- it is a property of the CURRENT host, not a
    comparison. fstab says this filesystem should exist; the device is gone.
    That is true on the very first run, which is what makes it the check that
    would have caught the Plex drive immediately rather than never.
    """
    events = []
    for target, info in (current.get("declared_mounts") or {}).items():
        if info.get("device_present"):
            continue
        events.append(
            {
                "type": "mount_missing",
                "severity": SEV_CRITICAL,
                "key": target,
                "message": (
                    f"fstab declares {target} ({info.get('spec')}) but no such "
                    f"device is attached -- filesystem is NOT mounted"
                    + (
                        "; 'nofail' means the host booted without warning"
                        if "nofail" in (info.get("options") or "")
                        else ""
                    )
                ),
                "details": {"mount": info},
            }
        )
    return events


def _diff_memory(baseline: dict, current: dict) -> list[dict]:
    was = (baseline.get("memory") or {}).get("total_bytes")
    now = (current.get("memory") or {}).get("total_bytes")
    if not was or not now or was == now:
        return []
    # Firmware reserves a few MB inconsistently across boots; only report a
    # change large enough to mean a physical DIMM was added or removed.
    if abs(now - was) < 256 * 1024 * 1024:
        return []
    direction = "increased" if now > was else "DECREASED"
    return [
        {
            "type": "memory_changed",
            "severity": SEV_WARNING,
            "key": "memory",
            "message": (f"Installed RAM {direction}: " f"{round(was / 1024**3, 1)} GB -> {round(now / 1024**3, 1)} GB"),
            "details": {"before_bytes": was, "after_bytes": now},
        }
    ]


def summarize(events: list[dict]) -> dict:
    """Roll events into the shape the KSO dashboard renders."""
    counts = {SEV_CRITICAL: 0, SEV_WARNING: 0, SEV_NOTICE: 0}
    for e in events:
        if e["severity"] in counts:
            counts[e["severity"]] += 1
    return {
        "total": len(events),
        "critical": counts[SEV_CRITICAL],
        "warning": counts[SEV_WARNING],
        "notice": counts[SEV_NOTICE],
        "worst_severity": (
            SEV_CRITICAL
            if counts[SEV_CRITICAL]
            else SEV_WARNING if counts[SEV_WARNING] else SEV_NOTICE if counts[SEV_NOTICE] else None
        ),
    }
