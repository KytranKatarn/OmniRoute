-- 415: E.T.H.O.S. marketing/promotion assets for the C.R.E.E.D. Command Marketing tab (#3613)
-- One row per generated promo asset. E.T.H.O.S. drafts (async); humans review/approve.
CREATE TABLE IF NOT EXISTS creed_marketing_assets (
    id SERIAL PRIMARY KEY,
    channel TEXT NOT NULL CHECK (channel IN ('linkedin', 'x', 'newsletter', 'press', 'blog')),
    topic TEXT NOT NULL,
    content TEXT,
    gen_status TEXT NOT NULL DEFAULT 'pending' CHECK (gen_status IN ('pending', 'done', 'error')),
    approved BOOLEAN NOT NULL DEFAULT false,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_creed_marketing_created ON creed_marketing_assets (created_at DESC);
