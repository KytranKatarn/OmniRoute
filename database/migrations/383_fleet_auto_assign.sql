-- Migration 383: Fleet model-affinity auto-assignment
-- auto_assigned flag on node_agents distinguishes hub-triggered auto-assignments
-- from manually curated ones. Auto-assigned rows are set on OTA model_pull ack
-- and cleared when a node goes offline.

ALTER TABLE node_agents ADD COLUMN IF NOT EXISTS auto_assigned BOOLEAN DEFAULT FALSE;
