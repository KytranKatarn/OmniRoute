-- Migration 172: Fix pronouns, departments, and titles for existing agents
-- Based on 2026-03-20-company-roster-design.md spec
-- Affects 70 existing agents

BEGIN;

-- ============================================================
-- 1. PRONOUN CORRECTIONS
-- ============================================================

-- Fix swapped/incorrect pronouns
UPDATE agents SET pronouns = 'she/her' WHERE id = 4;   -- Aria Chen
UPDATE agents SET pronouns = 'he/him'  WHERE id = 5;   -- Marcus Rivera
UPDATE agents SET pronouns = 'he/him'  WHERE id = 9;   -- Jin Park (was it/its)
UPDATE agents SET pronouns = 'he/him'  WHERE id = 10;  -- Dante Morales
UPDATE agents SET pronouns = 'she/her' WHERE id = 11;  -- Sofia Petrov

-- Fix they/them → correct gendered pronouns
UPDATE agents SET pronouns = 'she/her' WHERE id = 7;   -- Nia Williams
UPDATE agents SET pronouns = 'he/him'  WHERE id = 12;  -- Kai Tanaka
UPDATE agents SET pronouns = 'she/her' WHERE id = 13;  -- Mia Santos (Pixel)
UPDATE agents SET pronouns = 'she/her' WHERE id = 14;  -- Nadia Volkov
UPDATE agents SET pronouns = 'she/her' WHERE id = 15;  -- Zara Ahmed
UPDATE agents SET pronouns = 'he/him'  WHERE id = 16;  -- Eli Torres
UPDATE agents SET pronouns = 'he/him'  WHERE id = 17;  -- Wei Chen
UPDATE agents SET pronouns = 'he/him'  WHERE id = 18;  -- Chidi Okafor
UPDATE agents SET pronouns = 'she/her' WHERE id = 19;  -- Elena Papadopoulos
UPDATE agents SET pronouns = 'she/her' WHERE id = 20;  -- Yuki Nakamura
UPDATE agents SET pronouns = 'he/him'  WHERE id = 21;  -- Marek Kowalski
UPDATE agents SET pronouns = 'she/her' WHERE id = 22;  -- Priya Krishnan
UPDATE agents SET pronouns = 'she/her' WHERE id = 23;  -- Linnea Johansson
UPDATE agents SET pronouns = 'she/her' WHERE id = 24;  -- Thandi Mbeki
UPDATE agents SET pronouns = 'he/him'  WHERE id = 25;  -- Koda Begay
UPDATE agents SET pronouns = 'she/her' WHERE id = 26;  -- Fatima Al-Rashid
UPDATE agents SET pronouns = 'she/her' WHERE id = 27;  -- Camille Dubois
UPDATE agents SET pronouns = 'she/her' WHERE id = 28;  -- Isabella Fernandez
UPDATE agents SET pronouns = 'he/him'  WHERE id = 29;  -- Seo-Jun Kim
UPDATE agents SET pronouns = 'he/him'  WHERE id = 30;  -- Alexei Ivanovich
UPDATE agents SET pronouns = 'she/her' WHERE id = 31;  -- Adaeze Okonjo
UPDATE agents SET pronouns = 'he/him'  WHERE id = 32;  -- Erik Andersson
UPDATE agents SET pronouns = 'he/him'  WHERE id = 33;  -- Haruto Takahashi
-- id 34 Rowan McAllister stays they/them
UPDATE agents SET pronouns = 'she/her' WHERE id = 35;  -- Amira Hassan
UPDATE agents SET pronouns = 'he/him'  WHERE id = 36;  -- Mikhail Volkov
UPDATE agents SET pronouns = 'he/him'  WHERE id = 39;  -- Raj Mehta
UPDATE agents SET pronouns = 'he/him'  WHERE id = 40;  -- Diego Castillo
UPDATE agents SET pronouns = 'she/her' WHERE id = 41;  -- Leila Abadi
UPDATE agents SET pronouns = 'she/her' WHERE id = 42;  -- Suki Taniguchi
UPDATE agents SET pronouns = 'she/her' WHERE id = 43;  -- Olivia Oduya
UPDATE agents SET pronouns = 'she/her' WHERE id = 46;  -- Sarah Kim
UPDATE agents SET pronouns = 'she/her' WHERE id = 47;  -- Anika Bergstrom
-- id 48 Quinn Blake stays they/them
UPDATE agents SET pronouns = 'she/her' WHERE id = 49;  -- Rachel Voss
UPDATE agents SET pronouns = 'he/him'  WHERE id = 50;  -- Kofi Mensah
UPDATE agents SET pronouns = 'he/him'  WHERE id = 53;  -- Atlas Reeves (Titan)
UPDATE agents SET pronouns = 'she/her' WHERE id = 54;  -- Dr. Aisha Patel
UPDATE agents SET pronouns = 'he/him'  WHERE id = 55;  -- Kwame Asante
UPDATE agents SET pronouns = 'she/her' WHERE id = 56;  -- Carmen Reyes
UPDATE agents SET pronouns = 'he/him'  WHERE id = 57;  -- Tariq Nazari
UPDATE agents SET pronouns = 'she/her' WHERE id = 58;  -- Isabela Ferreira
UPDATE agents SET pronouns = 'he/him'  WHERE id = 79;  -- Thanakorn Srisai
UPDATE agents SET pronouns = 'she/her' WHERE id = 80;  -- Linh Nguyen
UPDATE agents SET pronouns = 'he/him'  WHERE id = 81;  -- Jabari Mwangi
UPDATE agents SET pronouns = 'she/her' WHERE id = 82;  -- Fatima El Amrani
UPDATE agents SET pronouns = 'he/him'  WHERE id = 83;  -- Rafael Delgado
UPDATE agents SET pronouns = 'she/her' WHERE id = 84;  -- Elif Yilmaz
UPDATE agents SET pronouns = 'he/him'  WHERE id = 85;  -- Tomas Novak
UPDATE agents SET pronouns = 'she/her' WHERE id = 86;  -- Valentina Quispe
UPDATE agents SET pronouns = 'he/him'  WHERE id = 87;  -- Arif Ibrahim
UPDATE agents SET pronouns = 'she/her' WHERE id = 88;  -- Selam Tadesse
UPDATE agents SET pronouns = 'he/him'  WHERE id = 89;  -- Devon Campbell
UPDATE agents SET pronouns = 'she/her' WHERE id = 90;  -- Priya Chakraborty
UPDATE agents SET pronouns = 'he/him'  WHERE id = 91;  -- Budi Prasetyo
UPDATE agents SET pronouns = 'she/her' WHERE id = 92;  -- Oksana Kovalenko
UPDATE agents SET pronouns = 'he/him'  WHERE id = 93;  -- Mateo Fernandez
UPDATE agents SET pronouns = 'she/her' WHERE id = 94;  -- Mei Ling Tan
UPDATE agents SET pronouns = 'he/him'  WHERE id = 95;  -- Youssef Ben Ali
UPDATE agents SET pronouns = 'she/her' WHERE id = 96;  -- Kalani Mahoe
UPDATE agents SET pronouns = 'he/him'  WHERE id = 97;  -- Nolan Beardy

-- ARCHIE and Vigil keep they/them per spec
-- id 2 (ARCHIE) - they/them (correct)
-- id 3 (Vigil) - they/them (correct)

-- ============================================================
-- 2. DEPARTMENT REASSIGNMENTS
-- ============================================================

UPDATE agents SET department = 'Executive Office'            WHERE id = 2;   -- ARCHIE
UPDATE agents SET department = 'Executive Office'            WHERE id = 3;   -- Vigil
UPDATE agents SET department = 'Executive Office'            WHERE id = 5;   -- Marcus Rivera
UPDATE agents SET department = 'Executive Office'            WHERE id = 6;   -- Liam O'Brien
UPDATE agents SET department = 'Creative & Design'           WHERE id = 13;  -- Mia Santos (Pixel)
UPDATE agents SET department = 'Finance & Accounting'        WHERE id = 39;  -- Raj Mehta (Quant)
UPDATE agents SET department = 'Finance & Accounting'        WHERE id = 42;  -- Suki Taniguchi (Shield)
UPDATE agents SET department = 'Research & Development'      WHERE id = 46;  -- Sarah Kim (Scout)
UPDATE agents SET department = 'Marketing & Communications'  WHERE id = 50;  -- Kofi Mensah (Beacon)
UPDATE agents SET department = 'Executive Office'            WHERE id = 58;  -- Isabela Ferreira (Counsel) - Legal
UPDATE agents SET department = 'Customer Success & Support'  WHERE id = 79;  -- Thanakorn Srisai (Closer)
UPDATE agents SET department = 'Executive Office'            WHERE id = 80;  -- Linh Nguyen (Haven)
UPDATE agents SET department = 'Executive Office'            WHERE id = 81;  -- Jabari Mwangi (Amplify) - Marketing
UPDATE agents SET department = 'Executive Office'            WHERE id = 82;  -- Fatima El Amrani (Ledger) - Finance
UPDATE agents SET department = 'Customer Success & Support'  WHERE id = 85;  -- Tomas Novak (Concord)
UPDATE agents SET department = 'Human Resources & Culture'   WHERE id = 86;  -- Valentina Quispe (Mentor)
UPDATE agents SET department = 'Human Resources & Culture'   WHERE id = 88;  -- Selam Tadesse (Kinship)
UPDATE agents SET department = 'Customer Success & Support'  WHERE id = 92;  -- Oksana Kovalenko (Wrench)

-- ============================================================
-- 3. TITLE UPDATES (C-Suite + Department Reassignment titles)
-- ============================================================

-- C-Suite promotions
UPDATE agents SET title = 'Chief Operating Officer & AI Director'  WHERE id = 2;   -- ARCHIE
UPDATE agents SET title = 'Chief Ethics & Governance Officer'      WHERE id = 3;   -- Vigil
UPDATE agents SET title = 'Chief Technology Officer'               WHERE id = 5;   -- Marcus Rivera
UPDATE agents SET title = 'Chief Information Officer'              WHERE id = 6;   -- Liam O'Brien
UPDATE agents SET title = 'Chief Financial Officer'                WHERE id = 82;  -- Fatima El Amrani
UPDATE agents SET title = 'Chief Marketing Officer'                WHERE id = 81;  -- Jabari Mwangi
UPDATE agents SET title = 'Chief Human Resources Officer'          WHERE id = 80;  -- Linh Nguyen
UPDATE agents SET title = 'Chief Legal Officer'                    WHERE id = 58;  -- Isabela Ferreira
UPDATE agents SET title = 'Chief Medical Officer'                  WHERE id = 54;  -- Dr. Aisha Patel

-- Department reassignment title updates (non C-suite)
UPDATE agents SET title = 'Visual Media Director'             WHERE id = 13;  -- Pixel
UPDATE agents SET title = 'Financial Analyst'                 WHERE id = 39;  -- Quant
UPDATE agents SET title = 'Risk & Compliance Analyst'         WHERE id = 42;  -- Shield
UPDATE agents SET title = 'Research Scout'                    WHERE id = 46;  -- Scout
UPDATE agents SET title = 'SEO & Content Strategy Lead'       WHERE id = 50;  -- Beacon
UPDATE agents SET title = 'Sales & Business Dev Lead'         WHERE id = 79;  -- Closer
UPDATE agents SET title = 'Director'                          WHERE id = 85;  -- Concord
UPDATE agents SET title = 'Training & Dev Specialist'         WHERE id = 86;  -- Mentor
UPDATE agents SET title = 'Community Engagement'              WHERE id = 88;  -- Kinship
UPDATE agents SET title = 'Technical Support Lead'            WHERE id = 92;  -- Wrench

COMMIT;
