-- Add direction, order_type, trail_percent to open_positions
ALTER TABLE open_positions ADD COLUMN direction TEXT DEFAULT 'long';
ALTER TABLE open_positions ADD COLUMN order_type TEXT DEFAULT 'market';
ALTER TABLE open_positions ADD COLUMN trail_percent REAL;
