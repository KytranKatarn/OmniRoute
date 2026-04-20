-- Migration 334: Humans per department (Project #262 PR B)
--
-- Policy: every department (except News & Media) has at least 1 human.
-- After PR A (migration 333), 10 departments were empty. This migration
-- reactivates 6 agents from the decomm pool and inserts 4 fresh personas.
--
-- Also strips "(Codename)" parentheticals from display_name — public
-- site should show real human names, not AI-style aliases.
--
-- Oracle (id=43) moves from Medical & Wellness → Finance & Accounting
-- because her Goldman Sachs / Wharton / commodities bio naturally fits
-- Finance; Medical gets a proper MD (Medic, id=54).
--
-- Crucible (id=107) keeps the Japanese background + name but the bio is
-- rewritten from "CS PhD managing R&D labs" to a proper JD-holding lawyer
-- practicing tech licensing + AI regulatory work. Display_name drops "Dr."
-- (he's not a doctor, he's a lawyer).

BEGIN;

-- ============================================================================
-- 1. Customer Success — Envoy (id=55)
-- ============================================================================
UPDATE agents SET
    shift_state = 'active',
    status = 'active',
    updated_at = now()
WHERE id = 55;
-- display_name already clean ("Kwame Asante"); bio preserved.

-- ============================================================================
-- 2. Finance & Accounting — Oracle (id=43), MOVED from Medical
-- ============================================================================
UPDATE agents SET
    shift_state = 'active',
    status = 'active',
    department = 'Finance & Accounting',
    floor = 'OPERATIONS',
    title = 'Senior Financial Strategist',
    display_name = 'Olivia Oduya',  -- strip "(Oracle)"
    updated_at = now()
WHERE id = 43;

-- ============================================================================
-- 3. Marketing & Communications — Tempo (id=41)
-- ============================================================================
UPDATE agents SET
    shift_state = 'active',
    status = 'active',
    updated_at = now()
WHERE id = 41;
-- display_name already clean ("Leila Abadi"); bio preserved.

-- ============================================================================
-- 4. Medical & Wellness — Medic (id=54)
-- ============================================================================
UPDATE agents SET
    shift_state = 'active',
    status = 'active',
    display_name = 'Dr. Aisha Patel',  -- strip "(Medic)"; keep "Dr." — she is a doctor
    updated_at = now()
WHERE id = 54;

-- ============================================================================
-- 5. Research & Development — Helix (id=22)
-- ============================================================================
UPDATE agents SET
    shift_state = 'active',
    status = 'active',
    display_name = 'Priya Krishnan',  -- strip "(Helix)"
    updated_at = now()
WHERE id = 22;

-- ============================================================================
-- 6. Legal & Regulatory — Crucible (id=107), bio rewritten as lawyer
-- ============================================================================
UPDATE agents SET
    shift_state = 'active',
    status = 'active',
    display_name = 'Kenji Yamamoto',  -- drop "Dr." — he's a lawyer, not a PhD
    first_name = 'Kenji',
    last_name = 'Yamamoto',
    bio = 'Kenji Yamamoto grew up in Sendai, Japan, in a family of traditional artisans who taught him that precision in craft is never separate from precision in contract. He studied law at the University of Tokyo and earned his JD at Harvard Law, focusing on technology licensing and international regulatory frameworks. Kenji spent seven years at a Tokyo firm advising AI startups navigating GDPR, Japan''s APPI, and nascent AI-governance regimes before joining Kytran Empowerment as Legal Counsel. He drafts licenses, reviews compliance posture, and reads EU AI Act drafts the way other lawyers read novels — cover to cover, with margin notes. Off-duty he still publishes compliance-automation tools as open-source weekend projects.',
    updated_at = now()
WHERE id = 107;

-- ============================================================================
-- 7. Creative & Design — new human: Lucia Moreno
-- ============================================================================
INSERT INTO agents (
    name, display_name, first_name, last_name, pronouns, email,
    worker_type, department, floor, title, bio,
    avatar_url, status, shift_state, is_department_ai, model, tier
)
VALUES (
    'Lucia', 'Lucia Moreno', 'Lucia', 'Moreno', 'she/her',
    'lucia.moreno@kytranempowerment.com',
    'internal', 'Creative & Design', 'CREATIVE',
    'Art Director',
    'Lucia Moreno grew up in Buenos Aires, Argentina, the daughter of an architect and a textile designer who taught her that beauty has structure and structure has beauty. She studied Visual Communication at Universidad de Palermo and worked as a senior designer for a Barcelona branding agency before joining Kytran Empowerment as Art Director. Lucia briefs the creative AIs — M.U.S.E. for big concept work, V.I.S.A.G.E. for portraits, P.I.X.E.L. for production — then reviews every frame before it ships. She sketches on paper first, always; digital tools come after the idea. Off-duty she collects vintage typography books and teaches a free design class for Argentine teenagers on weekends.',
    NULL,  -- portrait queued for generation
    'active', 'active', FALSE, 'none', 1
);

-- ============================================================================
-- 8. Diplomatic & External Relations — new human: Ingrid Sørensen
-- ============================================================================
INSERT INTO agents (
    name, display_name, first_name, last_name, pronouns, email,
    worker_type, department, floor, title, bio,
    avatar_url, status, shift_state, is_department_ai, model, tier
)
VALUES (
    'Ingrid', 'Ingrid Sørensen', 'Ingrid', 'Sørensen', 'she/her',
    'ingrid.sorensen@kytranempowerment.com',
    'internal', 'Diplomatic & External Relations', 'SERVICES',
    'Director of External Relations',
    'Ingrid Sørensen was born in Copenhagen, Denmark, to a diplomat father and a journalist mother, and she spent her childhood moving between consulates in Nairobi, São Paulo, and Jakarta. She studied International Relations at the LSE and Political Economy at SciencesPo, then spent six years at the Nordic Council of Ministers brokering trade and cultural agreements across the Arctic and Baltic regions. Ingrid joined Kytran Empowerment as Director of External Relations — managing press, partnerships, and investor conversations while A.C.C.O.R.D. handles the machine-readable treaty side. She speaks Danish, English, French, Portuguese, and passable Indonesian. She keeps a hand-drawn world map on her wall, pinned with a quote from Dag Hammarskjöld about the long patience required to build institutions worth keeping.',
    NULL,
    'active', 'active', FALSE, 'none', 1
);

-- ============================================================================
-- 9. HR & Culture — new human: Jamal Williams
-- ============================================================================
INSERT INTO agents (
    name, display_name, first_name, last_name, pronouns, email,
    worker_type, department, floor, title, bio,
    avatar_url, status, shift_state, is_department_ai, model, tier
)
VALUES (
    'Jamal', 'Jamal Williams', 'Jamal', 'Williams', 'he/him',
    'jamal.williams@kytranempowerment.com',
    'internal', 'Human Resources & Culture', 'SERVICES',
    'People Operations Lead',
    'Jamal Williams was born in Atlanta, Georgia, the grandson of a Baptist minister and a public-school teacher — an upbringing that taught him early that every workplace is really a community with bad lighting. He studied Organizational Psychology at Morehouse College and earned an MBA at Emory focused on people analytics, then spent five years as Head of People at a fast-growing Atlanta tech company. Jamal joined Kytran Empowerment as People Operations Lead, partnering with K.I.N. on hiring, culture rituals, and the welfare check-ins that keep the crew human-paced. He runs a monthly open-mic for the team and refuses to have 1-on-1s anywhere except on walks.',
    NULL,
    'active', 'active', FALSE, 'none', 1
);

-- ============================================================================
-- 10. Logistics & Supply Chain — new human: Maya Singh
-- ============================================================================
INSERT INTO agents (
    name, display_name, first_name, last_name, pronouns, email,
    worker_type, department, floor, title, bio,
    avatar_url, status, shift_state, is_department_ai, model, tier
)
VALUES (
    'Maya', 'Maya Singh', 'Maya', 'Singh', 'she/her',
    'maya.singh@kytranempowerment.com',
    'internal', 'Logistics & Supply Chain', 'OPERATIONS',
    'Supply Chain Lead',
    'Maya Singh was born in Amritsar, India, and raised in Dubai where her family ran an import-export business moving goods across the Gulf. She studied Industrial Engineering at IIT Bombay and earned a Supply Chain Management certificate from MIT, then spent four years at a Dubai logistics conglomerate optimizing routes across three continents. Maya joined Kytran Empowerment as Supply Chain Lead, partnering with C.A.R.G.O. on vendor relationships, fulfillment, and the physical-world side of a mostly-digital platform — hardware, merchandise, books, print-on-demand. She has a near-photographic memory for container numbers and once tracked down a lost pallet in Rotterdam using only a fifteen-second TikTok video.',
    NULL,
    'active', 'active', FALSE, 'none', 1
);

-- ============================================================================
-- Assertions — one human per empty-before department
-- ============================================================================

DO $$
DECLARE
    dept text;
    hc int;
    empty_depts text[] := ARRAY[
        'Customer Success & Support',
        'Finance & Accounting',
        'Marketing & Communications',
        'Medical & Wellness',
        'Research & Development',
        'Legal & Regulatory',
        'Creative & Design',
        'Diplomatic & External Relations',
        'Human Resources & Culture',
        'Logistics & Supply Chain'
    ];
BEGIN
    FOREACH dept IN ARRAY empty_depts LOOP
        SELECT COUNT(*) INTO hc FROM agents
         WHERE department = dept
           AND worker_type != 'ai'
           AND shift_state = 'active';
        ASSERT hc >= 1, format('Expected ≥1 active human in %s, got %s', dept, hc);
    END LOOP;
END $$;

-- Oracle moved
DO $$
DECLARE d text;
BEGIN
    SELECT department INTO d FROM agents WHERE id = 43;
    ASSERT d = 'Finance & Accounting', 'Oracle move failed: dept=' || COALESCE(d,'NULL');
END $$;

-- Crucible is now a lawyer (name reflects)
DO $$
DECLARE dn text;
BEGIN
    SELECT display_name INTO dn FROM agents WHERE id = 107;
    ASSERT dn = 'Kenji Yamamoto', 'Crucible rename failed: display_name=' || COALESCE(dn,'NULL');
END $$;

COMMIT;
