-- 495_review_slots.sql (#7322)
-- Cross-PR F.O.R.G.E. review slot. owned_attempt() already stops the SAME PR being reviewed
-- twice; nothing limited reviews of DIFFERENT PRs, so two reviews piled onto Defiant's single
-- inference slot and hit elapsed_time_limit. A row here is a LEASE: free when holder IS NULL,
-- its heartbeat is older than the TTL (crashed process) or acquired_at is older than the hard
-- max-hold (hung but alive thread). All times are DB time (NOW()), because the holders are
-- 4 platform workers + the scheduler.
CREATE TABLE IF NOT EXISTS review_slots (
    slot         INTEGER PRIMARY KEY,
    repo         TEXT,
    pr_number    INTEGER,
    holder       TEXT,
    acquired_at  TIMESTAMPTZ,
    heartbeat_at TIMESTAMPTZ
);

COMMENT ON TABLE review_slots IS
    'F.O.R.G.E. review concurrency leases (#7322). Free when holder IS NULL or lease expired.';
