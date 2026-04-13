-- Migration 120: Drop unused directory tables (Decision #431)
-- directory_members, directory_transactions, directory_agent_memories
-- have 0 rows and 0 code references. Chat tables (directory_conversations,
-- directory_messages) are kept — used by Department HQ chat routes.

DROP TABLE IF EXISTS directory_transactions CASCADE;
DROP TABLE IF EXISTS directory_agent_memories CASCADE;
DROP TABLE IF EXISTS directory_members CASCADE;
