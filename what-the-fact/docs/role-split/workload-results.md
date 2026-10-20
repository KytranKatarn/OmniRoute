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

**Resolved in the tier-2 boundary change (Codex, 2026-10-20):** the legacy
`POST /api/upgrade-tier2/<id>` keeps its subscriber gate and delegates to the
existing rate-limited consumer proxy and bounded asynchronous tech analysis.
It returns the existing tech `queued` / `done` response, replacing its former
synchronous `bias_summary` / `claims_count` response. Callers poll
`GET /api/proxy/articles/<id>/analyze/status` and then reload the article.
No in-repository browser caller uses the legacy URL; the current UI already uses
this asynchronous proxy contract. External legacy clients must adopt polling.
The poll now requires a completed full/deep tier as well as `ai_analyzed`, so a
quick-tier result cannot falsely report completion. Proxy errors retain tech's
HTTP status and `Retry-After` header.

The updated write harness passes **19/19** against a disposable PostgreSQL 16
copy with synthetic rows and restricted service logins. It sends the real legacy
consumer route through the real proxy to the tech route, verifies a new claim
and completed article independently, and checks consumer editorial grants remain
absent. Transport uses Flask's test client; background scheduling runs inline and
external inference supplies synthetic results. This verifies persistence and
routing, not live inference, process concurrency or production deployment.
The 27 focused offline tests cover the gate, rate limit, proxy errors and existing
concurrency guard. Production role/credential cutover remains separate.

`static_table_scan.py` now also checks WRITE rights against the helper modules each service imports, and found two further read gaps the crawl could not see because the helpers are fail-soft: `parliament.dept_contracts`, `parliament.cost_projection_snapshots` (now granted to the consumer).
