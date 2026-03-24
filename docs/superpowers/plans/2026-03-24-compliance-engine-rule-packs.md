# Compliance Engine + Rule Packs Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the compliance scanning engine that loads STIG rule packs, runs automated checks against the system, stores results, and provides one-click remediation — all within the Security Network module.

**Architecture:** A service layer (`compliance_service.py`) with a modular scanner that iterates JSON rule packs, executing each check type (file_content, service_status, sysctl_value, etc.) via `host_command_client` or System Ops APIs. Results stored in PostgreSQL. Three rule packs (Ubuntu, Docker, Network) encoded as JSON files.

**Tech Stack:** Python, Flask, PostgreSQL, psycopg2, host_command_client, JSON rule packs

**Spec:** `docs/superpowers/specs/2026-03-24-compliance-module-design.md` (Phases 1-3)

**Scope:** Engine + 3 rule packs + scan API endpoint. Does NOT include UI tabs, SOC 2 matrix, badges, or export — those are separate plans.

---

## File Map

### Files to Create

| File | Responsibility |
|------|---------------|
| `tools/security_network/compliance_service.py` | Core engine: rule loader, scanner, result storage, remediation executor |
| `tools/security_network/compliance_routes.py` | API endpoints: run scan, get results, get history, apply fix |
| `tools/security_network/rule_packs/ubuntu-22.04-stig.json` | Ubuntu 22.04 STIG rules (~50 initial, expandable) |
| `tools/security_network/rule_packs/docker-stig.json` | Docker STIG rules (~30 initial, expandable) |
| `tools/security_network/rule_packs/network-stig.json` | Network STIG rules (~30 initial, expandable) |
| `database/migrations/compliance_tables.sql` | 6 table migration |

### Files to Modify

| File | Changes |
|------|---------|
| `tools/security_network/__init__.py` | Register compliance_routes |

### Note on Rule Pack Size

The spec calls for ~510 total rules. For this plan, we'll create a representative starter set (~110 rules total) covering the most impactful checks. Each pack is designed to be expanded incrementally — adding rules is just adding JSON entries, no code changes needed.

---

## Task 1: Database Migration — 6 Compliance Tables

**Files:**
- Create: `platform_v2/database/migrations/compliance_tables.sql`

- [ ] **Step 1: Create the migration file**

Write the SQL from the spec's Section 7, adapted for idempotent execution (IF NOT EXISTS everywhere):

```sql
-- Compliance Module Tables
-- Run: docker exec archie_database psql -U archie -d archie -f /mnt/archie_brain/platform_v2/database/migrations/compliance_tables.sql

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

CREATE INDEX IF NOT EXISTS idx_scan_results_scan_id ON compliance_scan_results(scan_id);
CREATE INDEX IF NOT EXISTS idx_scan_results_status ON compliance_scan_results(status);
CREATE INDEX IF NOT EXISTS idx_scan_results_severity ON compliance_scan_results(severity);
CREATE INDEX IF NOT EXISTS idx_scans_completed ON compliance_scans(completed_at);
CREATE INDEX IF NOT EXISTS idx_evidence_control ON compliance_evidence(control_id);
CREATE INDEX IF NOT EXISTS idx_remediations_scan ON compliance_remediations(scan_id);
```

- [ ] **Step 2: Run the migration**

```bash
docker exec archie_database psql -U archie -d archie -f /mnt/archie_brain/platform_v2/database/migrations/compliance_tables.sql
```

Expected: All tables created without errors.

- [ ] **Step 3: Verify tables exist**

```bash
docker exec archie_database psql -U archie -d archie -c "\dt compliance_*"
```

Expected: 6 tables listed.

- [ ] **Step 4: Commit**

```bash
git add platform_v2/database/migrations/compliance_tables.sql
git commit -m "feat(compliance): database migration — 6 tables for scanning + evidence"
```

---

## Task 2: Compliance Engine — `compliance_service.py`

**Files:**
- Create: `platform_v2/tools/security_network/compliance_service.py`

- [ ] **Step 1: Create the compliance service**

This is the core engine. It needs:

1. **`load_rule_pack(pack_path)`** — Read JSON file, upsert into `compliance_rule_packs` table
2. **`load_all_packs()`** — Load all JSON files from `rule_packs/` directory
3. **`run_scan(pack_ids=None, triggered_by="manual")`** — Run a full compliance scan:
   - Create scan record with UUID
   - For each rule in selected packs, run the check
   - Store results in `compliance_scan_results`
   - Calculate score, update scan summary
   - Return scan_id
4. **`_execute_check(rule)`** — Dispatch to the right check type handler
5. **Check type handlers:**
   - `_check_file_content(check)` — Read file via host_command, grep for pattern
   - `_check_file_permission(check)` — stat file via host_command
   - `_check_file_exists(check)` — test -f via host_command
   - `_check_command_output(check)` — Run command via host_command, match output
   - `_check_service_status(check)` — Check systemd service via host_command
   - `_check_sysctl_value(check)` — Read sysctl via host_command
   - `_check_package_installed(check)` — dpkg-query via host_command
   - `_check_docker_config(check)` — Read docker daemon.json or inspect
   - `_check_firewall_rule(check)` — Query System Ops firewall API
   - `_check_port_listening(check)` — Query System Ops network API
6. **`apply_fix(scan_id, rule_id, user_id)`** — Execute a remediation:
   - Look up the rule's fix definition
   - Execute via host_command_client
   - Record in `compliance_remediations` with before/after values
7. **`get_scan_results(scan_id)`** — Fetch results for a scan
8. **`get_scan_history(limit=20)`** — Recent scans with scores
9. **`get_latest_scores()`** — Most recent scan scores per pack

The engine should use `host_command_client.submit_and_wait()` for OS-level checks (file reads, sysctl, packages, services). Use `is_queue_available()` to gracefully handle when host_monitor isn't running.

For checks that read System Ops data (firewall, network, docker), use internal function calls to `system_service` or make HTTP requests to the local API.

**IMPORTANT:** Each check must be wrapped in try/except — a single failing check should not abort the entire scan. Failures get status='error' with the exception message.

- [ ] **Step 2: Verify it imports cleanly**

```bash
docker exec archie_platform python3 -c "from tools.security_network.compliance_service import run_scan; print('Import OK')"
```

- [ ] **Step 3: Commit**

```bash
git add platform_v2/tools/security_network/compliance_service.py
git commit -m "feat(compliance): scanning engine — rule loader + 10 check types + remediation"
```

---

## Task 3: Compliance API Routes — `compliance_routes.py`

**Files:**
- Create: `platform_v2/tools/security_network/compliance_routes.py`
- Modify: `platform_v2/tools/security_network/__init__.py`

- [ ] **Step 1: Create compliance_routes.py**

```python
def register_compliance_routes(bp, admin_required_decorator):

    @bp.route("/api/compliance/scan", methods=["POST"])
    @login_required
    @admin_required_decorator
    def api_run_compliance_scan():
        """Trigger a compliance scan. Optional: pack_ids filter."""
        # Read pack_ids from request JSON (or scan all if not specified)
        # Call run_scan()
        # Return scan_id + summary

    @bp.route("/api/compliance/scans")
    @login_required
    @admin_required_decorator
    def api_scan_history():
        """Get recent scan history with scores."""
        # Call get_scan_history()

    @bp.route("/api/compliance/scans/<scan_id>")
    @login_required
    @admin_required_decorator
    def api_scan_results(scan_id):
        """Get detailed results for a specific scan."""
        # Call get_scan_results(scan_id)
        # Support filters: ?status=fail&severity=high&pack_id=ubuntu-22.04-stig

    @bp.route("/api/compliance/scores")
    @login_required
    @admin_required_decorator
    def api_latest_scores():
        """Get latest compliance scores per pack."""
        # Call get_latest_scores()

    @bp.route("/api/compliance/packs")
    @login_required
    @admin_required_decorator
    def api_list_packs():
        """List loaded rule packs with metadata."""

    @bp.route("/api/compliance/fix", methods=["POST"])
    @login_required
    @admin_required_decorator
    def api_apply_fix():
        """Apply a remediation fix for a specific rule."""
        # Read scan_id, rule_id from JSON
        # Call apply_fix(scan_id, rule_id, current_user.id)
        # Return before/after values

    @bp.route("/api/compliance/packs/reload", methods=["POST"])
    @login_required
    @admin_required_decorator
    def api_reload_packs():
        """Reload rule packs from disk."""
        # Call load_all_packs()
```

- [ ] **Step 2: Register in __init__.py**

Add to Security Network's `__init__.py`:
```python
from .compliance_routes import register_compliance_routes
register_compliance_routes(security_network_bp, admin_required)
```

Look at the existing `__init__.py` to see how other routes are registered and follow the same pattern.

- [ ] **Step 3: Restart and verify endpoints exist**

```bash
docker compose restart archie_platform && sleep 5
curl -s http://192.168.1.200:3000/tools/security-network/api/compliance/packs -b "session=..." | head -c 200
```

- [ ] **Step 4: Commit**

```bash
git add platform_v2/tools/security_network/compliance_routes.py platform_v2/tools/security_network/__init__.py
git commit -m "feat(compliance): API routes — scan, results, scores, fix, packs"
```

---

## Task 4: Ubuntu STIG Rule Pack — Starter Set (~50 rules)

**Files:**
- Create: `platform_v2/tools/security_network/rule_packs/ubuntu-22.04-stig.json`

- [ ] **Step 1: Create the Ubuntu rule pack**

Write ~50 of the most impactful Ubuntu 22.04 STIG rules covering:

**SSH Configuration (~10 rules):**
- V-238196: FIPS-validated MACs (file_content /etc/ssh/sshd_config)
- V-238197: SSH idle timeout (file_content ClientAliveInterval)
- V-238198: SSH root login disabled (file_content PermitRootLogin)
- V-238199: SSH protocol version 2 (file_content Protocol)
- V-238200: SSH X11 forwarding disabled (file_content X11Forwarding)
- V-238201: SSH max auth tries (file_content MaxAuthTries)
- V-238202: SSH warning banner (file_content Banner)
- V-238203: SSH empty passwords denied (file_content PermitEmptyPasswords)
- V-238204: SSH AllowTcpForwarding disabled (file_content AllowTcpForwarding)
- V-238205: SSH strong key exchange (file_content KexAlgorithms)

**Password Policy (~8 rules):**
- V-238210: Min password length 14 (file_content /etc/security/pwquality.conf minlen)
- V-238211: Uppercase required (file_content ucredit)
- V-238212: Lowercase required (file_content lcredit)
- V-238213: Digit required (file_content dcredit)
- V-238214: Special char required (file_content ocredit)
- V-238215: Password history 5 (file_content /etc/pam.d/common-password remember)
- V-238216: Max password age 60 days (file_content /etc/login.defs PASS_MAX_DAYS)
- V-238217: Min password age 1 day (file_content /etc/login.defs PASS_MIN_DAYS)

**Audit Logging (~8 rules):**
- V-238220: auditd installed (package_installed auditd)
- V-238221: auditd enabled (service_status auditd)
- V-238222: Audit log not world-readable (file_permission /var/log/audit 0750)
- V-238223: Audit config not world-readable (file_permission /etc/audit/auditd.conf 0640)
- V-238224: Log failed login attempts (file_content /etc/pam.d/common-auth pam_tally2)
- V-238225: Audit log max size (file_content /etc/audit/auditd.conf max_log_file)
- V-238226: Audit log action on full (file_content /etc/audit/auditd.conf space_left_action)
- V-238227: Audit user/group changes (command_output auditctl -l, pattern "identity")

**Kernel Parameters (~8 rules):**
- V-238230: ASLR enabled (sysctl_value kernel.randomize_va_space = 2)
- V-238231: Core dumps restricted (sysctl_value fs.suid_dumpable = 0)
- V-238232: SYN cookies enabled (sysctl_value net.ipv4.tcp_syncookies = 1)
- V-238233: IP forwarding disabled (sysctl_value net.ipv4.ip_forward = 0)
- V-238234: Source routing disabled (sysctl_value net.ipv4.conf.all.accept_source_route = 0)
- V-238235: ICMP redirects disabled (sysctl_value net.ipv4.conf.all.accept_redirects = 0)
- V-238236: Secure ICMP redirects disabled (sysctl_value net.ipv4.conf.all.secure_redirects = 0)
- V-238237: Log martians enabled (sysctl_value net.ipv4.conf.all.log_martians = 1)

**File Permissions (~8 rules):**
- V-238240: /etc/passwd permissions (file_permission /etc/passwd 0644)
- V-238241: /etc/shadow permissions (file_permission /etc/shadow 0640)
- V-238242: /etc/group permissions (file_permission /etc/group 0644)
- V-238243: /etc/gshadow permissions (file_permission /etc/gshadow 0640)
- V-238244: /etc/passwd owner root (file_permission /etc/passwd owner=root)
- V-238245: /etc/shadow owner root (file_permission /etc/shadow owner=root)
- V-238246: No world-writable dirs without sticky (command_output find)
- V-238247: No unowned files (command_output find / -nouser)

**Services (~8 rules):**
- V-238250: Disable telnet (service_status telnet disabled)
- V-238251: Disable rsh (package_installed rsh-server absent)
- V-238252: Disable tftp (service_status tftpd-hpa disabled)
- V-238253: NTP configured (service_status chrony enabled)
- V-238254: Disable avahi (service_status avahi-daemon disabled)
- V-238255: Disable CUPS (if not needed) (service_status cups disabled)
- V-238256: Disable bluetooth (service_status bluetooth disabled)
- V-238257: USB storage disabled (file_content /etc/modprobe.d/ usb-storage)

Each rule includes: rule_id, severity, title, description, check definition, fix definition, soc2_mapping, cci.

- [ ] **Step 2: Commit**

```bash
git add platform_v2/tools/security_network/rule_packs/ubuntu-22.04-stig.json
git commit -m "feat(compliance): Ubuntu 22.04 STIG rule pack — 50 rules"
```

---

## Task 5: Docker STIG Rule Pack — Starter Set (~30 rules)

**Files:**
- Create: `platform_v2/tools/security_network/rule_packs/docker-stig.json`

- [ ] **Step 1: Create the Docker rule pack**

~30 rules covering:

**Daemon Configuration (~10 rules):**
- Docker daemon.json exists with proper settings
- TLS enabled for remote API
- User namespaces enabled
- Live restore enabled
- Default ulimits set
- Logging driver configured (json-file with max-size)
- No insecure registries
- Content trust enabled
- Icc (inter-container communication) disabled
- Userns-remap configured

**Container Security (~10 rules):**
- No privileged containers
- No containers sharing host PID namespace
- No containers sharing host network
- AppArmor/seccomp profiles applied
- Read-only root filesystem where possible
- No containers with all capabilities
- Memory limits set
- CPU limits set
- PIDs limit set
- Restart policy set (not "always" without max)

**Image & Logging (~10 rules):**
- Base images from trusted registries
- No secrets in environment variables
- Health checks defined
- Log rotation configured
- Docker socket not mounted in containers (except managers)
- No containers running as root (where avoidable)
- Images scanned for vulnerabilities
- Docker version is current
- Docker Compose version is current
- Unused images/volumes cleaned up

Check types: `docker_config` for daemon.json, `command_output` for `docker inspect`, `file_content` for daemon.json.

- [ ] **Step 2: Commit**

```bash
git add platform_v2/tools/security_network/rule_packs/docker-stig.json
git commit -m "feat(compliance): Docker STIG rule pack — 30 rules"
```

---

## Task 6: Network STIG Rule Pack — Starter Set (~30 rules)

**Files:**
- Create: `platform_v2/tools/security_network/rule_packs/network-stig.json`

- [ ] **Step 1: Create the Network rule pack**

~30 rules covering:

**Firewall (~10 rules):**
- UFW enabled (firewall_rule status=active)
- Default incoming policy = deny
- Default outgoing policy = allow
- No ANY/ANY rules (command_output ufw status verbose)
- SSH limited to specific IPs (firewall_rule)
- No unnecessary open ports
- IPv6 firewall enabled
- Logging enabled (file_content /etc/ufw/ufw.conf LOGLEVEL)
- No deprecated rules (review old rules)
- Rate limiting on exposed services

**Ports & Services (~10 rules):**
- No FTP (port 21) listening (port_listening 21 = false)
- No Telnet (port 23) listening
- No unencrypted HTTP for admin (port 80 only if reverse proxy)
- HTTPS on port 443 if web service (port_listening)
- SSH on non-default port (optional, informational)
- No SMTP relay (port 25 limited)
- DNS only if intentional (port 53)
- No NFS unless needed (port 2049)
- No SMB unless needed (port 445)
- No legacy RPC (port 111)

**TLS & Encryption (~10 rules):**
- TLS 1.2 minimum (command_output openssl)
- Strong cipher suites (file_content nginx/apache/sshd configs)
- Valid SSL certificates (command_output openssl verify)
- HSTS enabled (file_content nginx config)
- No self-signed certs in production
- Certificate expiry > 30 days
- OCSP stapling enabled
- No SSL 3.0 / TLS 1.0 / TLS 1.1
- Perfect forward secrecy ciphers preferred
- Certificate chain complete

- [ ] **Step 2: Commit**

```bash
git add platform_v2/tools/security_network/rule_packs/network-stig.json
git commit -m "feat(compliance): Network STIG rule pack — 30 rules"
```

---

## Task 7: Integration Test — Run a Scan

- [ ] **Step 1: Load rule packs and run a scan**

```bash
# Load packs
curl -X POST http://192.168.1.200:3000/tools/security-network/api/compliance/packs/reload -b "session=..."

# Run scan
curl -X POST http://192.168.1.200:3000/tools/security-network/api/compliance/scan -b "session=..." -H "Content-Type: application/json" -d '{}'

# Get results
curl http://192.168.1.200:3000/tools/security-network/api/compliance/scores -b "session=..."
```

Expected: Scan completes with scores. Some rules pass, some fail — that's expected on a real system.

- [ ] **Step 2: Verify scan results in database**

```bash
docker exec archie_database psql -U archie -d archie -c "SELECT scan_id, total_rules, passed, failed, score FROM compliance_scans ORDER BY completed_at DESC LIMIT 1"
```

- [ ] **Step 3: Verify individual results**

```bash
docker exec archie_database psql -U archie -d archie -c "SELECT rule_id, severity, status FROM compliance_scan_results WHERE scan_id = (SELECT scan_id FROM compliance_scans ORDER BY completed_at DESC LIMIT 1) AND status = 'fail' LIMIT 10"
```

- [ ] **Step 4: Commit any integration fixes**

```bash
git commit -m "fix(compliance): integration fixes from first live scan"
```
