-- 037_naics_codes.sql — Shared Entity Graph NAICS sector reference (Phase 0).
--
-- Captures into git the NAICS Canada 2022 sector dimension + sector-resolver that
-- were applied live to the hub `wtf` DB on 2026-06-25 (ADR-EG-001 amendment,
-- decision #843). Reproducibility fix: these objects existed in the DB but not in
-- any migration. Idempotent — safe to re-run.
--
-- naics_sector_for(code) maps any 2–6 digit NAICS code to its top-level sector,
-- handling the combined 31-33 / 44-45 / 48-49 ranges via the `prefixes` array.

CREATE SCHEMA IF NOT EXISTS shared;

CREATE TABLE IF NOT EXISTS shared.naics_codes (
    code         text NOT NULL,
    code_kind    text NOT NULL,
    label        text NOT NULL,
    sector_code  text NOT NULL,
    sector_label text NOT NULL,
    prefixes     text[],
    source       text DEFAULT 'NAICS Canada 2022',
    loaded_at    timestamptz DEFAULT now(),
    PRIMARY KEY (code)
);

INSERT INTO shared.naics_codes (code, code_kind, label, sector_code, sector_label, prefixes) VALUES
  ('11','sector','Agriculture, forestry, fishing and hunting','11','Agriculture, forestry, fishing and hunting','{11}'),
  ('21','sector','Mining, quarrying, and oil and gas extraction','21','Mining, quarrying, and oil and gas extraction','{21}'),
  ('22','sector','Utilities','22','Utilities','{22}'),
  ('23','sector','Construction','23','Construction','{23}'),
  ('31-33','sector','Manufacturing','31-33','Manufacturing','{31,32,33}'),
  ('41','sector','Wholesale trade','41','Wholesale trade','{41}'),
  ('44-45','sector','Retail trade','44-45','Retail trade','{44,45}'),
  ('48-49','sector','Transportation and warehousing','48-49','Transportation and warehousing','{48,49}'),
  ('51','sector','Information and cultural industries','51','Information and cultural industries','{51}'),
  ('52','sector','Finance and insurance','52','Finance and insurance','{52}'),
  ('53','sector','Real estate and rental and leasing','53','Real estate and rental and leasing','{53}'),
  ('54','sector','Professional, scientific and technical services','54','Professional, scientific and technical services','{54}'),
  ('55','sector','Management of companies and enterprises','55','Management of companies and enterprises','{55}'),
  ('56','sector','Administrative and support, waste management and remediation services','56','Administrative and support, waste management and remediation services','{56}'),
  ('61','sector','Educational services','61','Educational services','{61}'),
  ('62','sector','Health care and social assistance','62','Health care and social assistance','{62}'),
  ('71','sector','Arts, entertainment and recreation','71','Arts, entertainment and recreation','{71}'),
  ('72','sector','Accommodation and food services','72','Accommodation and food services','{72}'),
  ('81','sector','Other services (except public administration)','81','Other services (except public administration)','{81}'),
  ('91','sector','Public administration','91','Public administration','{91}')
ON CONFLICT (code) DO NOTHING;

CREATE OR REPLACE FUNCTION shared.naics_sector_for(p_code text)
 RETURNS text
 LANGUAGE sql
 IMMUTABLE
AS $function$
    SELECT sector_code FROM shared.naics_codes
    WHERE code_kind='sector'
      AND left(regexp_replace(coalesce(p_code,''),'\D','','g'),2) = ANY(prefixes)
    LIMIT 1;
$function$;
