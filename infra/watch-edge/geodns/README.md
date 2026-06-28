# Watch-Edge GeoDNS — self-hosted gdnsd (#4319, ADR-010)

Authoritative **GeoDNS** for the Watch-Series domains, run on **our own outposts** — no
third-party GeoDNS provider. Answers `what-the-fact.com` (and later the other Watch domains)
with the **nearest healthy regional edge**, with native health-checked failover.

- **Decision:** ADR-010 (`mcp log_decision` #864) — self-hosted gdnsd, not Route 53/NS1/ClouDNS.
- **Design:** `.claude/plans/2026-06-18-watch-edge-funnel-cdn-design.md`
- **Implementation plan:** `.claude/plans/2026-06-28-watch-edge-geodns-gdnsd-implementation.md`
- **Engine:** gdnsd 3.8.x (Alpine community pkg) + DB-IP `ip-to-country-lite` (free, no API key).

## Files
| File | Purpose |
|------|---------|
| `config/config` | gdnsd main config — geoip map (continent→DC) + http_status health checks |
| `config/zones/what-the-fact.com` | the zone — apex/www `DYNA geoip!wtf_edge`; NS glue |
| `config/geoip/*.mmdb` | DB-IP country DB (**gitignored**, fetched by `fetch-geoip.sh`) |
| `Dockerfile` / `docker-compose.yml` | gdnsd container (host net, `:53`, read-only rootfs) |
| `fetch-geoip.sh` | pull the monthly DB-IP MMDB (run on each node + monthly cron) |

## Routing (matches the egress node↔country map)
| Region (continent) | → Datacenter | Edge IP(s) |
|---|---|---|
| NA / SA / default | `na` | Beacon `2.25.170.252` |
| EU / AF | `eu` | Outpost-UK `2.24.130.153`, Outpost-Lithuania `72.62.112.210` |
| AS / OC | `apac` | Outpost-Singapore `156.67.217.86` |

Each continent has a **preference list** (`map` in `config/config`); if its first DC has no
healthy edge, gdnsd falls through to the next (e.g. EU edges all down → EU users get NA).

## Nameservers (≥3, geo-spread)
`ns1`=Outpost-US (76.13.107.109, NA) · `ns2`=Outpost-UK (2.24.130.153, EU) · `ns3`=Outpost-Singapore (156.67.217.86, APAC).
> ⚠️ `ns1` needs **task #4552** first — Outpost-US `remote_nodes.hostname` is the stale docker-bridge `172.27.0.1`, not its real public IP.

## Validation (done 2026-06-28, cont-105 — isolated on the hub, zero production touch)
- `gdnsd checkconf` → exit 0; GeoIP2 DB loads (840,354 nets, 4 dclists); zone loads.
- Live geo via `dig @127.0.0.1 -p 5353 what-the-fact.com +subnet=<ip>`:
  - US `+subnet=76.13.107.109` → `2.25.170.252` (NA) ✓
  - UK `+subnet=2.24.130.153` → `2.24.130.153 72.62.112.210` (EU) ✓
  - SG `+subnet=156.67.217.86` → `156.67.217.86` (APAC) ✓
  - default → `2.25.170.252` (NA) ✓
- Health: http_status monitors run live (marked unreachable test edges `DOWN`); **fail-safe still
  answered** when all-down (no black-hole). Live cross-region failover demo deferred to Stage 3
  (needs ≥2 reachable edges).

Reproduce: `./fetch-geoip.sh && docker build -t watch-geodns . && docker run --rm -v $PWD/config:/etc/gdnsd:ro watch-geodns checkconf`

## Deploy (Stage 3 — undelegated, no public cutover)
On each nameserver node (Outpost-US/UK/Singapore):
```sh
rsync -a infra/watch-edge/geodns/  <node>:/opt/archie-edge/geodns/   # exclude nothing; mmdb fetched on node
ssh <node> 'cd /opt/archie-edge/geodns && ./fetch-geoip.sh && docker compose up -d --build'
ssh <node> 'sudo ufw allow 53/udp && sudo ufw allow 53/tcp'           # then re-verify the SOCKS5 mesh-only gate
dig @<node_public_ip> what-the-fact.com +short                        # answers authoritatively, still undelegated
```

## Cutover (Stage 4 — owner-gated, the only outward-facing step)
1. **MIRROR the full Hostinger zone** into `config/zones/what-the-fact.com` first (MX, SPF/DKIM/
   DMARC TXT, every subdomain). A dropped MX = mail outage — diff against the live export.
2. Registrar: create glue `ns1/ns2/ns3.what-the-fact.com` → the public IPs; switch NS Hostinger→ours.
3. Verify from multiple external vantages; watch propagation.
- **Rollback = revert the registrar NS to Hostinger** (instant). Keep the Hostinger zone intact.

## Gotchas
- gdnsd 3.x `start` is foreground — **no `-f` flag** (it errors).
- We OWN DNS-layer uptime (no anycast SLA) — keep ≥3 geo-spread NS, monitor each answers.
- APAC is a single node (Singapore) — failover degrades latency, not uptime, until a 2nd APAC node.
- Opening `:53` must not weaken the SOCKS5 mesh-only DOCKER-USER gate (KB mistake #272166).
- `geoip2_db` path is relative to `config/geoip/`. DB refresh = monthly cron on each node.
