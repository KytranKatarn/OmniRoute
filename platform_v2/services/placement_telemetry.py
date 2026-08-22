"""Persist GPU-vs-CPU model placement decisions (#5273, Phase 1).

Why this module exists at all
-----------------------------
``model_service.gpu_placement_options()`` is THE single placement decision point
and already computes everything worth recording — it just throws it at a log
line. ``docker logs archie_scheduler | grep placement`` is a ring buffer that a
container restart erases, so there is no history to query. The #5903 hunt burned
four hypotheses (VRAM exhaustion, dead Ollama, CPU demotion, slot leak) reaching
a fact one ``SELECT`` would have returned.

Why it is a SEPARATE module rather than an inline INSERT
--------------------------------------------------------
``model_service`` deliberately imports NO database machinery — only json,
logging, os, socket, time, urllib. It is a low-level Ollama HTTP client. Adding
``from database import ...`` at its module level would give it a DB dependency it
has never had and invite an import cycle. So the write lives here and
``model_service`` reaches it through a LAZY import inside its own try/except.

⚠️ A ROW IS ONE LOAD, NOT ONE REQUEST
-------------------------------------
``gpu_placement_options`` runs when a model is (re)loaded, and ``KEEP_ALIVE`` is
60m. One ``cpu`` row therefore means the model SAT in CPU mode, serving every
request that arrived during that span — and on this pre-AVX2 Xeon a 7B on CPU
cannot finish inside the 240s/300s deadline (a guaranteed failure, not a slow
path — see ``model_service.py`` lines 56-64 and task #5623).

Consequence for analysis: derive TIME-IN-STATE with ``lead()`` over consecutive
rows per model. A raw count understates the impact badly.
"""

from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)

# The reasons the single decision point can produce. Kept here so a typo at a
# call site is visible in one place rather than silently creating a new bucket
# that every existing query then misses.
REASONS = (
    "resident",  # already resident in VRAM
    "comfyui_reserved",  # ComfyUI awake — GPUs reserved for image gen
    "budget_fit",  # budget >= needed
    "budget_short",  # budget < needed
    "vram_unknown",  # exception path — placement was GUESSING
)


def record_placement(
    *,
    model: str,
    decision: str,
    reason: str,
    budget_gb: Optional[float] = None,
    needed_gb: Optional[float] = None,
    resident_vram_gb: Optional[float] = None,
    node_name: Optional[str] = None,
    detail: Optional[str] = None,
) -> None:
    """Append one placement decision to ``model_placement_log``. Never raises.

    Fail-safe contract, deliberately in two halves:

    1. **Never break the caller.** Placement must proceed even if the DB is
       unreachable. This mirrors ``telemetry_writer.log_marker`` ("telemetry must
       never break the caller").

    2. **But do NOT go quiet.** ``telemetry_writer`` swallows to ``logger.debug``;
       this one uses ``logger.warning`` on purpose. This table IS a monitoring
       surface, and a monitoring surface that fails silently is "unmonitored
       while APPEARING monitored" — the exact defect class behind
       ``mission_revert_at`` (#5902, written and read nowhere) and W.A.R.D.E.N.'s
       integrity check (#2366, which queried a non-existent table and swallowed
       the exception every run). A dropped row must be visible in the logs.

    Note: an ad-hoc ``docker exec ... python3 -c`` context may lack DB
    credentials that the real app process has (observed live as
    ``fe_sendauth: no password supplied``). That path will warn and continue,
    which is the intended behaviour — not a reason to weaken the contract.
    """
    try:
        # Lazy import: keeps this module (and therefore model_service's lazy
        # import of it) free of a module-level DB dependency.
        from database import get_db_cursor

        with get_db_cursor(commit=True) as (_conn, cur):
            cur.execute(
                """
                INSERT INTO model_placement_log
                    (model, decision, reason, budget_gb, needed_gb,
                     resident_vram_gb, node_name, detail)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    model,
                    decision,
                    reason,
                    budget_gb,
                    needed_gb,
                    resident_vram_gb,
                    node_name,
                    detail,
                ),
            )
    except Exception as exc:  # never break placement — but never go quiet either
        logger.warning(
            "placement_telemetry: DROPPED a placement row for %s -> %s (%s): %s",
            model,
            decision,
            reason,
            exc,
        )
