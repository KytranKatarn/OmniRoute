-- Migration 081: Multi-language voice profiles per agent
-- Allows agents to have multiple voice profiles (one per language)
-- e.g., ARCHIE with English (Kokoro) + Québécois French (XTTS v2)

-- Drop the old unique constraint (one profile per agent)
ALTER TABLE agent_voice_profiles DROP CONSTRAINT IF EXISTS agent_voice_profiles_agent_id_key;

-- Add new unique constraint: one profile per agent per language
ALTER TABLE agent_voice_profiles ADD CONSTRAINT agent_voice_profiles_agent_language_key UNIQUE (agent_id, language);

SELECT 'Migration 081 completed - Multi-language voice profiles per agent' as status;
