#!/usr/bin/env bash
# A.R.C.H.I.E. STIG Compliance Hardening Script
# Fixes ~47 compliance failures across SSH, kernel, Docker, and password policy
# Run as root: sudo bash scripts/compliance_harden.sh [--restart-docker]

set -euo pipefail

BACKUP_DIR="/root/compliance-backup-$(date +%Y%m%d-%H%M%S)"
SSHD_CONFIG="/etc/ssh/sshd_config"
SYSCTL_CONF="/etc/sysctl.conf"
DOCKER_JSON="/etc/docker/daemon.json"
PWQUALITY="/etc/security/pwquality.conf"
LOGINDEFS="/etc/login.defs"
RESTART_DOCKER=false
CHANGES=0

# Parse args
for arg in "$@"; do
    case $arg in
        --restart-docker) RESTART_DOCKER=true ;;
        -h|--help)
            echo "Usage: sudo bash $0 [--restart-docker]"
            echo "  --restart-docker  Restart Docker daemon after hardening (causes brief container downtime)"
            exit 0
            ;;
    esac
done

echo "═══════════════════════════════════════════"
echo "  A.R.C.H.I.E. STIG Compliance Hardening"
echo "═══════════════════════════════════════════"
echo ""

# ═══ BACKUP ═══
echo "[1/6] Backing up configs to $BACKUP_DIR..."
mkdir -p "$BACKUP_DIR"
for f in "$SSHD_CONFIG" "$SYSCTL_CONF" "$DOCKER_JSON" "$PWQUALITY" "$LOGINDEFS"; do
    if [ -f "$f" ]; then
        cp -p "$f" "$BACKUP_DIR/"
        echo "  Saved: $f"
    fi
done
echo "  Backups complete"
echo ""

# ═══ SSH HARDENING (~32 rules) ═══
echo "[2/6] Hardening SSH..."

add_ssh_setting() {
    local key="$1"
    local value="$2"
    if grep -q "^${key} " "$SSHD_CONFIG" 2>/dev/null; then
        sed -i "s|^${key} .*|${key} ${value}|" "$SSHD_CONFIG"
        echo "  Updated: ${key} ${value}"
    elif grep -q "^#${key} " "$SSHD_CONFIG" 2>/dev/null; then
        sed -i "s|^#${key} .*|${key} ${value}|" "$SSHD_CONFIG"
        echo "  Uncommented: ${key} ${value}"
    else
        echo "${key} ${value}" >> "$SSHD_CONFIG"
        echo "  + Added: ${key} ${value}"
    fi
    CHANGES=$((CHANGES + 1))
}

if [ -f "$SSHD_CONFIG" ]; then
    add_ssh_setting "Protocol" "2"
    add_ssh_setting "PermitRootLogin" "no"
    add_ssh_setting "PermitEmptyPasswords" "no"
    add_ssh_setting "MaxAuthTries" "3"
    add_ssh_setting "ClientAliveInterval" "600"
    add_ssh_setting "ClientAliveCountMax" "0"
    add_ssh_setting "LoginGraceTime" "60"
    add_ssh_setting "X11Forwarding" "no"
    add_ssh_setting "AllowTcpForwarding" "no"
    add_ssh_setting "Banner" "/etc/issue.net"
    add_ssh_setting "MACs" "hmac-sha2-256,hmac-sha2-512"
    add_ssh_setting "Ciphers" "aes256-ctr,aes192-ctr,aes128-ctr"
    add_ssh_setting "KexAlgorithms" "ecdh-sha2-nistp256,ecdh-sha2-nistp384,ecdh-sha2-nistp521,diffie-hellman-group14-sha256"

    # Create banner if missing
    if [ ! -f /etc/issue.net ]; then
        echo "Authorized users only. All activity may be monitored and reported." > /etc/issue.net
        echo "  + Created /etc/issue.net"
    fi
    echo "  SSH hardened (13 settings)"
else
    echo "  WARNING: $SSHD_CONFIG not found, skipping"
fi
echo ""

# ═══ SYSCTL HARDENING (3 rules) ═══
echo "[3/6] Hardening kernel parameters..."

apply_sysctl() {
    local param="$1"
    local value="$2"
    sysctl -w "${param}=${value}" >/dev/null 2>&1 || echo "  WARNING: Could not set ${param} live (may need reboot)"
    if grep -q "^${param}" "$SYSCTL_CONF" 2>/dev/null; then
        sed -i "s|^${param}.*|${param} = ${value}|" "$SYSCTL_CONF"
        echo "  Updated: ${param} = ${value}"
    else
        echo "${param} = ${value}" >> "$SYSCTL_CONF"
        echo "  + Added: ${param} = ${value}"
    fi
    CHANGES=$((CHANGES + 1))
}

apply_sysctl "net.ipv6.conf.all.disable_ipv6" "1"
apply_sysctl "net.ipv4.tcp_keepalive_time" "1800"
apply_sysctl "net.ipv4.conf.all.rp_filter" "1"
echo "  Kernel params hardened (3 settings)"
echo ""

# ═══ DOCKER HARDENING (~12 rules) ═══
echo "[4/6] Hardening Docker daemon..."

if [ -f "$DOCKER_JSON" ]; then
    DOCKER_CFG=$(cat "$DOCKER_JSON")
else
    DOCKER_CFG="{}"
fi

python3 -c "
import json, sys

existing = json.loads('''$DOCKER_CFG''')

# Security settings — only add if not already present
hardening = {
    'icc': False,
    'live-restore': True,
    'log-driver': 'json-file',
    'log-opts': {'max-size': '10m', 'max-file': '3'},
    'no-new-privileges': True,
    'storage-driver': 'overlay2',
    'default-ulimits': {
        'nofile': {'Name': 'nofile', 'Hard': 65536, 'Soft': 65536}
    },
    'insecure-registries': [],
    'userns-remap': 'default',
}

added = 0
for k, v in hardening.items():
    if k not in existing:
        existing[k] = v
        print(f'  + Added: {k} = {v}')
        added += 1
    else:
        print(f'  Kept existing: {k} = {existing[k]}')

with open('$DOCKER_JSON', 'w') as f:
    json.dump(existing, f, indent=2)
print(f'  Docker daemon.json updated ({added} new, {len(hardening) - added} existing)')
"
CHANGES=$((CHANGES + 7))

if [ "$RESTART_DOCKER" = true ]; then
    echo "  Restarting Docker (containers will briefly stop)..."
    systemctl restart docker
    echo "  Docker restarted"
else
    echo "  Docker restart skipped (run with --restart-docker to apply)"
fi
echo ""

# ═══ PASSWORD POLICY (~10 rules) ═══
echo "[5/6] Hardening password policy..."

if [ -f "$PWQUALITY" ]; then
    set_pwquality() {
        local key="$1"
        local val="$2"
        if grep -q "^${key}" "$PWQUALITY" 2>/dev/null; then
            sed -i "s|^${key}.*|${key} = ${val}|" "$PWQUALITY"
        elif grep -q "^# *${key}" "$PWQUALITY" 2>/dev/null; then
            sed -i "s|^# *${key}.*|${key} = ${val}|" "$PWQUALITY"
        else
            echo "${key} = ${val}" >> "$PWQUALITY"
        fi
        echo "  Set: ${key} = ${val}"
        CHANGES=$((CHANGES + 1))
    }

    set_pwquality "minlen" "14"
    set_pwquality "ucredit" "-1"
    set_pwquality "lcredit" "-1"
    set_pwquality "dcredit" "-1"
    set_pwquality "ocredit" "-1"
    set_pwquality "difok" "8"
else
    echo "  WARNING: $PWQUALITY not found (install libpam-pwquality), skipping"
fi

if [ -f "$LOGINDEFS" ]; then
    sed -i 's/^PASS_MAX_DAYS.*/PASS_MAX_DAYS\t60/' "$LOGINDEFS"
    sed -i 's/^PASS_MIN_DAYS.*/PASS_MIN_DAYS\t1/' "$LOGINDEFS"
    echo "  Set: PASS_MAX_DAYS = 60"
    echo "  Set: PASS_MIN_DAYS = 1"
    CHANGES=$((CHANGES + 2))
else
    echo "  WARNING: $LOGINDEFS not found, skipping"
fi

# PAM hardening — password history and account lockout
COMMON_PASSWORD="/etc/pam.d/common-password"
COMMON_AUTH="/etc/pam.d/common-auth"

if [ -f "$COMMON_PASSWORD" ]; then
    if ! grep -q "remember=" "$COMMON_PASSWORD" 2>/dev/null; then
        sed -i '/pam_unix.so/ s/$/ remember=5/' "$COMMON_PASSWORD"
        echo "  + Added: pam_unix.so remember=5"
        CHANGES=$((CHANGES + 1))
    else
        echo "  Kept: pam_unix.so remember already set"
    fi
fi

if [ -f "$COMMON_AUTH" ]; then
    if ! grep -q "pam_faillock\|pam_tally2" "$COMMON_AUTH" 2>/dev/null; then
        # Add pam_faillock before pam_unix
        sed -i '/pam_unix.so/i auth    required    pam_faillock.so preauth silent deny=3 unlock_time=900' "$COMMON_AUTH"
        echo "  + Added: pam_faillock.so (deny=3, unlock_time=900)"
        CHANGES=$((CHANGES + 1))
    else
        echo "  Kept: pam_faillock already configured"
    fi
fi
echo ""

# ═══ RESTART SERVICES ═══
echo "[6/6] Restarting services..."

# Restart SSH (safe — existing sessions stay connected)
if systemctl restart ssh 2>/dev/null; then
    echo "  SSH restarted (ssh.service)"
elif systemctl restart sshd 2>/dev/null; then
    echo "  SSH restarted (sshd.service)"
else
    echo "  WARNING: Could not restart SSH service"
fi

# Reload sysctl
sysctl -p >/dev/null 2>&1 && echo "  sysctl reloaded" || echo "  WARNING: sysctl reload had errors"

echo ""
echo "═══════════════════════════════════════════"
echo "  Hardening Complete: ~$CHANGES changes applied"
echo "  Backups at: $BACKUP_DIR"
echo "═══════════════════════════════════════════"
echo ""
echo "NEXT STEPS:"
if [ "$RESTART_DOCKER" = false ]; then
    echo "  1. Restart Docker to apply daemon.json changes:"
    echo "     sudo systemctl restart docker"
    echo "  2. Wait for containers to come back up (~30s)"
    echo "  3. Re-run compliance scan to verify new score"
else
    echo "  1. Re-run compliance scan to verify new score"
fi
