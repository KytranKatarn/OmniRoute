-- #6819 — a human affordance to clear a FALSE finding.
--
-- Before this, a wrong REQUEST CHANGES could only be re-rolled (nondeterministic) or sent to
-- coders (which files a repair for a defect that does not exist). There was no way to say
-- "this observation is factually wrong, here is why".
--
-- PRINCIPLE: correct the INPUT, never override the OUTPUT. A dismissal removes ONE false
-- finding from the set the verdict is computed over; the verdict is then recomputed. If a real
-- blocking finding remains, the PR stays blocked. `verdict_refusal` and the tier ceiling are
-- untouched — "nothing merges on a non-approval" (decision #953) still binds, because the
-- verdict legitimately changed rather than being bypassed.
--
-- SECOND PAYOFF: every row is a LABELLED false-positive example, which is the corpus #6799 and
-- #6800 need and do not have.
CREATE TABLE IF NOT EXISTS pr_review_finding_dismissals (
    id               SERIAL PRIMARY KEY,
    pr_number        INTEGER      NOT NULL,
    repo             VARCHAR(200) NOT NULL,
    -- Which finding. Fingerprint of the NORMALISED finding line, so re-review wording drift
    -- (whitespace/severity tag) does not orphan the dismissal.
    finding_fp       VARCHAR(64)  NOT NULL,
    finding_text     TEXT         NOT NULL,
    -- ⚠️ SCOPED TO THE HEAD SHA ON PURPOSE. A dismissal is a judgement about SPECIFIC code. New
    -- commits may make the finding true, so a dismissal must NOT survive them silently. The
    -- cost is re-dismissing after a push; the alternative is a stale clearance on changed code.
    head_sha         VARCHAR(64),
    -- No silent dismissals: the rationale is NOT NULL and non-empty (see CHECK below).
    rationale        TEXT         NOT NULL,
    dismissed_by     VARCHAR(120) NOT NULL,
    created_at       TIMESTAMPTZ  NOT NULL DEFAULT now(),
    revoked_at       TIMESTAMPTZ,
    revoked_by       VARCHAR(120),
    CONSTRAINT pr_review_dismissal_rationale_not_blank CHECK (btrim(rationale) <> ''),
    CONSTRAINT pr_review_dismissal_unique UNIQUE (pr_number, repo, finding_fp, head_sha)
);

CREATE INDEX IF NOT EXISTS idx_pr_dismissal_lookup
    ON pr_review_finding_dismissals (pr_number, repo, head_sha)
 WHERE revoked_at IS NULL;

COMMENT ON TABLE pr_review_finding_dismissals IS
 '#6819 — per-finding false-positive dismissals. Corrects the verdict INPUT; never bypasses verdict_refusal. Also the labelled corpus for #6799/#6800.';
