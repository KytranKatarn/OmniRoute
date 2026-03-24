# STIG + SOC 2 Compliance Module — Design Spec

**Date:** 2026-03-24
**Status:** Approved
**Author:** Claude + Kyt

---

## 1. Overview

A compliance scanning and evidence collection system that:
- Runs automated checks against STIG rule packs (Ubuntu 22.04, Docker, Network)
- Maps findings to SOC 2 Trust Service Criteria with evidence collection
- Provides one-click remediation with confirmation for common failures
- Exports STIG Viewer-compatible `.ckl` checklist files and evidence packages
- Exposes live compliance score badges via public API
- Ships in both A.R.C.H.I.E. (full) and Kytran Server Manager (subset)

## 2. Decisions

| # | Decision | Choice |
|---|----------|--------|
| 1 | Audience | Both: internal (A.R.C.H.I.E.) + external (Kytran Server Manager) |
| 2 | STIG scope | Ubuntu 22.04 + Docker + Network (~510 rules) |
| 3 | Rule architecture | Modular JSON rule packs — engine loads any pack |
| 4 | SOC 2 scope | Technical controls + evidence collection (auditor prep toolkit) |
| 5 | Remediation | One-click with LCARS confirmation modal; auto-remediation as future phase |
| 6 | Website badges | "We follow" text badges + live API-driven score badges |
| 7 | Module home | Security Network — two new tabs (Compliance + Hardening) |
| 8 | Boundary | System Ops = facts (reads data), Security Network = judgments (assesses compliance) |

## 3. Architecture

```
+-------------------------------------------------------------+
|                  Security Network Module                      |
|  +--------------+  +---------------+  +-----------------+    |
|  | Compliance   |  | Hardening     |  | Evidence        |    |
|  | Tab          |  | Tab           |  | Collector       |    |
|  |              |  |               |  |                 |    |
|  | STIG scores  |  | Fix buttons   |  | Auto-snapshot   |    |
|  | SOC 2 matrix |  | Before/after  |  | Artifact store  |    |
|  | History      |  | Confirmation  |  | Export .ckl     |    |
|  +------+-------+  +-------+-------+  +--------+--------+    |
|         |                  |                    |             |
|  +------+------------------+--------------------+----------+  |
|  |              Compliance Engine (service layer)           |  |
|  |  +-----------+  +------------+  +---------------------+  | |
|  |  | Rule      |  | Scanner    |  | Remediation         |  | |
|  |  | Loader    |  | Engine     |  | Engine              |  | |
|  |  |           |  |            |  |                     |  | |
|  |  | JSON rule |  | Runs each  |  | host_command_client |  | |
|  |  | packs     |  | check      |  | for OS-level fixes  |  | |
|  |  +-----------+  +------------+  +---------------------+  | |
|  +----------------------------------------------------------+ |
|                            |                                  |
|                    Data Sources:                               |
|  System Ops API --- Security Network --- host_command_client   |
|  (CPU/disk/net/fw)  (scans/SSL/events)  (OS-level commands)   |
+---------------------------------------------------------------+

+---------------------------------------------------------------+
|                    Public Badge API                             |
|  GET /api/public/compliance/badges                             |
|  -> { stig_score: 94, soc2_score: 87, last_scan: "2h ago" }  |
|  GET /api/public/compliance/badge/stig.svg                     |
|  -> SVG badge image for website embedding                      |
+---------------------------------------------------------------+
```

### Data Flow

1. **Scan trigger** (manual or scheduled) loads rule pack JSON
2. **Scanner engine** iterates rules, runs each check type against the system
3. **Results** stored in `compliance_scan_results` with pass/fail/error/not_applicable
4. **SOC 2 mapping** aggregates STIG results by Trust Service Criteria
5. **Evidence collector** auto-snapshots relevant artifacts (firewall rules, audit logs, SSL certs)
6. **Badge API** serves latest scores as JSON and SVG images (public, no auth)
7. **Remediation** runs fix commands via `host_command_client` after admin confirmation

### Module Boundary

| Module | Responsibility |
|--------|---------------|
| **System Operations** | Provides raw system data (CPU, disk, firewall state, services, processes, Docker, network) via API endpoints |
| **Security Network** | Owns compliance logic — loads rules, runs checks, stores results, renders UI, provides remediation |
| **host_command_client** | Executes OS-level commands for both scanning (read config files) and remediation (apply fixes) |

## 4. Rule Pack Format

Each STIG is a JSON file loaded into `compliance_rule_packs` table:

```json
{
  "id": "ubuntu-22.04-stig",
  "name": "Ubuntu 22.04 STIG",
  "version": "V1R1",
  "source": "DISA",
  "rules": [
    {
      "rule_id": "V-238196",
      "severity": "high",
      "title": "SSH must be configured to use only FIPS-validated MACs",
      "description": "Without cryptographic integrity protections, information can be altered during transmission.",
      "check": {
        "type": "file_content",
        "path": "/etc/ssh/sshd_config",
        "pattern": "^MACs\\s+",
        "expected": "hmac-sha2-256,hmac-sha2-512",
        "negate": false
      },
      "fix": {
        "type": "file_line",
        "path": "/etc/ssh/sshd_config",
        "line": "MACs hmac-sha2-256,hmac-sha2-512",
        "restart_service": "sshd",
        "risk": "medium"
      },
      "soc2_mapping": ["CC6.1", "CC6.7"],
      "cci": "CCI-001453"
    }
  ]
}
```

### Check Types

| Type | What It Checks | Data Source |
|------|---------------|-------------|
| `file_content` | Grep a file for a pattern, compare to expected | host_command_client |
| `file_permission` | Check file owner/group/mode | host_command_client |
| `file_exists` | Check if file exists (or doesn't) | host_command_client |
| `command_output` | Run a command, check output against pattern | host_command_client |
| `service_status` | Check if systemd service is enabled/running/disabled | System Ops services API |
| `sysctl_value` | Check kernel parameter via sysctl | host_command_client |
| `package_installed` | Check if apt package is installed (or not) | host_command_client |
| `docker_config` | Check Docker daemon.json or container config | System Ops docker API |
| `firewall_rule` | Check if UFW rule exists | System Ops firewall API |
| `port_listening` | Check if a port is/isn't listening | System Ops network API |

### Fix Types

| Type | What It Does | Risk |
|------|-------------|------|
| `file_line` | Add/replace a line in a config file | Varies |
| `file_permission` | chmod/chown a file | Low |
| `service_action` | Enable/disable/restart a systemd service | Medium |
| `sysctl_set` | Set a kernel parameter | Medium |
| `package_install` | Install/remove an apt package | Medium |
| `command_run` | Run an arbitrary whitelisted command | High |
| `firewall_add` | Add a UFW rule | Medium |
| `docker_config_set` | Modify Docker daemon.json | High |

## 5. Three STIG Rule Packs

### Ubuntu 22.04 STIG (~260 rules)

| Category | Example Rules | Count |
|----------|--------------|-------|
| SSH Configuration | FIPS MACs, key exchange, protocol version, root login, idle timeout | ~30 |
| Password Policy | Complexity, history, lockout, expiry, PAM config | ~25 |
| Audit Logging | auditd rules, log permissions, log rotation, remote logging | ~40 |
| File Permissions | /etc/passwd, /etc/shadow, /etc/group, home dirs, SUID/SGID | ~50 |
| Kernel Parameters | ASLR, core dumps, SYN cookies, IP forwarding, source routing | ~30 |
| Account Management | Inactive accounts, UID 0, duplicate UIDs, umask | ~25 |
| Services | Disable unnecessary (telnet, rsh, tftp), enable required (chrony) | ~30 |
| Filesystem | Separate partitions, noexec/nosuid/nodev on /tmp, /var | ~15 |
| Network | TCP wrappers, IPv6, DCCP/SCTP/RDS disabled | ~15 |

### Docker STIG (~100 rules)

| Category | Example Rules | Count |
|----------|--------------|-------|
| Daemon Configuration | TLS, user namespace, live restore, logging driver | ~20 |
| Container Isolation | Privileged mode, PID namespace, network mode, capabilities | ~25 |
| Images | Base image provenance, no secrets in layers, image scanning | ~15 |
| Networking | ICC, default bridge, published ports | ~15 |
| Resource Limits | Memory, CPU, restart policy, PIDs limit | ~15 |
| Logging | Log driver, log opts, container log size | ~10 |

### Network STIG (~150 rules)

| Category | Example Rules | Count |
|----------|--------------|-------|
| Firewall | Default deny, allowed ports justified, no ANY rules | ~30 |
| Open Ports | Only necessary ports listening, no legacy ports (23, 21) | ~25 |
| Services | No unnecessary network services, NTP configured | ~20 |
| TLS/SSL | Min TLS 1.2, strong ciphers, valid certificates | ~25 |
| DNS | DNSSEC, no open resolver, authorized forwarders | ~15 |
| Protocols | No unencrypted protocols (FTP, Telnet, HTTP for admin) | ~20 |
| Routing | No IP forwarding (unless router), no source routing | ~15 |

## 6. SOC 2 Control Matrix

### Trust Service Criteria Mapping

| Category | ID Range | Automated Controls | Manual Attestations |
|----------|----------|-------------------|-------------------|
| **Security** (Common Criteria) | CC1-CC9 | Access control (RBAC), encryption (SSL), firewall, vulnerability scans, audit logging, intrusion detection | Security policy, incident response plan, vendor management |
| **Availability** | A1.1-A1.3 | Uptime monitoring, health alerts, backup verification, capacity planning | Business continuity plan, disaster recovery testing |
| **Processing Integrity** | PI1.1-PI1.5 | Audit trail completeness, input validation, error rates | Change management policy, QA procedures |
| **Confidentiality** | C1.1-C1.2 | Encryption at rest/transit, access restrictions, data classification | Data retention policy, NDA tracking |
| **Privacy** | P1-P8 | (Minimal — mostly organizational) | Privacy policy, consent management, data subject rights |

### Evidence Artifacts

| Artifact | Source | Auto-Collected | Format |
|----------|--------|---------------|--------|
| Firewall rule snapshot | System Ops firewall API | Yes | JSON + text |
| Access control config | RBAC permissions dump | Yes | JSON |
| Audit log export | audit_log table (last 90 days) | Yes | CSV |
| SSL certificate status | SSL monitors | Yes | JSON |
| Vulnerability scan results | Nmap/Nuclei results | Yes | JSON |
| Docker security config | Docker daemon.json + container audit | Yes | JSON |
| Password policy config | PAM/login.defs check | Yes | Text |
| Service inventory | Running services list | Yes | JSON |
| User account inventory | Active users, roles, last login | Yes | JSON |
| Backup verification | Backup Manager last run | Yes | JSON |
| Network port inventory | Listening ports + processes | Yes | JSON |

Evidence stored in `compliance_evidence` table with timestamps. Exportable as ZIP "evidence package" for auditors.

## 7. Database Schema

```sql
-- Rule packs loaded into the system
CREATE TABLE IF NOT EXISTS compliance_rule_packs (
    id SERIAL PRIMARY KEY,
    pack_id VARCHAR(100) UNIQUE NOT NULL,
    name VARCHAR(200) NOT NULL,
    version VARCHAR(20),
    source VARCHAR(50) DEFAULT 'DISA',
    total_rules INTEGER DEFAULT 0,
    rules JSONB NOT NULL,
    loaded_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Scan runs (one per scan execution)
CREATE TABLE IF NOT EXISTS compliance_scans (
    id SERIAL PRIMARY KEY,
    scan_id UUID UNIQUE NOT NULL,
    pack_ids TEXT[] NOT NULL,
    total_rules INTEGER DEFAULT 0,
    passed INTEGER DEFAULT 0,
    failed INTEGER DEFAULT 0,
    errors INTEGER DEFAULT 0,
    not_applicable INTEGER DEFAULT 0,
    manual INTEGER DEFAULT 0,
    score DECIMAL(5,2),
    started_at TIMESTAMP,
    completed_at TIMESTAMP,
    triggered_by VARCHAR(100),
    node_id VARCHAR(64) DEFAULT 'hub'
);

-- Individual rule results per scan
CREATE TABLE IF NOT EXISTS compliance_scan_results (
    id SERIAL PRIMARY KEY,
    scan_id UUID NOT NULL REFERENCES compliance_scans(scan_id),
    pack_id VARCHAR(100) NOT NULL,
    rule_id VARCHAR(50) NOT NULL,
    severity VARCHAR(20),
    status VARCHAR(20) NOT NULL CHECK (status IN ('pass', 'fail', 'error', 'not_applicable', 'manual')),
    actual_value TEXT,
    expected_value TEXT,
    details TEXT,
    soc2_controls TEXT[],
    scanned_at TIMESTAMP DEFAULT NOW()
);

-- SOC 2 evidence artifacts
CREATE TABLE IF NOT EXISTS compliance_evidence (
    id SERIAL PRIMARY KEY,
    control_id VARCHAR(20) NOT NULL,
    artifact_type VARCHAR(50) NOT NULL,
    artifact_name VARCHAR(200),
    artifact_data JSONB,
    file_path TEXT,
    collected_at TIMESTAMP DEFAULT NOW(),
    valid_until TIMESTAMP,
    scan_id UUID REFERENCES compliance_scans(scan_id)
);

-- Manual attestations for organizational controls
CREATE TABLE IF NOT EXISTS compliance_attestations (
    id SERIAL PRIMARY KEY,
    control_id VARCHAR(20) NOT NULL,
    category VARCHAR(50) NOT NULL CHECK (category IN ('security', 'availability', 'processing_integrity', 'confidentiality', 'privacy')),
    attested_by INTEGER REFERENCES users(id),
    status VARCHAR(20) NOT NULL CHECK (status IN ('compliant', 'non_compliant', 'not_applicable', 'in_progress')),
    notes TEXT,
    evidence_url TEXT,
    attested_at TIMESTAMP DEFAULT NOW(),
    expires_at TIMESTAMP
);

-- Remediation actions taken
CREATE TABLE IF NOT EXISTS compliance_remediations (
    id SERIAL PRIMARY KEY,
    scan_id UUID REFERENCES compliance_scans(scan_id),
    rule_id VARCHAR(50) NOT NULL,
    pack_id VARCHAR(100),
    action_type VARCHAR(50),
    command_executed TEXT,
    result VARCHAR(20) CHECK (result IN ('success', 'failed', 'pending', 'cancelled')),
    risk_level VARCHAR(20),
    executed_by INTEGER REFERENCES users(id),
    confirmed_at TIMESTAMP,
    executed_at TIMESTAMP DEFAULT NOW(),
    before_value TEXT,
    after_value TEXT
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_scan_results_scan_id ON compliance_scan_results(scan_id);
CREATE INDEX IF NOT EXISTS idx_scan_results_status ON compliance_scan_results(status);
CREATE INDEX IF NOT EXISTS idx_scan_results_severity ON compliance_scan_results(severity);
CREATE INDEX IF NOT EXISTS idx_scans_completed ON compliance_scans(completed_at);
CREATE INDEX IF NOT EXISTS idx_evidence_control ON compliance_evidence(control_id);
CREATE INDEX IF NOT EXISTS idx_remediations_scan ON compliance_remediations(scan_id);
```

## 8. UI Design — Two New Tabs in Security Network

### Compliance Tab

```
+------------------------------------------------------------------+
|  STIG COMPLIANCE                                    [Run Scan] ▼  |
+------------------------------------------------------------------+
|                                                                    |
|  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐         |
|  │ OVERALL  │  │ UBUNTU   │  │ DOCKER   │  │ NETWORK  │         |
|  │   94%    │  │   96%    │  │   91%    │  │   89%    │         |
|  │  A Grade │  │ 250/260  │  │  91/100  │  │ 134/150  │         |
|  └──────────┘  └──────────┘  └──────────┘  └──────────┘         |
|                                                                    |
|  Filter: [All Packs ▼] [All Severity ▼] [Failed Only ☐]          |
|                                                                    |
|  ┌─────────┬──────┬─────────────────────────┬────────┬─────────┐ |
|  │ Rule ID │ Sev  │ Title                   │ Status │ Action  │ |
|  ├─────────┼──────┼─────────────────────────┼────────┼─────────┤ |
|  │V-238196 │ HIGH │ SSH FIPS-validated MACs  │ ✅ PASS│         │ |
|  │V-238197 │ HIGH │ SSH idle timeout 600s    │ ❌ FAIL│ [Fix]   │ |
|  │V-238198 │ MED  │ Audit log permissions    │ ✅ PASS│         │ |
|  └─────────┴──────┴─────────────────────────┴────────┴─────────┘ |
|                                                                    |
|  ── SOC 2 TRUST CRITERIA ──                                       |
|  ▸ Security (CC6)     87% ████████░░  12/14 controls              |
|  ▸ Availability (A1)  92% █████████░   3/3  controls              |
|  ▸ Processing (PI1)   80% ████████░░   4/5  controls              |
|  ▸ Confidential (C1)  100%██████████   2/2  controls              |
|  ▸ Privacy (P1-P8)    -- manual attestation required --           |
|                                                                    |
|  [Export .ckl] [Export CSV] [Download Evidence Package]            |
|                                                                    |
|  ── SCAN HISTORY ──                                                |
|  [Chart: score over time, last 30 scans]                          |
+------------------------------------------------------------------+
```

### Hardening Tab

```
+------------------------------------------------------------------+
|  SYSTEM HARDENING                        [Fix All Low-Risk]       |
+------------------------------------------------------------------+
|                                                                    |
|  ── CRITICAL (3 findings) ──                                      |
|  ┌────────────────────────────────────────────────────────────┐   |
|  │ V-238220: Root login must be disabled via SSH              │   |
|  │ Current: PermitRootLogin yes                               │   |
|  │ Expected: PermitRootLogin no                               │   |
|  │ Risk: HIGH  |  Pack: Ubuntu 22.04                          │   |
|  │                                           [Apply Fix ▶]   │   |
|  └────────────────────────────────────────────────────────────┘   |
|                                                                    |
|  ── HIGH (7 findings) ──                                          |
|  ...                                                               |
|                                                                    |
|  ── MEDIUM (12 findings) ──                                       |
|  ...                                                               |
|                                                                    |
|  ── LOW (5 findings) ──                                           |
|  ...                                                               |
+------------------------------------------------------------------+
```

### Remediation Confirmation Modal (LCARS)

```
+------------------------------------------+
|  ▌ APPLY SECURITY FIX                    |
|  ┌──────────────────────────────────────┐|
|  │ Rule: V-238220                       ||
|  │ Title: Disable SSH root login        ||
|  │                                      ||
|  │ This will:                           ||
|  │  1. Set PermitRootLogin no           ||
|  │     in /etc/ssh/sshd_config          ||
|  │  2. Restart sshd service             ||
|  │                                      ||
|  │ Risk Level: HIGH                     ||
|  │                                      ||
|  │ ⚠ This may affect active SSH         ||
|  │   sessions using root login.         ||
|  └──────────────────────────────────────┘|
|                                          |
|  [Cancel]              [Apply Fix ▶]     |
+------------------------------------------+
```

## 9. Public Badge API

### Endpoints

```
GET /api/public/compliance/badges
→ {
    "stig": {
      "score": 94,
      "grade": "A",
      "passed": 475,
      "total": 510,
      "last_scan": "2026-03-24T14:30:00Z",
      "packs": {
        "ubuntu-22.04": { "score": 96, "passed": 250, "total": 260 },
        "docker": { "score": 91, "passed": 91, "total": 100 },
        "network": { "score": 89, "passed": 134, "total": 150 }
      }
    },
    "soc2": {
      "score": 87,
      "grade": "B+",
      "categories": {
        "security": { "score": 87, "automated": 12, "manual": 2, "total": 14 },
        "availability": { "score": 92, "automated": 3, "manual": 0, "total": 3 },
        "processing_integrity": { "score": 80, "automated": 4, "manual": 1, "total": 5 },
        "confidentiality": { "score": 100, "automated": 2, "manual": 0, "total": 2 },
        "privacy": { "score": null, "automated": 0, "manual": 0, "total": 8 }
      }
    }
  }

GET /api/public/compliance/badge/stig.svg
→ SVG shield badge: "STIG | 94% A | green"

GET /api/public/compliance/badge/soc2.svg
→ SVG shield badge: "SOC 2 | 87% B+ | blue"

GET /api/public/compliance/badge/ubuntu.svg
→ SVG shield badge: "Ubuntu STIG | 96% | green"
```

### Grade Scale

| Score | Grade | Badge Color |
|-------|-------|-------------|
| 95-100 | A+ | Bright green |
| 90-94 | A | Green |
| 85-89 | B+ | Blue |
| 80-84 | B | Blue |
| 70-79 | C | Yellow |
| 60-69 | D | Orange |
| < 60 | F | Red |

### Security

- Public endpoints — no auth required
- Only expose scores and grades, never individual findings
- Rate limited: 60 requests/minute
- Cache: scores cached for 5 minutes

## 10. Website Integration

### kytranempowerment.com Compliance Section

Add to the company website:

```html
<!-- "We follow" text badges -->
<div class="compliance-badges">
  <div class="badge">
    <img src="https://img.shields.io/badge/DISA_STIG-Hardened-green" />
  </div>
  <div class="badge">
    <img src="https://img.shields.io/badge/SOC_2-Controls_Implemented-blue" />
  </div>
</div>

<!-- Live score badges from API -->
<div class="live-badges">
  <img src="http://192.168.1.200:3000/api/public/compliance/badge/stig.svg" alt="STIG Score" />
  <img src="http://192.168.1.200:3000/api/public/compliance/badge/soc2.svg" alt="SOC 2 Score" />
</div>
```

Also add to the Products showcase page (`/products`) and the standalone product README.

## 11. Standalone (Kytran Server Manager) Scope

### Ships With

- Compliance engine (rule loader + scanner + results storage)
- All 3 STIG rule packs (Ubuntu, Docker, Network)
- One-click remediation with confirmation
- Evidence collection (SQLite-based)
- .ckl export
- SOC 2 control matrix (technical controls only)
- Badge API
- Compliance + Hardening tabs in the UI

### Does NOT Ship With

- Nmap/Nikto/Nuclei/ZAP scanner integration (Security Network feature)
- Governance audit log (A.R.C.H.I.E. platform feature)
- Agent automation for scheduled scans (agent loop feature)
- Manual attestations for organizational SOC 2 controls (platform feature)

### Standalone Integration

The compliance engine lives in `kytran_server_manager/compliance/` as a self-contained module:
```
compliance/
├── __init__.py
├── engine.py          # Scanner engine
├── loader.py          # Rule pack loader
├── remediation.py     # Fix execution
├── evidence.py        # Artifact collection
├── export.py          # .ckl and CSV export
├── badges.py          # SVG badge generation
└── rule_packs/
    ├── ubuntu-22.04-stig.json
    ├── docker-stig.json
    └── network-stig.json
```

## 12. Implementation Phases

### Phase 1: Compliance Engine — Rule Loader + Scanner
- Create `compliance_service.py` in Security Network
- Rule pack loader (reads JSON, stores in DB)
- Scanner engine (iterates rules, runs check types)
- Result storage in `compliance_scans` + `compliance_scan_results`
- Database migration for all 6 tables

### Phase 2: Ubuntu STIG Rule Pack
- Research and encode ~260 Ubuntu 22.04 STIG rules as JSON
- Cover all check types: file_content, file_permission, command_output, service_status, sysctl_value, package_installed
- Include fix definitions for each rule with risk levels
- Include SOC 2 control mappings (CCI → CC mapping)

### Phase 3: Docker + Network STIG Packs
- Docker STIG: ~100 rules covering daemon, containers, images, networking, logging
- Network STIG: ~150 rules covering firewall, ports, TLS, DNS, protocols
- Both with fix definitions and SOC 2 mappings

### Phase 4: Compliance Tab UI
- Score cards (overall + per-pack)
- Rule results table with filter bar
- SOC 2 trust criteria expandable panels
- Export buttons (.ckl, .csv, evidence ZIP)
- Scan history chart (Chart.js)
- Register as new tab in Security Network template

### Phase 5: Hardening Tab UI
- Findings grouped by severity
- Each finding: current vs expected, risk level, fix button
- LCARS confirmation modal for remediation
- Before/after comparison display
- "Fix All Low-Risk" batch button
- Remediation history log

### Phase 6: SOC 2 Evidence Collector
- Auto-collect evidence artifacts from platform APIs
- Evidence storage in `compliance_evidence` table
- Manual attestation UI for organizational controls
- Evidence package export (ZIP with manifest)

### Phase 7: Export — .ckl + Evidence ZIP
- STIG Viewer-compatible .ckl XML generation
- CSV export of all findings
- Evidence ZIP with: findings CSV, evidence artifacts, attestations, scan metadata

### Phase 8: Public Badge API + SVG Generation
- Public endpoints (no auth, rate limited, cached)
- JSON scores endpoint
- SVG badge generation (shields.io-compatible format)
- Per-pack badge endpoints

### Phase 9: Website Integration
- Add compliance section to kytranempowerment.com
- Add live badges to Products showcase page
- Add badges to Kytran Server Manager README

### Phase 10: Standalone Integration
- Extract compliance engine into `kytran_server_manager/compliance/`
- Adapt for SQLite (no PostgreSQL dependency)
- Bundle rule packs
- Add Compliance + Hardening tabs to standalone dashboard
- Add badge API to standalone app

### Future: Auto-Remediation
- Scheduled compliance scan via agent loop job
- Low-risk fixes auto-applied (Tier 1 auto-approval)
- Medium/high-risk fixes queued for human approval via Telegram (Tier 2)
- Compliance score tracking over time with alerting on regression

---

## Appendix A: .ckl Export Format Reference

STIG Viewer uses XML-based `.ckl` (checklist) files. Minimal structure:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<CHECKLIST>
  <ASSET>
    <ROLE>None</ROLE>
    <ASSET_TYPE>Computing</ASSET_TYPE>
    <HOST_NAME>archie-hub</HOST_NAME>
    <HOST_IP>192.168.1.200</HOST_IP>
    <HOST_FQDN>archie.local</HOST_FQDN>
    <TARGET_KEY>4072</TARGET_KEY>
    <WEB_OR_DATABASE>false</WEB_OR_DATABASE>
  </ASSET>
  <STIGS>
    <iSTIG>
      <STIG_INFO>
        <SI_DATA><SID_NAME>title</SID_NAME><SID_DATA>Ubuntu 22.04 STIG</SID_DATA></SI_DATA>
        <SI_DATA><SID_NAME>version</SID_NAME><SID_DATA>V1R1</SID_DATA></SI_DATA>
      </STIG_INFO>
      <VULN>
        <STIG_DATA><VULN_ATTRIBUTE>Vuln_Num</VULN_ATTRIBUTE><ATTRIBUTE_DATA>V-238196</ATTRIBUTE_DATA></STIG_DATA>
        <STIG_DATA><VULN_ATTRIBUTE>Severity</VULN_ATTRIBUTE><ATTRIBUTE_DATA>high</ATTRIBUTE_DATA></STIG_DATA>
        <STIG_DATA><VULN_ATTRIBUTE>Rule_Title</VULN_ATTRIBUTE><ATTRIBUTE_DATA>SSH FIPS MACs</ATTRIBUTE_DATA></STIG_DATA>
        <STATUS>NotAFinding</STATUS>
        <FINDING_DETAILS>Automated check: PASS. MACs set to hmac-sha2-256,hmac-sha2-512</FINDING_DETAILS>
        <COMMENTS>Scanned by Kytran Server Manager</COMMENTS>
      </VULN>
    </iSTIG>
  </STIGS>
</CHECKLIST>
```

Status values: `NotAFinding` (pass), `Open` (fail), `Not_Applicable`, `Not_Reviewed` (manual).

Reference: DISA STIG Viewer 2.x format specification.

## Appendix B: Evidence Artifact Types

| Type Key | Description | Collection Source |
|----------|-------------|-------------------|
| `firewall_config` | UFW rules + status snapshot | System Ops firewall API |
| `audit_log_export` | Last 90 days of audit entries | audit_log table |
| `ssl_cert_status` | All monitored cert statuses + expiry | SSL monitors |
| `access_control_config` | RBAC roles, permissions, user list | RBAC + users table |
| `docker_config` | daemon.json + container security audit | System Ops docker API |
| `password_policy` | PAM config + login.defs | host_command_client |
| `service_inventory` | Running/enabled services | System Ops services API |
| `sysctl_dump` | All kernel parameters | host_command_client |
| `package_list` | Installed packages with versions | host_command_client |
| `network_listeners` | Listening ports + owning processes | System Ops network API |
| `user_accounts` | Active users, roles, last login dates | users table |
| `backup_status` | Last backup run + verification | Backup Manager API |
| `vulnerability_scan` | Latest Nmap/Nuclei results | Security Network scans |

## Appendix C: SQLite Schema Translation (Standalone)

| PostgreSQL | SQLite Equivalent |
|------------|-------------------|
| `SERIAL PRIMARY KEY` | `INTEGER PRIMARY KEY AUTOINCREMENT` |
| `UUID` | `TEXT` (store as string) |
| `JSONB` | `TEXT` (store as JSON string, parse in Python) |
| `TEXT[]` | `TEXT` (store as comma-separated or JSON array) |
| `TIMESTAMP DEFAULT NOW()` | `TIMESTAMP DEFAULT CURRENT_TIMESTAMP` |
| `DECIMAL(5,2)` | `REAL` |
| `VARCHAR(N)` | `TEXT` (SQLite ignores length) |
| `REFERENCES table(col)` | Supported (enable with `PRAGMA foreign_keys = ON`) |
| `CHECK constraints` | Supported natively |

## Appendix D: Batch Remediation Safety

- **Max per batch:** 10 fixes
- **Confirmation required:** Always, even for low-risk
- **If > 5 fixes in batch:** Extra warning: "You are about to apply N fixes. Review each one below."
- **Execution order:** Low-risk first, then medium (high-risk never batched)
- **Rollback:** Before-values stored in `compliance_remediations` for manual rollback reference
- **No auto-batch for services that require restart** — each restart is a separate confirmation

## Appendix E: Fleet Compliance Aggregation

- Each node scanned independently (scan has `node_id` column in `compliance_scans`)
- Hub Compliance tab shows: hub score + per-node scores in a fleet summary card
- Clicking a node shows that node's findings (via proxy, same as Starship health panels)
- Badge API returns hub scores by default; `?node_id=xxx` parameter for node-specific scores
- Fleet-wide score = weighted average by rule count across all online nodes
