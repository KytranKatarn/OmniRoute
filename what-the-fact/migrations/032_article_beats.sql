-- 032_article_beats.sql
-- Beat/topic classification for articles and beat subscription registry

ALTER TABLE wtf.articles
  ADD COLUMN IF NOT EXISTS beat VARCHAR(64);

CREATE INDEX IF NOT EXISTS ix_articles_beat ON wtf.articles (beat)
  WHERE beat IS NOT NULL;

CREATE TABLE IF NOT EXISTS wtf.beats (
    slug            VARCHAR(64) PRIMARY KEY,
    name            VARCHAR(128) NOT NULL,
    description     TEXT,
    stripe_price_id TEXT,
    active          BOOLEAN NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

INSERT INTO wtf.beats (slug, name, description) VALUES
  ('housing',       'Housing',           'Affordability, rental market, real estate policy'),
  ('climate',       'Climate',           'Environment, emissions, energy transition'),
  ('healthcare',    'Healthcare',        'Public health, OHIP, hospital capacity, drugs'),
  ('economy',       'Economy',           'Inflation, interest rates, jobs, trade'),
  ('parliament',    'Parliament',        'House of Commons, Senate, legislation'),
  ('immigration',   'Immigration',       'Refugees, IRCC, border, citizenship'),
  ('indigenous',    'Indigenous',        'First Nations, Métis, Inuit, treaty rights'),
  ('crime',         'Crime & Justice',   'Policing, courts, public safety'),
  ('education',     'Education',         'K-12, universities, student debt'),
  ('foreign-policy','Foreign Policy',    'Canada-US, NATO, international relations')
ON CONFLICT (slug) DO NOTHING;
