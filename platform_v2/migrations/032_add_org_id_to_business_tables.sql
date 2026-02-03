-- 032_add_org_id_to_business_tables.sql
-- Add org_id to per-organization business tables for multi-tenant scoping.
-- All org_id columns are nullable (existing data stays untouched until assigned).

-- user_stores
DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'user_stores' AND column_name = 'org_id') THEN
        ALTER TABLE user_stores ADD COLUMN org_id INTEGER REFERENCES organizations(id) ON DELETE SET NULL;
        CREATE INDEX IF NOT EXISTS idx_user_stores_org ON user_stores(org_id);
        RAISE NOTICE 'Added org_id to user_stores';
    END IF;
END $$;

-- store_products
DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'store_products' AND column_name = 'org_id') THEN
        ALTER TABLE store_products ADD COLUMN org_id INTEGER REFERENCES organizations(id) ON DELETE SET NULL;
        CREATE INDEX IF NOT EXISTS idx_store_products_org ON store_products(org_id);
        RAISE NOTICE 'Added org_id to store_products';
    END IF;
END $$;

-- store_orders
DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'store_orders' AND column_name = 'org_id') THEN
        ALTER TABLE store_orders ADD COLUMN org_id INTEGER REFERENCES organizations(id) ON DELETE SET NULL;
        CREATE INDEX IF NOT EXISTS idx_store_orders_org ON store_orders(org_id);
        RAISE NOTICE 'Added org_id to store_orders';
    END IF;
END $$;

-- website_builder_projects
DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'website_builder_projects' AND column_name = 'org_id') THEN
        ALTER TABLE website_builder_projects ADD COLUMN org_id INTEGER REFERENCES organizations(id) ON DELETE SET NULL;
        CREATE INDEX IF NOT EXISTS idx_website_projects_org ON website_builder_projects(org_id);
        RAISE NOTICE 'Added org_id to website_builder_projects';
    END IF;
END $$;

-- website_builder_pages
DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'website_builder_pages' AND column_name = 'org_id') THEN
        ALTER TABLE website_builder_pages ADD COLUMN org_id INTEGER REFERENCES organizations(id) ON DELETE SET NULL;
        CREATE INDEX IF NOT EXISTS idx_website_pages_org ON website_builder_pages(org_id);
        RAISE NOTICE 'Added org_id to website_builder_pages';
    END IF;
END $$;

-- invoices
DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'invoices' AND column_name = 'org_id') THEN
        ALTER TABLE invoices ADD COLUMN org_id INTEGER REFERENCES organizations(id) ON DELETE SET NULL;
        CREATE INDEX IF NOT EXISTS idx_invoices_org ON invoices(org_id);
        RAISE NOTICE 'Added org_id to invoices';
    END IF;
END $$;

-- Assign all existing data to Kytran Empowerment (first and only org)
DO $$
DECLARE
    ke_org_id INTEGER;
BEGIN
    SELECT id INTO ke_org_id FROM organizations WHERE slug = 'kytran-empowerment';
    IF ke_org_id IS NOT NULL THEN
        UPDATE user_stores SET org_id = ke_org_id WHERE org_id IS NULL;
        UPDATE store_products SET org_id = ke_org_id WHERE org_id IS NULL;
        UPDATE store_orders SET org_id = ke_org_id WHERE org_id IS NULL;
        UPDATE website_builder_projects SET org_id = ke_org_id WHERE org_id IS NULL;
        UPDATE website_builder_pages SET org_id = ke_org_id WHERE org_id IS NULL;
        UPDATE invoices SET org_id = ke_org_id WHERE org_id IS NULL;
        RAISE NOTICE 'Assigned existing data to Kytran Empowerment (org_id=%)', ke_org_id;
    END IF;
END $$;
