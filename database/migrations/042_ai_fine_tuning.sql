-- ============================================================================
-- Migration 042: AI Model Fine-tuning Tables
-- Phase 46: AI Model Fine-tuning Module
-- Date: 2026-01-19
-- ============================================================================

-- ============================================================================
-- FINE-TUNING DATASETS
-- ============================================================================

CREATE TABLE IF NOT EXISTS ft_datasets (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name VARCHAR(255) NOT NULL,
    description TEXT,
    dataset_type VARCHAR(50) DEFAULT 'conversation',  -- conversation, completion, instruction, classification
    source_type VARCHAR(50) DEFAULT 'upload',  -- upload, api, generated, imported
    file_path VARCHAR(500),
    file_format VARCHAR(20),  -- jsonl, csv, parquet, json
    total_samples INTEGER DEFAULT 0,
    train_samples INTEGER DEFAULT 0,
    validation_samples INTEGER DEFAULT 0,
    test_samples INTEGER DEFAULT 0,
    columns JSONB DEFAULT '[]',  -- Column definitions
    sample_data JSONB DEFAULT '[]',  -- Preview samples
    preprocessing_config JSONB DEFAULT '{}',
    status VARCHAR(30) DEFAULT 'pending',  -- pending, processing, ready, error
    error_message TEXT,
    size_bytes BIGINT DEFAULT 0,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(user_id, name)
);

-- ============================================================================
-- BASE MODELS (Available for Fine-tuning)
-- ============================================================================

CREATE TABLE IF NOT EXISTS ft_base_models (
    id SERIAL PRIMARY KEY,
    model_id VARCHAR(100) NOT NULL UNIQUE,
    model_name VARCHAR(255) NOT NULL,
    provider VARCHAR(50) NOT NULL,  -- ollama, openai, anthropic, huggingface
    model_type VARCHAR(50),  -- llm, embedding, vision, audio
    parameters VARCHAR(20),  -- 7B, 13B, 70B, etc.
    context_length INTEGER,
    supports_fine_tuning BOOLEAN DEFAULT TRUE,
    supports_lora BOOLEAN DEFAULT TRUE,
    supports_qlora BOOLEAN DEFAULT TRUE,
    base_model_path VARCHAR(500),
    description TEXT,
    capabilities JSONB DEFAULT '[]',
    default_config JSONB DEFAULT '{}',
    is_local BOOLEAN DEFAULT TRUE,
    is_available BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT NOW()
);

-- ============================================================================
-- FINE-TUNING JOBS
-- ============================================================================

CREATE TABLE IF NOT EXISTS ft_training_jobs (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    job_name VARCHAR(255) NOT NULL,
    base_model_id INTEGER REFERENCES ft_base_models(id),
    dataset_id INTEGER REFERENCES ft_datasets(id),

    -- Training Configuration
    training_method VARCHAR(30) DEFAULT 'lora',  -- full, lora, qlora, adapter
    epochs INTEGER DEFAULT 3,
    batch_size INTEGER DEFAULT 4,
    learning_rate FLOAT DEFAULT 2e-5,
    warmup_steps INTEGER DEFAULT 100,
    max_steps INTEGER,
    gradient_accumulation INTEGER DEFAULT 1,
    lora_r INTEGER DEFAULT 8,
    lora_alpha INTEGER DEFAULT 16,
    lora_dropout FLOAT DEFAULT 0.05,
    target_modules JSONB DEFAULT '["q_proj", "v_proj"]',

    -- Advanced Config
    optimizer VARCHAR(30) DEFAULT 'adamw',
    scheduler VARCHAR(30) DEFAULT 'cosine',
    weight_decay FLOAT DEFAULT 0.01,
    max_grad_norm FLOAT DEFAULT 1.0,
    fp16 BOOLEAN DEFAULT TRUE,
    bf16 BOOLEAN DEFAULT FALSE,
    gradient_checkpointing BOOLEAN DEFAULT TRUE,
    custom_config JSONB DEFAULT '{}',

    -- Status & Progress
    status VARCHAR(30) DEFAULT 'queued',  -- queued, preparing, training, evaluating, completed, failed, cancelled
    progress FLOAT DEFAULT 0.0,
    current_epoch INTEGER DEFAULT 0,
    current_step INTEGER DEFAULT 0,
    total_steps INTEGER,

    -- Metrics
    train_loss FLOAT,
    eval_loss FLOAT,
    metrics JSONB DEFAULT '{}',  -- perplexity, accuracy, etc.
    training_logs JSONB DEFAULT '[]',

    -- Output
    output_model_path VARCHAR(500),
    checkpoint_paths JSONB DEFAULT '[]',

    -- Timing
    started_at TIMESTAMP,
    completed_at TIMESTAMP,
    estimated_completion TIMESTAMP,
    training_time_seconds INTEGER,

    -- Resources
    gpu_used VARCHAR(100),
    memory_used_gb FLOAT,

    error_message TEXT,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- ============================================================================
-- FINE-TUNED MODELS (Output)
-- ============================================================================

CREATE TABLE IF NOT EXISTS ft_models (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    training_job_id INTEGER REFERENCES ft_training_jobs(id),
    base_model_id INTEGER REFERENCES ft_base_models(id),

    model_name VARCHAR(255) NOT NULL,
    model_id VARCHAR(100) NOT NULL UNIQUE,  -- For API calls
    description TEXT,

    -- Model Info
    model_path VARCHAR(500),
    adapter_path VARCHAR(500),  -- For LoRA adapters
    model_format VARCHAR(30),  -- gguf, safetensors, pytorch
    quantization VARCHAR(20),  -- none, int8, int4, fp16
    size_bytes BIGINT,

    -- Performance
    eval_metrics JSONB DEFAULT '{}',
    benchmark_results JSONB DEFAULT '{}',

    -- Usage
    is_deployed BOOLEAN DEFAULT FALSE,
    deployment_endpoint VARCHAR(500),
    api_calls INTEGER DEFAULT 0,
    last_used_at TIMESTAMP,

    -- Tags & Visibility
    tags TEXT[] DEFAULT '{}',
    is_public BOOLEAN DEFAULT FALSE,

    status VARCHAR(30) DEFAULT 'ready',  -- ready, deploying, deployed, archived
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- ============================================================================
-- EVALUATION RUNS
-- ============================================================================

CREATE TABLE IF NOT EXISTS ft_evaluations (
    id SERIAL PRIMARY KEY,
    model_id INTEGER NOT NULL REFERENCES ft_models(id) ON DELETE CASCADE,
    dataset_id INTEGER REFERENCES ft_datasets(id),

    eval_type VARCHAR(50) DEFAULT 'perplexity',  -- perplexity, accuracy, bleu, rouge, custom
    eval_config JSONB DEFAULT '{}',

    status VARCHAR(30) DEFAULT 'pending',
    progress FLOAT DEFAULT 0.0,

    -- Results
    metrics JSONB DEFAULT '{}',
    sample_outputs JSONB DEFAULT '[]',

    started_at TIMESTAMP,
    completed_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT NOW()
);

-- ============================================================================
-- SEED DEFAULT BASE MODELS
-- ============================================================================

INSERT INTO ft_base_models (model_id, model_name, provider, model_type, parameters, context_length, description, capabilities, default_config) VALUES
('llama3.2:3b', 'Llama 3.2 3B', 'ollama', 'llm', '3B', 131072, 'Compact and efficient model for fine-tuning', '["text-generation", "chat"]', '{"temperature": 0.7}'),
('llama3.2:1b', 'Llama 3.2 1B', 'ollama', 'llm', '1B', 131072, 'Smallest Llama model, great for experimentation', '["text-generation", "chat"]', '{"temperature": 0.7}'),
('qwen2.5:7b', 'Qwen 2.5 7B', 'ollama', 'llm', '7B', 32768, 'Powerful multilingual model', '["text-generation", "chat", "code"]', '{"temperature": 0.7}'),
('qwen2.5:3b', 'Qwen 2.5 3B', 'ollama', 'llm', '3B', 32768, 'Efficient Qwen model for fine-tuning', '["text-generation", "chat", "code"]', '{"temperature": 0.7}'),
('mistral:7b', 'Mistral 7B', 'ollama', 'llm', '7B', 32768, 'High-performance open model', '["text-generation", "chat"]', '{"temperature": 0.7}'),
('codellama:7b', 'Code Llama 7B', 'ollama', 'llm', '7B', 16384, 'Specialized for code generation', '["code", "text-generation"]', '{"temperature": 0.2}'),
('phi3:mini', 'Phi-3 Mini', 'ollama', 'llm', '3.8B', 4096, 'Microsoft small language model', '["text-generation", "chat", "reasoning"]', '{"temperature": 0.7}'),
('gemma2:2b', 'Gemma 2 2B', 'ollama', 'llm', '2B', 8192, 'Google lightweight model', '["text-generation", "chat"]', '{"temperature": 0.7}')
ON CONFLICT (model_id) DO NOTHING;

-- ============================================================================
-- INDEXES
-- ============================================================================

CREATE INDEX IF NOT EXISTS idx_ft_datasets_user ON ft_datasets(user_id);
CREATE INDEX IF NOT EXISTS idx_ft_datasets_status ON ft_datasets(status);
CREATE INDEX IF NOT EXISTS idx_ft_jobs_user ON ft_training_jobs(user_id);
CREATE INDEX IF NOT EXISTS idx_ft_jobs_status ON ft_training_jobs(status);
CREATE INDEX IF NOT EXISTS idx_ft_jobs_base_model ON ft_training_jobs(base_model_id);
CREATE INDEX IF NOT EXISTS idx_ft_models_user ON ft_models(user_id);
CREATE INDEX IF NOT EXISTS idx_ft_models_deployed ON ft_models(is_deployed);
CREATE INDEX IF NOT EXISTS idx_ft_evaluations_model ON ft_evaluations(model_id);

-- ============================================================================
-- VIEWS
-- ============================================================================

CREATE OR REPLACE VIEW v_ft_user_stats AS
SELECT
    u.id as user_id,
    u.username,
    COUNT(DISTINCT d.id) as total_datasets,
    COUNT(DISTINCT j.id) as total_jobs,
    COUNT(DISTINCT CASE WHEN j.status = 'completed' THEN j.id END) as completed_jobs,
    COUNT(DISTINCT CASE WHEN j.status = 'training' THEN j.id END) as active_jobs,
    COUNT(DISTINCT m.id) as total_models,
    COUNT(DISTINCT CASE WHEN m.is_deployed THEN m.id END) as deployed_models
FROM users u
LEFT JOIN ft_datasets d ON u.id = d.user_id
LEFT JOIN ft_training_jobs j ON u.id = j.user_id
LEFT JOIN ft_models m ON u.id = m.user_id
GROUP BY u.id, u.username;

-- ============================================================================
-- COMMENTS
-- ============================================================================

COMMENT ON TABLE ft_datasets IS 'Training datasets for fine-tuning';
COMMENT ON TABLE ft_base_models IS 'Available base models for fine-tuning';
COMMENT ON TABLE ft_training_jobs IS 'Fine-tuning training job records';
COMMENT ON TABLE ft_models IS 'Fine-tuned model outputs';
COMMENT ON TABLE ft_evaluations IS 'Model evaluation runs';

-- ============================================================================
-- DONE
-- ============================================================================

SELECT 'Migration 042: AI Fine-tuning tables created successfully' as result;
