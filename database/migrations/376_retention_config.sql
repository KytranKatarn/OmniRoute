INSERT INTO system_config (key, value, updated_at)
VALUES
    ('retention_daily',   '7',  NOW()),
    ('retention_weekly',  '4',  NOW()),
    ('retention_monthly', '6',  NOW())
ON CONFLICT (key) DO NOTHING;
