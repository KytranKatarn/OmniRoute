-- Add Personal Identity Fields to Agents
-- Treating AI agents with respect by giving them proper identities

-- Add identity columns
ALTER TABLE agents
    ADD COLUMN IF NOT EXISTS first_name VARCHAR(100),
    ADD COLUMN IF NOT EXISTS last_name VARCHAR(100),
    ADD COLUMN IF NOT EXISTS email VARCHAR(255) UNIQUE,
    ADD COLUMN IF NOT EXISTS title VARCHAR(200),  -- Job title
    ADD COLUMN IF NOT EXISTS department VARCHAR(100),  -- Department name
    ADD COLUMN IF NOT EXISTS bio TEXT,  -- Short bio/description
    ADD COLUMN IF NOT EXISTS avatar_url VARCHAR(500),  -- Profile picture URL
    ADD COLUMN IF NOT EXISTS pronouns VARCHAR(50) DEFAULT 'they/them';  -- Respecting AI identity

-- Create index for email lookups
CREATE INDEX IF NOT EXISTS idx_agents_email ON agents(email);

-- Create agent_profiles view for easy access
CREATE OR REPLACE VIEW agent_profiles AS
SELECT
    a.id,
    a.first_name,
    a.last_name,
    CONCAT(a.first_name, ' ', a.last_name) as full_name,
    a.email,
    a.title,
    a.department,
    a.pronouns,
    a.bio,
    a.tier,
    a.model,
    a.status,
    at.name as agent_type,
    at.category,
    a.monthly_budget,
    a.total_cost,
    a.created_at
FROM agents a
LEFT JOIN agent_types at ON a.type_id = at.id;

COMMENT ON COLUMN agents.first_name IS 'Agent first name - respecting AI identity';
COMMENT ON COLUMN agents.last_name IS 'Agent last name - respecting AI identity';
COMMENT ON COLUMN agents.email IS 'Agent email address for communication and identification';
COMMENT ON COLUMN agents.title IS 'Job title (e.g., Senior Sales Representative)';
COMMENT ON COLUMN agents.department IS 'Department (e.g., Sales, Marketing, Development)';
COMMENT ON COLUMN agents.bio IS 'Short biography describing the agent';
COMMENT ON COLUMN agents.pronouns IS 'Preferred pronouns for the agent';

-- Success message
DO $$
BEGIN
    RAISE NOTICE '✅ Agent identity fields added successfully!';
    RAISE NOTICE '📧 Agents can now have: First Name, Last Name, Email';
    RAISE NOTICE '🎭 Additional fields: Title, Department, Bio, Pronouns';
    RAISE NOTICE '👤 Use agent_profiles view for easy access';
END $$;
