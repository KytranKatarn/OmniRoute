"""Persist ACTUAL model residency, one row per loaded model per sample (#5273/#6106).

``model_placement_log`` records what the router DECIDED. This records what Ollama
REPORTS, so the two can be compared. They disagree exactly when a runner is
stranded on CPU: the router says "gpu" (omit num_gpu) while a live runner keeps
``size_vram = 0`` because Ollama does not reload it on an option-omitting request
(#5328). Before this table the only evidence was log lines.

Fed by the existing 5-min ``ollama_lifecycle_telemetry`` job, which already holds
the ``snapshot_ollama_lifecycle()`` result. No extra polling of Ollama.

Same fail-safe contract as ``placement_telemetry``: never break the caller, never
go quiet (``logger.warning`` on a dropped sample -- a monitoring surface that fails
silently is "unmonitored while APPEARING monitored").
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


def build_rows(
    snapshot: Dict[str, Any],
    *,
    node_name: str = "hub",
    cpu_pinned: Optional[Callable[[str], Optional[bool]]] = None,
) -> List[tuple]:
    """PURE: ``snapshot_ollama_lifecycle()`` output -> insert tuples.

    ``cpu_pinned(model)`` answers "does the Modelfile pin num_gpu 0?" and may raise or
    return None for unknown. It is consulted ONLY for a model holding no VRAM (the
    only case where the answer matters), so a healthy GPU model never costs an
    ``/api/show``. Unknown is stored as NULL, never guessed.
    """
    rows: List[tuple] = []
    for m in snapshot.get("models") or []:
        name = m.get("name")
        if not name:
            continue
        vram = float(m.get("vram_gb") or 0)
        pin: Optional[bool] = None
        if vram == 0 and cpu_pinned is not None:
            try:
                pin = cpu_pinned(name)
            except Exception as exc:  # unknown, not False
                logger.debug("residency_sampler: cpu_pinned(%s) failed: %s", name, exc)
        rows.append(
            (
                node_name,
                name,
                float(m.get("ram_gb") or 0),
                vram,
                m.get("seconds_remaining"),
                pin,
            )
        )
    return rows


def _default_cpu_pinned(model: str) -> Optional[bool]:
    from services.model_service import get_model_service

    return get_model_service().is_cpu_pinned_by_modelfile(model)


def record_samples(snapshot: Dict[str, Any], *, node_name: str = "hub") -> int:
    """Append one row per loaded model. Returns rows written. Never raises."""
    try:
        rows = build_rows(snapshot, node_name=node_name, cpu_pinned=_default_cpu_pinned)
        if not rows:
            return 0
        from database import get_db_cursor

        with get_db_cursor(commit=True) as (_conn, cur):
            cur.executemany(
                """
                INSERT INTO model_residency_samples
                    (node_name, model, size_gb, size_vram_gb, seconds_remaining, modelfile_cpu_pin)
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                rows,
            )
        return len(rows)
    except Exception as exc:  # never break the lifecycle job -- but never go quiet either
        logger.warning("residency_sampler: DROPPED a residency sample: %s", exc)
        return 0
