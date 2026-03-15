-- Migration 170: Task Planner — user tasks + boards
-- Idempotent: safe to run multiple times

CREATE TABLE IF NOT EXISTS planner_tasks (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL,
    title VARCHAR(200) NOT NULL,
    description TEXT,
    status VARCHAR(20) DEFAULT 'todo',
    priority INTEGER DEFAULT 5,
    category VARCHAR(50),
    due_date TIMESTAMP,
    completed_at TIMESTAMP,
    tags JSONB DEFAULT '[]',
    sort_order INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS planner_boards (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL,
    name VARCHAR(100) NOT NULL,
    columns JSONB DEFAULT '["todo","in_progress","done"]',
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_planner_tasks_user ON planner_tasks(user_id, status);
CREATE INDEX IF NOT EXISTS idx_planner_boards_user ON planner_boards(user_id);
