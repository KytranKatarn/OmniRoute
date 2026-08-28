#!/usr/bin/env python3
"""GPU per-card telemetry exporter (#5273 / #6106, host-side half).

Writes atomic JSON to platform_v2/.runtime/gpu_state.json — bind-mounted into
archie_platform/archie_scheduler as /app/.runtime/gpu_state.json — so
model_service.get_gpu_fit_budget can place models against REAL per-card free
VRAM instead of its worst-case "every resident byte sits on the largest card"
guess (the guess sent every 7B to CPU once ~13 GB was resident anywhere:
measured 2026-08-28, budget 1.3 GB while the TITAN had 5.7 GB free).

Also counts recent NVRM Xid lines from the kernel journal — an Xid 79 ("fallen
off the bus") hid as "the hub is slow" for 8 days once (#5595) and again on
2026-08-28. The gpu_state_monitor job alarms on xid_recent > 0 and on a STALE
file (an exporter that dies must not leave the platform silently back on the
worst-case path — unmonitored while appearing monitored).

Install (host cron, user kytran — nvidia-smi and journalctl -k both work
unprivileged here; kytran is in adm):

    * * * * * /usr/bin/python3 /mnt/archie_brain/scripts/gpu_state_exporter.py

Never raises; on any probe failure it still writes a file with cards=[] so
freshness and card-count are independently observable.
"""

import json
import os
import subprocess
import tempfile
import time

OUT = "/mnt/archie_brain/platform_v2/.runtime/gpu_state.json"
_XID_WINDOW = "10 min ago"


def _probe_cards():
    out = subprocess.run(
        [
            "nvidia-smi",
            "--query-gpu=index,name,memory.total,memory.used,memory.free,utilization.gpu",
            "--format=csv,noheader,nounits",
        ],
        capture_output=True,
        text=True,
        timeout=25,
    ).stdout
    cards = []
    for line in out.strip().splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) != 6:
            continue
        cards.append(
            {
                "index": int(parts[0]),
                "name": parts[1],
                "mem_total_mb": int(parts[2]),
                "mem_used_mb": int(parts[3]),
                "mem_free_mb": int(parts[4]),
                "util_pct": int(parts[5]),
            }
        )
    return cards


def _probe_xid():
    out = subprocess.run(
        ["journalctl", "-k", "--since", _XID_WINDOW, "--no-pager", "-q"],
        capture_output=True,
        text=True,
        timeout=25,
    ).stdout
    return sum(1 for line in out.splitlines() if "NVRM: Xid" in line)


def main():
    cards = []
    xid_recent = 0
    errors = []
    try:
        cards = _probe_cards()
    except Exception as exc:
        errors.append(f"nvidia-smi: {exc}")
    try:
        xid_recent = _probe_xid()
    except Exception as exc:
        errors.append(f"journalctl: {exc}")

    payload = {
        "ts": time.time(),
        "cards": cards,
        "xid_recent": xid_recent,
        "errors": errors,
    }
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(OUT), suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as fh:
            json.dump(payload, fh)
        os.replace(tmp, OUT)  # atomic — readers never see a torn file
    finally:
        if os.path.exists(tmp):
            try:
                os.unlink(tmp)
            except OSError:
                pass


if __name__ == "__main__":
    main()
