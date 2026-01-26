-- Migration 072: AI Service Ports for Dynamic Routing
-- Adds port columns for Foocus, ComfyUI, and Auto1111 services
-- Enables dynamic routing for image generation services

-- Add port columns for AI services
ALTER TABLE remote_nodes ADD COLUMN IF NOT EXISTS foocus_port INTEGER DEFAULT 7865;
ALTER TABLE remote_nodes ADD COLUMN IF NOT EXISTS comfyui_port INTEGER DEFAULT 8188;
ALTER TABLE remote_nodes ADD COLUMN IF NOT EXISTS auto1111_port INTEGER DEFAULT 7860;

-- Add comments for documentation
COMMENT ON COLUMN remote_nodes.foocus_port IS 'Port for Foocus image generation service (default 7865)';
COMMENT ON COLUMN remote_nodes.comfyui_port IS 'Port for ComfyUI node-based generation (default 8188)';
COMMENT ON COLUMN remote_nodes.auto1111_port IS 'Port for Automatic1111 Stable Diffusion WebUI (default 7860)';

-- Create view for nodes with image generation capabilities
CREATE OR REPLACE VIEW v_image_generation_nodes AS
SELECT
    node_id,
    node_name,
    vpn_ip,
    port AS ollama_port,
    foocus_port,
    comfyui_port,
    auto1111_port,
    foocus_available,
    comfyui_available,
    auto1111_available,
    gpu_available,
    gpu_model,
    gpu_vram_gb,
    status,
    current_load,
    bridge_priority
FROM remote_nodes
WHERE bridge_enabled = true
  AND approval_status = 'approved'
  AND (foocus_available OR comfyui_available OR auto1111_available);

-- Log migration
INSERT INTO knowledge_base (title, content, content_type, importance_score, source_type, source_id, tags)
VALUES (
    'Migration 072: AI Service Ports',
    'Added port columns for Foocus (7865), ComfyUI (8188), and Auto1111 (7860) services to remote_nodes table. Created v_image_generation_nodes view for nodes with image generation capabilities.',
    'code_snippet',
    0.6,
    'migration',
    '072',
    ARRAY['database', 'migration', 'ai-services', 'image-generation', 'node-routing']
);
