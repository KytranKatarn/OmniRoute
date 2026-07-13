-- Migration 039: Parliamentary indemnity & salary reference rates
-- Project #348 / "What Parliament Costs Canadians" — Phase 1 (data-ready cost model).
-- Run: psql $WTF_DATABASE_URL < 039_indemnity_rates.sql   (idempotent)
--
-- WHY: to show taxpayers the approximate annual + 5-year cost of each MP/senator we need
-- the base SALARY (sessional indemnity) + role top-ups as a published yearly constant,
-- alongside the office expenses already in parliament.mp_expenses. These figures are shown
-- PUBLICLY, so every amount is SOURCED (never guessed) and carries source_url for audit.
-- Stored in a small reference table so the numbers are updatable each April 1 without code.
--
-- ROLE VOCABULARY (role column):
--   mp             — MP basic sessional indemnity (backbencher salary)
--   senator        — Senator basic sessional indemnity (used in Phase 2; MP - $25,000 fixed differential)
--   minister_topup — ADDITIONAL salary for a Cabinet minister (= minister total - mp base)
--   pm_topup       — ADDITIONAL salary for the Prime Minister (PM total salary = exactly 2x the mp base)
--   speaker_topup  — ADDITIONAL salary for the Speaker (paid at minister level; = minister_topup)
--
-- fiscal_year = the year the rate takes effect (April 1 of that year -> March 31 of the next).
-- The cost model keys it to the calendar-year prefix of parliament.mp_expenses.period
-- ('YYYY-Qn'); a small calendar-vs-fiscal offset within a year is accepted + labelled
-- "approximate" (honesty rail — office totals also exclude pensions and central costs).
--
-- SOURCES (all figures below):
--   Canonical register: Library of Parliament, ParlInfo — "Indemnities, Salaries and
--     Allowances": https://lop.parl.ca/sites/ParlInfo/default/en_CA/People/Salaries
--   Mechanism: House of Commons Procedure & Practice, 4th ed., ch.4 (sessional allowance +
--     additional salaries adjusted every April 1 by the private-sector wage index; amounts
--     rounded DOWN to the nearest $100):
--     https://www.ourcommons.ca/procedure-and-practice-4/ch04-9-e.html
--   Per-year MP base + minister/PM totals corroborated by:
--     2022 MP $189,500  — OSFI 15th Actuarial Report on the MP Pension Plan (as at 31 Mar 2022)
--     2022 min $279,900 / PM $379,000 — Canadian Taxpayers Federation (Apr-2022 raise +$5,100 backbench)
--     2023 MP $194,600 / min $287,400 / PM $389,200 — CBC (cbc.ca/news/politics/canadian-politicians-pay-increase-1.7160362) + The Hill Times
--     2024 MP $203,100 / min $299,900 / PM $406,200 — OpenCouncil / CBC / Parliament of Canada Act; matches the live mp_expenses probe (219 MPs, office $122.4M + 219 x $203.1k = ~$167M)
--     2025 MP $209,800 / min $308,800 / PM $419,600 — The Hill Times (2025-05-12, official post-index: Carney $419,600 = 2x $209,800)
--   Derivation rules used (both verified against confirmed anchors):
--     * pm_topup = mp base           (PM total = 2x base: $379,000/$389,200/$406,200/$419,600 = 2x each year)
--     * senator = mp base - $25,000  (fixed differential: 2023 senator $169,600 and 2025 senator $184,800 both confirm)
--   FLAGGED (best-documented, lower confidence):
--     * 2021 mp $184,400 — derived: confirmed 2022 $189,500 minus the confirmed +$5,100 Apr-2022 backbench raise (some secondary sources cite $185,800).
--     * 2021 minister_topup/speaker_topup $90,400 — the confirmed 2022 rate used as the adjacent-year proxy (exact Apr-2021 minister total not independently sourced). Note: current cabinet_role has no historical dimension, so pre-2025 top-ups are inherently approximate.

CREATE TABLE IF NOT EXISTS parliament.indemnity_rates (
    fiscal_year INT     NOT NULL,          -- year the rate takes effect (Apr 1 .. Mar 31)
    role        TEXT    NOT NULL,          -- mp | senator | minister_topup | pm_topup | speaker_topup
    amount_cad  NUMERIC NOT NULL,          -- annual amount in CAD
    source_url  TEXT,                      -- authoritative source for the figure
    PRIMARY KEY (fiscal_year, role)
);

COMMENT ON TABLE parliament.indemnity_rates IS
  'Sourced reference rates (MP/senator sessional indemnity + PM/minister/Speaker top-ups) by fiscal year, for the "What Parliament Costs Canadians" cost model. Public-facing figures — every row carries source_url. Migration 039 / project #348.';

-- Idempotent upsert of the SOURCED seed (safe to re-run; updates amount + source if changed).
INSERT INTO parliament.indemnity_rates (fiscal_year, role, amount_cad, source_url) VALUES
  -- MP basic sessional indemnity (backbencher salary)
  (2021, 'mp', 184400, 'https://lop.parl.ca/sites/ParlInfo/default/en_CA/People/Salaries'),
  (2022, 'mp', 189500, 'https://lop.parl.ca/sites/ParlInfo/default/en_CA/People/Salaries'),
  (2023, 'mp', 194600, 'https://lop.parl.ca/sites/ParlInfo/default/en_CA/People/Salaries'),
  (2024, 'mp', 203100, 'https://lop.parl.ca/sites/ParlInfo/default/en_CA/People/Salaries'),
  (2025, 'mp', 209800, 'https://lop.parl.ca/sites/ParlInfo/default/en_CA/People/Salaries'),
  -- Prime Minister ADDITIONAL salary (pm_topup) = mp base each year (PM total = 2x base)
  (2021, 'pm_topup', 184400, 'https://lop.parl.ca/sites/ParlInfo/default/en_CA/People/Salaries'),
  (2022, 'pm_topup', 189500, 'https://lop.parl.ca/sites/ParlInfo/default/en_CA/People/Salaries'),
  (2023, 'pm_topup', 194600, 'https://lop.parl.ca/sites/ParlInfo/default/en_CA/People/Salaries'),
  (2024, 'pm_topup', 203100, 'https://lop.parl.ca/sites/ParlInfo/default/en_CA/People/Salaries'),
  (2025, 'pm_topup', 209800, 'https://lop.parl.ca/sites/ParlInfo/default/en_CA/People/Salaries'),
  -- Cabinet minister ADDITIONAL salary (minister_topup) = minister total - mp base
  (2021, 'minister_topup', 90400, 'https://lop.parl.ca/sites/ParlInfo/default/en_CA/People/Salaries'),
  (2022, 'minister_topup', 90400, 'https://lop.parl.ca/sites/ParlInfo/default/en_CA/People/Salaries'),
  (2023, 'minister_topup', 92800, 'https://lop.parl.ca/sites/ParlInfo/default/en_CA/People/Salaries'),
  (2024, 'minister_topup', 96800, 'https://lop.parl.ca/sites/ParlInfo/default/en_CA/People/Salaries'),
  (2025, 'minister_topup', 99000, 'https://lop.parl.ca/sites/ParlInfo/default/en_CA/People/Salaries'),
  -- Speaker ADDITIONAL salary (speaker_topup) — paid at minister level
  (2021, 'speaker_topup', 90400, 'https://lop.parl.ca/sites/ParlInfo/default/en_CA/People/Salaries'),
  (2022, 'speaker_topup', 90400, 'https://lop.parl.ca/sites/ParlInfo/default/en_CA/People/Salaries'),
  (2023, 'speaker_topup', 92800, 'https://lop.parl.ca/sites/ParlInfo/default/en_CA/People/Salaries'),
  (2024, 'speaker_topup', 96800, 'https://lop.parl.ca/sites/ParlInfo/default/en_CA/People/Salaries'),
  (2025, 'speaker_topup', 99000, 'https://lop.parl.ca/sites/ParlInfo/default/en_CA/People/Salaries'),
  -- Senator basic sessional indemnity (Phase 2) = mp base - $25,000 (fixed differential)
  (2021, 'senator', 159400, 'https://lop.parl.ca/sites/ParlInfo/default/en_CA/People/Salaries'),
  (2022, 'senator', 164500, 'https://lop.parl.ca/sites/ParlInfo/default/en_CA/People/Salaries'),
  (2023, 'senator', 169600, 'https://lop.parl.ca/sites/ParlInfo/default/en_CA/People/Salaries'),
  (2024, 'senator', 178100, 'https://lop.parl.ca/sites/ParlInfo/default/en_CA/People/Salaries'),
  (2025, 'senator', 184800, 'https://lop.parl.ca/sites/ParlInfo/default/en_CA/People/Salaries')
ON CONFLICT (fiscal_year, role) DO UPDATE
  SET amount_cad = EXCLUDED.amount_cad,
      source_url = EXCLUDED.source_url;

-- LEAST PRIVILEGE: indemnity_rates is REFERENCE data. The app only READS it (the cost model
-- looks up rates); it never writes. wtfuser therefore gets SELECT ONLY -- never INSERT/UPDATE/
-- DELETE -- so a bug or a compromise of the consumer/ingest can't tamper with the public
-- salary figures. The REVOKE self-heals any DB that previously received a broader grant.
REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON parliament.indemnity_rates FROM wtfuser;
GRANT SELECT ON parliament.indemnity_rates TO wtfuser;
