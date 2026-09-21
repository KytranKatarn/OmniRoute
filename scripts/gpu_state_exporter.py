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
import re
import subprocess
import sys
import tempfile
import time
import urllib.request

OUT = "/mnt/archie_brain/platform_v2/.runtime/gpu_state.json"
_XID_WINDOW = "10 min ago"

# ---------------------------------------------------------------------------
# Per-process attribution (added 2026-09-20)
#
# The pure resolution rules live in platform_v2/services/ollama_residency.py so
# the test suite can exercise them; only the /proc + nvidia-smi probing is here,
# because ONLY the host can do it -- archie_platform has its own PID namespace
# and cannot resolve a host PID to a command line.
#
# The /api/ps read below is a STATUS read, not inference: it asks which models
# are resident so a weights blob can be narrowed to one tag. ai-bridge.md has
# always allowed this ("Direct Ollama GET for /api/tags//api/ps is acceptable
# (not inference)"); ADR-013 governs routing INFERENCE through DHQ, and a status
# read bypasses no queue, welfare gate, agent selection or token accounting.
_PLATFORM_ROOT = "/mnt/archie_brain/platform_v2"
if _PLATFORM_ROOT not in sys.path:
    sys.path.insert(0, _PLATFORM_ROOT)

_OLLAMA_MODELS = os.getenv("OLLAMA_MODELS", "/mnt/llm_drive/ollama/models")
_OLLAMA_PS_URL = os.getenv("ARCHIE_OLLAMA_PS_URL", "http://192.168.1.200:11434/api/ps")
_MIB = 1048576


def _probe_cards():
    out = subprocess.run(
        [
            "nvidia-smi",
            # uuid is the join key to --query-compute-apps below. Index is NOT
            # usable for that and is misleading anyway: the TITAN is index 1.
            "--query-gpu=index,name,memory.total,memory.used,memory.free,utilization.gpu,uuid",
            "--format=csv,noheader,nounits",
        ],
        capture_output=True,
        text=True,
        timeout=25,
    ).stdout
    cards = []
    for line in out.strip().splitlines():
        parts = [p.strip() for p in line.split(",")]
        # Accept 6 OR 7 fields: an nvidia-smi without `uuid` support must keep
        # working, just without per-process attribution.
        if len(parts) < 6:
            continue
        cards.append(
            {
                "index": int(parts[0]),
                "name": parts[1],
                "mem_total_mb": int(parts[2]),
                "mem_used_mb": int(parts[3]),
                "mem_free_mb": int(parts[4]),
                "util_pct": int(parts[5]),
                "uuid": parts[6] if len(parts) > 6 else None,
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


def _resident_models():
    """Names of models Ollama currently reports loaded (status read, not inference).

    Used only to narrow a weights blob to ONE tag: 7 of 19 blobs on this hub back
    several tags, so without this a resident qwen2.5:7b resolves to weave:latest
    just as plausibly. Returns None (not an empty set) when unreadable, so the
    resolver reports ambiguity instead of silently narrowing to nothing.
    """
    try:
        with urllib.request.urlopen(_OLLAMA_PS_URL, timeout=8) as resp:
            payload = json.loads(resp.read())
    except Exception:
        return None
    names = {m.get("name") for m in (payload.get("models") or []) if m.get("name")}
    return names or None


def _probe_procs():
    """Per-process VRAM per card, named from Ollama's own manifests.

    One entry per (pid, card) pair, so a model SPANNING cards appears on both --
    which is the common case here (measured: mistral:7b at 5.18 GB on the Quadro
    plus 0.13 GB on the TITAN).
    """
    from services.ollama_residency import (
        blob_from_cmdline,
        manifest_index,
        resolve_model_name,
    )

    out = subprocess.run(
        [
            "nvidia-smi",
            "--query-compute-apps=pid,used_gpu_memory,gpu_uuid",
            "--format=csv,noheader,nounits",
        ],
        capture_output=True,
        text=True,
        timeout=25,
    ).stdout

    index = manifest_index(_OLLAMA_MODELS)
    resident = _resident_models()
    seen_cmdline = {}
    procs = []
    for line in out.strip().splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) != 3:
            continue
        pid, mem_mb, uuid = parts
        if pid not in seen_cmdline:
            try:
                with open(f"/proc/{pid}/cmdline", "rb") as fh:
                    seen_cmdline[pid] = fh.read().replace(b"\0", b" ").decode("utf-8", "replace")
            except OSError:
                # Runner PIDs churn: one vanished between two reads during
                # development. A gone process is reported, not dropped.
                seen_cmdline[pid] = ""
        resolved = resolve_model_name(blob_from_cmdline(seen_cmdline[pid]), index, resident)
        try:
            mem = int(mem_mb)
        except ValueError:
            continue
        procs.append(
            {
                "pid": pid,
                "uuid": uuid,
                "mem_mb": mem,
                "model": resolved["model"],
                "candidates": resolved["candidates"],
                "exact": resolved["exact"],
            }
        )
    return procs


def main():
    """One sample, or a sub-minute sampling loop.

    Cron's floor is 60s, which turned out too coarse for the pid -> model map:
    measured a 46s-old snapshot holding `procs: []` (the GPUs were idle when it
    ran) while the live cards held 4906 MiB, so NOTHING could be named. Model
    processes here live for minutes, so sampling every ~15s names almost all of
    them, while a 60s sample regularly lands in a gap.

    So one cron tick now samples several times:

        * * * * * /usr/bin/python3 .../gpu_state_exporter.py --loop-seconds 55

    Default (no flag) is a single shot, byte-identical to before, so the
    installed crontab keeps working unchanged until it is updated.
    """
    loop_seconds = 0.0
    interval = 15.0
    argv = sys.argv[1:]
    for i, a in enumerate(argv):
        if a == "--loop-seconds" and i + 1 < len(argv):
            loop_seconds = float(argv[i + 1])
        elif a.startswith("--loop-seconds="):
            loop_seconds = float(a.split("=", 1)[1])
        elif a == "--interval" and i + 1 < len(argv):
            interval = float(argv[i + 1])
        elif a.startswith("--interval="):
            interval = float(a.split("=", 1)[1])

    deadline = time.time() + loop_seconds
    while True:
        _sample_once()
        # Stop with enough margin that the next cron tick never overlaps this
        # one: overlapping writers are safe (the write is atomic) but pointless.
        if time.time() + interval >= deadline:
            return
        time.sleep(interval)


def _sample_once():
    cards = []
    procs = []
    xid_recent = 0
    errors = []
    try:
        cards = _probe_cards()
    except Exception as exc:
        errors.append(f"nvidia-smi: {exc}")
    try:
        procs = _probe_procs()
    except Exception as exc:
        # Attribution is an ENRICHMENT. Losing it must never cost the per-card
        # VRAM figures that placement depends on, so it fails on its own.
        errors.append(f"procs: {exc}")
    try:
        xid_recent = _probe_xid()
    except Exception as exc:
        errors.append(f"journalctl: {exc}")

    payload = {
        "ts": time.time(),
        "cards": cards,
        "procs": procs,
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
