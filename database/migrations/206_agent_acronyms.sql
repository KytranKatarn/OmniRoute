-- Migration 206: Add acronym display fields to agents table
-- Required for public directory API and website agent cards

ALTER TABLE agents ADD COLUMN IF NOT EXISTS acronym VARCHAR(50);
ALTER TABLE agents ADD COLUMN IF NOT EXISTS acronym_expansion TEXT;

-- Populate the 17 AI Director agents (names are UPPERCASE in DB)
UPDATE agents SET acronym = 'A.R.C.H.I.E.', acronym_expansion = 'Autonomous Resource & Cognitive Hyperintelligence Engine' WHERE name = 'ARCHIE';
UPDATE agents SET acronym = 'V.I.G.I.L.', acronym_expansion = 'Vigilant Intelligence for Governance, Integrity & Liability' WHERE name = 'VIGIL';
UPDATE agents SET acronym = 'F.O.R.G.E.', acronym_expansion = 'Full-cycle Optimization & Regenerative GitHub Engine' WHERE name = 'FORGE';
UPDATE agents SET acronym = 'S.H.I.E.L.D.', acronym_expansion = 'Security Hardening, Inspection, Enforcement & Liability Detection' WHERE name = 'SHIELD';
UPDATE agents SET acronym = 'B.A.S.E.', acronym_expansion = 'Business Administration & Systems Executive' WHERE name = 'BASE';
UPDATE agents SET acronym = 'C.A.R.G.O.', acronym_expansion = 'Coordinated Asset & Resource Governance Operator' WHERE name = 'CARGO';
UPDATE agents SET acronym = 'L.E.D.G.E.R.', acronym_expansion = 'Ledger & Economic Data Governance Engine for Revenue' WHERE name = 'LEDGER';
UPDATE agents SET acronym = 'D.A.R.W.I.N.', acronym_expansion = 'Data Analysis & Research for Wisdom & Innovation Network' WHERE name = 'DARWIN';
UPDATE agents SET acronym = 'M.U.S.E.', acronym_expansion = 'Multimedia & Unified Studio Engine' WHERE name = 'MUSE';
UPDATE agents SET acronym = 'S.I.G.N.A.L.', acronym_expansion = 'Strategic Information & Global Narrative Amplification Layer' WHERE name = 'SIGNAL';
UPDATE agents SET acronym = 'C.O.D.E.X.', acronym_expansion = 'Cataloging & Organizational Documentation Exchange' WHERE name = 'CODEX';
UPDATE agents SET acronym = 'R.E.S.O.L.V.E.', acronym_expansion = 'Responsive Engagement & Service Optimization for Loyalty & Value Enhancement' WHERE name = 'RESOLVE';
UPDATE agents SET acronym = 'K.I.N.', acronym_expansion = 'Kinship & Internal Nurturing' WHERE name = 'KIN';
UPDATE agents SET acronym = 'V.I.T.A.L.', acronym_expansion = 'Vital Intelligence for Therapeutic & Adaptive Lifestyle' WHERE name = 'VITAL';
UPDATE agents SET acronym = 'G.A.V.E.L.', acronym_expansion = 'Governance & Authoritative Verification for Ethics & Law' WHERE name = 'GAVEL';
UPDATE agents SET acronym = 'A.C.C.O.R.D.', acronym_expansion = 'Advisory Council for Communication, Outreach & Relational Diplomacy' WHERE name = 'ACCORD';
UPDATE agents SET acronym = 'S.P.E.C.T.R.A.', acronym_expansion = 'Systematic Pattern Extraction & Computational Trend Recognition Architecture' WHERE name = 'SPECTRA';
