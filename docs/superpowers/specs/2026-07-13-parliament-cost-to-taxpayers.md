# What Parliament Costs Canadians — cost-to-taxpayers feature (design)

**Goal:** show the approximate annual + 5-year cost to taxpayers of each MP and senator
(salary/indemnity + office expenses), and a national "cost of Parliament" view — to make
the ongoing cost of the legislature concrete and public. Pensions are OUT of scope (owner
decision — a longer-term cost tracked separately later).

**Owner-approved scope (2026-07-13, "all 3"):** WTF surface (MPs, data ready) + a NEW
Senate-expenditure ingest (senators) + cross-product surfacing on the civic-watch
transparency registry via the shared entity graph.

---

## 1. Cost model (the number)

`taxpayer_cost(person, year) = base_indemnity(year) + role_top_up(role, year) + office_expenses(year)`

- **base_indemnity** — the sessional indemnity (MP) / senator base salary, a published yearly
  constant. Source: Library of Parliament "Indemnities, Salaries and Allowances". Stored in a
  small reference table so it's auditable + updatable without code (values must be SOURCED, not
  guessed — the display is public).
- **role_top_up** — additional salary for PM / ministers / Speaker / party leaders / whips
  (e.g. Minister ≈ +$99k, PM ≈ +$190k). Keyed to the role the person holds that year.
- **office_expenses** — travel + hospitality + contracts + office-staff salaries.
  - MPs: `parliament.mp_expenses` (EXISTS — 4,428 rows, 339 MPs, 2021-Q1..2025-Q4, quarterly).
  - Senators: `parliament.senator_expenses` (NEW — see §4).

**Honesty rails:** label everything "approximate", show the components (don't just show one
big number), cite the sources (Library of Parliament indemnity tables; House/Senate proactive
expenditure disclosures), and note the period each figure covers + that office totals exclude
pensions and some central costs. Round to sensible precision. Never present a single figure as
exact.

## 2. Reference data (NEW table)

`parliament.indemnity_rates (fiscal_year INT, role TEXT /* mp|senator|minister_topup|pm_topup|speaker_topup|... */, amount_cad NUMERIC, source_url TEXT, PRIMARY KEY(fiscal_year, role))`
Seeded from the Library of Parliament tables (a subagent sources the exact values). One row per
(year, role). Grant SELECT to wtfuser + civic (least-privilege; reference data, read-only to apps).

## 3. Cost service + API (WTF, the single source of truth)

`ingest/parliament/cost.py` (or a service module) — pure functions:
- `mp_cost(mp_id, year) -> {indemnity, top_up, office{travel,hospitality,contracts,salaries}, total}`
- `mp_cost_5yr(mp_id) -> [{year, ...}], five_year_total`
- `senator_cost(...)` (once §4 lands)
- `parliament_cost_summary() -> {by_year:[{year, mp_total, senator_total, count, avg_per_member}], grand_total_5yr}`

**API (consumer app, read-only, cached):**
- `GET /api/cost/mp/<mp_id>` · `GET /api/cost/senator/<id>` · `GET /api/cost/summary`
Returns the model above + `_source` + `_note` (approximate). Public.

## 4. Senate-expenditure ingest (NEW — the senator data gap)

The Senate publishes quarterly senators' expenditures on sencanada.ca (Public Disclosure →
Senators' Expenses). NEW `ingest/parliament/senator_expenses.py`: fetch/parse the quarterly
report (CSV/HTML), upsert `parliament.senator_expenses (senator_id, period, travel_cad,
hospitality_cad, contracts_cad, office_cad, total_cad, source_url, synced_at)` matched to
`parliament.senators` by name. Migration adds the table + grants. Wire into run.py weekly.
Fail-soft (a bad scrape = skip, never wipe). Movement: none needed (it's a fact table, not a
roster). Flag reliability — if sencanada.ca structure is hard, ship MPs first + senators when
the parser is verified.

## 5. Surfaces

1. **WTF per-member cost panel** (on the MP / senator page): the current-year cost + a 5-year
   stacked bar (indemnity vs office components) + the 5-year total. XSS-safe (textContent).
2. **WTF "Cost of Parliament" page** (`/cost` or a section): national total per year, the
   rising trend, per-member average, top-cost members — the "how much it costs Canadians"
   headline. All figures labelled approximate + sourced.
3. **Civic-watch transparency (cross-product):** each official on `/registry/<abbr>` +
   `/officials` shows their approximate annual cost, LINKED to the WTF cost page. Sourced via
   the cost API keyed by the shared-graph `entity_id` (WTF mps/senators.entity_id ↔
   civic entities). Read-only; behind the civic login like the rest of that surface.

## 6. Build phases

- **P1 (data-ready):** indemnity_rates table + seed (sourced) + cost.py + `/api/cost/*` +
  the WTF national "Cost of Parliament" view + per-MP panel. Verifies against mp_expenses.
- **P2:** Senate-expenditure ingest → senator_expenses → senators in the model + views.
- **P3:** cross-product surfacing on civic-watch via the entity graph + cost API.

## 7. Verification

Every figure cross-checked against the raw disclosure (spot-check 3 members vs the official
House/Senate/Library sources). National totals sanity-checked (2024 House ≈ $167M incl.
indemnity per the read-only probe). Public financial display → NO guessed numbers; the
indemnity table carries source URLs.
