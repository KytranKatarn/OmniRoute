# Design port — the five pages with no data yet (for review)

Status: **proposal.** UPDATE after rebasing on main: §1 Debt is already built (row 25a, StatCan tables); §2 Global is in open PR #3573 (OECD DAC1 → `market_watch.oda_canada_annual`, not the GAC source proposed here); §4 Elections calendar and §5 homepage tile are implemented on this branch. Only §3 Platforms remains unbuilt. The sections below are kept as written for the reasoning.

Original status: **nothing built.** Written 2026-10-01 from the repo only; no DB or
network was available, so every "exists today" claim comes from code/migrations and
every external source is marked **VERIFY** (dataset id, licence, robots.txt) before use.

## The house pattern every page below must follow

This is already how `elections_results`, `boc_rates`, `fx_rates` and `statcan_indicators` work:

1. **Ingest module** `ingest/<area>/<name>.py` with `run_<name>(engine)` that **never raises**
   and writes a `parliament.ingest_log` heartbeat on the success path, the exception path
   *and* the swallowed-error path.
2. **Schedule** in `ingest/run.py` behind an ISO-week (or day) guard, cadence matched to the
   source's real release rhythm — not to how fresh the page would like to feel.
3. **Monitor** in `ingest/parliament/drift_guard.py`: add to `_MAX_AGE_DAYS` (cadence + slack)
   **and** `_REQUIRED_TASKS` (so "never ran" alarms instead of being skipped as "not tracked yet").
   A job with a heartbeat writer but no drift entry is unmonitored while appearing monitored.
4. **Read path**: route reads the table, renders `as of <date>` from the data's own
   timestamp, and says "no data" for an absent value — never 0 (the Map archetype rule).
5. **Retire the placeholder**: delete the entry from `_COMING_SOON` in `consumer/routes.py`
   in the same PR (a page that exists must not also be advertised as unbuilt).
6. Migration grants to `wtfuser` (apps don't connect as the owner) — migration 047 precedent.

"Keeps updating as time moves on" therefore means: scheduled ingest + heartbeat + drift alarm
+ visible as-of date on the page. Nothing is hand-entered.

## 1. Debt tracker — `wtf-debt` (route `/debt`)

- **Needs**: ~10 fiscal years of revenue, program expenses, public debt charges, annual
  balance, accumulated deficit; plus expenses by portfolio (the design's "where the money goes").
- **Exists**: only departmental *contracts* (`dept_contracts`). No fiscal aggregates.
- **Source (VERIFY)**: Finance Canada *Fiscal Reference Tables* / *Fiscal Monitor* and Public
  Accounts of Canada, via open.canada.ca CKAN (same host family as the elections ingest, so
  the robots.txt reasoning in migration 074 applies — check the resource host).
- **Schema**: `parliament.fiscal_year(fy, revenue, program_expenses, debt_charges, balance,
  accumulated_deficit, preliminary bool, source_url, fetched_at)`; `parliament.fiscal_portfolio(fy,
  portfolio, expenses)`.
- **Cadence**: weekly check, but data moves **annually** (+ monthly Fiscal Monitor). Drift window
  ~45 days like `senator_expenses_sync`; the heartbeat proves the job runs, `fy` max proves currency.
- **Honesty rules**: preliminary years flagged in the UI (design already says so); the four
  "measures of debt" stay labelled by measure; provincial debt explicitly out of scope. The
  design's series are "the design's reading of published tables" — **must be replaced by ingested
  values; do not ship the prototype numbers.**
- **Review questions**: monthly Fiscal Monitor in v1 or annual only? Is the accumulated-deficit
  definition on the page the one Finance publishes?

## 2. Global Affairs spending — `wtf-global` (route `/global`)

- **Needs**: international assistance by year/channel (bilateral / multilateral / humanitarian /
  Ukraine) and top recipients; share of federal spending.
- **Exists**: nothing (`_COMING_SOON['global']`: "not yet collected").
- **Source (VERIFY)**: Global Affairs Canada *Statistical Report on International Assistance* /
  GAC open data (IATI feed is the machine-readable candidate); OECD DAC ODA tables for the
  CAD-converted comparison. Licence + robots.txt check first.
- **Schema**: `parliament.intl_assistance(fy, channel, sector, recipient, amount_cad, source_url)`.
- **Cadence**: GAC publishes annually; weekly job + heartbeat, drift window ~60 days.
- **Cross-Watch link**: recipients that also lobby / hold contracts appear in the shared entity
  graph — reuse `shared/entity_graph.py`; "appearing in a register is a record, not a finding"
  stays on the page.
- **Review questions**: IATI vs the statistical report as primary? Recipient names are messy —
  do we link to the entity graph in v1 or ship amounts only?

## 3. Platforms & promises — `wtf-platforms` (route `/platforms`)

- **Needs**: commitments quoted from a platform document, with the document, and evidence for
  current status.
- **Exists**: `parliament.mp_promises` (5,561 rows) — **keyword-matched article snippets, not
  commitments** (sampled rows include ad boilerplate). The placeholder says so; do not surface it
  as "tracked promises".
- **This is the hard one — it is a content pipeline, not a feed.** Proposal:
  1. `parliament.platform_documents(party, ge_number, url, sha256, fetched_at)` — party platform
     PDFs/pages, added by an admin (few per election; a manual curated list is honest here).
  2. Commitment extraction **through the DHQ dispatcher** (hub dispatch, ADR-013), producing
     *candidate* commitments with the exact quoted sentence + page/offset.
  3. **Human review queue before anything is public** (reuse the dedup-review admin pattern,
     `dedup_admin_routes.py`). Status (`not_started / in_progress / kept / broken`) requires an
     evidence URL (bill, order in council, vote) — no evidence, no status.
- **Monitoring**: documents-fetched heartbeat + a "review backlog" count surfaced on the admin page;
  drift guard on the extraction job.
- **Review questions**: who reviews? Is 2025 federal platforms only the v1 scope? Do we accept
  "unreviewed candidates hidden" as the default?

## 4. Elections — `wtf-elections` (route `/elections`)

- **Needs**: calendar of federal, provincial, municipal elections with fixed-date rules and
  how soon each legislature must go to the polls; coverage readiness.
- **Exists**: completed federal results (GE43/44) feeding `/races` and `/parties`. No calendar.
- **Source**: there is no single feed. Fixed-date rules are statute (Canada Elections Act s.56.1
  and provincial equivalents); next dates come from Elections Canada / each provincial agency.
- **Proposal**: a **curated reference table** `parliament.election_calendar(jurisdiction, level,
  last_election, next_latest_date, rule, source_url, verified_at)` seeded in a migration with a
  source per row, plus a small job that **recomputes** "days until latest-possible date" at read
  time (never stored) and a **staleness alarm on `verified_at`** (e.g. > 180 days → drift guard
  problem) so a call or dissolution can't leave a wrong date on the page silently.
  Writ periods/snap elections are the failure mode: add a check that flags any row whose
  `next_latest_date` has passed.
- **Coverage readiness** column: derive from existing tables (candidates/results present?) —
  not a hand-typed label.
- **Review questions**: how many jurisdictions in v1 (13 provinces/territories + federal)?
  Municipal: province-level rule only, or per-city?

## 5. Homepage "Spread pressure" tile (PORT-STATUS row 4)

- **Already solved elsewhere**: row 8b built `aurora_map.spread_pressure()` — a province index
  from real current-conditions rows, formula printed, "no data" under 2 inputs. The homepage
  tile should **reuse that function**, not a new source.
- **Honesty gap to settle**: the design tile reads "84 · Extreme, next 48h" — a **forecast**.
  The index is current conditions, not a forecast. Either the tile is relabelled
  ("current spread pressure, province X") or it stays off until A.R.C.H.I.E. predictions exist
  and are scored against it (the 8b note already plans this).
- **Monitoring**: inherits `aurora_firewx` / `aurora_city_obs` drift entries (already required).
- **Review question**: relabel now, or leave the 6th tile out?

## Suggested build order (cheapest/most honest first)

1. Homepage tile (reuse, no new ingest) · 2. Elections calendar (curated + staleness alarm) ·
3. Debt (one well-defined source) · 4. Global (needs source verification) ·
5. Platforms (needs the review-queue process decided first).
