-- REVERT for the 2026-08-25 USS-245 cap raise (3 -> 5), made while USS-246 was down
-- for maintenance. Restore once USS-246 is back and carrying volume again.
UPDATE remote_nodes SET max_concurrent = 3 WHERE node_name ILIKE '%245%' RETURNING node_name, max_concurrent;
