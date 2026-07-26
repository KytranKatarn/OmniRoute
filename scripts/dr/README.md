# DR / Warm-Standby Orchestration Scripts (Project #368)

Version-controlled source of the disaster-recovery scripts that run on the **DR node**
(**Citadel — United States / boston-2**, mesh `100.64.0.10`, deployed at `/opt/archie-dr/`).
boston-2 holds a live brain-DB replica + the watch products; on a hub outage these scripts
promote it to primary, repoint the fleet, and flip public DNS — then fail back when the hub
returns.

> These are the canonical copies. To deploy: copy to `/opt/archie-dr/` on boston-2.
> The hub mesh IP is `100.64.0.4`; boston-2 is `100.64.0.10`; Beacon (front-door) is `100.64.0.11`.

## ⚠️ Required secret files (owner-staged on the DR node, gitignored — NEVER commit)
Each is a plain file at `/opt/archie-dr/`, mode `600`. The scripts read them at runtime
(`cat` / `source`); none are hardcoded. Missing files make the relevant step abort or skip
(fail-safe), not crash.

| File | Holds | Read by |
|------|-------|---------|
| `.hostinger_token` | Hostinger API token (DNS flips) | `dns_flip.sh`, `dns_flip_back.sh` (`TOKEN=$(cat …)`) |
| `.telegram_env` | `TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID` | `tg_notify.sh` (`source`) |
| `.replpw` | Postgres `replicator` password | `setup_replica.sh`, `failback.sh` (`PW=$(cat …)`) |

## Scripts
| Script | What it does |
|--------|--------------|
| `failover.sh` | Hub-outage failover: promote boston-2 replica → primary, start the standby platform + scheduler, repoint the fleet + WTF DB → boston-2, bring up the ingress Caddy, and **flip the Beacon front-door's Caddy upstream hub→boston-2** (step 4c). `platform.*` DNS STAYS on Beacon (`2.25.170.252`) — no A-record flip. Telegram alerts via `tg_notify.sh`. Non-fatal sub-steps never abort the failover. |
| `failback.sh` | Phased return to the hub: `precheck \| prep-source \| rebuild-hub \| switchover \| restore-normal \| verify`. Reverses the fleet / WTF / Beacon-upstream repoints. (No `platform.*` DNS flip — it never left Beacon.) |
| `dns_flip.sh` / `dns_flip_back.sh` | ⚠️ **DEPRECATED** (task #3787). `platform.*` lives permanently on Beacon (`2.25.170.252`); failover is the Beacon-upstream flip, not an A-record move. Retained ONLY as a manual EMERGENCY tool if **Beacon itself** is down (flip `platform` straight → boston-2 `2.25.133.122` / back). Not called by the automated flow. |
| `tg_notify.sh` | Shared Telegram alert helper (sourced by failover/failback). Silently skips if `.telegram_env` is absent. |
| `beacon_flip.sh` | **Shared SELECTIVE Beacon upstream flipper** (task #5214). Sourced by `failover.sh` / `failback.sh` / `auto_failback.sh` / `force_reset_to_hub.sh` so the DR-capable service map lives in ONE place. **Must be staged on boston-2** — see below. |
| `setup_replica.sh` | Initial `pg_basebackup` to (re)seed boston-2 as a hub streaming replica. |

## ⚠️ Beacon flips are SELECTIVE — only DR-capable services move

Beacon fronts ~20 upstreams and **exactly one** of them has a boston-2 counterpart.
A failover therefore flips only:

| Port | Service | When |
|------|---------|------|
| `3000` | platform (`archie_platform_standby`) | **always** — one line covers platform./api./bridge./consciousness./mediahub. via the `(platform_backend)` snippet |
| `8086` | C.R.E.E.D. | only if step 4e staged it **and** it answers on `:8086` |
| `8095` | Headscale control plane (`mesh.`) | only if step 4f staged it **and** it answers on `:8095` |

Everything else (KSO `:8085`, KBS `:8091`, Media Hub `:8105`, `archie_comms :3002`,
Plex/Jellyfin/Nagios/AdGuard/sandbox/terminal/codex/Tdarr) **stays pointed at the hub**.

This replaced a blanket `sed 's|100.64.0.4|100.64.0.10|g'` in all four scripts, which took
~20 healthy hub-only services offline on every failover and rewrote the Caddyfile's own
comments. ADR-009 (decision #955): *pointing a hostname at a host that cannot serve it is
worse than leaving it pointed at one that is merely down — the second is honest, the first
sends operators to debug the wrong system.*

**To make a new service DR-capable:** stand up its counterpart on boston-2 first, then add
its port to the map in `beacon_flip.sh`. Adding a port without a counterpart re-creates the
outage. Covered by `platform_v2/tests/test_beacon_selective_flip.py`.

## Safety
- **Never run `failover.sh` wholesale as a casual test** — it flips production DNS. For a drill, promote + stand up the standby manually and watch.
- Suppress the auto-failover watchdog before a planned hub power-down: `touch /opt/archie-dr/.watchdog_disabled`.
- **Deploy `beacon_flip.sh` whenever you deploy the DR scripts.** If it is missing the flip
  is SKIPPED with a loud warning (never silently blanket-flipped), so a failover would leave
  `platform.` pointed at the down hub:
  ```bash
  scp scripts/dr/beacon_flip.sh root@100.64.0.10:/opt/archie-dr/
  ```
- Verify a failover stayed selective — hub-only upstreams must survive:
  ```bash
  ssh root@2.25.170.252 "grep -c '^[[:space:]]*reverse_proxy http://100.64.0.4:' /etc/caddy/Caddyfile"
  # expect ~18, NEVER 0.  0 == a blanket flip took the hub-only services down.
  ```

Related: KB #270037 / #270232 / #270519 (Beacon front-door DR Phase-2), ADR #682 / #683.
