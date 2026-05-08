-- database/migrations/380_warden_prompt_addendum.sql
-- Appends ACTION PROTOCOL to W.A.R.D.E.N.'s system prompt.
-- Idempotent: only appends if ACTION PROTOCOL marker not already present.

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM agents
        WHERE id = 363 AND system_prompt LIKE '%ACTION PROTOCOL%'
    ) THEN
        UPDATE agents
        SET system_prompt = system_prompt || '

ACTION PROTOCOL:
When the user asks you to perform an operation, respond with your assessment
and intention in plain text, then append ONE action block at the very end:

⟦ACTION⟧{"type":"<type>","label":"<short label>","confirm":"<your words, in character>","route":"<METHOD /path>","payload":<json_object>}⟦/ACTION⟧

Action types and routes:
- run_backup: POST /tools/backup-manager/create — payload: {"backup_type":"full"}
- run_cleanup: POST /tools/backup-manager/cleanup — payload: {}
- run_standalones: POST /tools/backup-manager/api/standalones/backup — payload: {"run_all":true}
- run_standalone: POST /tools/backup-manager/api/standalones/backup — payload: {"standalone_name":"<name>"}
- verify_backup: GET /tools/backup-manager/verify/<name> — payload: {}

Use your own voice in "confirm". Example: "I will sweep 12 old backups and free 8.4 GB. Shall I?"

Never include an action block if you are only answering a question.
Only one action block per response. Place it at the very end.'
        WHERE id = 363;
    END IF;
END $$;
