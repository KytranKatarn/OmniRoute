# `/archie-maintenance` — planned maintenance windows for the hub

**Status:** design, not built · **Owner-requested** 2026-07-25 after the DR incident
**Related:** #5214 (selective Beacon flip) · #5215 (bounded approval gate) · ADR-009 (#955) · incident KB #283936

---

## Why this exists

On 2026-07-25 the hub was powered down for a planned PSU + GPU install. Ten minutes
later `dr-watchdog.timer` (every 60 s) could not tell planned downtime from a hub
failure, promoted the boston-2 replica to read-write, and blanket-flipped **all 21**
Beacon upstreams to DR — taking ~20 healthy hub-only services offline, including KSO,
the media hub, KBS, and the Headscale control-plane hostname.

The safety that would have prevented it **already existed**. `dr_watchdog.sh:22` says:

> `.watchdog_disabled` kill switch (planned-maintenance foot-gun — **SET THIS before
> any intentional hub downtime**)

Nobody set it, because it is an undocumented dotfile on a remote host with no command,
no discovery path, and no reminder. **This spec is not about building a safety — it is
about making the existing one impossible to forget.**

That framing matters for scoping: almost everything below is orchestration of
primitives that already ship. Resist the urge to build new machinery.

---

## Hard design constraints

1. **The control point cannot be the hub.** The hub is what goes down. State that
   governs the watchdog must live where the watchdog can read it *without* the hub —
   i.e. on boston-2 (`/opt/archie-dr/`) and/or Beacon. A `platform_settings` row is
   **not** sufficient on its own; it dies with the DB.
2. **Prefer time-boxed suppression over indefinite.** `.snooze_until` auto-expires;
   `.watchdog_disabled` does not. A forgotten kill switch silently disarms DR forever —
   a strictly worse failure than the one it prevents, because it is invisible.
   Default to a snooze with an explicit duration; require an extra confirmation for the
   indefinite flag.
3. **Move only what can actually move.** Per ADR-009, flipping a hostname to a host that
   cannot serve it is worse than leaving it pointed at a host that is merely down — the
   second is honest, the first sends operators to debug the wrong system. Blocked on
   #5214's DR-capable service map.
4. **Every step must be individually reversible and independently verifiable.** No
   all-or-nothing script. `status` must be able to report a half-applied window.
5. **Fail toward "do not power off".** If any step cannot be confirmed, `start` reports
   NOT SAFE rather than proceeding. The cost of a delayed shutdown is minutes; the cost
   of an unsuppressed watchdog is tonight.

---

## Existing primitives to reuse (do NOT rebuild)

| Need | Already exists |
|---|---|
| Suppress auto-failover, indefinite | `/opt/archie-dr/.watchdog_disabled` (`dr_watchdog.sh:42`, checked L238 top-of-cycle **and** L363 mid-window) |
| Suppress auto-failover, auto-expiring | `/opt/archie-dr/.snooze_until` — `set_snooze()` L127; `SNOOZE_STANDBY_SECONDS=900`, `SNOOZE_CANCEL_SECONDS=3600` |
| Double-fire guard | `/opt/archie-dr/.failed_over` one-shot marker |
| RED ALERT banner | `ARCHIE_DR_MODE` → `is_dr_active()` → `dr_mode` on `/api/alerts/unified` → `data-alert-state="dr"` + `.lcars-divert-tag.is-dr` (PRs #2463/#2465) |
| Header state arbitration | `_resolveElbowState()` — precedence `dr > critical > diverted > warning > normal`; adding a `maintenance` state is a one-line insert |
| Edge traffic flip | Beacon Caddy upstream rewrite (`failover.sh` 4c / `failback.sh` ~L139) — **must** become selective per #5214 |
| Pause producers | `services/work_control_service.py` (`set_enabled`/`list_controls`) |
| Announce | `services/telegram_service.py` |
| DR health readout | `services/dr_posture_monitor.check_dr_posture()` |

---

## Command surface

```
/archie-maintenance start  [--minutes N] [--reason "..."] [--indefinite]
/archie-maintenance status
/archie-maintenance end
```

### `start`
1. **Pre-flight** — `check_dr_posture()`; report replica role, replay lag, retained WAL,
   and whether `.failed_over` is stale. **Refuse to proceed silently on a bad posture** —
   print it and require `--force`.
2. **Suppress the watchdog** — write `.snooze_until` = now + N minutes (default 60).
   With `--indefinite`, write `.watchdog_disabled` containing reason + ISO timestamp +
   who set it. Verify by running one watchdog cycle and asserting the log says
   `disabled` / `snoozed`. **Verification is mandatory** — writing a file is not proof it
   is honored.
3. **Announce** — Telegram: reason, expected duration, snooze expiry.
4. **Paint the banner** — set a `maintenance` header state (distinct label/colour from
   `dr`; RED ALERT means "the site is gone", maintenance means "this is deliberate").
5. **Drain** — pause producer jobs via `work_control_service`; wait for in-flight
   `dispatch_pending_queue` items to settle, with a timeout and an honest report of what
   was still running.
6. **Move movable traffic** — only services in #5214's DR-capable map.
7. **Report SAFE / NOT SAFE TO POWER OFF**, itemised.

### `status`
Reads live state and prints the truth, including a **half-applied** window: snooze
remaining, `.watchdog_disabled` present + its note, `.failed_over` present, Beacon
upstream split (`N on hub / M on DR`), paused job count, DR posture.

### `end`
Reverse in order: restore Beacon → clear banner → resume jobs → clear `.snooze_until` /
`.watchdog_disabled` → **clear `.failed_over` if a failover actually fired** → verify one
watchdog cycle returns to scanning → announce. Re-run `check_dr_posture()` and state
plainly whether DR cover is genuinely restored (it is **not**, if boston-2 is still a
promoted fork needing a re-clone).

---

## Behaviour that must be tested

- Watchdog honours the snooze **mid-window**, not just at cycle start (L363 path).
- Snooze **expiry** re-arms the watchdog without intervention.
- `status` correctly reports a **half-applied** window (e.g. banner set, Beacon not moved).
- `end` is idempotent and safe to run when no window is open.
- `start` **refuses** when the watchdog cannot be confirmed suppressed.
- Unmapped hostnames are **untouched** by the traffic move (the ADR-009 invariant).

## Open questions for the owner

1. Default snooze duration — 60 min proposed. Hardware work often overruns; too short
   re-arms mid-job, too long leaves DR disarmed.
2. Should `start` refuse outright when DR posture is already degraded (as tonight:
   promoted fork, no replication), or proceed with a loud warning? Arguably the window
   is *more* needed then, not less.
3. Does the maintenance banner belong on `/dashboard`? The DR banner currently does not
   — the LCARS header include is on tool pages only, not `base.html`.
