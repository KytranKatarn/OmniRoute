-- 459_staging_smoke_qa_suite.sql
-- Self-heal deploy gate (#4930): proposal_service._sandbox_gate applies a
-- proposal's fix to the archie_staging worktree, restarts staging, then runs
-- P.R.O.B.E. QA suite #79 against it. Suite #79 never existed, so run_suite(79)
-- raised and the gate errored (fail-closed) on EVERY deploy — the pipeline could
-- never validate or deploy anything.
--
-- This creates a minimal staging SMOKE suite: after a fix is applied, archie_staging
-- must still boot and serve. type:api tests are plain authenticated-skipped HTTP GETs
-- (no browser); base_url is the in-cluster staging container, reachable from
-- archie_platform (verified: /health, /, /login all 200). No `auth` block => execute_spec
-- does not attempt a suite-level login (qa_spec_runner.py:114), matching the gate's
-- call signature run_suite(79) (session=None, skip_auth=False).
--
-- Idempotent: safe to re-run. id=79 is a backfill below the current sequence (max 102),
-- so it does not disturb nextval.

INSERT INTO qa_test_suites (id, name, description, target_url, spec, suite_type, is_active)
VALUES (
    79,
    'staging-smoke',
    'Self-heal deploy gate — archie_staging boots + serves after a fix is applied (#4930)',
    'http://archie_staging:3000',
    '{
      "suite": {
        "name": "staging-smoke",
        "base_url": "http://archie_staging:3000",
        "description": "Self-heal deploy gate smoke — archie_staging must boot + serve after a proposal fix is applied (#4930)"
      },
      "tests": [
        {"name": "health-endpoint", "path": "/health", "type": "api", "method": "GET", "skip_auth": true, "critical": true, "expect": {"status": [200]}},
        {"name": "home-serves", "path": "/", "type": "api", "method": "GET", "skip_auth": true, "expect": {"status": [200, 302]}},
        {"name": "login-renders", "path": "/login", "type": "api", "method": "GET", "skip_auth": true, "expect": {"status": [200]}}
      ]
    }'::jsonb,
    'internal',
    true
)
ON CONFLICT (id) DO UPDATE SET
    name        = EXCLUDED.name,
    description = EXCLUDED.description,
    target_url  = EXCLUDED.target_url,
    spec        = EXCLUDED.spec,
    suite_type  = EXCLUDED.suite_type,
    is_active   = true,
    updated_at  = NOW();
