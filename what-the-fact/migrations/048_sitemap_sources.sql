-- 048_sitemap_sources.sql — reactivate the 3 RSS-less Postmedia sources via
-- their open sitemap indexes (#4909). The 'sitemap:' prefix routes the
-- generic ingest loop to ingest/sources/sitemap_generic.py instead of the
-- RSS fetcher. Idempotent.

UPDATE wtf.sources SET rss_feed = 'sitemap:https://montrealgazette.com/sitemap.xml'
WHERE slug = 'montreal_gazette';

UPDATE wtf.sources SET rss_feed = 'sitemap:https://leaderpost.com/sitemap.xml'
WHERE slug = 'regina_leaderpost';

UPDATE wtf.sources SET rss_feed = 'sitemap:https://thestarphoenix.com/sitemap.xml'
WHERE slug = 'saskatoon_starphoenix';
