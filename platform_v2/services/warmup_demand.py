"""Demand threshold for the startup warm-up list (#7330, #6106).

``app._get_agent_models`` used to return one entry per DISTINCT model assigned to an active
agent, so a model carried by one agent that nobody dispatches to was preloaded exactly like
qwen2.5:7b (99 agents, 52k runs/7d). phi3.5 (0 runs) and qwen2.5-coder:7b (~100 runs) took
~8GB of hub VRAM and the 7B was demoted to CPU. #3945 hard-coded both; this derives it from
data so the next newly-assigned model cannot repeat it.

A model is warmed only if it had at least ``min_runs_7d`` dispatches in the last 7 days,
OR (when ``min_agents`` > 0) is carried by at least that many agents. Infrastructure models
are never filtered. ``hard_skip`` keeps the two entries that have documented, non-demand
reasons (vision model 500s without an image; dolphin3 cold-load blocks the warm-up).

Tunable with no deploy: ``platform_settings`` ``warmup:min_runs_7d`` / ``warmup:min_agents``.
Pure apart from ``load_thresholds``; never raises (bad config -> defaults).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Iterable, List, Mapping, Tuple

logger = logging.getLogger(__name__)

DEFAULT_MIN_RUNS_7D = 200
DEFAULT_MIN_AGENTS = 0  # 0 = the agent-count alternative is off

_PS_MIN_RUNS = "warmup:min_runs_7d"
_PS_MIN_AGENTS = "warmup:min_agents"


@dataclass(frozen=True)
class Thresholds:
    min_runs_7d: int = DEFAULT_MIN_RUNS_7D
    min_agents: int = DEFAULT_MIN_AGENTS


def _as_int(value, default: int) -> int:
    try:
        n = int(str(value).strip())
    except (TypeError, ValueError):
        return default
    return n if n >= 0 else default


def load_thresholds(cur) -> Thresholds:
    """Read the two tunables from ``platform_settings``; any error -> defaults."""
    try:
        cur.execute("SELECT key, value FROM platform_settings WHERE key IN (%s, %s)", (_PS_MIN_RUNS, _PS_MIN_AGENTS))
        found = {}
        for row in cur.fetchall() or []:
            key = row["key"] if isinstance(row, dict) else row[0]
            found[key] = row["value"] if isinstance(row, dict) else row[1]
        return Thresholds(
            min_runs_7d=_as_int(found.get(_PS_MIN_RUNS), DEFAULT_MIN_RUNS_7D),
            min_agents=_as_int(found.get(_PS_MIN_AGENTS), DEFAULT_MIN_AGENTS),
        )
    except Exception:
        logger.warning("warmup demand: threshold load failed; using defaults", exc_info=True)
        return Thresholds()


def filter_by_demand(
    rows: Iterable[Mapping],
    *,
    thresholds: Thresholds,
    infra: Iterable[str],
    hard_skip: Iterable[str],
) -> Tuple[List[str], List[Tuple[str, str]]]:
    """Return ``(kept_models_in_input_order, [(dropped_model, reason), ...])``.

    ``rows`` carry ``model``, ``dispatch_count`` and ``agent_count`` (already ordered by demand).
    """
    infra_set, skip_set = set(infra), set(hard_skip)
    kept: List[str] = []
    dropped: List[Tuple[str, str]] = []
    for row in rows:
        model = row["model"]
        runs = int(row.get("dispatch_count") or 0)
        agents = int(row.get("agent_count") or 0)
        if model in infra_set:
            continue  # infra models are added separately and never filtered
        if model in skip_set:
            dropped.append((model, "hard_skip"))
        elif runs >= thresholds.min_runs_7d or (thresholds.min_agents > 0 and agents >= thresholds.min_agents):
            kept.append(model)
        else:
            dropped.append((model, f"low_demand runs_7d={runs}<{thresholds.min_runs_7d} agents={agents}"))
    return kept, dropped
