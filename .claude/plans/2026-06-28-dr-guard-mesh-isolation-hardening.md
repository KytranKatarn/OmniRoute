# DR Guard Hardening — distinguish "hub mesh-isolated" from "hub dead"

**Date:** 2026-06-28 (cont-102) · **Branch:** `fix/dr-guard-mesh-isolation`
**Trigger:** cont-101 false DR failover (KB mistake #276161 / #276817). The hub dropped off the
Headscale mesh (NPM-decommission collateral) while its DB + platform were ALIVE; the watchdog
reached quorum and auto-promoted a (then-stale) replica — the #272172 data-loss pattern.

## Root cause (confirmed by reading the code)

`scripts/dr/watchdog/dr_watchdog.sh` has a genuine multi-vantage quorum (boston-2 + 3 outposts)
**but every vantage runs `probe_hub.sh` against the SAME hub mesh IP `100.64.0.4`** (TCP :5432 +
HTTP :3000). The mesh is a **shared single point of failure**: when the hub's tailscaled client
drops, all four probers see "down" at once. The quorum defeats *one node's blip*; it cannot defeat
*the hub leaving the mesh while alive*. `failover.sh`'s split-brain guard (`100.64.0.4:5432`) is
blind to the same thing (mesh IP), and it promotes WITHOUT checking the replica is current.

There is **no remote network path to the hub that bypasses the mesh** (Beacon/public proxy to the
hub *over* the mesh too). So no pull-probe can disambiguate. The fix must use a signal the hub
PUSHES out over a mesh-independent channel.

## Fix — two independent layers (owner-approved 2026-06-28)

### Layer 1 — Heartbeat veto (corrects the false TRIGGER)
Even mesh-isolated, the hub keeps **outbound public internet** (verified: hub → `root@2.25.133.122`
public SSH works). So:

- **Producer (hub):** new `scripts/dr/hub_heartbeat.sh`, cron every 60s. Checks LOCAL health
  (`pg_isready` on archie_database + HTTP 200 on `127.0.0.1:3000/login`); only if healthy, SSHes
  boston-2's **PUBLIC IP** (`2.25.133.122`, NOT mesh `100.64.0.10`) and writes
  `/opt/archie-dr/.hub_heartbeat` = `ts=<epoch> db=ok http=<code>`.
- **Consumer (watchdog):** new pure-ish helper `hub_heartbeat_fresh()` (reads the file; true if
  `now-ts <= HEARTBEAT_MAX_AGE` (default 300s) AND `db=ok`). The veto is applied **at the FIRE
  decision**, not at arm time — so the human still gets the "hub down" alert + buttons, but the
  **automatic** promotion is SUPPRESSED while the hub is provably alive ("mesh-isolated, not dead —
  reply /dr_proceed to override"). A genuinely dead hub stops posting → heartbeat ages past 300s
  well before the ~8-min fire → failover proceeds normally.
- **Override:** `/dr_proceed` runs `failover.sh --force` (human asserts hub-dead), bypassing the veto.

### Layer 2 — Replica-freshness guard (makes the CONSEQUENCE safe)
`failover.sh` currently promotes with no freshness check. Add a pre-promote guard:
refuse unless the local replica is a **healthy streaming standby** —
`pg_is_in_recovery()=t` AND WAL receiver active (`pg_stat_wal_receiver` row / `pg_last_wal_receive_lsn()`
advancing) AND `now() - pg_last_xact_replay_timestamp() <= REPLICA_MAX_LAG` (default 600s).
Else **abort + Telegram alert** (never promote stale data). Respects `--force`.
`failover.sh` also gains the same heartbeat veto as a backstop for manual/cron invocations
(respects `--force`, like the existing split-brain guard).

## Files

| File | Change |
|---|---|
| `scripts/dr/hub_heartbeat.sh` | NEW — hub-side producer (local-health-gated, SSH to boston-2 public). |
| `scripts/dr/watchdog/dr_watchdog.sh` | `hub_heartbeat_fresh()` helper + veto at fire-time (step 7) + arm-time log + `do_failover [force]`. |
| `scripts/dr/failover.sh` | heartbeat veto (respects --force) + replica-freshness guard before promote (respects --force). |
| `scripts/dr/watchdog/test_quorum.sh` | unit tests for `hub_heartbeat_fresh` (fresh / stale / missing / db!=ok). |
| `scripts/dr/watchdog/README.md`, `scripts/dr/DR_RUNBOOK.md` | document the heartbeat + the new tunables. |
| hub crontab | `* * * * * /opt/archie-dr/hub_heartbeat.sh` (installed at deploy). |

## Tunables (env, defaults)
`HEARTBEAT_MAX_AGE=300` · `HEARTBEAT_FILE=/opt/archie-dr/.hub_heartbeat` · `DR_NODE_PUBLIC=2.25.133.122`
· `REPLICA_MAX_LAG=600`.

## Known residual limitation (documented, not solved)
If the hub's mesh AND its public→boston-2 SSH path BOTH fail simultaneously while the hub's DB is
alive, the heartbeat goes stale and the watchdog can still auto-failover. This is a much narrower
failure than the mesh-only outage we hit, and Layer 2 still prevents promoting a *stale* replica.
Strictly better than today; the gap is the human-abort window + the freshness guard.

## Test plan (no prod impact)
1. `bash scripts/dr/watchdog/test_quorum.sh` (pure helpers incl. heartbeat freshness) on the hub.
2. `bash -n` syntax check all three scripts.
3. On boston-2 (DISABLED, DRY_RUN): write a FRESH `.hub_heartbeat` → drive a dead-hub drill →
   confirm the watchdog ARMS but the fire is VETOED ("hub alive via heartbeat"). Then write a STALE
   heartbeat → confirm DRY-RUN "would fire". Then remove the file → confirm "would fire" (no veto, no file).
4. failover.sh freshness guard: dry-run path that asserts it aborts when the replica is non-streaming.
5. Deploy producer cron on hub; confirm `.hub_heartbeat` lands fresh on boston-2 within 60s.
6. Clear stale flags → re-arm watchdog → confirm a clean guarding cycle in the journal.

## Deploy order (safety)
Watchdog is DISARMED now (`.watchdog_disabled` on boston-2). Build+test → scp scripts to boston-2 →
install hub cron → verify heartbeat flowing → clear stale DR flags (.failed_over/.awaiting_rebuild/
watchdog_state; replica is streaming, lag 0) → `rm .watchdog_disabled` → watch one clean cycle.
