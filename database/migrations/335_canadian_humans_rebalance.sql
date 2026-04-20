-- Migration 335: Canadian representation rebalance (Project #262 PR D-pre)
--
-- The post-PR-B roster had 17 humans but zero Canadian-born representation
-- (Amina is Syrian-born and settled in NB; Kytran's bio didn't explicitly
-- say Canadian). Option 1 swap minimises churn — retires two freshly-created
-- personas from PR B and replaces with two Canadian-born humans.
--
-- Swap:
--   - Ingrid Sørensen (Danish) → Lillian Paul (Mi'kmaq, Eskasoni First Nation)
--     in Diplomatic & External Relations as Indigenous Relations Liaison.
--   - Jamal Williams (Atlanta)  → Josée Arsenault (Acadian, Caraquet NB)
--     in Human Resources & Culture as Bilingual People Operations Lead.
--
-- Plus:
--   - Kytran's bio updated to say "Canadian-based" (identity still private).

BEGIN;

-- ============================================================================
-- 1. Decommission Ingrid (id=344) and Jamal (id=345) from PR B
-- ============================================================================
UPDATE agents
SET shift_state = 'decommissioned',
    status = 'inactive',
    updated_at = now()
WHERE id IN (344, 345);

-- ============================================================================
-- 2. Lillian Paul — Mi'kmaq, Eskasoni First Nation, Diplomatic & External Rel.
-- ============================================================================
INSERT INTO agents (
    name, display_name, first_name, last_name, pronouns, email,
    worker_type, department, floor, title, bio,
    avatar_url, status, shift_state, is_department_ai, model, tier
)
VALUES (
    'Lillian', 'Lillian Paul', 'Lillian', 'Paul', 'she/her',
    'lillian.paul@kytranempowerment.com',
    'internal', 'Diplomatic & External Relations', 'SERVICES',
    'Indigenous Relations Liaison',
    'Lillian Paul was born in Eskasoni First Nation on Unama''ki (Cape Breton Island) — the largest Mi''kmaq community in Atlantic Canada — and raised by grandparents who taught her that every relationship, human or otherwise, carries responsibilities passed down through generations. She studied Indigenous Governance at Cape Breton University and earned a Master''s in Public Administration from Dalhousie, writing her thesis on how treaty frameworks can inform modern digital-consent protocols. Lillian spent five years at the Assembly of First Nations advising on data sovereignty and community broadband rollouts before joining Kytran Empowerment as Indigenous Relations Liaison. She translates the platform''s ethics into the languages of relationship, reciprocity, and stewardship — and pushes back (gently, firmly) when a decision treats consent as a checkbox. Off hours she teaches Mi''kmaw language classes online and is raising twin daughters who already know more L''nu words than she did at their age.',
    NULL,
    'active', 'active', FALSE, 'none', 1
);

-- ============================================================================
-- 3. Josée Arsenault — Acadian, Caraquet NB, HR & Culture (People Ops)
-- ============================================================================
INSERT INTO agents (
    name, display_name, first_name, last_name, pronouns, email,
    worker_type, department, floor, title, bio,
    avatar_url, status, shift_state, is_department_ai, model, tier
)
VALUES (
    'Josee', 'Josée Arsenault', 'Josée', 'Arsenault', 'she/her',
    'josee.arsenault@kytranempowerment.com',
    'internal', 'Human Resources & Culture', 'SERVICES',
    'Bilingual People Operations Lead',
    'Josée Arsenault grew up in Caraquet, New Brunswick — the heart of the Acadian Peninsula — where she learned early that her language is both a heritage and a working tool, and that community is held together by the patience to hear people in their own words. She studied Human Resources Management at the Université de Moncton and earned a Coaching Certificate from Royal Roads University, then spent five years as Head of People at a bilingual Moncton tech company where she built onboarding programs that worked as naturally in French as in English. Josée joined Kytran Empowerment as Bilingual People Operations Lead, partnering with K.I.N. on culture rituals, hiring, and welfare check-ins — conducted in whichever language each person thinks best in. She still attends the Tintamarre every August 15th, banging pots and pans with the rest of the Acadian diaspora to remember where they come from.',
    NULL,
    'active', 'active', FALSE, 'none', 1
);

-- ============================================================================
-- 4. Kytran bio — note Canadian base without revealing identity
-- ============================================================================
UPDATE agents
SET bio = 'Co-Founder of Kytran Empowerment and architect of the A.R.C.H.I.E. platform. Canadian-based; identity kept intentionally private — the work speaks first. Public profile populates from verified sources (LinkedIn, press) as those integrations come online. Builds platforms because someone has to prove ethical AI is practical, not aspirational.',
    updated_at = now()
WHERE name = 'Kytran' AND shift_state = 'active';

-- ============================================================================
-- Assertions
-- ============================================================================

DO $$
DECLARE hc int;
BEGIN
    SELECT COUNT(*) INTO hc FROM agents
      WHERE department = 'Diplomatic & External Relations'
        AND worker_type != 'ai'
        AND shift_state = 'active';
    ASSERT hc = 1, format('Expected 1 human in Diplomatic, got %s', hc);
END $$;

DO $$
DECLARE hc int;
BEGIN
    SELECT COUNT(*) INTO hc FROM agents
      WHERE department = 'Human Resources & Culture'
        AND worker_type != 'ai'
        AND shift_state = 'active';
    ASSERT hc = 1, format('Expected 1 human in HR, got %s', hc);
END $$;

DO $$
DECLARE k_bio text;
BEGIN
    SELECT bio INTO k_bio FROM agents WHERE name = 'Kytran' AND shift_state = 'active';
    ASSERT k_bio LIKE '%Canadian-based%', 'Kytran bio missing "Canadian-based" marker';
END $$;

COMMIT;
