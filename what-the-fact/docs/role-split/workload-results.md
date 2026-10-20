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
