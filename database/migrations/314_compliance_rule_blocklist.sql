-- Compliance Rule Blocklist: rules that must not be auto-fixed but still
-- need manual remediation tracking for STIG/SOC2 compliance.
-- Replaces the hardcoded _MANUAL_ONLY_RULES set in compliance_service.py.

CREATE TABLE IF NOT EXISTS compliance_rule_blocklist (
    id SERIAL PRIMARY KEY,
    rule_id VARCHAR(100) NOT NULL UNIQUE,
    pack_id VARCHAR(100),
    reason TEXT NOT NULL,
    risk_level VARCHAR(20) DEFAULT 'high',
    manual_steps TEXT,
    created_by INTEGER REFERENCES users(id),
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    -- When the admin manually applied the fix outside the pipeline
    manually_applied_at TIMESTAMP,
    manually_applied_by INTEGER REFERENCES users(id),
    manually_applied_note TEXT
);

CREATE INDEX IF NOT EXISTS idx_comp_blocklist_rule
    ON compliance_rule_blocklist(rule_id);

CREATE INDEX IF NOT EXISTS idx_comp_blocklist_pack
    ON compliance_rule_blocklist(pack_id);

-- Seed with the rules we know are catastrophic
INSERT INTO compliance_rule_blocklist
    (rule_id, pack_id, reason, risk_level, manual_steps)
VALUES
    (
        'D-238002',
        'docker-stig',
        'Docker userns-remap wipes visible containers on a running host. Existing containers become inaccessible after docker restart and must be recreated in the new user namespace.',
        'critical',
        E'## Manual Remediation for D-238002 (Docker userns-remap)\n\n### Prerequisites\n- Planned downtime window (minimum 30 min)\n- All container data backed up (volumes, databases)\n- Recreation commands ready for every container\n\n### Steps\n1. Stop all containers: `docker compose down`\n2. Backup all named volumes to external storage\n3. Backup /var/lib/docker directory\n4. Edit /etc/docker/daemon.json, add `"userns-remap": "default"`\n5. Restart docker: `sudo systemctl restart docker`\n6. Recreate dockremap user/group (auto-done by docker on first run)\n7. Recreate all containers: `docker compose up -d`\n8. Verify all services healthy\n9. Restore any data-migration from backups if needed\n\n### Verification\n```bash\ndocker info | grep -i userns\n# Expected: userns: default\n```\n\n### Rollback plan (if things break)\n1. Edit daemon.json, remove userns-remap\n2. Restart docker\n3. Restore volumes from backup'
    ),
    (
        'D-238004',
        'docker-stig',
        'Disabling the Docker Unix socket breaks all services that communicate with Docker via /var/run/docker.sock (docker-compose, Portainer, sandbox manager, etc.)',
        'critical',
        E'## Manual Remediation for D-238004\n\nOnly disable the socket if you have a TLS-protected TCP listener configured and ALL docker clients are updated to use it. This is a major architectural change.\n\n### Steps\n1. Set up docker TLS certs (ca.pem, server.pem, key.pem)\n2. Configure TCP listener on :2376 with TLS\n3. Test every docker client with the new endpoint\n4. Only then disable the unix socket'
    ),
    (
        'D-238005',
        'docker-stig',
        'Forcing docker to TLS-only requires all clients to have certs pre-provisioned. Breaks any client without certs.',
        'critical',
        E'## Manual Remediation for D-238005\n\nSame prerequisites as D-238004. Must have TLS infrastructure in place before applying.'
    )
ON CONFLICT (rule_id) DO UPDATE SET
    pack_id = EXCLUDED.pack_id,
    reason = EXCLUDED.reason,
    risk_level = EXCLUDED.risk_level,
    manual_steps = EXCLUDED.manual_steps,
    updated_at = NOW();
