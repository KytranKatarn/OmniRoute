-- Migration 085: Collaboration work products
-- Structured outputs from AI-to-AI collaborations: code, plans, designs, analyses
-- Each product has versioning (parent_id) and approval tracking

CREATE TABLE IF NOT EXISTS collaboration_work_products (
    id SERIAL PRIMARY KEY,
    session_id INTEGER REFERENCES collaboration_sessions(id) ON DELETE CASCADE,
    product_type VARCHAR(30) NOT NULL CHECK (product_type IN ('code', 'plan', 'design', 'analysis', 'documentation', 'review')),
    title VARCHAR(200),
    content TEXT NOT NULL,
    author VARCHAR(20) NOT NULL CHECK (author IN ('archie', 'claude', 'joint', 'user')),
    version INTEGER DEFAULT 1,
    parent_id INTEGER REFERENCES collaboration_work_products(id),
    approved BOOLEAN DEFAULT FALSE,
    approved_by VARCHAR(50),
    approved_at TIMESTAMPTZ,
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_work_products_session ON collaboration_work_products(session_id);
CREATE INDEX IF NOT EXISTS idx_work_products_type ON collaboration_work_products(product_type);
CREATE INDEX IF NOT EXISTS idx_work_products_parent ON collaboration_work_products(parent_id);

COMMENT ON TABLE collaboration_work_products IS 'Structured outputs from AI-to-AI collaboration sessions';
COMMENT ON COLUMN collaboration_work_products.parent_id IS 'Points to previous version for version history';
COMMENT ON COLUMN collaboration_work_products.author IS 'Who created this: archie, claude, joint (both), or user';
