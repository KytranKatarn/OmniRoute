# OmniRoute Quota Awareness ("Deep Space Nine" — Phase 2)

**Date:** 2026-09-19 · **Owner decision:** scope this phase to the providers OmniRoute fronts only (currently `opencode-zen`). The stated end goal is DS9 eventually becoming one unified UI for ALL free-tier providers, including the ones already tracked separately (groq/cerebras/cohere/qwen3_cloud via `ai_bridge/external_providers.py`) — that unification is explicitly NOT this phase. The DHQ Contractors tab is the intended eventual home for that unified view; this phase starts building there under its current name, with a future rename to "DS9" expected once it actually does more than OmniRoute.
**Prior art this builds on:** `docs/superpowers/specs/2026-09-18-omniroute-reliability-watchdog-design.md` (Phase 1 — reliability watchdog, merged to main 2026-09-18; its §11 explicitly deferred quota-awareness to this phase). `platform_v2/services/omniroute_telemetry.py` (PR #3339 — already reads OmniRoute's `call_logs` sqlite read-only and mirrors real inference into `task_execution_log`, every 10 min). `ai_bridge/external_providers.py`'s `weekly_budget_status()`/`check_weekly_budget()`/`pick_free_text_provider()` (#3658/#3659) — the existing, proven shape for "free-tier budget status + alert threshold + routing hint" for groq/cerebras/cohere/qwen3_cloud. This phase mirrors that shape for OmniRoute-fronted providers rather than inventing a new one.

## 1. Why now

Live measurement taken during this design (2026-09-19, last 500 `call_logs` rows on the `omniroute` container): **246 `rate_limited` + 48 `quota_exhausted` = 59% of recent calls are currently being throttled**, on the `opencode-zen` upstream, with zero existing visibility anywhere in the platform. This is an active, ongoing condition, not a hypothetical future risk.

## 2. Goal & non-goals

**Goal.** Make throttling on OmniRoute-fronted providers visible — as it's happening, as a trend, and as a queryable status a future caller could use — without touching how OmniRoute or its combo fallback actually route requests.

**Non-goals (explicit):**
- **No dispatch/routing behavior change.** `get_quota_status()` (§4) is built and exposed but nothing calls it to change what happens on a request in this phase. Wiring it into a routing decision is future work, same boundary Phase 1 drew around "no routing-engine swap."
- **No unification with the groq/cerebras/cohere/qwen3_cloud budget system.** Explicit long-term goal (see header), not built here. The two systems stay separate; `get_quota_status()`'s return shape mirrors `weekly_budget_status()`'s deliberately, so unifying later is a UI/aggregation change, not a data-model rewrite.
- **No Contractors→"DS9" tab rename.** Cosmetic, deferred until the tab actually shows more than one provider family.
- **No OpenRouter, 9Router, or DeepSeek-V4-Flash work.** Phase 1's §11 Phase 3/4, untouched here.
- **No new sqlite mount or credential.** Reuses the exact read-only mount PR #3339 established on `archie_platform`/`archie_scheduler`.

## 3. Why this reads `call_logs` directly, not `task_execution_log`

`omniroute_telemetry.py` (PR #3339) deliberately drops every row where `tokens_in == 0 and tokens_out == 0` before it reaches `task_execution_log` — "a refused call is not inference," the same principle as the admission-gate lesson in `fleet.md`. That's correct for that table's job (clean inference/carbon/cost analytics) and wrong for this one: a quota-exhausted or rate-limited call is *exactly* a 0-token row, so it's exactly what that filter removes. Making `task_execution_log` serve both purposes would mean picking one filter that's wrong for the other consumer. Instead, this phase reads `call_logs` on its own independent cadence, for its own narrower question ("was this call throttled, and by what"), and leaves the telemetry mirror untouched.

`call_logs.error_type` already carries an exact enum distinguishing `quota_exhausted` and `rate_limited` from `model_not_found` and `server_error` — no inference from HTTP status codes or error-message text needed.

**One exclusion required:** a recurring row shape — `status=200, tokens_in=0, tokens_out=0, error_type=null, requested_model=null`, observed hourly on `opencode-zen` — is OmniRoute's own internal keep-alive/model-refresh ping, not a call of ours. Counting it as a "successful" call would understate the real throttle rate. `scan_quota_status()` excludes rows matching this exact shape before computing totals.

## 4. Architecture

New module: `platform_v2/services/omniroute_quota_service.py`.

```
scan_quota_status(window_hours=24) -> None  # window_hours is a default; both this
                                             # and the status bands below are
                                             # platform_settings-tunable, no deploy needed
  - opens the same read-only call_logs mount PR #3339 uses
  - SELECT rows in the window, excluding the keep-alive shape (§3)
  - group by `provider` (the upstream: opencode-zen, horde, cloudflare-playground,
    uncloseai, whatever OmniRoute adds later)
  - per provider: total, throttled (error_type IN ('quota_exhausted','rate_limited')),
    rate = throttled/total
  - INSERT one row per provider into omniroute_quota_snapshots (new table, §5)
  - on any error (schema drift, unreadable file): log loud, write nothing —
    same precedent as PR #3339's own schema-drift handling

get_quota_status(provider=None) -> dict | list[dict]
  - reads the LATEST snapshot row(s) from omniroute_quota_snapshots
  - shape: {provider, window_hours, total, throttled, rate, status, last_scan_at}
  - status bands (platform_settings-tunable, defaults):
      rate <  0.30 -> "ok"
      rate <  0.70 -> "degraded"
      rate >= 0.70 -> "exhausted"
  - THIS is the routing-hint interface: same shape as weekly_budget_status(),
    callable by a future dispatch/combo-selection guard with zero data-layer
    changes. No caller consumes it yet in this phase.
```

Scheduled via a new APScheduler job, `omniroute_quota_scan`, every 15 minutes — independent of the telemetry mirror's 10-minute cadence (different concern, no reason to couple them).

## 5. Components

| Component | Location | Purpose |
|---|---|---|
| `omniroute_quota_service.py` | `platform_v2/services/` | scan + status-read functions (§4) |
| `omniroute_quota_snapshots` | new table, platform Postgres | `(id, provider, window_hours, total, throttled, rate, created_at)` — one row per provider per scan; gives the dashboard/digest a real trend, not just a point-in-time read |
| `omniroute_quota_scan` job | `ai_bridge/agent_loop.py`, APScheduler, every 15 min | calls `scan_quota_status()` |
| Telegram alert | reuses the platform's own `services/telegram_service.py` (`send_system`), NOT Phase 1's independent Citadel bash path | see §6 for why these stay separate |
| Digest line | fold into the existing `kin_welfare_digest` job (`ai_bridge/agent_loop.py`) | one line per provider, appended to that digest's existing output |
| Dashboard card | DHQ → Contractors tab | current rate per provider + a trend sparkline from `omniroute_quota_snapshots` |

## 6. Why this phase's alerting does NOT reuse Phase 1's Citadel/Telegram path

Phase 1's watchdog pushes to Citadel specifically because it answers "is OmniRoute alive at all" — a question that must still get answered even if the hub itself is down or unreachable, so its alert path is deliberately independent of the hub. This phase answers a different question — "how much of our own traffic is being throttled" — which is inherently a hub-local computation: if the hub can't run this scan, it also isn't making OmniRoute calls, so there's no failure mode where the hub is down but this alert still needs to fire. Using the platform's own existing `telegram_service.send_system()` is therefore the right-sized choice, not a downgrade — it avoids inventing a second SSH-push mechanism for a signal that doesn't need off-hub redundancy.

## 7. Data flow (every 15 minutes)

1. `omniroute_quota_scan` job fires.
2. `scan_quota_status(window_hours=24)` reads `call_logs`, excludes keep-alive rows, groups by provider, computes total/throttled/rate.
3. One row per provider written to `omniroute_quota_snapshots`.
4. For each provider, compare the new `status` band to the previous scan's:
   - Transition into `exhausted`, confirmed for **K=2 consecutive scans** (same anti-blip logic as Phase 1's `OMNIROUTE_CONFIRM`) → one Telegram alert naming the provider and current rate.
   - Transition back out of `exhausted` → one "recovered" alert, counter reset.
   - No transition → no alert (never spam every cycle).
5. `kin_welfare_digest`'s existing run reads the latest `get_quota_status()` for each known provider and appends one summary line.
6. DHQ Contractors tab card calls `get_quota_status()` on page load / refresh, plus a small query against `omniroute_quota_snapshots` for the sparkline.

## 8. Error handling & false-positive guards

- **Fail-open**: any scan error leaves the previous snapshot standing and fires no alert — a counting bug must never manufacture a false "exhausted" alert, mirroring `weekly_budget_status()`'s own fail-open philosophy ("a counting error never blocks dispatch").
- **Schema drift** in `call_logs` (a renamed/missing column): fails loud in logs, writes nothing — same precedent as PR #3339.
- **Keep-alive rows**: excluded by exact shape match (§3), not by a blanket "ignore all 0-token rows" rule, since 0-token rows are also exactly the throttling signal this phase needs — the exclusion must be narrow.
- **K=2 confirmation gate**: prevents a single transient scan (e.g., a brief burst of retries right after a real outage recovers) from firing a spurious alert.
- **Provider disappears from recent data** (0 total calls in the window): reported as `status: "unknown"`, not `"ok"` — an idle provider isn't a healthy one, it's just unmeasured.

## 9. Testing

- `test_omniroute_quota_service.py`: real temp-sqlite fixture seeded with rows matching each `error_type` value plus the keep-alive shape — proves the exclusion removes exactly the keep-alive rows and nothing else, and that rate/status-band boundaries classify correctly at 0.29/0.30/0.69/0.70.
- Mutation-check at authoring time (out-of-tree copy, per this repo's standard): removing the keep-alive exclusion, the `error_type` filter, or the K=2 confirmation gate must each turn a test red.
- Manual verification before enabling alerts: run `scan_quota_status()` once by hand, confirm the computed rate roughly matches the 59% measured live during this design (§1), before wiring Telegram.

## 10. Rollout

1. Ship `omniroute_quota_service.py` + the `omniroute_quota_snapshots` migration + the scan job, logging output only — no alert, no dashboard card yet. Confirm a few real cycles land sane numbers.
2. Wire the Telegram alert (§7 step 4).
3. Add the DHQ Contractors tab card.
4. Fold the digest line into `kin_welfare_digest`.

## 11. Standing constraints (carried from Phase 1)

REMOTE 192.168.1.200 · branch+PR, never main · never commit secrets · 2 failures→STOP+ask · this phase's read of `call_logs` is infrastructure monitoring (same category as Phase 1's canary), not an application dispatch path, so ADR-013 does not apply to it · never widen OmniRoute's network exposure · this phase must never gate, arm, or influence hub-failover logic (untouched by everything here) · mesh-only transport for anything network-exposed — not applicable here since nothing new is exposed.

## 12. Deferred to later phases (explicit)

- **Unify with the groq/cerebras/cohere/qwen3_cloud budget system** into one Contractors/"DS9" view — the stated end goal, not this phase.
- **Consume the routing hint**: have combo-selection or a dispatch guard actually act on `get_quota_status()` (e.g., prefer a less-throttled upstream) — the interface is ready, nothing calls it yet.
- **Contractors tab → "DS9" rename**, once the tab covers more than OmniRoute.
- **Phase 3/4** (Codex CLI reliability, OpenRouter, 9Router reassessment, DeepSeek-V4-Flash) — unchanged from Phase 1's §11.
