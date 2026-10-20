# Restricted-role workload results

See [workload-test-plan.md](workload-test-plan.md) for the matrix these results answer.

## Results to date (Claude CLI, 2026-10-20/21, scratch PostgreSQL 16 from the live schema-only dump)

| Harness | Scope | Result |
|---|---|---|
| `workload_ingest.py` | wtf_ingest: GIC/BoC/FX upserts, EC refresh success / mid-import failure / empty / overlap, ingest_log, DDL+TRUNCATE denied | 13/13 |
| `workload_ingest_api.py` | wtf_ingest_api: route surface, 503/401/400, ingest persistence, idempotent repeat, merge-following, companies, receipt, denied consumer tables | 17/17 (after fix 1) |
| `workload_crawl.py consumer` / `tech` | every parameter-free GET route, restricted vs superuser | 0 differences (113 consumer / 18 tech routes) after fixes 2-4 |
| `static_table_scan.py` | every audited table referenced by consumer / tech / ingest-api source vs the role's grants | clean |

**Defects the workloads found (all fixed in `permissions.json`; none would have shown in the ACL-only rehearsal):**
1. `wtf_ingest_api` could not write its push receipt: `record_push()` swallows the error, so the drift guard would have seen entity pushes go quiet. Granted INSERT + SELECT on `parliament.ingest_log` only.
2. `wtf_consumer` lacked SELECT on `parliament.indemnity_rates` and `parliament.minister_travel` (`/api/cost/*` returned 500).
3. `wtf_consumer` lacked SELECT on `shared.chain_link_types` (`/api/public/chain/links` returned 500).
4. `wtf_consumer` lacked SELECT on `wtf.beats` (checkout path; found by the static scan, not the crawl).

**Still NOT covered:** parameterised GET routes (only the static scan sees them), every authenticated write (API-key lifecycle, alerts, newsletter, claims, dedup, snapshot caches), tech Deep Dive persistence + the `sync_article_latest_verdict` trigger, the securities job and four other market modules, the hub scraper login, DR fallback reads, and the EC scale gate. A clean crawl is read coverage only.

### Write-path results (workload_writes.py, 14/15) and the scan extension

Real code, real `wtf_consumer` / `wtf_tech` logins, every effect verified by an operator read: newsletter subscribe/unsubscribe, alert create/delete, article-view logging, admin claim create/update, dedup `distinct` and a real `same` merge (consumer); score flag, Deep Dive persistence (`bias_scores`, `fact_checks`, `articles`) and the `sync_article_latest_verdict` trigger (tech) all PASS.

**OPEN (blocks cutover, needs an owner decision):** the consumer's `/api/upgrade-tier2` calls `ingest.tier2_upgrade.persist_upgrade`, which UPDATEs `bias_scores`, DELETE/INSERTs `fact_checks` and UPDATEs `articles`. `wtf_consumer` has none of those write grants and must not get them (public-facing role). Move the upgrade to the tech service or the tier-2 precompute worker. The harness case stays FAILING until this is resolved.

`static_table_scan.py` now also checks WRITE rights against the helper modules each service imports, and found two further read gaps the crawl could not see because the helpers are fail-soft: `parliament.dept_contracts`, `parliament.cost_projection_snapshots` (now granted to the consumer).
