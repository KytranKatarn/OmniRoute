"""Attribute GPU-resident models to the specific card carrying them.

WHY THIS IS NOT A ONE-LINER
---------------------------
Ollama's ``/api/ps`` does not say which card a model sits on. Measured against
the host Ollama (0.24.0) on 2026-09-20, a model entry carries exactly::

    name, model, size, size_vram, digest, expires_at, context_length, details

and nothing device-shaped. ``nvidia-smi`` *does* know, but per PROCESS::

    nvidia-smi --query-compute-apps=pid,used_gpu_memory,gpu_uuid

So the two halves of the answer live in different places, and the seam between
them is a PID that ``archie_platform`` cannot resolve: the container has its own
PID namespace (``/proc/1/cmdline`` is gunicorn), so ``/proc/<host-pid>/cmdline``
simply does not exist inside it -- verified, not assumed. Sharing the host PID
namespace would buy a UI label at the cost of the container's isolation, which
is a bad trade for a label.

What is left is matching a process's VRAM allocation against a model's
``size_vram``. That works, and on a single-model read it matches to the byte.
But it is only TRUSTWORTHY WHEN UNAMBIGUOUS: two 7B models at the same
quantisation allocate near-identical VRAM, and arbitrarily picking one would
print a confident falsehood about which card is carrying which model -- the
exact class of defect this panel has been getting fixed for all week (a status
that misdescribes a healthy system).

Hence the contract below: attribute only when the assignment is FORCED, and
report the rest as unresolved. An unresolved model is still shown by the caller,
under its node's GPU heading without a card, because hiding a resident model is
worse than admitting we cannot pin its slot.

A first attempt to validate byte-matching live was VACUOUS -- only one
GPU-resident model existed across six samples, so any matcher "passed". The
disambiguation behaviour is therefore pinned by unit tests with synthetic
multi-model inputs; see tests/test_gpu_residency.py.
"""

from __future__ import annotations

import logging
import subprocess
from typing import Any, Dict, Iterable, List, Optional

logger = logging.getLogger(__name__)

_MIB = 1048576

# A process's allocation exceeds the model's own weights: CUDA context, KV
# cache and scratch buffers all land on the card too. 3% plus a 256 MiB floor
# covers the observed spread without being loose enough to let two distinct
# models collide -- and when it IS loose enough, the uniqueness rule below
# refuses the match rather than guessing.
_TOL_PCT = 3.0
_TOL_FLOOR_BYTES = 256 * _MIB


def gpu_process_snapshot(timeout: float = 4.0) -> Optional[List[Dict[str, Any]]]:
    """Per-process, per-card VRAM as nvidia-smi reports it.

    Returns one entry per (pid, card) pair, or None when nvidia-smi is
    unavailable. None means UNKNOWN -- never an empty list, which would read as
    "nothing is resident" and is a different claim entirely (ADR-017).
    """
    try:
        r = subprocess.run(
            [
                "nvidia-smi",
                "--query-compute-apps=pid,used_gpu_memory,gpu_uuid",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        logger.debug("gpu_residency: nvidia-smi compute-apps unavailable: %s", exc)
        return None
    if r.returncode != 0:
        logger.debug("gpu_residency: nvidia-smi rc=%s %s", r.returncode, r.stderr[:200])
        return None

    out: List[Dict[str, Any]] = []
    # One row per line. Splitting the whole payload on ',' merges rows -- the
    # bug this panel already shipped once for the per-GPU query.
    for line in r.stdout.strip().splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) != 3:
            continue
        try:
            out.append({"pid": parts[0], "bytes": int(parts[1]) * _MIB, "uuid": parts[2]})
        except ValueError:
            continue
    return out


def _tolerance(size_vram: int) -> float:
    return max(size_vram * _TOL_PCT / 100.0, _TOL_FLOOR_BYTES)


def pid_name_map(state: Optional[Dict[str, Any]]) -> Optional[Dict[str, Dict[str, Any]]]:
    """PID -> model name, from the host exporter. None when it has none.

    WHY THIS SPLIT: the exporter runs on a 60s cron, so its VRAM FIGURES go
    stale fast -- measured a 46s-old snapshot reporting both cards empty while
    nvidia-smi showed 4906 MiB live, because models cycle on KEEP_ALIVE expiry.
    Using its numbers made the panel contradict itself (a card reading
    "0 / 8 GB - 0%" while listing models).

    But a PID is a STABLE IDENTITY for the life of its process: a 60s-old name
    for a still-running pid is still correct, and a pid that has exited simply
    will not appear in the live nvidia-smi list. So the exporter supplies only
    the mapping -- which the container cannot compute at all, having its own PID
    namespace -- and every byte figure is read live.
    """
    if not state or "procs" not in state:
        return None
    procs = state.get("procs")
    if procs is None:
        return None
    out: Dict[str, Dict[str, Any]] = {}
    for p in procs:
        pid = str(p.get("pid") or "")
        if not pid:
            continue
        out[pid] = {
            "model": p.get("model"),
            "candidates": list(p.get("candidates") or []),
            "exact": bool(p.get("exact")),
        }
    return out or None


def attribute_named(
    procs: Optional[Iterable[Dict[str, Any]]],
    pid_names: Optional[Dict[str, Dict[str, Any]]],
    models: Optional[Iterable[Dict[str, Any]]] = None,
) -> Optional[Dict[str, Any]]:
    """Attribute LIVE per-card process bytes using exporter-supplied names.

    ``procs`` is ``gpu_process_snapshot()`` -- read now, so the numbers are
    current. ``pid_names`` is ``pid_name_map()`` -- up to 60s old, which is fine
    because it is keyed by a pid that either still exists (name still right) or
    is absent from ``procs`` (so never consulted).

    Returns None when either input is missing, so the caller falls back to
    byte-matching rather than rendering an empty GPU section.
    """
    if procs is None or not pid_names:
        return None

    by_uuid: Dict[str, List[Dict[str, Any]]] = {}
    anon_by_uuid: Dict[str, List[Dict[str, Any]]] = {}
    named: set = set()
    for p in procs:
        uuid = p.get("uuid")
        if not uuid:
            continue
        nbytes = int(p.get("bytes") or 0)
        info = pid_names.get(str(p.get("pid"))) or {}
        name = info.get("model") if info.get("exact") else None
        if name:
            by_uuid.setdefault(uuid, []).append({"name": name, "bytes": nbytes})
            named.add(name)
        else:
            anon_by_uuid.setdefault(uuid, []).append(
                {"bytes": nbytes, "candidates": list(info.get("candidates") or [])}
            )
    for lst in by_uuid.values():
        lst.sort(key=lambda d: -d["bytes"])
    for lst in anon_by_uuid.values():
        lst.sort(key=lambda d: -d["bytes"])

    unresolved = sorted(
        m["name"] for m in (models or []) if (m.get("size_vram") or 0) > 0 and m.get("name") and m["name"] not in named
    )
    return {
        "by_uuid": by_uuid,
        "anon_by_uuid": anon_by_uuid,
        "unresolved": unresolved,
        "available": True,
        "source": "exporter",
    }


def attribute_from_state(
    state: Optional[Dict[str, Any]],
    models: Optional[Iterable[Dict[str, Any]]] = None,
) -> Optional[Dict[str, Any]]:
    """Exact attribution from the host exporter, or None if it has none.

    This is the PREFERRED path and it needs no guessing. The exporter
    (scripts/gpu_state_exporter.py) runs on the host, so it can read
    /proc/<pid>/cmdline, take the weights blob a runner was started with, and
    resolve it through Ollama's own manifests -- narrowed by the resident set,
    because 7 of 19 blobs here back several tags. Measured live: 4 of 4
    processes named exactly, including a mistral:7b SPANNING both cards
    (5.18 GB Quadro + 0.13 GB TITAN) that byte-matching can never name because
    mistral and both 7Bs report near-identical size_vram.

    Returns None -- not an empty result -- when the payload carries no `procs`
    key at all, which is how an older exporter cleanly hands over to the
    byte-matching fallback instead of reading as "no models resident".
    """
    if not state or "procs" not in state:
        return None
    procs = state.get("procs")
    if procs is None:
        return None

    by_uuid: Dict[str, List[Dict[str, Any]]] = {}
    anon_by_uuid: Dict[str, List[Dict[str, Any]]] = {}
    named: set = set()
    for p in procs:
        uuid = p.get("uuid")
        if not uuid:
            continue
        nbytes = int(p.get("mem_mb") or 0) * _MIB
        name = p.get("model") if p.get("exact") else None
        if name:
            by_uuid.setdefault(uuid, []).append({"name": name, "bytes": nbytes})
            named.add(name)
        else:
            # Ambiguous or unnameable: report the bytes and the candidates, so a
            # busy card is never drawn as idle and the reader is never handed a
            # single name the data does not support.
            anon_by_uuid.setdefault(uuid, []).append({"bytes": nbytes, "candidates": list(p.get("candidates") or [])})
    for lst in by_uuid.values():
        lst.sort(key=lambda d: -d["bytes"])
    for lst in anon_by_uuid.values():
        lst.sort(key=lambda d: -d["bytes"])

    # A model /api/ps calls GPU-resident that no process accounted for is still
    # reported, under the node's GPU heading without a card.
    unresolved = sorted(
        m["name"] for m in (models or []) if (m.get("size_vram") or 0) > 0 and m.get("name") and m["name"] not in named
    )
    return {
        "by_uuid": by_uuid,
        "anon_by_uuid": anon_by_uuid,
        "unresolved": unresolved,
        "available": True,
        "source": "exporter",
    }


def attribute(
    models: Iterable[Dict[str, Any]],
    procs: Optional[Iterable[Dict[str, Any]]],
) -> Dict[str, Any]:
    """Match GPU-resident models to cards, but only where the match is forced.

    ``models``: dicts with ``name`` and ``size_vram`` (bytes).
    ``procs``:  ``gpu_process_snapshot()`` output, or None when unknown.

    Returns::

        {"by_uuid":      {uuid: [{"name", "bytes"}]},   # named, forced matches
         "anon_by_uuid": {uuid: [{"bytes"}]},           # measured, unnameable
         "unresolved":   [name],                        # resident, no card
         "available":    bool}

    ``available`` is False when nvidia-smi told us nothing -- the caller must
    then show GPU models without a card rather than claim every card is empty.
    ``anon_by_uuid`` is why a busy card never renders as idle: the bytes are
    ground truth even when the model behind them is not identifiable.
    """
    gpu_models = [m for m in (models or []) if (m.get("size_vram") or 0) > 0 and m.get("name")]
    if procs is None:
        return {
            "by_uuid": {},
            "anon_by_uuid": {},
            "unresolved": [m["name"] for m in gpu_models],
            "available": False,
        }

    # A model that SPANS cards is one process holding memory on several, so
    # group by pid first and match on the pid's TOTAL. The per-card split is
    # then a property of the winning pid -- which is how a spanning model gets
    # shown on both cards instead of being forced onto one.
    by_pid: Dict[str, Dict[str, Any]] = {}
    for p in procs:
        e = by_pid.setdefault(p["pid"], {"total": 0, "cards": {}})
        e["total"] += p["bytes"]
        e["cards"][p["uuid"]] = e["cards"].get(p["uuid"], 0) + p["bytes"]

    # Candidate edges: model <-> pid within tolerance.
    cands: Dict[str, List[str]] = {}
    for m in gpu_models:
        tol = _tolerance(m["size_vram"])
        cands[m["name"]] = [pid for pid, e in by_pid.items() if abs(e["total"] - m["size_vram"]) <= tol]

    # Constraint propagation: assign only FORCED pairs. A pair is forced when
    # the model has exactly one remaining candidate pid AND that pid is wanted
    # by exactly one remaining model. Anything still contested when propagation
    # stalls stays unresolved -- deliberately, because a tie here means the
    # bytes genuinely cannot tell the two models apart.
    assigned: Dict[str, str] = {}
    open_models = {m["name"] for m in gpu_models}
    open_pids = set(by_pid)

    progress = True
    while progress:
        progress = False
        for name in sorted(open_models):
            avail = [p for p in cands[name] if p in open_pids]
            if len(avail) != 1:
                continue
            pid = avail[0]
            rivals = [
                other
                for other in open_models
                if other != name and pid in cands[other]
                # a rival only counts if it could still take this pid
            ]
            if rivals:
                continue
            assigned[name] = pid
            open_models.discard(name)
            open_pids.discard(pid)
            progress = True
            break

    by_uuid: Dict[str, List[Dict[str, Any]]] = {}
    for name, pid in assigned.items():
        for uuid, nbytes in by_pid[pid]["cards"].items():
            by_uuid.setdefault(uuid, []).append({"name": name, "bytes": nbytes})
    for lst in by_uuid.values():
        lst.sort(key=lambda d: -d["bytes"])

    # A card holding an UNNAMED allocation is not an idle card. Reporting only
    # the named models let a Quadro sitting at 6.8/8 GB render as "idle" -- a
    # flatly false statement, and the same failure class this whole panel keeps
    # being fixed for. The bytes are measured ground truth even when the name
    # is not, so they are reported separately rather than dropped.
    anon_by_uuid: Dict[str, List[Dict[str, Any]]] = {}
    for pid in sorted(open_pids):
        for uuid, nbytes in by_pid[pid]["cards"].items():
            anon_by_uuid.setdefault(uuid, []).append({"bytes": nbytes})
    for lst in anon_by_uuid.values():
        lst.sort(key=lambda d: -d["bytes"])

    return {
        "by_uuid": by_uuid,
        "anon_by_uuid": anon_by_uuid,
        "unresolved": sorted(open_models),
        "available": True,
    }
