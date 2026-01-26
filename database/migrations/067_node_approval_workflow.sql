-- Migration 067: Node Approval Workflow
-- Phase: Bridge Node Management Interface
--
-- Adds approval workflow columns to remote_nodes table:
-- - approval_status: pending/approved/rejected
-- - approved_by: user who approved
-- - approved_at: when approved
-- Also adds additional node info columns for enhanced install.sh

-- Add approval workflow columns
ALTER TABLE remote_nodes ADD COLUMN IF NOT EXISTS approval_status VARCHAR(20) DEFAULT 'pending';
ALTER TABLE remote_nodes ADD COLUMN IF NOT EXISTS approved_by INTEGER REFERENCES users(id);
ALTER TABLE remote_nodes ADD COLUMN IF NOT EXISTS approved_at TIMESTAMP;

-- Add enhanced hardware info columns
ALTER TABLE remote_nodes ADD COLUMN IF NOT EXISTS cpu_model VARCHAR(200);
ALTER TABLE remote_nodes ADD COLUMN IF NOT EXISTS disk_gb FLOAT;
ALTER TABLE remote_nodes ADD COLUMN IF NOT EXISTS os_info VARCHAR(200);
ALTER TABLE remote_nodes ADD COLUMN IF NOT EXISTS ollama_available BOOLEAN DEFAULT FALSE;

-- Create index for approval status filtering
CREATE INDEX IF NOT EXISTS idx_remote_nodes_approval ON remote_nodes(approval_status);

-- Update existing nodes to be approved (they were registered before approval workflow)
UPDATE remote_nodes SET approval_status = 'approved' WHERE approval_status IS NULL OR approval_status = 'pending';

-- Create view for pending nodes (for UI quick access)
CREATE OR REPLACE VIEW v_pending_nodes AS
SELECT
    n.id,
    n.node_id,
    n.node_name,
    n.hostname,
    n.vpn_ip,
    n.port,
    n.cpu_cores,
    n.cpu_model,
    n.ram_gb,
    n.gpu_model,
    n.gpu_vram_gb,
    n.disk_gb,
    n.os_info,
    n.ollama_available,
    n.created_at,
    n.approval_status
FROM remote_nodes n
WHERE n.approval_status = 'pending'
ORDER BY n.created_at DESC;

-- Create view for node summary stats
CREATE OR REPLACE VIEW v_node_network_summary AS
SELECT
    COUNT(*) FILTER (WHERE status = 'online' AND approval_status = 'approved') as nodes_online,
    COUNT(*) FILTER (WHERE status = 'offline' AND approval_status = 'approved') as nodes_offline,
    COUNT(*) FILTER (WHERE status = 'degraded' AND approval_status = 'approved') as nodes_degraded,
    COUNT(*) FILTER (WHERE approval_status = 'pending') as nodes_pending,
    COUNT(*) FILTER (WHERE approval_status = 'rejected') as nodes_rejected,
    COUNT(*) FILTER (WHERE approval_status = 'approved') as nodes_total_approved,
    SUM(cpu_cores) FILTER (WHERE status = 'online' AND approval_status = 'approved') as total_cpu_cores_online,
    SUM(ram_gb) FILTER (WHERE status = 'online' AND approval_status = 'approved') as total_ram_gb_online,
    COUNT(*) FILTER (WHERE gpu_available = true AND status = 'online' AND approval_status = 'approved') as gpu_nodes_online
FROM remote_nodes
WHERE is_active = true;

-- Add comment for documentation
COMMENT ON COLUMN remote_nodes.approval_status IS 'Node approval state: pending (awaiting admin), approved (active), rejected (denied)';
COMMENT ON COLUMN remote_nodes.approved_by IS 'User ID who approved/rejected the node';
COMMENT ON COLUMN remote_nodes.approved_at IS 'Timestamp when node was approved/rejected';
