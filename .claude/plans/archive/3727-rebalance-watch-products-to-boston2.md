# Task #3727 — Rebalance Watch products: outpost-boston → outpost-boston-2

**Status:** ✅ COMPLETE 5/5 (2026-06-03) — market, gov, civic, legal, WTF(consumer+tech+ingest) all LIVE on boston-2. Phase D cleanup (stop old containers + remove stale legal_api/dup KSO) DEFERRED per owner.
**Author:** Claude, 2026-06-03. Project #371. ADR-001/#691. KB mistakes #270474 + #270476 (fresh-volume perms). Tasks #3727 + #3742 done.

## OUTCOME (2026-06-03)
**Migrated + live on boston-2 (8c/32GB), all HTTPS 200 + valid LE certs:**
- ✅ **market** (SQLite watch market.db) · ✅ **gov** (Postgres `gov_watch_db`, 36,246 rows pg_dump/restore) · ✅ **civic** (SQLite watch.db 54MB) · ✅ **legal** (pre-existing).
- DNS flipped: market/gov/civic → 2.25.133.122. Old containers KEPT RUNNING on outpost-boston as rollback (Phase D cleanup deferred per owner).

**Key learning — gap-free copy-cert cutover (ADR-001/#691, mistake #270474):**
gov FIRST attempt FAILED — ACME couldn't issue post-DNS-flip (LE resolver cached old IP from the pre-flip Caddy ACME attempt → brief gov outage → rolled DNS back). Re-did gov via **copy-cert** (copy the existing cert from outpost-boston's Caddy `/data/caddy/certificates/<issuer>/<domain>/` → boston-2's Caddy, verify forced-IP HTTPS BEFORE the flip) → zero gap. Used copy-cert for civic too. **This is the method for the WTF follow-up.**

**WTF ✅ DONE (task #3742)** — consumer+tech+ingest all migrated to boston-2 (3 domains live: what-the-fact.com/.tech + wtf.kytranempowerment.com, valid certs; ingest polling RSS + writing hub wtf DB; single-ingest). Root cause of the earlier consumer boot fail: fresh named volume was root-owned but consumer runs as nobody(65534) on read_only rootfs → couldn't open local sqlite → `chown -R 65534:65534` the volume (KB #270476). Apex A + AAAA both → boston-2 on .com/.tech (left MX/TXT). ⚠️ The apex AAAA had still pointed to the OLD outpost-boston IPv6 (2a02:4780:2d:9cce::1); FIXED 2026-06-03 → boston-2 IPv6 (2a02:4780:75:5c82::1) — boston-2 Caddy is dual-stack ([::]:443) and confirmed serving WTF over IPv6 with a valid cert. wtf.kytranempowerment.com has A only. KB #270482. outpost consumer/tech kept as rollback; outpost ingest STOPPED (single-ingest). _(Original deferral notes below retained for reference.)_
- wtf-tech builds + serves fine. **wtf-consumer won't boot on boston-2:** `read_only` rootfs + runs as `nobody` + local sqlite `consumer/db.py` `/app/data/wtf_billing.db` (vol `what-the-fact_wtf_billing_data`). Migrated wtf_billing.db + chowned vol to 65534 (rw ok) — STILL `sqlite3.OperationalError: unable to open database file` at `init_billing_table`. Source consumer ALSO has `/app/data/wtf.db` (NOT migrated) — prime suspect. Stopped after 2 attempts (hard rule).
- 3 WTF certs already staged in boston-2 Caddy. WTF DB = hub (no move; agents keep writing). boston-2 WTF staged + STOPPED. Single-ingest cutover required (stop outpost ingest → start boston-2 ingest). 3 DNS: what-the-fact.com + .tech (separate apex zones) + wtf.kytranempowerment.com.

**Phase D (NOT done, per owner — keep rollback):** stop old market/gov/civic containers on outpost-boston + remove stale `kytran_legal_api` + duplicate `kytran-system-operations` — only after WTF done + a stability window.

---

### Original plan (below) — retained for reference

## Goal
Move the live Watch products off the smallest box (outpost-boston, 2c/8GB) onto
the big idle box (outpost-boston-2, 8c/32GB) in the **same Boston DC** — removing
the single-point-of-failure / no-headroom risk. Legal already lives on boston-2.

## Verified current state (live, 2026-06-03)
| | outpost-boston (SOURCE) | outpost-boston-2 (TARGET) |
|---|---|---|
| Public IP | 76.13.107.109 | 2.25.133.122 |
| Mesh IP | 100.64.0.2 | 100.64.0.10 |
| SSH | `kytran@100.64.0.2` | `root@100.64.0.10` |
| CPU/RAM | 2c / 8GB (5.5GB free, load 0.24) | 8c / 32GB (29GB free, load 0.55) |
| Disk | 97G (32G free) | 387G (336G free) |
| Runs | gov+gov_db, civic, market, **legal(stale)**, WTF×3, **KSO(dup)**, agents | DR replica, legal(canonical), ingress caddy, agents |
| Caddy | `archie_outpost_proxy` | `/opt/archie-ingress/Caddyfile` (172.18.0.1:<port>) |

**Note:** outpost-boston is NOT actively overloaded right now (12% load, 5.5GB
free). This is a resilience move (SPOF + no spike headroom), not an emergency —
so we go canary-first, unrushed, fully reversible.

## Products to move + DB handling
| Product | Container(s) | DB | Migration |
|---|---|---|---|
| gov_watch | kytran_gov_watch + gov_watch_db | **Postgres container** | `pg_dump -Fc` → restore into new gov_watch_db on boston-2 |
| civic_watch | kytran_watch_api | **SQLite** (/app/data/watch.db) | copy file (online `.backup`) |
| market_watch | kytran_market_api | **SQLite** (/app/data/market.db) | copy file (online `.backup`) |
| WTF | wtf-consumer/ingest/tech | **DB on HUB** (`@100.64.0.4/wtf`) | NO data move — redeploy apps pointing at hub wtf DB (bonus: co-locates with DR replica) |
| legal_watch | — | — | already on boston-2 ✅ |

## Sequence (canary-first, reversible)
**Phase A — Stage on boston-2 (ZERO user impact, nothing cut over):**
1. `rsync --exclude=.env` each product dir `kytran@100.64.0.2:/opt/archie-products/<p>` → `root@100.64.0.10:/opt/archie-products/<p>`. Bring `.env` over carefully (review secrets; keep BRIDGE_URL=mesh, WTF_DATABASE_URL=hub).
2. `docker compose up -d --build` each on boston-2; join the ingress-reachable network.
3. Migrate DBs: gov pg_dump→restore; civic/market sqlite copy. (Initial copy — final re-sync happens at each cutover to avoid drift.)
4. **Verify on boston-2 by direct IP:port** (before any DNS): each product returns 200 + non-empty data (reuse P.R.O.B.E. data-nonempty checks).

**Phase B — Canary cutover (ONE product, lowest traffic — recommend market_watch):**
5. Add its `reverse_proxy 172.18.0.1:<port>` to boston-2 `/opt/archie-ingress/Caddyfile`, reload Caddy.
6. **Final DB re-sync** for that product (fresh dump/copy, seconds before DNS).
7. Repoint its DNS A-record 76.13.107.109 → 2.25.133.122 (Hostinger DNS MCP).
8. **Verify live** over the public domain. Leave the outpost-boston container RUNNING (rollback = revert DNS).
9. Watch for ~1 cycle; confirm clean.

**Phase C — Cut over the rest** (gov, civic, then WTF consumer+tech) one at a time, same final-resync→DNS→verify pattern.

**Phase D — Decommission on outpost-boston (only after ALL verified, keep a rollback window):**
10. Stop (don't delete yet) migrated containers; remove their Caddy entries on outpost-boston.
11. **Cleanups:** remove the stale `kytran_legal_api` (canonical is boston-2) and the duplicate `kytran-system-operations` (canonical is hub) — after confirming neither serves anything unique.
12. After a stable window, delete the stopped containers + dirs on outpost-boston.

## Rollback (any phase)
- Pre-DNS: nothing to roll back (boston-2 staging is additive).
- Post-DNS per product: revert the A-record to 76.13.107.109 (outpost-boston container still running). DNS TTL governs recovery time.

## Key risks / mitigations
- **DB drift** between dump and cutover → final re-sync seconds before each DNS flip; WTF has no drift (DB on hub).
- **DNS propagation lag** → keep source containers up through the rollback window; low TTL if possible.
- **SSL** → boston-2 Caddy auto-provisions Let's Encrypt on first request per domain (same as legal).
- **what-the-fact.tech** + apex `what-the-fact.com` both move (wtf-tech + wtf-consumer); ingest has no public DNS.
- **DR interaction** → boston-2 is the DR node; adding products there is fine in normal ops, and WTF co-location actually helps DR. Confirm failover.sh still behaves (products are separate from the DR replica/standby).

## Open decisions for owner
1. **Canary product?** (recommend market_watch or civic_watch — lowest traffic.)
2. **All in one session, or canary now + rest later?**
3. **Maintenance window** acceptable (brief per-product), or strict zero-downtime?
4. Confirm OK to **repoint production DNS** (gov/civic/market/what-the-fact[.com/.tech]).
