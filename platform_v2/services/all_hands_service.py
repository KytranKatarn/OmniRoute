"""All Hands protocol — parallel multi-agent fan-out / fan-in dispatch (#2586).

MVP: a SYNCHRONOUS agent-level fan-out. Given a ``capability`` and a list of work
``items`` (prompts), it selects up to N distinct welfare-gated agents
(``coordinator.select_agents``), assigns items round-robin, dispatches each item
CONCURRENTLY to its assigned agent via the normal DHQ ``dispatch(prefer_agent=…)``
path — so K.I.N. welfare + C.R.E.E.D. + cost tracking + the cold-load queue are
all enforced per item — then fans the results back IN: aligned to input order,
with successes and partial failures separated.

**Call from a job / worker, NOT a web request.** It blocks until the whole batch
completes, and ADR-013 forbids long inference on the gunicorn web thread. Concurrency
is bounded (``all_hands:max_concurrency``, default 6) so a big batch can't swamp the
hub GPU/queue — the dispatch path still welfare-gates each individual item.

Partial-failure semantics: a single item failing NEVER fails the whole batch — the
failed item is captured with its error and the run continues (``partial=True`` when
some but not all items fail). Only an empty/invalid ``items`` list raises.

Deferred to follow-ups (see #2586 project): a progress UI in the DHQ Dispatch tab;
persistent async batches (a ``batch_id`` / ``parent_task_id`` cohort on
``unified_tasks`` + a batch worker); and cross-department / fleet agent expansion
beyond the home department (today a fan-out draws only from the capability's home
department, so it can under-parallelize for single-agent departments).
"""

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable, List, Optional

logger = logging.getLogger(__name__)

# Hard ceiling on concurrent in-flight dispatches per fan-out. The dispatch path
# still welfare/K.I.N.-gates each item; this just caps burst pressure on the hub.
_DEFAULT_MAX_CONCURRENCY = 6
_MAX_CONCURRENCY_KEY = "all_hands:max_concurrency"


def _max_concurrency() -> int:
    """Concurrent-dispatch ceiling from platform_settings; default 6. Never raises."""
    try:
        from db import get_db

        conn = get_db()
        try:
            cur = conn.cursor()
            cur.execute("SELECT value FROM platform_settings WHERE key = %s", (_MAX_CONCURRENCY_KEY,))
            row = cur.fetchone()
            cur.close()
        finally:
            conn.close()
        if row:
            val = row["value"] if isinstance(row, dict) else row[0]
            return max(1, int(val))
    except Exception:  # noqa: BLE001 — a settings hiccup must not break a fan-out
        pass
    return _DEFAULT_MAX_CONCURRENCY


def _default_select_agents(capability: str, n: int) -> list:
    from services.department_coordinator import get_coordinator

    return get_coordinator().select_agents(capability, n) or []


def all_hands_dispatch(
    capability: str,
    items: List[str],
    *,
    module_id: str = "all_hands",
    max_agents: Optional[int] = None,
    system_prompt: Optional[str] = None,
    dispatch_fn: Optional[Callable] = None,
    select_agents_fn: Optional[Callable] = None,
) -> dict:
    """Fan ``items`` across multiple agents in parallel; fan the results back in.

    Returns::

        {
          "ok": True,
          "capability": <str>,
          "total": <int>, "succeeded": <int>, "failed": <int>,
          "partial": <bool>,                 # some-but-not-all failed
          "agents_selected": [<name>, ...],  # from select_agents (pins)
          "agents_used": [<name>, ...],      # actual agents per DispatchResult
          "results": [                        # ALIGNED to items input order
            {"index", "item", "agent", "success", "response", "error"}, ...
          ],
        }

    ``dispatch_fn`` / ``select_agents_fn`` are injectable for testing; production
    defaults are the DHQ dispatch() and coordinator.select_agents().
    """
    if not items or not isinstance(items, list):
        raise ValueError("items must be a non-empty list of prompt strings")

    if dispatch_fn is None:
        from tools.department_hq.services.department_dispatcher import dispatch as dispatch_fn
    if select_agents_fn is None:
        select_agents_fn = _default_select_agents

    want = min(len(items), max_agents) if max_agents else len(items)
    agents = select_agents_fn(capability, want) or []
    agent_names = [a.get("name") for a in agents if a.get("name")]

    if agent_names:
        # round-robin assign each item to a distinct selected agent
        assignments = [agent_names[i % len(agent_names)] for i in range(len(items))]
    else:
        # No welfare-clear agent right now → un-pinned dispatch per item (the
        # dispatcher selects/queues); still fans out (bounded) + aggregates.
        logger.info("all_hands: no available agent for '%s' — un-pinned fallback", capability)
        assignments = [None] * len(items)

    workers = max(1, min(len(items), len(agent_names) or len(items), _max_concurrency()))

    def _one(idx: int) -> dict:
        item = items[idx]
        agent = assignments[idx]
        try:
            kw = {"module_id": module_id}
            if system_prompt:
                kw["system_prompt"] = system_prompt
            if agent:
                kw["prefer_agent"] = agent
            res = dispatch_fn(capability, item, **kw)
            success = bool(getattr(res, "success", False))
            return {
                "index": idx,
                "item": item,
                "agent": getattr(res, "agent_name", None) or agent,
                "success": success,
                "response": getattr(res, "response", None),
                "error": None if success else (getattr(res, "error", None) or "dispatch failed"),
            }
        except Exception as e:  # noqa: BLE001 — one item's failure must not kill the batch
            logger.exception("all_hands: item %d failed", idx)
            return {
                "index": idx,
                "item": item,
                "agent": agent,
                "success": False,
                "response": None,
                "error": str(e)[:500],
            }

    results: list = [None] * len(items)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(_one, i): i for i in range(len(items))}
        for fut in as_completed(futures):
            r = fut.result()
            results[r["index"]] = r

    succeeded = sum(1 for r in results if r and r["success"])
    failed = len(results) - succeeded
    used = sorted({r["agent"] for r in results if r and r.get("agent")})
    return {
        "ok": True,
        "capability": capability,
        "total": len(items),
        "succeeded": succeeded,
        "failed": failed,
        "partial": 0 < failed < len(items),
        "agents_selected": agent_names,
        "agents_used": used,
        "results": results,
    }
