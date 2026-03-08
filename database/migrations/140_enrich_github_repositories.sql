-- Migration 140: Enrich github_repositories with description, URLs, and fix indexed_files sync
-- Idempotent: safe to run multiple times

-- Add description and URL columns
ALTER TABLE github_repositories ADD COLUMN IF NOT EXISTS description TEXT;
ALTER TABLE github_repositories ADD COLUMN IF NOT EXISTS github_url TEXT;
ALTER TABLE github_repositories ADD COLUMN IF NOT EXISTS homepage_url TEXT;

-- Fix indexed_files to match actual knowledge_base counts
UPDATE github_repositories r
SET indexed_files = COALESCE(sub.actual_count, 0)
FROM (
    SELECT memory_metadata->>'repo' as repo,
           count(*) as actual_count
    FROM knowledge_base
    WHERE knowledge_type = 'github_file'
    GROUP BY memory_metadata->>'repo'
) sub
WHERE sub.repo = r.repo_name
  AND r.indexed_files IS DISTINCT FROM sub.actual_count;

-- Set repos with 0 KB entries to indexed_files = 0
UPDATE github_repositories
SET indexed_files = 0
WHERE repo_name NOT IN (
    SELECT DISTINCT memory_metadata->>'repo'
    FROM knowledge_base
    WHERE knowledge_type = 'github_file'
) AND indexed_files != 0;

-- Populate github_url from repo_name
UPDATE github_repositories
SET github_url = 'https://github.com/' || repo_name
WHERE github_url IS NULL;
