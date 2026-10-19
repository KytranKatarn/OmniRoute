-- 493_model_placement_log_percard.sql — per-card placement fields (#5273 / #6106)
--
-- WHY: model_service.gpu_placement_options() began passing `card_index` and
-- `cards_free_gb` (per-card placement, #6810 follow-up) but
-- placement_telemetry.record_placement() did not accept them, so every per-card
-- decision raised TypeError inside the caller's guard and was DROPPED:
-- 41 "placement telemetry unavailable" warnings in 3h on 2026-10-19, i.e. the
-- observer was blind to exactly the decisions that matter on a two-card hub.
--
-- Additive and nullable: existing rows and the pre-per-card branches (which pass
-- neither field) are unaffected. Idempotent.

ALTER TABLE model_placement_log
    ADD COLUMN IF NOT EXISTS card_index    SMALLINT,        -- index into cards_free_gb that was chosen
    ADD COLUMN IF NOT EXISTS cards_free_gb NUMERIC(6,2)[];  -- free GB per card at decision time
