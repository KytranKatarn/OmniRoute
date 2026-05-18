-- Migration 386: WTF DHQ Orchestration — agent skills for Project #350
-- Adds missing skills so dispatcher routes WTF capabilities to correct News & Media agents.
-- All existing primary skills (bias_analysis/B.I.A.S., fact_check/V.E.R.I.F.Y.,
-- geo_extraction/L.O.C.A.L., web_scraping/S.C.O.U.T.) already exist — not duplicated here.

-- V.E.R.I.F.Y. (id=116): secondary bias_analysis capability (fallback when B.I.A.S. busy)
INSERT INTO agent_skills (agent_id, skill_name, skill_category, proficiency_level, notes)
VALUES (116, 'bias_analysis', 'news_media', 4, 'Secondary — fallback when B.I.A.S. unavailable')
ON CONFLICT (agent_id, skill_name) DO NOTHING;

-- I.N.K. (id=23): clustering — WTF story grouping pipeline
INSERT INTO agent_skills (agent_id, skill_name, skill_category, proficiency_level, notes)
VALUES (23, 'clustering', 'news_media', 5, 'WTF story cluster pipeline — Jaccard similarity grouping')
ON CONFLICT (agent_id, skill_name) DO NOTHING;

-- D.R.A.F.T. (id=79): summarization for WTF article summaries
INSERT INTO agent_skills (agent_id, skill_name, skill_category, proficiency_level, notes)
VALUES (79, 'summarization', 'news_media', 5, 'WTF cluster summary generation')
ON CONFLICT (agent_id, skill_name) DO NOTHING;

-- F.A.C.T. (id=48): data_ingestion — WTF RSS pipeline orchestration
INSERT INTO agent_skills (agent_id, skill_name, skill_category, proficiency_level, notes)
VALUES (48, 'data_ingestion', 'news_media', 5, 'WTF RSS ingest + article priority selection')
ON CONFLICT (agent_id, skill_name) DO NOTHING;
