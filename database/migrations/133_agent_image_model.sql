-- Add image_model column to agents for non-Ollama generation capabilities (ComfyUI, etc.)
ALTER TABLE agents ADD COLUMN IF NOT EXISTS image_model VARCHAR(200);

-- Set Pixel's ComfyUI model
UPDATE agents SET image_model = 'sd_xl_base_1.0.safetensors' WHERE name = 'Pixel';
