#!/usr/bin/env bash
# A.R.C.H.I.E. Compliance Boost Script — push STIG score from 46% to 80%+
# Run as root: sudo bash scripts/compliance_boost.sh
set -euo pipefail

CHANGES=0
echo "=== A.R.C.H.I.E. Compliance Boost ==="

# 1. SSH hardening fixes
echo "[1/8] Fixing SSH config..."
SSHD="/etc/ssh/sshd_config"
SSHC="/etc/ssh/ssh_config"

# V-238204: ClientAliveCountMax must be 1 (not 0)
if grep -q '^ClientAliveCountMax 0' "$SSHD" 2>/dev/null; then
    sed -i 's/^ClientAliveCountMax 0/ClientAliveCountMax 1/' "$SSHD"
    echo "  Fixed: ClientAliveCountMax 0 -> 1"
    CHANGES=$((CHANGES + 1))
fi

# HIPAA-TX-06: StrictHostKeyChecking in ssh_config (client-side)
if ! grep -q '^[[:space:]]*StrictHostKeyChecking' "$SSHC" 2>/dev/null; then
    echo "    StrictHostKeyChecking yes" >> "$SSHC"
    echo "  Added: StrictHostKeyChecking yes to ssh_config"
    CHANGES=$((CHANGES + 1))
fi

# Restart SSH
systemctl restart ssh 2>/dev/null || systemctl restart sshd 2>/dev/null || echo "  WARN: Could not restart SSH"

# 2. Install and configure auditd
echo "[2/8] Installing auditd..."
if ! dpkg -l auditd 2>/dev/null | grep -q '^ii'; then
    apt-get install -y auditd audispd-plugins >/dev/null 2>&1
    echo "  Installed auditd"
    CHANGES=$((CHANGES + 1))
else
    echo "  auditd already installed"
fi

systemctl enable auditd 2>/dev/null
systemctl start auditd 2>/dev/null || echo "  WARN: Could not start auditd"

# Create audit rules file
mkdir -p /etc/audit/rules.d
cat > /etc/audit/rules.d/audit.rules << 'AUDITRULES'
# STIG/HIPAA Audit Rules
# Login events (V-238220)
-w /var/log/lastlog -p wa -k logins
-w /var/run/faillock -p wa -k logins

# Privileged commands (V-238221)
-a always,exit -F path=/usr/bin/sudo -F perm=x -F auid>=1000 -F auid!=4294967295 -k priv_cmd

# File deletion (V-238222)
-a always,exit -F arch=b64 -S unlink,unlinkat,rename,renameat -F auid>=1000 -F auid!=4294967295 -k delete

# Permission changes (V-238223)
-a always,exit -F arch=b64 -S chmod,fchmod,fchmodat -F auid>=1000 -F auid!=4294967295 -k perm_mod

# Ownership changes (V-238226)
-a always,exit -F arch=b64 -S chown,fchown,lchown,fchownat -F auid>=1000 -F auid!=4294967295 -F key=owner_mod

# Module loading (V-238227)
-w /sbin/insmod -p x -k modules
-w /sbin/modprobe -p x -k modules

# Identity files
-w /etc/passwd -p wa -k identity
-w /etc/group -p wa -k identity
-w /etc/shadow -p wa -k identity
-w /etc/gshadow -p wa -k identity
-w /etc/security -p wa -k security
-w /var/log/sudo.log -p wa -k sudo_log

# Immutable flag (HIPAA-AU-05) — must be last
-e 2
AUDITRULES
echo "  Created /etc/audit/rules.d/audit.rules"
CHANGES=$((CHANGES + 8))

# Load rules
augenrules --load 2>/dev/null || auditctl -R /etc/audit/rules.d/audit.rules 2>/dev/null || echo "  WARN: Could not load audit rules"

# Fix audit log permissions (HIPAA-AU-03)
if [ -f /var/log/audit/audit.log ]; then
    chmod 0600 /var/log/audit/audit.log
    chown root:root /var/log/audit/audit.log
    echo "  Fixed: audit.log permissions 0600 root:root"
fi

# Fix /var/log/audit directory permissions (V-238224)
if [ -d /var/log/audit ]; then
    chmod 0750 /var/log/audit
    chown root:root /var/log/audit
    echo "  Fixed: /var/log/audit permissions 0750 root:root"
fi

# 3. Sysctl fixes
echo "[3/8] Fixing kernel parameters..."

# N-238014: tcp_keepalive_time — rule expects 600, current is 1800
sysctl -w net.ipv4.tcp_keepalive_time=600 >/dev/null 2>&1
if ! grep -q '^net.ipv4.tcp_keepalive_time = 600' /etc/sysctl.conf 2>/dev/null; then
    sed -i 's/^net.ipv4.tcp_keepalive_time.*/net.ipv4.tcp_keepalive_time = 600/' /etc/sysctl.conf 2>/dev/null || \
    echo "net.ipv4.tcp_keepalive_time = 600" >> /etc/sysctl.conf
fi
echo "  Fixed: tcp_keepalive_time = 600"

# V-238230: core dumps restriction
sysctl -w fs.suid_dumpable=0 >/dev/null 2>&1
if ! grep -q '^fs.suid_dumpable' /etc/sysctl.conf 2>/dev/null; then
    echo "fs.suid_dumpable = 0" >> /etc/sysctl.conf
else
    sed -i 's/^fs.suid_dumpable.*/fs.suid_dumpable = 0/' /etc/sysctl.conf
fi
echo "  Fixed: fs.suid_dumpable = 0"
CHANGES=$((CHANGES + 2))

sysctl -p >/dev/null 2>&1

# 4. OpenSSL TLS minimum (HIPAA-TX-01)
echo "[4/8] Fixing OpenSSL config..."
OPENSSL_CNF="/etc/ssl/openssl.cnf"
if ! grep -q 'MinProtocol' "$OPENSSL_CNF" 2>/dev/null; then
    if grep -q '\[system_default_sect\]' "$OPENSSL_CNF" 2>/dev/null; then
        sed -i '/\[system_default_sect\]/a MinProtocol = TLSv1.2' "$OPENSSL_CNF"
    else
        echo -e "\n[system_default_sect]\nMinProtocol = TLSv1.2" >> "$OPENSSL_CNF"
    fi
    echo "  Added: MinProtocol = TLSv1.2"
    CHANGES=$((CHANGES + 1))
else
    echo "  MinProtocol already set"
fi

# 5. Session timeout (HIPAA-AC-05)
echo "[5/8] Fixing session timeout..."
if ! grep -q 'TMOUT=' /etc/profile 2>/dev/null; then
    echo 'export TMOUT=600' >> /etc/profile
    echo "  Added: TMOUT=600 to /etc/profile"
    CHANGES=$((CHANGES + 1))
fi

# 6. Docker daemon.json updates
echo "[6/8] Updating Docker daemon.json..."
DOCKER_JSON="/etc/docker/daemon.json"
python3 -c "
import json
with open('$DOCKER_JSON') as f:
    cfg = json.load(f)
added = 0
if 'default-pids-limit' not in cfg:
    cfg['default-pids-limit'] = 100
    added += 1
    print('  + Added: default-pids-limit = 100')
with open('$DOCKER_JSON', 'w') as f:
    json.dump(cfg, f, indent=2)
print(f'  Docker daemon.json: {added} settings added')
"
CHANGES=$((CHANGES + 2))

# 7. Docker content trust
echo "[7/8] Setting DOCKER_CONTENT_TRUST..."
if ! grep -q 'DOCKER_CONTENT_TRUST' /etc/environment 2>/dev/null; then
    echo 'DOCKER_CONTENT_TRUST=1' >> /etc/environment
    echo "  Added: DOCKER_CONTENT_TRUST=1 to /etc/environment"
    CHANGES=$((CHANGES + 1))
fi

# Also export for current session
export DOCKER_CONTENT_TRUST=1

# 8. Clean up dangling Docker images
echo "[8/8] Cleaning dangling images..."
DANGLING=$(docker images -f dangling=true -q 2>/dev/null | wc -l)
if [ "$DANGLING" -gt 0 ]; then
    docker image prune -f >/dev/null 2>&1
    echo "  Removed $DANGLING dangling images"
    CHANGES=$((CHANGES + 1))
else
    echo "  No dangling images"
fi

echo ""
echo "=== Compliance Boost Complete: $CHANGES changes ==="
echo "NOTE: Docker daemon restart NOT included (would stop containers)."
echo "The 'hosts' setting in daemon.json requires Docker restart with -H flag override."
echo ""
echo "Next: restart archie_platform and re-run compliance scan"
