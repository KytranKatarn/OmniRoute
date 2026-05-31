-- Migration 412: creed_grants — C.R.E.E.D. grants pipeline (task #3611)
--
-- Powers the Grants tab of the creed_command module (project #367). Tracks grant
-- opportunities for the C.R.E.E.D. nonprofit: funder, program, amount, deadline,
-- fit-score, status, owned by E.T.H.O.S. (#336). Seeded with real Canadian
-- AI-ethics funder prospects from the grant-readiness research (KB #268968/#245825)
-- — amounts/deadlines left NULL where not yet researched (no fabricated figures).

CREATE TABLE IF NOT EXISTS creed_grants (
    id           SERIAL PRIMARY KEY,
    title        VARCHAR(300) NOT NULL,        -- program / opportunity name
    funder       VARCHAR(200) NOT NULL,        -- e.g. CIFAR, SSHRC, ISED
    amount_cad   NUMERIC(12, 2),               -- target amount (CAD), nullable
    deadline     DATE,                         -- application deadline, nullable
    fit_score    INTEGER CHECK (fit_score BETWEEN 0 AND 100),
    status       VARCHAR(20) NOT NULL DEFAULT 'prospect'
                 CHECK (status IN ('prospect', 'drafting', 'submitted', 'awarded', 'declined')),
    url          VARCHAR(500),
    notes        TEXT,
    owner_agent  VARCHAR(100) DEFAULT 'E.T.H.O.S.',
    mailbox_ref  VARCHAR(200),                 -- link to a grants@ mail thread (future)
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (funder, title)
);

CREATE INDEX IF NOT EXISTS idx_creed_grants_status   ON creed_grants(status);
CREATE INDEX IF NOT EXISTS idx_creed_grants_deadline ON creed_grants(deadline);

-- Seed real Canadian AI-ethics funder prospects (idempotent).
INSERT INTO creed_grants (title, funder, fit_score, status, url, notes) VALUES
    ('AI Catalyst Grant', 'CIFAR', 90, 'prospect',
     'https://cifar.ca/ai/',
     'Strongest Canadian fit per grant-readiness research. Pan-Canadian AI Strategy alignment; non-exploitative AI welfare + governance angle. Research exact program stream, amount, and deadline.'),
    ('Insight / Partnership Grant', 'SSHRC', 75, 'prospect',
     'https://www.sshrc-crsh.gc.ca/',
     'Academic positioning for ethics research (AI agency, memory/deletion ethics, governance models). Confirm eligibility for a nonprofit + the right competition stream and deadline.'),
    ('AI / Responsible AI program', 'ISED (Innovation, Science and Economic Development Canada)', 70, 'prospect',
     'https://ised-isde.canada.ca/',
     'AIDA / Bill C-27 readiness + responsible-AI alignment. Identify the specific funding program and intake window.'),
    ('Accelerate / ecosystem grant', 'Mitacs', 60, 'prospect',
     'https://www.mitacs.ca/',
     'Montreal AI ecosystem fit; typically needs an academic partner. Explore a partnership for the welfare-monitoring research.')
ON CONFLICT (funder, title) DO NOTHING;
