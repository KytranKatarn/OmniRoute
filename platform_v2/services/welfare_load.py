"""Token-based agent load + fatigue — single source of the welfare formula (FIX-12).

K.I.N. welfare/fatigue was historically computed from ACTION/QUERY COUNT
(``utilization = min(COUNT(dispatches_last_hour) / 20, 1.0)``), so an agent firing
200 tiny 50-token classify calls looked "exhausted" while one doing 10 huge
40k-token analyses looked "light" — and K.I.N. rested exactly the wrong agents,
stranding healthy ones idle. (Review: ``.claude/kin-welfare-review.md``, KB #270619.)

This module replaces that with a TOKEN + DURATION load over a rolling window, so
fatigue tracks real compute load, not how many times an agent was pinged. The data
already exists: ``task_execution_log.tokens_used`` (real Ollama eval_count) +
``duration_ms`` per dispatch, and ``agent_budgets.token_limit_per_day``.

PURE FUNCTIONS ONLY — no DB, no side effects. Callers (FIX-1
``agent_service.update_welfare_after_task``, FIX-2 dispatcher ``_update_agent_welfare``,
FIX-5 ``jobs.kin_workload_monitor``) supply the windowed ``SUM(tokens_used)`` /
``SUM(duration_ms)`` / failure counts and the agent's daily budget, and import the
ONE formula here so all three surfaces agree.

Decay is intrinsic: because load is computed over a sliding window of
``task_execution_log``, old work ages out automatically — once an agent stops, the
windowed token sum falls and stress decays on the next recompute. No separate decay
term is needed for the load itself.
"""

from __future__ import annotations

# Productive hours/day used to turn a DAILY token budget into a per-window ceiling.
# A 150k/day budget => 15k/hr is "full load" for a 60-minute window.
PRODUCTIVE_HOURS_PER_DAY = 10.0

# Fallback daily token budget when an agent has none configured, so a missing/zero
# budget does NOT make every dispatch read as fully loaded (over-sensitive).
DEFAULT_TOKEN_LIMIT_PER_DAY = 150_000

# Tokens dominate (they are the real compute/cost signal); wall-clock duration is a
# FLOOR so a long but token-cheap job still registers as occupancy.
TOKEN_WEIGHT = 0.7
DURATION_WEIGHT = 0.3

# Stress/energy coefficients — same shape as the legacy action-count model so existing
# thresholds (winding_down @0.70, cooldown @0.85, DB CHECK ceiling 0.90) still map.
STRESS_BASE = 0.2
STRESS_LOAD_COEF = 0.4
STRESS_FAILURE_COEF = 0.3
STRESS_CEILING = 0.9  # agent_emotional_state.stress_level CHECK ceiling

ENERGY_BASE = 0.9
ENERGY_LOAD_COEF = 0.6
ENERGY_FAILURE_COEF = 0.2
ENERGY_FLOOR = 0.1


def _num(value, default: float = 0.0) -> float:
    """Coerce a possibly-None / non-numeric DB value to float."""
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def compute_token_load(
    tokens,
    duration_ms,
    token_limit_per_day,
    decay_window_min: int = 60,
) -> float:
    """Return an agent's load in ``[0.0, 1.0]`` from real work over the window.

    Args:
        tokens: windowed ``SUM(task_execution_log.tokens_used)`` for the agent.
        duration_ms: windowed ``SUM(duration_ms)`` for the agent.
        token_limit_per_day: ``agent_budgets.token_limit_per_day`` (daily ceiling).
            ``None``/``0`` falls back to ``DEFAULT_TOKEN_LIMIT_PER_DAY``.
        decay_window_min: the rolling window length the sums were taken over.

    1.0 means "fully loaded for this window". A 50-token ping contributes ~0; a
    50k-token analysis against a 150k/day budget contributes a meaningful load.
    """
    toks = max(0.0, _num(tokens))
    dur_ms = max(0.0, _num(duration_ms))
    limit = _num(token_limit_per_day)
    if limit <= 0:
        limit = DEFAULT_TOKEN_LIMIT_PER_DAY
    window_min = decay_window_min if decay_window_min and decay_window_min > 0 else 60

    # Daily budget -> per-window token ceiling (scaled to the window length).
    tokens_full = max(1.0, (limit / PRODUCTIVE_HOURS_PER_DAY) * (window_min / 60.0))
    token_load = min(toks / tokens_full, 1.0)

    # Wall-clock occupancy: window_min of busy time == full occupancy.
    duration_full_ms = window_min * 60 * 1000
    duration_load = min(dur_ms / duration_full_ms, 1.0)

    return min(TOKEN_WEIGHT * token_load + DURATION_WEIGHT * duration_load, 1.0)


def stress_energy_from_load(load: float, failures, total) -> tuple[float, float]:
    """Map a load (+ failure rate) to ``(stress, energy)`` in DB-valid ranges.

    Replaces the action-count ``utilization`` term with ``load`` while keeping the
    same coefficient shape, so existing welfare thresholds continue to apply.
    """
    load = max(0.0, min(_num(load), 1.0))
    total_n = _num(total)
    failure_rate = (_num(failures) / total_n) if total_n > 0 else 0.0
    failure_rate = max(0.0, min(failure_rate, 1.0))

    stress = round(
        min(STRESS_BASE + load * STRESS_LOAD_COEF + failure_rate * STRESS_FAILURE_COEF, STRESS_CEILING),
        2,
    )
    energy = round(
        max(ENERGY_BASE - load * ENERGY_LOAD_COEF - failure_rate * ENERGY_FAILURE_COEF, ENERGY_FLOOR),
        2,
    )
    return stress, energy


if __name__ == "__main__":  # pragma: no cover - self-test
    # 200 tiny 50-token classify calls (10k tokens) over the hour @150k/day budget:
    cheap = compute_token_load(200 * 50, 200 * 400, 150_000)
    # 10 heavy 40k-token analyses (400k tokens) same budget:
    heavy = compute_token_load(10 * 40_000, 10 * 12_000, 150_000)
    # idle:
    idle = compute_token_load(0, 0, 150_000)
    print(f"cheap-200-pings load={cheap:.3f}  heavy-10-analyses load={heavy:.3f}  idle load={idle:.3f}")
    cs, ce = stress_energy_from_load(cheap, 0, 200)
    hs, he = stress_energy_from_load(heavy, 0, 10)
    print(f"cheap -> stress={cs} energy={ce}   heavy -> stress={hs} energy={he}")
    # The whole point: many cheap pings must NOT out-stress a few heavy analyses.
    assert cheap < heavy, "cheap high-count work must read LIGHTER than heavy token work"
    assert idle == 0.0, "idle must be zero load"
    assert hs > cs, "heavy token work must produce more stress than cheap pings"
    assert 0.0 <= heavy <= 1.0 and 0.1 <= he <= 0.9
    # No-budget fallback must not peg load to 1.0 on modest tokens:
    assert compute_token_load(10_000, 0, None) < 0.5, "missing budget must not over-saturate"
    print("welfare_load self-test: ALL PASS")
