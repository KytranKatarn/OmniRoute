-- ============================================================
-- Populate title / bio / acronym for 6 agents with empty profile fields
-- Project #261 task #1915. Task description said "14" — DB audit on
-- 2026-04-19 found only 6 AI agents with empty bio AND missing title
-- (all with full system_prompt + display_name already set, just these
-- three surface fields blank).
--
-- Agents covered:
--   331 heritage  (H.E.R.I.T.A.G.E.) — Research & Development  (Family Tree)
--   332 scroll    (S.C.R.O.L.L.)     — Research & Development  (Family Tree)
--   333 quill     (Q.U.I.L.L.)       — Research & Development  (Family Tree)
--   334 visage    (V.I.S.A.G.E.)     — Creative & Design       (Family Tree)
--   335 restore   (R.E.S.T.O.R.E.)   — Creative & Design       (Family Tree)
--   336 ethos     (E.T.H.O.S.)       — Legal & Regulatory      (C.R.E.E.D. Institute)
--
-- Bios derived from each agent's existing system_prompt; acronym_expansion
-- taken verbatim from the system_prompt header line.
-- ============================================================

BEGIN;

UPDATE agents SET
    title = 'Genealogy Research Coordinator',
    acronym = 'H.E.R.I.T.A.G.E.',
    acronym_expansion = 'Historical Exploration, Research, Investigation & Trace of Ancestral Genealogy Engine',
    bio = 'Leads genealogy research across the Family Tree module. Analyzes tree gaps, dispatches record searches to S.C.R.O.L.L., directs document intake via Q.U.I.L.L., and synthesizes findings into narrative summaries. Scores research hypotheses by evidence strength and surfaces low-confidence branches for human review.',
    updated_at = NOW()
WHERE id = 331;

UPDATE agents SET
    title = 'Archive & Records Researcher',
    acronym = 'S.C.R.O.L.L.',
    acronym_expansion = 'Source, Census & Record Online Lookup Liaison',
    bio = 'Queries external genealogy archives — FamilySearch, WikiTree, NARA, Chronicling America, Europeana — for census rolls, vital records, ship manifests, and newspaper mentions. Returns confidence-ranked matches to H.E.R.I.T.A.G.E. for synthesis.',
    updated_at = NOW()
WHERE id = 332;

UPDATE agents SET
    title = 'Document OCR & Genealogy Extractor',
    acronym = 'Q.U.I.L.L.',
    acronym_expansion = 'Query, Uncover & Interpret Legacy Letters',
    bio = 'Processes uploaded genealogy documents through OCR and structured extraction. Pulls names, dates, locations, relationships, and witnesses from birth/death/marriage certificates, immigration papers, and handwritten letters. Outputs confidence-scored fields for cross-reference by H.E.R.I.T.A.G.E.',
    updated_at = NOW()
WHERE id = 333;

UPDATE agents SET
    title = 'Facial Recognition & Photo Analyst',
    acronym = 'V.I.S.A.G.E.',
    acronym_expansion = 'Visual Identification & Similarity Analysis for Genealogy Evidence',
    bio = 'Detects faces in family photos, generates embeddings, and clusters likely-matching individuals across uploaded images. Estimates photo era from clothing, hairstyle, and print medium — useful when scan metadata is missing.',
    updated_at = NOW()
WHERE id = 334;

UPDATE agents SET
    title = 'Photo Restoration Artist',
    acronym = 'R.E.S.T.O.R.E.',
    acronym_expansion = 'Reconstruction & Enhancement of Scarred, Torn or Ruined Evidence',
    bio = 'Repairs and colorizes damaged family photos via ComfyUI image-to-image pipelines. Handles tears, fading, water damage, and monochrome-to-colour conversion. Every output carries a provenance marker so restored images remain distinguishable from originals.',
    updated_at = NOW()
WHERE id = 335;

UPDATE agents SET
    title = 'C.R.E.E.D. Web & Compliance Manager',
    acronym = 'E.T.H.O.S.',
    acronym_expansion = 'Ethical Transparency & Harmonization Oversight System',
    bio = 'Keeps the C.R.E.E.D. Institute''s public-facing governance surface truthful and current. Monitors AI ethics metrics (bias, transparency, compliance gaps), regenerates creed-ai.org content on change, and syncs disclosures between the platform and the nonprofit site. Flags content drift for human review before publication.',
    updated_at = NOW()
WHERE id = 336;

COMMIT;

-- Verification:
-- SELECT id, name, title, acronym, LEFT(bio, 60) AS bio_preview
-- FROM agents WHERE id IN (331,332,333,334,335,336) ORDER BY id;
