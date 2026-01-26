# A.R.C.H.I.E. VPN Integration Plan

## Secure Remote Node Connectivity via vpn.kytranempowerment.com

**Version**: 1.0.0
**Last Updated**: 2026-01-22
**Status**: Planning

---

## 1. Overview

Enable remote nodes (outside the local network) to securely connect to A.R.C.H.I.E. and contribute AI processing power.

### Goals

1. **Secure Connectivity**: Encrypted tunnel for all node traffic
2. **Seamless Integration**: Remote nodes work identically to local nodes
3. **Auto-Configuration**: One-command VPN setup for new nodes
4. **Resilient**: Auto-reconnect, failover, health monitoring

### Domain Structure

```
kytranempowerment.com
├── vpn.kytranempowerment.com     → VPN Server (WireGuard)
├── archie.kytranempowerment.com  → A.R.C.H.I.E. Platform
├── api.kytranempowerment.com     → Public API (rate-limited)
└── pool.kytranempowerment.com    → Mining Pool (optional)
```

---

## 2. Architecture

### Network Topology

```
                        Internet
                            │
        ┌───────────────────┼───────────────────┐
        │                   │                   │
        ▼                   ▼                   ▼
  ┌──────────┐       ┌──────────┐       ┌──────────┐
  │ Remote   │       │  Router  │       │ Remote   │
  │ Node A   │       │ (Public) │       │ Node B   │
  │ Home PC  │       │          │       │ Cloud VM │
  └────┬─────┘       └────┬─────┘       └────┬─────┘
       │                  │                   │
       │    WireGuard     │                   │
       └──────────────────┼───────────────────┘
                          │
                    Port 51820
                          │
              ┌───────────┴───────────┐
              │  vpn.kytranempowerment │
              │    WireGuard Server    │
              │      10.0.0.1/24       │
              └───────────┬───────────┘
                          │
              ┌───────────┴───────────┐
              │   A.R.C.H.I.E. Server  │
              │    192.168.1.200       │
              │    10.0.0.1 (VPN)      │
              └───────────────────────┘
                          │
              ┌───────────┴───────────┐
              │    Local Network       │
              │    192.168.1.0/24      │
              │                        │
              │  ┌─────┐    ┌─────┐   │
              │  │.246 │    │.248 │   │
              │  │Node │    │Node │   │
              │  └─────┘    └─────┘   │
              └────────────────────────┘
```

### IP Allocation

| Range | Purpose |
|-------|---------|
| 10.0.0.1 | A.R.C.H.I.E. Central (VPN interface) |
| 10.0.0.2-10 | Reserved (infrastructure) |
| 10.0.0.11-50 | High-priority nodes |
| 10.0.0.51-200 | Standard nodes |
| 10.0.0.201-254 | Temporary/testing |

---

## 3. VPN Server Setup

### 3.1 Prerequisites

```bash
# On A.R.C.H.I.E. server (192.168.1.200)
# Requires: Public IP or port forwarding for UDP 51820

sudo apt update
sudo apt install -y wireguard wireguard-tools qrencode
```

### 3.2 Server Configuration

```bash
# Generate server keys
umask 077
wg genkey | tee /etc/wireguard/server_private.key | wg pubkey > /etc/wireguard/server_public.key

# Create server config
cat > /etc/wireguard/wg0.conf << 'EOF'
[Interface]
# Server identity
Address = 10.0.0.1/24
ListenPort = 51820
PrivateKey = <server-private-key>

# Enable IP forwarding
PostUp = sysctl -w net.ipv4.ip_forward=1
PostUp = iptables -A FORWARD -i wg0 -j ACCEPT
PostUp = iptables -A FORWARD -o wg0 -j ACCEPT
PostUp = iptables -t nat -A POSTROUTING -o eth0 -j MASQUERADE

PostDown = iptables -D FORWARD -i wg0 -j ACCEPT
PostDown = iptables -D FORWARD -o wg0 -j ACCEPT
PostDown = iptables -t nat -D POSTROUTING -o eth0 -j MASQUERADE

# DNS for VPN clients (optional, use internal DNS)
# DNS = 10.0.0.1

# Peer configurations will be appended below
EOF
```

### 3.3 Enable and Start

```bash
sudo systemctl enable wg-quick@wg0
sudo systemctl start wg-quick@wg0

# Verify
sudo wg show
```

### 3.4 Firewall Rules

```bash
# Allow WireGuard
sudo ufw allow 51820/udp

# Allow traffic from VPN subnet
sudo ufw allow from 10.0.0.0/24
```

---

## 4. Node Enrollment API

### 4.1 New Endpoints

Add to `/mnt/archie_brain/platform_v2/tools/bridge/routes.py`:

```python
@bridge_bp.route('/api/vpn/enroll', methods=['POST'])
def vpn_enroll_node():
    """
    Generate VPN configuration for a new node.

    Request:
        {
            "node_name": "my-gpu-node",
            "node_type": "standard",  # standard, priority, temporary
            "public_key": "base64-public-key"  # If node generated own keys
        }

    Response:
        {
            "success": true,
            "vpn_ip": "10.0.0.52",
            "config": "... WireGuard config ...",
            "qr_code": "base64-png"  # For mobile setup
        }
    """
    pass

@bridge_bp.route('/api/vpn/nodes', methods=['GET'])
def vpn_list_nodes():
    """List all VPN-connected nodes with status"""
    pass

@bridge_bp.route('/api/vpn/nodes/<node_id>/revoke', methods=['POST'])
def vpn_revoke_node(node_id):
    """Revoke VPN access for a node"""
    pass

@bridge_bp.route('/api/vpn/status', methods=['GET'])
def vpn_status():
    """Get VPN server status and connected peers"""
    pass
```

### 4.2 VPN Manager Service

Create `/mnt/archie_brain/platform_v2/tools/bridge/vpn_manager.py`:

```python
"""
VPN Manager - Handles WireGuard peer management
"""
import subprocess
import ipaddress
from typing import Optional, Dict, Any

class VPNManager:
    def __init__(self):
        self.interface = 'wg0'
        self.subnet = ipaddress.ip_network('10.0.0.0/24')
        self.server_ip = '10.0.0.1'
        self.endpoint = 'vpn.kytranempowerment.com:51820'
        self.server_public_key = self._get_server_public_key()

    def _get_server_public_key(self) -> str:
        """Read server public key"""
        with open('/etc/wireguard/server_public.key', 'r') as f:
            return f.read().strip()

    def allocate_ip(self, node_type: str = 'standard') -> str:
        """Allocate next available VPN IP"""
        # Query database for used IPs
        # Return next available based on node_type range
        pass

    def generate_peer_config(self, node_name: str, peer_public_key: str,
                            vpn_ip: str) -> str:
        """Generate WireGuard config for a peer"""
        return f"""[Interface]
PrivateKey = <client-private-key>
Address = {vpn_ip}/24
DNS = 10.0.0.1

[Peer]
PublicKey = {self.server_public_key}
Endpoint = {self.endpoint}
AllowedIPs = 10.0.0.0/24, 192.168.1.0/24
PersistentKeepalive = 25
"""

    def add_peer(self, peer_public_key: str, vpn_ip: str) -> bool:
        """Add peer to WireGuard server"""
        cmd = f"wg set {self.interface} peer {peer_public_key} allowed-ips {vpn_ip}/32"
        result = subprocess.run(cmd.split(), capture_output=True)
        return result.returncode == 0

    def remove_peer(self, peer_public_key: str) -> bool:
        """Remove peer from WireGuard server"""
        cmd = f"wg set {self.interface} peer {peer_public_key} remove"
        result = subprocess.run(cmd.split(), capture_output=True)
        return result.returncode == 0

    def get_peer_status(self) -> Dict[str, Any]:
        """Get status of all connected peers"""
        result = subprocess.run(['wg', 'show', self.interface, 'dump'],
                               capture_output=True, text=True)
        # Parse and return peer info
        pass
```

### 4.3 Database Schema

```sql
-- VPN peer tracking
CREATE TABLE vpn_peers (
    id SERIAL PRIMARY KEY,
    node_id VARCHAR(50) REFERENCES remote_nodes(node_id),
    vpn_ip INET NOT NULL UNIQUE,
    public_key VARCHAR(64) NOT NULL UNIQUE,
    node_type VARCHAR(20) DEFAULT 'standard',
    last_handshake TIMESTAMP,
    bytes_received BIGINT DEFAULT 0,
    bytes_sent BIGINT DEFAULT 0,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT NOW(),
    revoked_at TIMESTAMP
);

CREATE INDEX idx_vpn_peers_node ON vpn_peers(node_id);
CREATE INDEX idx_vpn_peers_active ON vpn_peers(is_active);

-- VPN allocation tracking
CREATE TABLE vpn_ip_allocations (
    ip INET PRIMARY KEY,
    allocated_to VARCHAR(50),
    allocated_at TIMESTAMP,
    released_at TIMESTAMP
);
```

---

## 5. Node Client VPN Support

### 5.1 Auto-Configuration

Update `/mnt/archie_brain/node_client/vpn_client.py`:

```python
"""
VPN Client - Handles WireGuard connection for remote nodes
"""
import os
import subprocess
import platform
from typing import Optional

class VPNClient:
    def __init__(self, config_path: str = None):
        self.system = platform.system().lower()
        self.config_path = config_path or self._default_config_path()
        self.interface = 'archie-vpn'

    def _default_config_path(self) -> str:
        if self.system == 'windows':
            return r'C:\ProgramData\WireGuard\archie.conf'
        else:
            return '/etc/wireguard/archie.conf'

    def enroll(self, central_url: str, node_name: str) -> bool:
        """Enroll with VPN server and configure locally"""
        import requests

        # Generate local keys
        private_key, public_key = self._generate_keys()

        # Request VPN config from central
        resp = requests.post(
            f"{central_url}/tools/bridge/api/vpn/enroll",
            json={
                "node_name": node_name,
                "public_key": public_key
            }
        )

        if resp.status_code == 200:
            data = resp.json()
            config = data['config'].replace('<client-private-key>', private_key)
            self._write_config(config)
            return True
        return False

    def _generate_keys(self) -> tuple:
        """Generate WireGuard keypair"""
        if self.system == 'windows':
            # Use wireguard.exe
            pass
        else:
            result = subprocess.run(
                'wg genkey | tee /dev/stderr | wg pubkey',
                shell=True, capture_output=True, text=True
            )
            lines = result.stderr.strip() + '\n' + result.stdout.strip()
            private, public = lines.strip().split('\n')
            return private, public

    def connect(self) -> bool:
        """Bring up VPN connection"""
        if self.system == 'windows':
            cmd = f'wireguard.exe /installtunnelservice "{self.config_path}"'
        else:
            cmd = f'wg-quick up {self.config_path}'

        result = subprocess.run(cmd, shell=True, capture_output=True)
        return result.returncode == 0

    def disconnect(self) -> bool:
        """Bring down VPN connection"""
        if self.system == 'windows':
            cmd = f'wireguard.exe /uninstalltunnelservice {self.interface}'
        else:
            cmd = f'wg-quick down {self.config_path}'

        result = subprocess.run(cmd, shell=True, capture_output=True)
        return result.returncode == 0

    def is_connected(self) -> bool:
        """Check if VPN is connected"""
        try:
            if self.system == 'windows':
                result = subprocess.run(['wireguard.exe', '/show', self.interface],
                                       capture_output=True)
            else:
                result = subprocess.run(['wg', 'show', self.interface],
                                       capture_output=True)
            return result.returncode == 0
        except:
            return False
```

### 5.2 Installation Integration

Add to `install.sh` / `install.ps1`:

```bash
# Linux VPN setup
setup_vpn() {
    echo "Setting up VPN connection..."

    # Install WireGuard
    sudo apt install -y wireguard-tools

    # Enroll with central
    python3 -c "
from vpn_client import VPNClient
client = VPNClient()
if client.enroll('$CENTRAL_URL', '$NODE_NAME'):
    client.connect()
    print('VPN connected successfully')
else:
    print('VPN enrollment failed')
"
}

# Ask user if remote
read -p "Is this node on a different network than A.R.C.H.I.E.? (y/n) " remote
if [[ "$remote" == "y" ]]; then
    setup_vpn
fi
```

---

## 6. Migration Plan

### Phase 1: VPN Server Setup (on .109 after migration)

1. Install WireGuard on .109
2. Configure server with domain vpn.kytranempowerment.com
3. Set up DNS records
4. Configure firewall/port forwarding

### Phase 2: Bridge VPN Integration

1. Create vpn_manager.py
2. Add VPN enrollment API endpoints
3. Add database tables
4. Update Bridge UI with VPN tab

### Phase 3: Node Client Update

1. Add vpn_client.py to node_client
2. Update installer scripts
3. Add VPN health checks to heartbeat
4. Test with remote node

### Phase 4: Documentation & Testing

1. Update documentation
2. Test various network scenarios
3. Create troubleshooting guide
4. Security audit

---

## 7. Security Considerations

### Key Management

- Server private key: 600 permissions, root only
- Peer public keys stored in database
- Keys rotatable via API

### Network Isolation

- VPN traffic only to A.R.C.H.I.E. services
- No inter-node direct traffic (hub-and-spoke)
- Rate limiting on VPN enrollment

### Audit Logging

```sql
CREATE TABLE vpn_audit_log (
    id SERIAL PRIMARY KEY,
    event_type VARCHAR(50),  -- enroll, connect, disconnect, revoke
    node_id VARCHAR(50),
    vpn_ip INET,
    remote_ip INET,
    details JSONB,
    created_at TIMESTAMP DEFAULT NOW()
);
```

---

## 8. DNS Configuration

### Required Records

```
; A.R.C.H.I.E. Domain Configuration
; Add to kytranempowerment.com DNS

; VPN Server (WireGuard)
vpn     A       <public-ip>

; A.R.C.H.I.E. Platform (after migration)
archie  A       <public-ip>

; API endpoint
api     CNAME   archie.kytranempowerment.com.

; Mining Pool
pool    A       <public-ip>
```

### SSL Certificates

```bash
# Use Let's Encrypt for HTTPS
sudo certbot certonly --standalone -d archie.kytranempowerment.com
sudo certbot certonly --standalone -d api.kytranempowerment.com
```

---

## 9. Timeline

| Phase | Task | Duration |
|-------|------|----------|
| 1 | VPN Server Setup | 2-4 hours |
| 2 | Bridge VPN Integration | 4-6 hours |
| 3 | Node Client Update | 3-4 hours |
| 4 | Testing & Documentation | 2-3 hours |

**Total Estimate**: 11-17 hours

---

**Dependencies:**
- A.R.C.H.I.E. migration to .109 (Phase 73)
- Public IP or port forwarding
- DNS access for kytranempowerment.com
