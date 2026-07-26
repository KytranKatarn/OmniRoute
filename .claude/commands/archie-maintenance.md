# A.R.C.H.I.E. Maintenance Window

Open a maintenance window so a **deliberate** shutdown never looks like a hub failure.

## Why this exists

On 2026-07-25 a *planned* power-down triggered a real DR failover. The watchdog cannot tell
"Kytran turned the hub off on purpose" from "the hub died" — both look like an unreachable
hub. That failover then blanket-flipped all 21 Beacon upstreams and took ~20 healthy
hub-only services down with it.

A window tells the watchdog the outage is intentional, **before** it happens.

---

## Commands

All run via the platform container. `ARGUMENTS` selects the action.

### `status` — what is happening right now (default, always safe)

```bash
docker exec archie_platform python3 -c "
import sys; sys.path.insert(0,'/app')
from services.maintenance_window_service import window_status
import json; print(json.dumps(window_status(), indent=2, default=str))"
```

### `open <minutes> "<reason>"` — ad-hoc window, starting NOW

Use before an unplanned-but-deliberate restart. **`start_window` runs a REAL watchdog cycle
and refuses to report SAFE unless the watchdog actually reports snoozed/disabled** — it will
not take your word for it.

```bash
docker exec archie_platform python3 -c "
import sys; sys.path.insert(0,'/app')
from services.maintenance_window_service import start_window
import json; print(json.dumps(start_window(minutes=45, reason='hub RAM upgrade', actor='kytran'), indent=2, default=str))"
```

⚠️ Read the returned `posture_warnings`. They tell you what DR is *unable* to cover during
the window (a stale replica, a disarmed watchdog). An empty list is the only clean result.

### `close` — end the window and re-arm DR

```bash
docker exec archie_platform python3 -c "
import sys; sys.path.insert(0,'/app')
from services.maintenance_window_service import end_window
import json; print(json.dumps(end_window(actor='kytran'), indent=2, default=str))"
```

An open window **suppresses the DR watchdog**. If you forget, the 5-minute
`maintenance_window_driver` job closes it once its duration elapses — but do not rely on
that. A window left open is DR left disarmed while you believe it is armed.

---

## Planned windows (the Repair Bay batching flow)

Repair Bay appends fixes to the next window instead of deploying ad-hoc, so several
changes ship together and you are told the list **beforehand**.

```bash
# 1. schedule (or reuse the next one within 24h)
docker exec archie_platform python3 -c "
import sys; sys.path.insert(0,'/app')
from services.maintenance_schedule_service import next_window
print(next_window(create_if_missing=True))"

# 2. Repair Bay adds items ->  add_item(window_id, title=..., kind=..., ref=...)
# 3. see the manifest before it runs
docker exec archie_platform python3 -c "
import sys; sys.path.insert(0,'/app')
from services.maintenance_schedule_service import get_manifest, list_windows
for w in list_windows(limit=5):
    print(w['id'], w['status'], w['scheduled_start'], '->', [i['title'] for i in get_manifest(w['id'])])"
```

**You are told before it opens.** The `maintenance_window_driver` job (every 5 min):

1. **closes** expired windows first — releasing DR suppression takes priority over everything
2. **announces** windows starting within `MAINTENANCE_ANNOUNCE_LEAD_MIN` (default 60) with the fix list
3. **opens** announced windows whose start has arrived

It **never** opens an un-announced window. A window that reaches its start time without
having been announced gets announced and waits for the next tick — one tick late beats a
silent production change. Only a human passing `force_unannounced=True` can skip that.

---

## Cheat sheet

| Situation | Do this |
|---|---|
| About to reboot the hub | `open 30 "reason"`, verify `posture_warnings` is empty, then reboot |
| Finished early | `close` — do not wait for the timer |
| "Did DR fire because of me?" | `status`, then check `.snooze_until` / `.failed_over` on boston-2 |
| Batch several fixes | `next_window(create_if_missing=True)` and let Repair Bay append |

**Never** run `failover.sh` to "test" this — it flips production DNS. Interactive runs
require `--force` / `DR_CONFIRM=FAILOVER-NOW` for exactly that reason.
