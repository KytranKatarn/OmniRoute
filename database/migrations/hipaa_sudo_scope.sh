#!/bin/bash
# HIPAA-AC-08: Scope down NOPASSWD sudo for kytran automation user
#
# This script documents the required sudoers change. DO NOT auto-apply.
# Review carefully, then apply manually:
#   sudo visudo -f /etc/sudoers.d/kytran
#
# Current broad rule to REPLACE:
#   kytran ALL=(ALL) NOPASSWD: ALL
#
# Audit findings (2026-03-29):
#   - platform_v2/services/backup_integration_service.py: subprocess sudo rm -rf (backup cleanup)
#   - kytran-server-manager: no sudo calls found (standalone uses host command client)
#   - backup_manager_routes.py: references sudo in deploy.sh instructions (doc only, not runtime)
#   - app_builder deployment_generator.py: certbot references in generated deploy scripts (doc only)
#
# Required commands:
#   1. /usr/bin/rm -rf  (backup cleanup — backup_integration_service.py line 103)
#   2. /usr/bin/docker, /usr/bin/docker compose  (container management)
#   3. /usr/bin/systemctl restart archie*, /usr/bin/systemctl status archie*  (service control)
#   4. /usr/sbin/ufw  (firewall — security_network module)
#   5. /usr/bin/certbot  (TLS cert renewal)
#
# Recommended replacement for /etc/sudoers.d/kytran:

cat << 'EOF'
# Kytran automation user — scoped NOPASSWD sudo (HIPAA-AC-08)
# Last reviewed: 2026-03-29
# Replaces: kytran ALL=(ALL) NOPASSWD: ALL

# Container management
kytran ALL=(ALL) NOPASSWD: /usr/bin/docker
kytran ALL=(ALL) NOPASSWD: /usr/bin/docker compose
kytran ALL=(ALL) NOPASSWD: /usr/local/bin/docker-compose

# Service control (ARCHIE services only)
kytran ALL=(ALL) NOPASSWD: /usr/bin/systemctl restart archie*
kytran ALL=(ALL) NOPASSWD: /usr/bin/systemctl start archie*
kytran ALL=(ALL) NOPASSWD: /usr/bin/systemctl stop archie*
kytran ALL=(ALL) NOPASSWD: /usr/bin/systemctl status archie*

# Firewall management
kytran ALL=(ALL) NOPASSWD: /usr/sbin/ufw

# TLS certificate renewal
kytran ALL=(ALL) NOPASSWD: /usr/bin/certbot

# Backup cleanup (backup_integration_service.py — specific path prefix only)
kytran ALL=(ALL) NOPASSWD: /usr/bin/rm -rf /mnt/archie_brain/backups/*
EOF

echo ""
echo "Review complete. Apply with: sudo visudo -f /etc/sudoers.d/kytran"
echo "Validate with: sudo visudo -c"
