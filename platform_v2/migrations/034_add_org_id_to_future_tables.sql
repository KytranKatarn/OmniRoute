-- 034_add_org_id_to_future_tables.sql
-- Add org_id to crm_contacts and scheduled_events if they exist.
-- These tables may not exist yet; the DO blocks handle that gracefully.

-- crm_contacts
DO $$ BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'crm_contacts')
       AND NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'crm_contacts' AND column_name = 'org_id')
    THEN
        ALTER TABLE crm_contacts ADD COLUMN org_id INTEGER REFERENCES organizations(id) ON DELETE SET NULL;
        CREATE INDEX IF NOT EXISTS idx_crm_contacts_org ON crm_contacts(org_id);
        RAISE NOTICE 'Added org_id to crm_contacts';
    END IF;
END $$;

-- scheduled_events
DO $$ BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'scheduled_events')
       AND NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'scheduled_events' AND column_name = 'org_id')
    THEN
        ALTER TABLE scheduled_events ADD COLUMN org_id INTEGER REFERENCES organizations(id) ON DELETE SET NULL;
        CREATE INDEX IF NOT EXISTS idx_scheduled_events_org ON scheduled_events(org_id);
        RAISE NOTICE 'Added org_id to scheduled_events';
    END IF;
END $$;

-- Assign existing data to Kytran Empowerment (if tables exist and have data)
DO $$
DECLARE
    ke_org_id INTEGER;
BEGIN
    SELECT id INTO ke_org_id FROM organizations WHERE slug = 'kytran-empowerment';
    IF ke_org_id IS NOT NULL THEN
        IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'crm_contacts') THEN
            EXECUTE 'UPDATE crm_contacts SET org_id = $1 WHERE org_id IS NULL' USING ke_org_id;
        END IF;
        IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'scheduled_events') THEN
            EXECUTE 'UPDATE scheduled_events SET org_id = $1 WHERE org_id IS NULL' USING ke_org_id;
        END IF;
    END IF;
END $$;
