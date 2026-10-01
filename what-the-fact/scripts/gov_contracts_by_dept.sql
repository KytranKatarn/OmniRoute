-- Run INSIDE gov_watch_db (Citadel). Emits one row per (department, signing year).
--
-- WHAT THIS MEASURES — and what it deliberately does not:
--   "Contracts signed": the value AT SIGNING (original_value) of each contract, counted once,
--   in the calendar year it was signed. It is a COMMITMENT measure, not spending: the
--   disclosures carry no payments, and a multi-year contract counts in full in its first year.
--
-- WHY THE DE-DUPLICATION (measured 2026-10-01, not assumed): the proactive-disclosure file
-- re-reports a contract in later quarters (SkyAlyne's $11.2B appears under both 2024-25 Q2 and
-- 2025-26 Q4 with the same date and value). Grouping by REPORTING period would roughly double
-- the total (≈$100B/yr vs ≈$20-36B/yr once each contract is counted once). A contract is
-- identified by (owner_org, vendor, contract_date, original_value).
--
-- WHY original_value, not contract_value: contract_value is the amended total and carries data-
-- entry errors (one row reads $20.0B against $15M signed). Amendments are excluded on purpose.
--
-- The department is NOT buyer_name (blank/"NA"/a person's name on ~75% of rows); it is the
-- raw_row owner_org / owner_org_title the source file supplies.
COPY (
  WITH c AS (
    SELECT DISTINCT ON (raw_row->>'owner_org', vendor_name, contract_date, original_value)
           raw_row->>'owner_org'                          AS owner_org,
           split_part(raw_row->>'owner_org_title', ' | ', 1) AS title_en,
           contract_date,
           original_value
      FROM proactive_disclosures
     WHERE contract_date IS NOT NULL
       AND contract_date <= current_date          -- a signing date in the future is an entry error
       AND contract_date >= DATE '2004-01-01'     -- series is usable from Dec 2003 (gov-watch.md)
       AND original_value IS NOT NULL
       AND original_value >= 0
       AND coalesce(raw_row->>'owner_org', '') <> ''
  )
  SELECT owner_org,
         max(title_en)                         AS title_en,
         extract(year FROM contract_date)::int AS year,
         count(*)                              AS n_contracts,
         sum(original_value)                   AS signed_value,
         max(original_value)                   AS largest_value
    FROM c
   GROUP BY owner_org, extract(year FROM contract_date)
   ORDER BY 3, 1
) TO STDOUT WITH CSV;
