-- 134: Register Archie main server as starbase node
-- Idempotent: ON CONFLICT DO UPDATE

INSERT INTO remote_nodes (
    node_id, node_name, description, hostname, port,
    status, is_active, approval_status,
    deployment_mode, bridge_enabled, bridge_priority,
    gpu_available, gpu_model, gpu_vram_gb,
    cpu_model, cpu_cores, ram_gb, disk_gb,
    ollama_available, comfyui_available, docker_available,
    nvidia_docker, iaae_compliant,
    os_info, region, timezone
) VALUES (
    'archie-starbase',
    'Archie Starbase',
    'Primary A.R.C.H.I.E. server — hosts platform, database, all modules',
    '192.168.1.200',
    11434,
    'online',
    true,
    'approved',
    'starbase',
    true,
    100,
    true,
    'NVIDIA Quadro M4000',
    8.0,
    'Intel Xeon E5-2658 v2',
    20,
    128.0,
    110.0,
    true,
    true,
    true,
    true,
    true,
    'Ubuntu 24.04 LTS',
    'local',
    'America/Toronto'
) ON CONFLICT (node_id) DO UPDATE SET
    node_name = EXCLUDED.node_name,
    hostname = EXCLUDED.hostname,
    deployment_mode = EXCLUDED.deployment_mode,
    bridge_enabled = EXCLUDED.bridge_enabled,
    bridge_priority = EXCLUDED.bridge_priority,
    status = EXCLUDED.status,
    is_active = EXCLUDED.is_active,
    approval_status = EXCLUDED.approval_status,
    updated_at = NOW();
