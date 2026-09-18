# OmniRoute Reliability Watchdog ("Deep Space Nine" — Phase 1)

**Date:** 2026-09-18 · **Owner decision:** reliability first; quota-awareness and capability-expansion (9Router reassessment, OpenRouter, a local DeepSeek-V4-Flash contract agent) are explicit later phases, not this spec.
**Prior art this builds on:** `docs/superpowers/specs/2026-09-09-phase3-omniroute-contractor-design.md` (registered OmniRoute as a `contractor_providers` row for the Agent Academy A/B lane + a gated coding lane) and `scripts/dr/watchdog/dr_watchdog.sh` / `hub_heartbeat.sh` (the DR quorum watchdog and its hub→Citadel heartbeat push, both reused here rather than re-invented).

## 1. Incident this responds to

2026-09-17, ~16:54 UTC (3 minutes after a hub reboot): OmniRoute's stored OpenCode-provider credential broke (`OPENCODE | refresh failed`, `AutoRefreshDaemon … checking 0 credentials` on restart). Every OpenCode CLI request from then on failed after a ~10-minute stall (a combo fallback chain tried ~8 models, hit a 401 on one, which tripped a provider-wide circuit breaker that skipped the rest without trying them, then the client hit `Combo loop safety timeout (600000ms)` and surfaced as "Provider Overloaded"). **Nothing detected this for 22+ hours** — Docker's own health check on the `omniroute` container reported `healthy` the entire time, because it only verifies the process is running, not that it can serve a real request. The break was only found by manually reading container logs during an unrelated investigation.

## 2. Goal & non-goals

**Goal.** Detect this exact failure class — and its siblings (a provider-wide auth break, a fully dead container) — within minutes, and alert Kytran through a path that does not depend on OmniRoute, the hub's own Telegram integration, or a human happening to read logs. Scoped to protecting **OpenCode CLI's routing path only**.

**Non-goals (explicit):**
- **No Codex CLI integration.** Codex CLI's own reliability is a separate, later problem (owner decision, 2026-09-18). Note for that later work: `docker-compose.yml`'s `omniroute` service comment says its loopback port publish exists so "the host codex CLI needs a stable endpoint" — worth reconciling against `codex-agent.md`'s Phase-A (no API key, no custom endpoint) description before that phase starts; not resolved here.
- **No quota/rate-limit tracking.** Real-time proximity-to-cap awareness across providers is phase 2. 9Router's built-in live quota tracking is a strong candidate to revisit then.
- **No routing-engine swap.** OmniRoute stays the engine. 9Router's actual differentiator (fronting an already-paid subscription's OAuth session) doesn't fit our free-tier-only use case as well as OmniRoute's "one key, one pool of free models" design, and its benchmarked speed advantage belongs to `9router-go`, an unofficial third-party reimplementation, not mainline 9Router.
- **No DeepSeek-V4-Flash local agent.** Feasible as a `worker_type='contract'` roster agent later (mirrors how Codex CLI is already integrated), deferred.
- **Never touches hub-failover logic.** This is additive to `dr_watchdog.sh`'s existing cycle. A broken OmniRoute must never arm or influence the DR quorum/failover decision — that logic is untouched.
- **No new network exposure for OmniRoute.** See §3 for why the original mesh-bind idea was dropped.

## 3. Why this isn't a mesh-reachable probe (course correction during design)

The first draft of this design had Citadel probe OmniRoute directly over a new mesh-IP bind (`100.64.0.4:20128`, mirroring `archie_database`'s dual LAN+mesh bind). That's wrong for this container specifically: `docker-compose.yml`'s `omniroute` service carries a live, tracked, **unpatched CRITICAL Next.js CVE** (16.3.1; no fixed OmniRoute release exists — 3.8.50 is latest, `main`/`next` are unstable dev branches) whose current risk assessment rests partly on the port being loopback-only (added 2026-09-14, published as `127.0.0.1:20128:20128` for the host's own Codex CLI). Publishing it to the mesh would hand every enrolled fleet node a reachable path to a container with a known, unpatched RCE-class CVE — a real security regression, just to make a health check simpler.

**Resolution: push, don't pull.** `hub_heartbeat.sh` already does exactly this shape of thing for Postgres liveness — checks something hub-local, pushes a status line to Citadel over SSH (`root@2.25.133.122`, key `~/.ssh/id_ed25519`), completely independent of the mesh. This design adds a sibling script that does the same for OmniRoute: probe over `127.0.0.1:20128` (the same loopback access already used for every manual check this session), push the result to Citadel, and let Citadel's side — folded into `dr_watchdog.sh`'s existing 60s cycle rather than a new systemd timer — age the heartbeat out and alert on staleness or a bad reading. Same detection value (off-hub, doesn't depend on OmniRoute or a human), zero new exposure, zero new SSH credential (reuses the hub's existing outbound key and Citadel's existing inbound trust), and one fewer new moving part than the original draft.

## 4. Architecture

**On the hub** (new cron, e.g. every 2 minutes): `scripts/watchdog/omniroute_probe_heartbeat.sh` runs a 3-tier check against `127.0.0.1:20128`:

1. **Liveness** — `GET /api/health` (no auth). Non-200/unreachable → OmniRoute itself is down.
2. **Provider state** — `GET /api/status` (or `/api/providers`), authenticated with `OMNIROUTE_API_KEY` (already in root `.env`, 0600, uncommitted — same key `_call_openai_compatible` already uses per the Phase 3 spec). Parses the `opencode` provider's credential count / circuit-breaker flag directly — the exact signal that sat unread in logs for 22 hours.
3. **Deep canary** (throttled to roughly every 15th cycle, ~30 min, tracked in a local hub-side state file) — one minimal real completion through OmniRoute's actual OpenCode combo path. Catches the gap between tiers 1-2 and reality: tier 2 can report "credentials present" while the provider still silently rejects requests, which is part of why this went undetected before.

The script then pushes one status line to Citadel via the same SSH mechanism `hub_heartbeat.sh` uses, to a new file `/opt/archie-dr/.omniroute_heartbeat` (co-located with `.hub_heartbeat` since it rides the same push channel — but tracked and read independently; it is not part of the DR failover decision).

**On Citadel**, `dr_watchdog.sh`'s existing per-cycle run gains one additional, self-contained step: read `.omniroute_heartbeat`, and if it's stale (no push in > ~2 probe intervals — catches "the hub-side cron itself stopped") or its content shows a tier-2/3 failure, call the **same Telegram alert function the script already has** (direct `api.telegram.org` call via `$DR/.telegram_env`, independent of the hub — confirmed live in `dr_watchdog.sh`). This step never touches `consec_down`, `armed_at`, `.failed_over`, or any other failover state — it is purely observational, appended after the existing quorum logic, not interleaved with it.

Consecutive-failure counting and the kill switch live in a new, separate directory — `/opt/archie-reliability/` on Citadel — deliberately not `/opt/archie-dr/`, so this watchdog's bookkeeping can never be mistaken for DR tooling (or vice versa) the way today's stray-worktree cleanup had to untangle two similarly-named but unrelated things.

## 5. Components

| Component | Location | Purpose |
|---|---|---|
| `omniroute_probe_heartbeat.sh` | `scripts/watchdog/`, deployed to the hub, cron every 2 min | 3-tier probe + push |
| `probe_omniroute.sh` | `scripts/watchdog/` | the probe logic alone, split out for independent testing (mirrors `probe_hub.sh`'s split from `dr_watchdog.sh`) — emits a `PROBE_RESULT=` stdout sentinel per tier, never relies on a bare exit code |
| `.omniroute_heartbeat` | `/opt/archie-dr/` on Citadel (pushed file) | `ts=… tier1=ok/fail tier2=ok/fail/skipped tier3=ok/fail/skipped detail=…` |
| `.last_canary` | hub-local (e.g. `/opt/archie_omniroute_watchdog/`) | throttles the deep canary to ~every 15th cycle |
| watchdog state + kill switch | `/opt/archie-reliability/` on Citadel | consecutive-failure count, last-known-good timestamp, `.omniroute_watchdog_disabled` |
| alerting | reuses `dr_watchdog.sh`'s existing Telegram function | no new channel |
| the one code change | `dr_watchdog.sh` gains one additive step at the end of its cycle | reads the heartbeat, alerts on stale/bad, touches nothing else |

## 6. Data flow (hub side, every 2 minutes)

1. Cron fires `omniroute_probe_heartbeat.sh`.
2. Tier 1 (`/api/health`) fails → skip tiers 2-3, push `tier1=fail`.
3. Tier 1 OK → tier 2 (`/api/status`, authed) — parse for the `opencode` provider's credential/breaker state.
4. Every ~15th cycle only: tier 3 deep canary (one real completion through the OpenCode combo path).
5. Push one line to `/opt/archie-dr/.omniroute_heartbeat` on Citadel over the existing SSH channel, always — including on full success, so staleness itself is meaningful.

**Citadel side (folded into the existing `dr_watchdog.sh` 60s cycle):**

6. Read `.omniroute_heartbeat`. Stale (no push within ~2x the hub's probe interval) or any tier reporting `fail` → increment the consecutive-failure counter in `/opt/archie-reliability/`.
7. At **K consecutive failures** (same "ride out transient blips" logic as the DR quorum, K configurable, default matching DR's 3) → send **one** Telegram alert naming which tier failed and the specific error, then throttle repeats to hourly reminders rather than every cycle.
8. A subsequent good reading after a prior failure state → one "recovered" alert, counter reset.

## 7. Error handling & the false-positive guard

- **Tier 1 fails, tiers 2-3 skipped** → alert says "OmniRoute container itself is down." Different remediation (restart container) than a provider break.
- **Tier 1 OK, tier 2/3 fail** → alert says "OmniRoute is up, but the `opencode` provider is broken" — today's actual failure shape.
- **False-positive guard, load-bearing**: a single free-tier *model* failing inside the fallback combo (quota-exhausted 402, upstream-unavailable 400 — both observed live in today's logs for unrelated models) is normal, expected behavior for a free-tier aggregator and must **never** alert on its own. Only a provider-wide breaker trip, a zero-credential reading, or a full canary failure counts.
- **Heartbeat push itself fails** (SSH hiccup, not an OmniRoute problem) → Citadel sees staleness, not a false "down" reading with wrong detail — the alert for pure staleness should say so distinctly from a reported tier failure, so remediation isn't misdirected at OmniRoute when the actual fault is the push channel.
- **Citadel itself is down** → this check can't run at all. Same accepted blind spot the DR watchdog already has; not worth a second vantage just for this.
- **Kill switch**: `.omniroute_watchdog_disabled` in `/opt/archie-reliability/`, checked before alerting — set before any planned OmniRoute restart or re-auth.

## 8. Testing

- `test_probe_omniroute.sh` (same style as the existing `dr/watchdog/test_probe_sentinel.sh` / `test_quorum.sh`): stub each tier's HTTP response; prove the false-positive guard actually holds (a lone 402/400 on one fallback model must NOT count as failure; a zero-credential or breaker-tripped reading MUST).
- `DRY_RUN=1` on both the hub probe and the Citadel-side check (matching `dr_watchdog.sh`'s existing convention) — runs the full cycle, logs what it would push/alert, touches neither the real Telegram API nor a real completion.
- A real drill: disconnect the OpenCode provider in OmniRoute's own Settings UI (the state we are literally in right now), confirm the heartbeat reflects it within one push cycle and the Citadel-side alert fires within K cycles, then reconnect and confirm the recovery alert. Per this repo's testing standard, prove the test fails against the current (unmonitored) state before the fix ships, not just that it looks plausible after.

## 9. Rollout

1. Ship `probe_omniroute.sh` + `omniroute_probe_heartbeat.sh`, deploy to the hub, add the cron line. Runs standalone first (logs locally) before wiring the push, so tier-1/2/3 logic is proven against live OmniRoute before anything reaches Citadel.
2. Wire the SSH push to `/opt/archie-dr/.omniroute_heartbeat`, reusing the existing key/target — no new credential provisioning.
3. Add the one additive step to `dr_watchdog.sh`'s cycle (read heartbeat, alert on stale/bad) — reviewed carefully to confirm it cannot touch `consec_down`/`armed_at`/`.failed_over`.
4. Create `/opt/archie-reliability/` on Citadel for this watchdog's own state.
5. Live proof: the drill in §8, using the actual currently-broken OpenCode credential as the first real test case.
6. Re-authenticate OmniRoute's OpenCode connection (separate, manual, owner-only step — Settings → Providers, reachable today only via an SSH tunnel to the hub's loopback) and confirm the recovery alert fires.

## 10. Standing constraints (carried)

REMOTE 192.168.1.200 · branch+PR, never main · never commit secrets · 2 failures→STOP+ask · all platform inference via the DHQ dispatcher (ADR-013) — **not applicable to this watchdog's canary**, which is infrastructure monitoring hitting OmniRoute directly, the same category as `probe_hub.sh`'s direct TCP/HTTP checks, not an application dispatch path · never widen OmniRoute's network exposure without re-justifying against its tracked CVE · this watchdog must never gate, arm, or influence hub-failover logic · mesh-only transport for anything that IS network-exposed, never a public hostname.

## 11. Deferred to later phases (explicitly out of scope here)

- **Phase 2 — quota awareness**: real-time proximity-to-cap tracking across free-tier providers (OpenRouter's documented 50/1,000-per-day + 20/min limits are a concrete, ready-to-use dataset). Revisit 9Router's built-in quota tracking here, once phase 1 has given us real operational data on whether OmniRoute's monolithic-architecture fragility (flagged upstream in its own issue #14073) recurs.
- **Phase 3 — Codex CLI reliability**, once its actual relationship to OmniRoute's loopback port is reconciled (see §2).
- **Phase 4 — capability expansion**: OpenRouter as an additional OmniRoute upstream; a self-hosted DeepSeek-V4-Flash box wired in as a `worker_type='contract'` roster agent (same integration shape as Codex CLI), gated on having spare dedicated hardware (96GB+ RAM, not shared with the hub) and tracking the required community `llama.cpp` fork until DeepSeek V4 architecture support lands upstream.
