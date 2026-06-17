-- 439_fix_brand_colors.sql — correct Watch Series brand accents to match the
-- live site icons/favicons (migration 438 seeded placeholder colors).
UPDATE media_brands SET accent_color = '#f97316' WHERE id = 3;  -- Gov Watch (orange)
UPDATE media_brands SET accent_color = '#ffd740' WHERE id = 4;  -- Civic Watch (gold)
UPDATE media_brands SET accent_color = '#8b5cf6' WHERE id = 5;  -- Legal Watch (purple)
UPDATE media_brands SET accent_color = '#10b981' WHERE id = 6;  -- Market Watch (emerald)
UPDATE media_brands SET accent_color = '#e63946' WHERE id = 7;  -- What The Fact (red)
