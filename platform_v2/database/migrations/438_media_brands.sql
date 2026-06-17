-- 438_media_brands.sql — multi-brand registry for Media Studio
-- Brand assets are media_library rows with owner_type='brand' and owner_id=<media_brands.id>.
-- Lets the Gallery show a brand section per product (Kytran Empowerment, C.R.E.E.D., the Watch Series)
-- instead of a single hard-coded "Kytran Empowerment" brand.

CREATE TABLE IF NOT EXISTS media_brands (
    id           SERIAL PRIMARY KEY,
    name         VARCHAR(120) NOT NULL,
    slug         VARCHAR(120) UNIQUE NOT NULL,
    accent_color VARCHAR(16)  DEFAULT '#22c55e',
    description  TEXT,
    created_at   TIMESTAMPTZ  DEFAULT NOW()
);

INSERT INTO media_brands (id, name, slug, accent_color, description) VALUES
  (1, 'Kytran Empowerment', 'kytran-empowerment', '#22c55e', 'Kytran Empowerment Inc. — parent brand'),
  (2, 'C.R.E.E.D.',         'creed',              '#c9a44c', 'C.R.E.E.D. Institute — AI ethics governance nonprofit (creed-ai.org)'),
  (3, 'Gov Watch',          'gov-watch',          '#3b82f6', 'Federal procurement & tender intelligence'),
  (4, 'Civic Watch',        'civic-watch',        '#8b5cf6', 'Municipal & civic spending transparency'),
  (5, 'Legal Watch',        'legal-watch',        '#f59e0b', 'Courts, rulings & regulatory intelligence'),
  (6, 'Market Watch',       'market-watch',       '#10b981', 'Securities, filings & market reaction'),
  (7, 'What The Fact',      'what-the-fact',      '#00bcd4', 'News bias scoring & fact-checking')
ON CONFLICT (id) DO NOTHING;

-- keep the sequence ahead of the seeded ids
SELECT setval('media_brands_id_seq', GREATEST((SELECT MAX(id) FROM media_brands), 1), true);
