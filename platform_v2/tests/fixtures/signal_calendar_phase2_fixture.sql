-- SIGNAL Calendar Phase 2 visual verification fixture.
-- Seeds one autonomy_approval_queue row per status for account='company'
-- spread across the current week. Idempotent — uses fixed reason markers so
-- DELETE-by-marker can clean up before re-insert.

BEGIN;

-- Clean any prior fixture rows
DELETE FROM autonomy_approval_queue
 WHERE reason LIKE '[PHASE2_FIXTURE]%';

-- 1. POSTED (Monday this week, EN)
INSERT INTO autonomy_approval_queue
    (action_type, action_data, status, reason, created_at, approved_at, executed_at, execution_result, telegram_message_id)
VALUES
    ('linkedin_post',
     '{"post_type":"company","language":"en","content":"[PHASE2_FIXTURE] posted EN sample content"}'::jsonb,
     'executed',
     '[PHASE2_FIXTURE] posted EN',
     date_trunc('week', CURRENT_DATE) + interval '0 day' + interval '13 hours',
     date_trunc('week', CURRENT_DATE) + interval '0 day' + interval '13 hours 5 min',
     date_trunc('week', CURRENT_DATE) + interval '0 day' + interval '13 hours 10 min',
     '{"success":true,"_status":"posted"}'::jsonb,
     9001);

-- 2. PENDING (today, FR)
INSERT INTO autonomy_approval_queue
    (action_type, action_data, status, reason, created_at, telegram_message_id)
VALUES
    ('linkedin_post',
     '{"post_type":"company","language":"fr","content":"[PHASE2_FIXTURE] ⚜️ pending FR contenu test"}'::jsonb,
     'pending',
     '[PHASE2_FIXTURE] pending FR ⚜️',
     CURRENT_DATE + interval '9 hours',
     9002);

-- 3. EXECUTING (today, EN)
INSERT INTO autonomy_approval_queue
    (action_type, action_data, status, reason, created_at, approved_at, telegram_message_id)
VALUES
    ('linkedin_post',
     '{"post_type":"company","language":"en","content":"[PHASE2_FIXTURE] executing EN sample"}'::jsonb,
     'approved',
     '[PHASE2_FIXTURE] executing EN',
     CURRENT_DATE + interval '8 hours',
     CURRENT_DATE + interval '8 hours 5 min',
     9003);

-- 4. FAILED (Tuesday this week, EN)
INSERT INTO autonomy_approval_queue
    (action_type, action_data, status, reason, created_at, approved_at, executed_at, execution_result, telegram_message_id)
VALUES
    ('linkedin_post',
     '{"post_type":"company","language":"en","content":"[PHASE2_FIXTURE] failed EN sample"}'::jsonb,
     'executed',
     '[PHASE2_FIXTURE] failed EN',
     date_trunc('week', CURRENT_DATE) + interval '1 day' + interval '9 hours',
     date_trunc('week', CURRENT_DATE) + interval '1 day' + interval '9 hours 5 min',
     date_trunc('week', CURRENT_DATE) + interval '1 day' + interval '9 hours 6 min',
     '{"success":false,"error":"Could not find Start a post button"}'::jsonb,
     9004);

-- 5. REJECTED (Wednesday this week, FR)
INSERT INTO autonomy_approval_queue
    (action_type, action_data, status, reason, created_at, telegram_message_id)
VALUES
    ('linkedin_post',
     '{"post_type":"company","language":"fr","content":"[PHASE2_FIXTURE] ⚜️ rejected FR contenu"}'::jsonb,
     'rejected',
     '[PHASE2_FIXTURE] rejected FR ⚜️',
     date_trunc('week', CURRENT_DATE) + interval '2 day' + interval '10 hours',
     9005);

-- (deferred state from Layer A Phase 4 — skip for now; design notes deferred is post-v1)

COMMIT;

-- Verify
SELECT id, status, reason, created_at::date AS d
  FROM autonomy_approval_queue
 WHERE reason LIKE '[PHASE2_FIXTURE]%'
 ORDER BY created_at;
