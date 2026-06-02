# A.R.C.H.I.E. Disaster-Recovery tooling (off-hub canonical copy)

These are the DR scripts that run on the **DR node, outpost-boston-2** (`2.25.133.122`,
mesh `100.64.0.10`, KVM8 32GB) at `/opt/archie-dr/`. This `dr/` dir is the **git-tracked
backup** so the tooling survives even if boston-2 (or the hub) is the thing that's down —
clone it from GitHub onto any machine to recover.

Full design + status: `.claude/plans/dr-plan-boston2.md` · SPOF audit:
`.claude/hub-spof-dependency-audit.md` · KB #270037 (initiative), #270036 (replica),
#270039/#270040 (Hostinger DNS gotchas). Project #368. Goal: survive a Starbase (hub) outage.

## Files
| File | Purpose |
|---|---|
| `setup_replica.sh` | Stand up / re-clone the streaming Postgres replica of the hub brain DB on boston-2 (:5433). |
| `failover.sh` | **The failover.** Split-brain-guarded: promote replica→RW → start standby platform → start Caddy ingress → flip DNS → verify. Run: `ssh root@2.25.133.122 /opt/archie-dr/failover.sh [--force]`. |
| `dns_flip.sh` | Flip `platform.kytranempowerment.com` A-record → boston-2 via Hostinger DNS API (DELETE-then-CREATE; sends `User-Agent` to pass the WAF). |
| `docker-compose.standby.yml` | The warm standby `archie_platform_standby` (DB→127.0.0.1:5433, no GPU). |
| `Caddyfile` + `docker-compose.caddy.yml` | Public HTTPS ingress for the recovered platform (started by failover.sh). |
| `DR_RUNBOOK.md` | Operator runbook: failover, **manual fleet-repoint** (Phase 5b), failback. |

## Secrets are NOT in these files
- Replication password → `boston-2:/opt/archie-dr/.replpw` (600)
- Hostinger API token → `boston-2:/opt/archie-dr/.hostinger_token` (600)
The scripts read those at runtime. Keep secrets off git.

## Status (2026-06-02)
Phases 1–4 done & **drilled** (~14s RTO, hub-safe); Phase 5 ingress + DNS flip **verified**;
Phase 5b (fleet-follow) scoped/designed + manual procedure in the runbook, automated build
deferred to a drilled session; Phases 6–7 (failback, automation) planned.
