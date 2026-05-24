-- Migration 394: Add parliament_vote signal type to cross_watch_signals
-- Safe to re-run (idempotent via constraint name).

-- Postgres cannot ADD to a CHECK in-place — drop + recreate.
ALTER TABLE shared.cross_watch_signals
    DROP CONSTRAINT IF EXISTS cross_watch_signals_signal_type_check;

ALTER TABLE shared.cross_watch_signals
    ADD CONSTRAINT cross_watch_signals_signal_type_check
    CHECK (signal_type IN (
        'new_tender', 'lobbying_activity', 'bill_passed',
        'news_coverage', 'market_movement', 'legal_ruling',
        'parliament_vote'
    ));
