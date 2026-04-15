#!/usr/bin/env bash
# Permanent brainstorm server launcher for A.R.C.H.I.E.
# Wraps the superpowers visual companion with correct subdomain config.
#
# Usage: scripts/start-brainstorm.sh
# URL:   https://brainstorm.kytranempowerment.com
#
# Infrastructure (all permanent, no reconfiguration needed):
#   - Port 52000 (UFW allowed)
#   - NPM proxy: brainstorm.kytranempowerment.com -> 192.168.1.200:52000 (SSL)
#   - AdGuard split DNS: brainstorm.kytranempowerment.com -> 192.168.1.200
#   - Hostinger DNS: A record via DDNS script

BRAINSTORM_PORT=52000 \
  /home/kytran/.claude/plugins/cache/claude-plugins-official/superpowers/5.0.7/skills/brainstorming/scripts/start-server.sh \
  --project-dir /mnt/archie_brain \
  --host 0.0.0.0 \
  --url-host brainstorm.kytranempowerment.com
