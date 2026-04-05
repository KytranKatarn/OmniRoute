#!/bin/bash
# DNS Redirect — Route all DNS through AdGuard for monitoring
# This intercepts any device trying to use external DNS (8.8.8.8, etc.)
# and transparently redirects to AdGuard (192.168.1.200:53)
#
# SAFETY: Only redirects traffic from OTHER LAN devices (via eno1 PREROUTING).
#         The "! -d $ADGUARD_IP" exclusion prevents redirect loops.
#         Traffic originating from 192.168.1.200 itself is NOT affected.
#
# To undo: sudo iptables -t nat -F PREROUTING && sudo iptables -t nat -F POSTROUTING

ADGUARD_IP="192.168.1.200"
LAN_IFACE="eno1"

echo "[dns-redirect] Applying DNS interception rules on interface $LAN_IFACE..."

# --- UDP port 53 redirect ---
iptables -t nat -C PREROUTING -i "$LAN_IFACE" -p udp --dport 53 ! -d "$ADGUARD_IP" -j DNAT --to-destination "$ADGUARD_IP":53 2>/dev/null || \
iptables -t nat -A PREROUTING -i "$LAN_IFACE" -p udp --dport 53 ! -d "$ADGUARD_IP" -j DNAT --to-destination "$ADGUARD_IP":53

# --- TCP port 53 redirect ---
iptables -t nat -C PREROUTING -i "$LAN_IFACE" -p tcp --dport 53 ! -d "$ADGUARD_IP" -j DNAT --to-destination "$ADGUARD_IP":53 2>/dev/null || \
iptables -t nat -A PREROUTING -i "$LAN_IFACE" -p tcp --dport 53 ! -d "$ADGUARD_IP" -j DNAT --to-destination "$ADGUARD_IP":53

# --- Masquerade so return traffic routes correctly ---
iptables -t nat -C POSTROUTING -p udp --dport 53 -j MASQUERADE 2>/dev/null || \
iptables -t nat -A POSTROUTING -p udp --dport 53 -j MASQUERADE

iptables -t nat -C POSTROUTING -p tcp --dport 53 -j MASQUERADE 2>/dev/null || \
iptables -t nat -A POSTROUTING -p tcp --dport 53 -j MASQUERADE

echo "[dns-redirect] DNS redirect active — all port 53 traffic on $LAN_IFACE redirected to AdGuard ($ADGUARD_IP)"
echo "[dns-redirect] Verify with: sudo iptables -t nat -L PREROUTING -n | grep 53"
