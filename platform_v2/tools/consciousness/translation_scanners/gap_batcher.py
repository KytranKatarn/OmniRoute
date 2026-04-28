"""gap_batcher.py — batches open domain translation gaps into delegate_task calls.

Called at the end of run_translation_coverage_scan() for domain-sourced gaps.
Batches up to BATCH_SIZE keys per delegate_task call so the dispatcher does
not receive single-key requests that waste agent context.

Only routes gaps with source starting 'domain:' — filesystem scanner gaps
are handled by generator.py's process_missing_gap() flow.
"""

from __future__ import annotations

import json
import logging

from database import get_db_cursor

logger = logging.getLogger("agent_loop")

# Imported at module level so tests can patch it.
# delegation_service is always available inside the platform container.
try:
    from services.delegation_service import delegate_task
except ImportError:  # outside Flask context (e.g. direct python invocation)
    delegate_task = None  # type: ignore[assignment]

BATCH_SIZE = 20
NIGHTLY_ROUTE_CAP = 200  # max gaps to delegate per nightly run


def _load_unrouted_domain_gaps(limit: int = NIGHTLY_ROUTE_CAP) -> list[dict]:
    """Load open missing gaps from domain sources not yet routed."""
    with get_db_cursor() as (_conn, cur):
        cur.execute(
            """SELECT id, source, language, key, gap_type, snippet
               FROM translation_gaps
               WHERE status = 'open'
                 AND gap_type = 'missing'
                 AND source LIKE 'domain:%%'
               ORDER BY created_at ASC
               LIMIT %s""",
            (limit,),
        )
        return [dict(r) for r in cur.fetchall()]


def _mark_routed(gap_ids: list[int], task_id: int | None) -> None:
    with get_db_cursor(commit=True) as (_conn, cur):
        cur.execute(
            "UPDATE translation_gaps SET status='routed', task_id=%s WHERE id = ANY(%s)",
            (task_id, gap_ids),
        )


def route_domain_gaps_to_translate(dry_run: bool = False) -> dict:
    """Batch open domain translation gaps into delegate_task calls.

    Returns ``{"batches_sent": int, "gaps_routed": int, "errors": int}``.
    """
    gaps = _load_unrouted_domain_gaps()
    if not gaps:
        logger.info("[GapBatcher] no unrouted domain gaps found")
        return {"batches_sent": 0, "gaps_routed": 0, "errors": 0}

    # Group by language for coherent batches
    by_lang: dict[str, list[dict]] = {}
    for gap in gaps:
        by_lang.setdefault(gap["language"], []).append(gap)

    batches_sent = 0
    gaps_routed = 0
    errors = 0

    for lang, lang_gaps in by_lang.items():
        for i in range(0, len(lang_gaps), BATCH_SIZE):
            batch = lang_gaps[i : i + BATCH_SIZE]
            gap_ids = [g["id"] for g in batch]
            keys = [g["key"] for g in batch]
            sources = list({g["source"] for g in batch})
            reason = (
                f"Fill {len(keys)} missing translation keys for language='{lang}' "
                f"on domains: {', '.join(sources)}. "
                f"Sample keys: {json.dumps(keys[:3])}"
            )

            if dry_run:
                logger.info("[GapBatcher][DRY] lang=%s keys=%d", lang, len(keys))
                gaps_routed += len(batch)
                batches_sent += 1
                continue

            try:
                result = delegate_task(
                    capability="translate",
                    reason=reason,
                    args={"language": lang, "keys": keys, "sources": sources, "gap_ids": gap_ids},
                    delegation_source="automation",
                    requested_by="probe_domain_audit",
                    priority=4,
                )
                if result.get("success"):
                    _mark_routed(gap_ids, result.get("task_id"))
                    gaps_routed += len(batch)
                    batches_sent += 1
                    logger.info(
                        "[GapBatcher] routed %d gaps lang=%s → task_id=%s",
                        len(batch),
                        lang,
                        result.get("task_id"),
                    )
                else:
                    logger.warning("[GapBatcher] delegate_task failed: %s", result.get("error"))
                    errors += 1
            except Exception:  # noqa: BLE001
                logger.exception("[GapBatcher] batch send failed lang=%s", lang)
                errors += 1

    return {"batches_sent": batches_sent, "gaps_routed": gaps_routed, "errors": errors}
