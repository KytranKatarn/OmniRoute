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
| `setup_replica.sh` | Initial `pg_basebackup` to (re)seed boston-2 as a hub streaming replica. |

## Safety
- **Never run `failover.sh` wholesale as a casual test** — it flips production DNS. For a drill, promote + stand up the standby manually and watch.
- Suppress the auto-failover watchdog before a planned hub power-down: `touch /opt/archie-dr/.watchdog_disabled`.

Related: KB #270037 / #270232 / #270519 (Beacon front-door DR Phase-2), ADR #682 / #683.
