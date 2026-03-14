-- Migration 169: Health modules — Fitness + Therapy + DOC persistence
-- Idempotent: safe to run multiple times

-- Fitness
CREATE TABLE IF NOT EXISTS fitness_workout_logs (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL,
    workout_type VARCHAR(50) NOT NULL,
    exercises JSONB DEFAULT '[]',
    duration_min INTEGER DEFAULT 0,
    calories INTEGER DEFAULT 0,
    notes TEXT,
    logged_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS fitness_goals (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL,
    goal_type VARCHAR(50) NOT NULL,
    target NUMERIC NOT NULL,
    current NUMERIC DEFAULT 0,
    unit VARCHAR(20) DEFAULT '',
    deadline DATE,
    created_at TIMESTAMP DEFAULT NOW()
);

-- Therapy
CREATE TABLE IF NOT EXISTS therapy_mood_logs (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL,
    mood_score INTEGER NOT NULL CHECK (mood_score BETWEEN 1 AND 10),
    energy_score INTEGER CHECK (energy_score BETWEEN 1 AND 10),
    notes TEXT,
    tags JSONB DEFAULT '[]',
    logged_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS therapy_sessions (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL,
    session_type VARCHAR(50) DEFAULT 'general',
    notes TEXT,
    exercises_done JSONB DEFAULT '[]',
    duration_min INTEGER DEFAULT 0,
    logged_at TIMESTAMP DEFAULT NOW()
);

-- DOC
CREATE TABLE IF NOT EXISTS health_symptom_logs (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL,
    symptoms JSONB DEFAULT '[]',
    severity INTEGER CHECK (severity BETWEEN 1 AND 10),
    notes TEXT,
    logged_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS health_medications (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL,
    name VARCHAR(100) NOT NULL,
    dosage VARCHAR(50),
    frequency VARCHAR(50),
    start_date DATE,
    end_date DATE,
    active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT NOW()
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_fitness_logs_user ON fitness_workout_logs(user_id, logged_at DESC);
CREATE INDEX IF NOT EXISTS idx_fitness_goals_user ON fitness_goals(user_id);
CREATE INDEX IF NOT EXISTS idx_therapy_mood_user ON therapy_mood_logs(user_id, logged_at DESC);
CREATE INDEX IF NOT EXISTS idx_therapy_sessions_user ON therapy_sessions(user_id, logged_at DESC);
CREATE INDEX IF NOT EXISTS idx_health_symptoms_user ON health_symptom_logs(user_id, logged_at DESC);
CREATE INDEX IF NOT EXISTS idx_health_meds_user ON health_medications(user_id, active);
