-- 398_ship_classes.sql
-- Data-driven GPU-VRAM -> Star Trek ship-class index for the fleet.
-- Any GPU node auto-classes from its live remote_nodes.gpu_vram_gb (populated by
-- the node heartbeat agent). Re-tune tiers later with a plain UPDATE -- no code,
-- no deploy. Idempotent: safe to re-run.

CREATE TABLE IF NOT EXISTS ship_classes (
    tier          integer PRIMARY KEY,
    min_vram_gb   numeric NOT NULL,   -- inclusive lower bound
    max_vram_gb   numeric,            -- exclusive upper bound; NULL = open-ended (top tier)
    class_name    text NOT NULL,
    model_ceiling text,               -- largest model the tier comfortably runs
    example_cards text
);

INSERT INTO ship_classes (tier, min_vram_gb, max_vram_gb, class_name, model_ceiling, example_cards) VALUES
  (1,  0,   5,    'Runabout',     '1.5b-3b',    'GTX 1650, RTX 3050 Laptop'),
  (2,  5,   7,    'Nova',         '7B (q4)',    'RTX 2060, RTX 3060 Laptop'),
  (3,  7,   9,    'Defiant',      '7-8B',       'RTX 3070, RTX 4060'),
  (4,  9,   13,   'Intrepid',     '12-14B',     'RTX 3080, RTX 4070, RTX 3060 12G'),
  (5,  13,  17,   'Constitution', '14-24B',     'RTX 4080, RTX 4060 Ti 16G, A4000'),
  (6,  17,  25,   'Galaxy',       '30-34B',     'RTX 3090, RTX 4090, A5000'),
  (7,  25,  49,   'Sovereign',    '70B (q)',    'RTX 5090, RTX A6000, L40'),
  (8,  49,  81,   'Dreadnought',  '70B+/100B',  'A100 80G, H100 80G'),
  (9,  81,  NULL, 'Armada',       'frontier',   'multi-GPU / 80GB+ clusters')
ON CONFLICT (tier) DO UPDATE SET
    min_vram_gb   = EXCLUDED.min_vram_gb,
    max_vram_gb   = EXCLUDED.max_vram_gb,
    class_name    = EXCLUDED.class_name,
    model_ceiling = EXCLUDED.model_ceiling,
    example_cards = EXCLUDED.example_cards;

-- VRAM (GB) -> ship class. Returns NULL when vram is NULL/below tier 1.
CREATE OR REPLACE FUNCTION fleet_ship_class(vram numeric)
RETURNS text LANGUAGE sql STABLE AS $$
    SELECT class_name FROM ship_classes
    WHERE vram IS NOT NULL
      AND vram >= min_vram_gb
      AND (max_vram_gb IS NULL OR vram < max_vram_gb)
    ORDER BY tier DESC
    LIMIT 1;
$$;

-- Live per-node class. GPU nodes get a class; CPU-only nodes (Outposts/Citadel)
-- and the hub (Starbase, exempt) return NULL ship_class.
CREATE OR REPLACE VIEW v_fleet_ship_class AS
SELECT
    n.id,
    n.node_name,
    n.mesh_ip,
    n.gpu_available,
    n.gpu_model,
    n.gpu_vram_gb,
    CASE WHEN n.gpu_available AND n.gpu_vram_gb IS NOT NULL
         THEN fleet_ship_class(n.gpu_vram_gb::numeric)
    END AS ship_class
FROM remote_nodes n
WHERE n.status <> 'decommissioned';
