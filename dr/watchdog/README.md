# DR Phase 7 — Quorum Auto-Promote Watchdog (#3685)

Closes the last manual gap in DR: something off-hub notices the hub is down and,
after a **human-abortable delay**, runs `failover.sh`. Detection is **multi-vantage
(quorum)** so one node's network blip can't trigger a false failover.

Spec: `.claude/plans/dr-phase7-quorum-watchdog.md` · Builds on Part A (`tg_notify`, PR #1384).

---

## ⚠️ FOOT-GUN — planned hub maintenance

**Before ANY intentional hub downtime (reboot, upgrade, network work), disarm the watchdog:**

```bash
ssh root@100.64.0.10 'touch /opt/archie-dr/.watchdog_disabled'
```

Re-arm afterwards:

```bash
ssh root@100.64.0.10 'rm -f /opt/archie-dr/.watchdog_disabled'
```

If you skip this, the watchdog will see the hub down, reach quorum, and (5 min later,
unless you reply `/dr_abort` on Telegram) auto-failover to boston-2.

---

## How it works

- **Coordinator** runs on **boston-2** (`100.64.0.10`) — the only node that can promote
  itself. One cycle per run, driven by `dr-watchdog.timer` (60s). State persists in
  `/opt/archie-dr/watchdog_state`.
- **Vantages:** boston-2 + 3 global outposts (`root@100.64.0.5 / .7 / .8`, DR key
  `/opt/archie-dr/.ssh/id_ed25519`).
- **Probe target:** hub mesh `100.64.0.4` — TCP `:5432` **and** HTTP `:3000/login`. Both
  must fail to call the hub "down from here" (`probe_hub.sh`).
- **Quorum rule:** declare DOWN only when **boston-2 can't reach the hub AND ≥2 of the 3
  outposts also can't**. An outpost we can't SSH does **not** count as a down-vote (guards
  boston-2's own mesh blip).
- **Staged fire:** `K=3` consecutive quorum-down cycles → **arm** (Telegram warning) →
  `ABORT_WINDOW=300s` → re-confirm quorum + check for `/dr_abort` → run `failover.sh`.

### Cycle (steps in `dr_watchdog.sh`)
1. `.watchdog_disabled` present → exit.
2. `.failed_over` present → exit (one-shot).
3. boston-2 probes hub. Reachable → reset counters, exit.
4. Hub down from boston-2 → SSH each outpost, run `probe_hub.sh`, tally.
5. `<QUORUM` outposts down → boston-2 blip, reset, exit. Else `consec_down++`.
6. `consec_down ≥ K` and not armed → record `armed_at`, Telegram "auto-failover in 5 min".
7. Armed and `now > armed_at + ABORT_WINDOW` → re-confirm quorum (else disarm "recovered");
   poll Telegram `getUpdates` for `/dr_abort` (else); → run `failover.sh`, write `.failed_over`.

---

## Operator actions (Telegram buttons or commands)

The **arm** alert carries three inline buttons. They are sent AND read by the boston-2
watchdog (`sendMessage` + `getUpdates`), so they work during a real hub outage — the hub's
own bot is down and plays no part. Each is also a text command.

| Button | Command | Effect |
|---|---|---|
| ✅ **Proceed now** | `/dr_proceed` | Fire `failover.sh` immediately, skipping the rest of the abort window. |
| 🛑 **Cancel DRP** | `/dr_abort` (`/dr_cancel`, `abort`, `cancel`) | **Snooze `SNOOZE_CANCEL_SECONDS` (default 60 min)**, then auto-resume scanning. NOT a permanent disable. |
| ⏸ **Standby** | `/dr_standby` (`standby`) | **Snooze `SNOOZE_STANDBY_SECONDS` (default 15 min)**, then re-check + re-alert if the hub is still down. |

While armed, actions are polled every **`ARMED_POLL_INTERVAL` (default 5s)** in one
long invocation, so a tap is acknowledged (toast **and** reply message) within seconds.
If no action arrives, the watchdog fires automatically once the abort window elapses.
A hub recovery during the window auto-cancels (you get a "hub recovered" message).

**Snooze vs disable:** the Cancel/Standby buttons write a self-expiring `.snooze_until`
file — they always come back. The only *indefinite* stop is the manual
`.watchdog_disabled` kill switch (for planned maintenance), which a button never sets.

> **Drill caveat:** Telegram allows only one `getUpdates` consumer per bot. In a real outage
> the hub bot is down, so boston-2 reads taps cleanly. During a drill with the hub UP, the
> hub's bot may swallow the tap first — to test buttons cleanly, briefly stop the hub's
> Telegram bot.

---

## Files

| File | Where | In git? |
|---|---|---|
| `dr_watchdog.sh` | coordinator on boston-2 | ✅ |
| `probe_hub.sh` | streamed to each outpost over SSH | ✅ |
| `dr-watchdog.service` / `.timer` | `/etc/systemd/system/` on boston-2 | ✅ |
| `../tg_notify.sh` | shared Telegram helper (sourced by watchdog + failover.sh) | ✅ |
| `/opt/archie-dr/watchdog_state` | `consec_down`, `armed_at` | ❌ runtime |
| `/opt/archie-dr/.watchdog_disabled` | kill switch | ❌ runtime |
| `/opt/archie-dr/.failed_over` | one-shot marker | ❌ runtime |
| `/opt/archie-dr/.telegram_env` | bot token + chat id (chmod 600) | ❌ secret |

## Tunables (env, with defaults)

`K=3` · `QUORUM=2` · `ABORT_WINDOW=300` · `SSH_TIMEOUT=15` · `HUB_MESH=100.64.0.4` ·
`DR_MESH=100.64.0.10` · `FLEET_KEY=/opt/archie-dr/.ssh/id_ed25519` · `DRY_RUN=0` ·
`ARMED_POLL_INTERVAL=5` · `SNOOZE_STANDBY_SECONDS=900` · `SNOOZE_CANCEL_SECONDS=3600`.

---

## Deploy to boston-2 (DISABLED-first)

```bash
# From hub, copy the watchdog + shared helper (DR key/secret already on boston-2):
DR=root@100.64.0.10:/opt/archie-dr
scp dr/tg_notify.sh                 $DR/tg_notify.sh
scp -r dr/watchdog                  $DR/watchdog
scp dr/failover.sh                  $DR/failover.sh           # refactored to source tg_notify.sh
ssh root@100.64.0.10 'chmod +x /opt/archie-dr/tg_notify.sh /opt/archie-dr/failover.sh /opt/archie-dr/watchdog/*.sh'

# Install the timer but DO NOT enable yet:
ssh root@100.64.0.10 'cp /opt/archie-dr/watchdog/dr-watchdog.{service,timer} /etc/systemd/system/ && systemctl daemon-reload'
```

## Dry-run drill (hub never touched)

```bash
# 1. Syntax + unit (run on hub before deploy):
bash dr/watchdog/test_quorum.sh

# 2. On boston-2 — one manual cycle pointed at a DEAD hub IP so quorum trips,
#    in DRY_RUN so failover.sh is only echoed. Run it K times to arm, then once
#    more after 5 min to hit the "would fire" path:
ssh root@100.64.0.10
  cd /opt/archie-dr
  for i in 1 2 3; do DRY_RUN=1 HUB_MESH=192.0.2.1 K=3 ABORT_WINDOW=1 ./watchdog/dr_watchdog.sh; sleep 2; done
  sleep 2
  DRY_RUN=1 HUB_MESH=192.0.2.1 K=3 ABORT_WINDOW=1 ./watchdog/dr_watchdog.sh   # → "DRY-RUN would fire"
  rm -f watchdog_state                                                        # reset drill state
```
`192.0.2.1` is TEST-NET-1 (RFC 5737) — guaranteed unreachable, so boston-2's own probe fails
and the outposts (probing the real `100.64.0.4`) report UP → **no real quorum** → it will NOT
arm unless you also force the outpost view. To exercise the full arm→fire path safely, set
`OUTPOSTS=()` is not allowed (needs quorum); instead keep `HUB_MESH=192.0.2.1` so the outposts
ALSO probe the dead IP — they will, because the probe inherits `HUB_MESH` over SSH. That trips a
real (but harmless, dry-run) quorum. Confirm the staged Telegram alerts arrive.

### Abort test
Arm as above (dry-run), then within the window reply `/dr_abort` on Telegram and run one more
cycle — it should log "operator /dr_abort received", write `.watchdog_disabled`, and stand down.
Clean up: `rm -f /opt/archie-dr/.watchdog_disabled /opt/archie-dr/watchdog_state`.

## Enable (only after the drill passes)

```bash
ssh root@100.64.0.10 'systemctl enable --now dr-watchdog.timer'
ssh root@100.64.0.10 'systemctl list-timers dr-watchdog.timer'
journalctl -u dr-watchdog.service -f      # watch live cycles
```

## Failback reset (after the hub returns and you fail back)

```bash
ssh root@100.64.0.10 'rm -f /opt/archie-dr/.failed_over /opt/archie-dr/watchdog_state /opt/archie-dr/.watchdog_disabled'
```
The `.failed_over` one-shot stays until you clear it, so the watchdog won't re-fire while you
re-clone the replica. Clear it once boston-2 is streaming again and the timer can resume guarding.

## cron fallback (if not using systemd)

```cron
* * * * * /opt/archie-dr/watchdog/dr_watchdog.sh >> /var/log/dr_watchdog.log 2>&1
```
