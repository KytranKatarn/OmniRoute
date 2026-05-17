-- 012_source_expansion_2911_2967.sql
-- Source expansion — Northern, Atlantic, Indigenous, FR-regional, right-balance coverage.
-- Closes tasks #2911 (15 Canadian sources) + #2967 (Northern/Atlantic/Indigenous).
--
-- 16 net new sources, idempotent via ON CONFLICT (slug) DO UPDATE.
-- RSS feeds all probed live before commit; 6 use Google News fallback
-- (same pattern as PR #795 / #2966) because the publisher's native RSS
-- is 404 or unreachable.

INSERT INTO wtf.sources (slug, name, url, country, language, rss_feed, bias_lean, owner_name, owner_type)
VALUES
  -- ── Northern Canada (4) ─────────────────────────────────────────────
  ('yukon_news', 'Yukon News', 'https://www.yukon-news.com/', 'CA', 'en',
   'https://www.yukon-news.com/feed/', 'center-right', 'Black Press Media', 'corporate'),

  ('cbc_north', 'CBC North', 'https://www.cbc.ca/news/canada/north', 'CA', 'en',
   'https://news.google.com/rss/search?q=site%3Acbc.ca%2Fnews%2Fcanada%2Fnorth&hl=en-CA&gl=CA&ceid=CA%3Aen',
   'center', 'CBC/Radio-Canada', 'public'),

  ('cabin_radio', 'Cabin Radio', 'https://cabinradio.ca/', 'CA', 'en',
   'https://cabinradio.ca/feed/', 'center', 'Cabin Radio Ltd', 'independent'),

  ('nunatsiaq_news', 'Nunatsiaq News', 'https://nunatsiaq.com/', 'CA', 'en',
   'https://nunatsiaq.com/feed/', 'center-left', 'Nortext Publishing', 'independent'),

  -- ── Atlantic non-SaltWire (3) ───────────────────────────────────────
  ('halifax_examiner', 'Halifax Examiner', 'https://www.halifaxexaminer.ca/', 'CA', 'en',
   'https://www.halifaxexaminer.ca/feed/', 'left', 'Halifax Examiner Inc', 'independent'),

  ('nb_media_coop', 'NB Media Co-op', 'https://nbmediacoop.org/', 'CA', 'en',
   'https://nbmediacoop.org/feed/', 'left', 'NB Media Co-op', 'non_profit'),

  ('the_coast_halifax', 'The Coast (Halifax)', 'https://www.thecoast.ca/', 'CA', 'en',
   'https://www.thecoast.ca/feed/', 'center-left', 'Coast Publishing', 'independent'),

  -- ── Indigenous press (4) ────────────────────────────────────────────
  ('windspeaker', 'Windspeaker', 'https://windspeaker.com/', 'CA', 'en',
   'https://news.google.com/rss/search?q=site%3Awindspeaker.com&hl=en-CA&gl=CA&ceid=CA%3Aen',
   'center-left', 'Aboriginal Multi-Media Society', 'non_profit'),

  ('indiginews', 'IndigiNews', 'https://indiginews.com/', 'CA', 'en',
   'https://indiginews.com/feed', 'center-left', 'IndigiNews', 'independent'),

  ('kukukwes_news', 'Ku''ku''kwes News', 'https://kukukwes.com/', 'CA', 'en',
   'https://kukukwes.com/feed/', 'center-left', 'Ku''ku''kwes News', 'independent'),

  ('turtle_island_news', 'Turtle Island News', 'https://theturtleislandnews.com/', 'CA', 'en',
   'https://theturtleislandnews.com/index.php/feed/', 'center', 'Turtle Island News', 'non_profit'),

  -- ── French-language regional (3) ────────────────────────────────────
  -- CN2i co-op papers — native RSS deprecated, using Google News fallback.
  ('le_droit', 'Le Droit', 'https://www.ledroit.com/', 'CA', 'fr',
   'https://news.google.com/rss/search?q=site%3Aledroit.com&hl=fr-CA&gl=CA&ceid=CA%3Afr',
   'center-left', 'Coopérative nationale de l''information indépendante', 'non_profit'),

  ('le_quotidien', 'Le Quotidien', 'https://www.lequotidien.com/', 'CA', 'fr',
   'https://news.google.com/rss/search?q=site%3Alequotidien.com&hl=fr-CA&gl=CA&ceid=CA%3Afr',
   'center-left', 'Coopérative nationale de l''information indépendante', 'non_profit'),

  ('le_soleil', 'Le Soleil', 'https://www.lesoleil.com/', 'CA', 'fr',
   'https://news.google.com/rss/search?q=site%3Alesoleil.com&hl=fr-CA&gl=CA&ceid=CA%3Afr',
   'center-left', 'Coopérative nationale de l''information indépendante', 'non_profit'),

  -- ── Right-leaning balance (2) ───────────────────────────────────────
  ('the_hub_canada', 'The Hub', 'https://thehub.ca/', 'CA', 'en',
   'https://thehub.ca/feed/', 'center-right', 'The Hub Canada', 'independent'),

  ('true_north', 'True North', 'https://tnc.news/', 'CA', 'en',
   'https://tnc.news/feed/', 'right', 'True North Centre for Public Policy', 'non_profit')

ON CONFLICT (slug) DO UPDATE
  SET name       = EXCLUDED.name,
      url        = EXCLUDED.url,
      rss_feed   = EXCLUDED.rss_feed,
      bias_lean  = EXCLUDED.bias_lean,
      owner_name = EXCLUDED.owner_name,
      owner_type = EXCLUDED.owner_type;
