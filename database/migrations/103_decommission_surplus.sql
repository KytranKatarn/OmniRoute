-- ============================================================
-- LLM Ecosystem Redesign — Decommission Surplus Agents
-- Keeps: 34 AI acronym + 16 human staff = 50 active roster
-- Decision #441
-- ============================================================

BEGIN;

-- Decommission human-named internal agents not in the kept-16 list
-- Keeping: Nexus, Scholar, Wordsmith, CodeSmith, Architect, CommRelay,
--          Dispatch, Envoy, Value, Tempo, Sage, Thorn, Nova, Echo,
--          Juno, Koda (16 core internal staff agents)

UPDATE agents SET shift_state = 'decommissioned'
WHERE worker_type = 'internal'
AND shift_state NOT IN ('decommissioned')
AND name IN (
    'DataMind',
    'Delphi',
    'Beacon-A',
    'Forge',
    'Onyx',
    'Wrench',
    'Atlas',
    'Runway',
    'Quill',
    'Catalyst',
    'Oracle',
    'Scout',
    'Spark-Jr',
    'Helix',
    'Luna',
    'Maven',
    'Polyglot',
    'Crucible',
    'Titan'
);

-- Decommission human-named contractor agents (replaced by cloud providers)
UPDATE agents SET shift_state = 'decommissioned'
WHERE worker_type = 'contractor'
AND shift_state NOT IN ('decommissioned')
AND name IN ('Pixel', 'Lens', 'Atom', 'Prism', 'Spark');

COMMIT;
