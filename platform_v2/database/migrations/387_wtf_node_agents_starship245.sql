-- Migration 387: WTF fleet failback — B.I.A.S. + V.E.R.I.F.Y. on Starship-245
-- Starship-245 (node_id=120, RTX 3070 32GB) joins Starship-246 as secondary
-- fleet node for WTF bias analysis and fact-checking (Project #350 task #3162).
-- Agents start inactive and become active when fleet health check confirms
-- the node is online with the required models loaded.

INSERT INTO node_agents
    (node_id, source_agent_id, hub_agent_id, name, display_name,
     model, status, department, auto_assigned, station_codes, config_version)
VALUES
    -- B.I.A.S. — bias analysis (qwen2.5:7b on GPU for higher quality)
    (120, 49, 49, 'B.I.A.S.', 'B.I.A.S.',
     'qwen2.5:7b', 'inactive', 'News & Media', true, '{}', 1),
    -- V.E.R.I.F.Y. — fact-check + bias_analysis secondary (qwen2.5:7b)
    (120, 116, 116, 'V.E.R.I.F.Y.', 'V.E.R.I.F.Y.',
     'qwen2.5:7b', 'inactive', 'News & Media', true, '{}', 1)
ON CONFLICT DO NOTHING;
