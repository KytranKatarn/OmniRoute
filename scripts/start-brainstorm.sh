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

# Pin the server's "owner" to PID 1 (init/systemd) so it never dies.
# The upstream script's grandparent-PID detection doesn't survive Claude's
# Bash tool (parent shell exits immediately after a command). Our local
# patch to start-server.sh honors BRAINSTORM_OWNER_PID_OVERRIDE.
# Permanent fix: task #2069 — build brainstorm as a platform module.
setsid nohup env BRAINSTORM_PORT=52000 BRAINSTORM_OWNER_PID_OVERRIDE=1 \
  /home/kytran/.claude/plugins/cache/claude-plugins-official/superpowers/5.0.7/skills/brainstorming/scripts/start-server.sh \
  --project-dir /mnt/archie_brain \
  --host 0.0.0.0 \
  --url-host brainstorm.kytranempowerment.com \
  </dev/null >>/tmp/brainstorm-launcher.log 2>&1 &
disown
sleep 2
# Print the startup JSON so callers can parse URL/session paths
tail -n 1 /tmp/brainstorm-launcher.log
