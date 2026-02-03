-- 033_fix_migration_status_constraint.sql
-- Add CHECK constraint on organizations.migration_status that was missing from 030.

DO $$ BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.check_constraints
        WHERE constraint_name = 'organizations_migration_status_check'
    ) THEN
        ALTER TABLE organizations ADD CONSTRAINT organizations_migration_status_check
            CHECK (migration_status IN ('exporting', 'provisioning', 'importing', 'verifying', 'complete'));
    END IF;
END $$;
