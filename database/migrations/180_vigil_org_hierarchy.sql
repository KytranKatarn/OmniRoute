-- Migration: 180_vigil_org_hierarchy.sql
-- Decision #250: Vigil manages Security, Compliance, Privacy, DevOps, IT (13 agents)
BEGIN;

-- Set reports_to_agent_id = 3 (Vigil) for all 13 agents
UPDATE agents SET reports_to_agent_id = 3
WHERE id IN (
    36,   -- Sentry (Mikhail Volkov) — Security Analyst
    8,    -- DataMind (Amara Osei) — Chief Data Analyst
    18,   -- Cipher (Chidi Okafor) — Cryptography
    34,   -- Thorn (Rowan McAllister) — Pen Tester
    108,  -- Bastion (Anika Osei) — SOC Analyst
    132,  -- Ironclad (David Park) — Cybersecurity Ops Lead
    109,  -- Sentinel-2 (Grant Morrison) — Audit & Risk
    87,   -- Mandate (Arif Ibrahim) — Regulatory Compliance
    120,  -- Vault (Lars Eriksson) — Data Privacy Officer
    42,   -- Shield (Suki Taniguchi) — Risk & Compliance
    98,   -- Pipeline (Derek Huang) — DevOps Lead
    21,   -- Forge (Marek Kowalski) — Build & DevOps
    100   -- Helpdesk (Jordan Alexis) — IT Help Desk
);

COMMIT;
