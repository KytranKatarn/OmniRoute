-- 052: index the lobbying org leaderboard.
--
-- /lobbying (#3047) groups 67,985 parliament.lobbyist_contacts rows by
-- normalized client_org. Existing indexes cover (mp_id) and
-- (communication_date) only, so the org aggregates were seq scans.
-- Functional index matches the query's GROUP BY expression byte-identically
-- (upper(btrim(client_org))) — a plain btree on client_org would not be used.
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_lobbyist_org_norm
    ON parliament.lobbyist_contacts (upper(btrim(client_org)));

-- Recent-activity + "last 12 months" panels filter on date and then join mps.
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_lobbyist_date_mp
    ON parliament.lobbyist_contacts (communication_date DESC, mp_id);
