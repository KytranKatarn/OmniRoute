-- Install pgvector extension for ARCHIE Consciousness
-- This enables vector similarity search for semantic embeddings
--
-- PREREQUISITE: The database container must use pgvector/pgvector:pg16 image
-- (Updated in docker-compose.yml)
--
-- Run: docker exec -i archie_database psql -U archie -d archie < scripts/install_pgvector.sql

-- Create the vector extension
CREATE EXTENSION IF NOT EXISTS vector;

-- Verify installation
SELECT extname, extversion FROM pg_extension WHERE extname = 'vector';
