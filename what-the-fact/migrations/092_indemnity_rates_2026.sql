-- 092_indemnity_rates_2026.sql — the April 1, 2026 indemnity / salary rates.
--
-- ⚠️ APPLIES TO CITADEL (what-the-fact-wtf-postgres-1, wtfuser/wtf), NOT the hub. See README.md.
--
-- WHY: parliament.indemnity_rates stopped at fiscal_year 2025, so the 2026 year-to-date on /cost had NO base
-- salary: House $107.3M (mp_indemnity 0) + Senate $4.4M (office only) = $111.7M against $248.0M for 2025, and the
-- projected full year ($226.8M) was understated the same way. Task #7130. When 2026 completes (~Feb 2027) the
-- same gap would have put a full year with zero salary INTO the 5-year headline.
--
-- Roles are the ones migration 039 defines (fiscal_year = the year the rate takes effect, April 1 .. March 31):
--   mp             basic sessional allowance
--   minister_topup ADDITIONAL salary for a Cabinet minister      (minister total = mp + this)
--   pm_topup       ADDITIONAL salary for the Prime Minister      (PM total = 2 x mp)
--   speaker_topup  ADDITIONAL salary for the Speaker             (paid at the minister level)
--   senator        senator basic sessional indemnity
--
-- SOURCES (read 2026-10-06, not estimated):
--   House of Commons, Board of Internal Economy — "Sessional allowance and additional salaries":
--     https://www.ourcommons.ca/boie/en/by-laws-and-policies/mas/allowance-and-additional-salaries
--     "...came into effect on April 1, 2026, rounded down to the nearest hundred dollars as per section 67 of
--     the Parliament of Canada Act": Members (sessional allowance) 217,700 · Prime Minister 217,700 (additional) ·
--     Speaker / Cabinet Ministers 103,600 (additional).
--   Cross-check: minister total 217,700 + 103,600 = 321,300 and PM total 2 x 217,700 = 435,400 — the figures
--     press reports gave for 2026 (CTF: MP raise $7,900 = 217,700 - 209,800, PM $15,800 = 435,400 - 419,600).
--   senator 192,700 = mp 217,700 - 25,000. Same fixed differential migration 039 confirmed against the 2023
--     ($169,600) and 2025 ($184,800) senator figures; a press report of the 2026 senate base gives $192,700.
--     FLAGGED lower confidence than the House rows: the Senate-side page was not readable (lop.parl.ca blocks
--     datacentre clients), so this row is the confirmed differential applied to the confirmed 2026 MP base.
--
-- Idempotent upsert (re-runnable).

INSERT INTO parliament.indemnity_rates (fiscal_year, role, amount_cad, source_url) VALUES
  (2026, 'mp',             217700, 'https://www.ourcommons.ca/boie/en/by-laws-and-policies/mas/allowance-and-additional-salaries'),
  (2026, 'minister_topup', 103600, 'https://www.ourcommons.ca/boie/en/by-laws-and-policies/mas/allowance-and-additional-salaries'),
  (2026, 'pm_topup',       217700, 'https://www.ourcommons.ca/boie/en/by-laws-and-policies/mas/allowance-and-additional-salaries'),
  (2026, 'speaker_topup',  103600, 'https://www.ourcommons.ca/boie/en/by-laws-and-policies/mas/allowance-and-additional-salaries'),
  (2026, 'senator',        192700, 'https://www.ourcommons.ca/boie/en/by-laws-and-policies/mas/allowance-and-additional-salaries (mp - 25,000 differential; see migration 039)')
ON CONFLICT (fiscal_year, role) DO UPDATE
  SET amount_cad = EXCLUDED.amount_cad, source_url = EXCLUDED.source_url;

INSERT INTO public.schema_migrations (version, filename, description, applied_at)
VALUES ('092', '092_indemnity_rates_2026.sql',
        'April 1 2026 MP / minister / PM / Speaker / senator indemnity rates (House of Commons BOIE)', now())
ON CONFLICT (version) DO NOTHING;
