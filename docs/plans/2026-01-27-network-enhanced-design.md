# Network Tab: Port-to-Stack Mapping, Topology & Bandwidth

**Date**: 2026-01-27
**Module**: System Operations → Network Tab
**Status**: Design Complete — Awaiting Implementation
**Dependencies**: Docker Tab (for stack definitions and port mappings)

---

## Overview

Enhance the Network tab to show port-to-stack correlation, clickable web UI links, a visual topology map, connection grouping by stack, and per-port/per-stack bandwidth monitoring. This transforms the tab from a raw data view into an operational network dashboard.

## Feature 1: Port-to-Stack Mapping

### How It Works
1. Query `docker_stacks` table for all registered stacks
2. For each stack, parse `docker-compose.yml` to extract port mappings
3. Cross-reference with host listening ports from `ss -tlnp`
4. Group ports by stack with color-coded headers (using stack's assigned color)

### UI Display
```
┌─────────────────────────────────────────────┐
│ A.R.C.H.I.E. Stack          ■ #00D4AA      │
├──────┬──────────┬─────────┬────────┬────────┤
│ Port │ Service  │ Status  │ In     │ Out    │
├──────┼──────────┼─────────┼────────┼────────┤
│ 3000 │ Platform │ ● OPEN  │ 12KB/s │ 45KB/s │ 🔗
│ 5432 │ Postgres │ ● OPEN  │ 2KB/s  │ 8KB/s  │
│ 6379 │ Redis    │ ● OPEN  │ 500B/s │ 1KB/s  │
└──────┴──────────┴─────────┴────────┴────────┘

┌─────────────────────────────────────────────┐
│ Plex Stack                   ■ #E5A00D      │
├──────┬──────────┬─────────┬────────┬────────┤
│ Port │ Service  │ Status  │ In     │ Out    │
├──────┼──────────┼─────────┼────────┼────────┤
│32400 │ Plex     │ ● OPEN  │ 38MB/s │ 2MB/s  │ 🔗
│32469 │ DLNA     │ ● OPEN  │ 0B/s   │ 0B/s   │
└──────┴──────────┴─────────┴────────┴────────┘

┌─────────────────────────────────────────────┐
│ Unassigned Ports             ■ grey         │
├──────┬──────────┬─────────┬────────┬────────┤
│ 22   │ sshd     │ ● OPEN  │ 1KB/s  │ 3KB/s  │
│ 53   │ systemd  │ ● OPEN  │ 200B/s │ 400B/s │
└──────┴──────────┴─────────┴────────┴────────┘
```

## Feature 2: Web UI Links

### Auto-Detection
Ports known to serve web UIs are auto-tagged:
- 3000 (A.R.C.H.I.E. Platform)
- 8080, 8443 (common web)
- 32400 (Plex)
- 8123 (Home Assistant)
- 9000 (Portainer)
- Custom ports from stack creation wizard

### Manual Tagging
During stack creation (Step 2: Compose File), the wizard identifies exposed ports and asks:
- "Does port 32400 serve a web UI?" → Yes/No
- If yes, record URL pattern: `http://{host}:{port}` or custom path

### UI Display
- Clickable link icon next to web UI ports in the port table
- Opens in new tab: `http://192.168.1.200:3000`, `http://192.168.1.200:32400/web`
- Tooltip shows the full URL on hover

### Storage
Web UI port tags stored in `docker_stacks` table as a JSON field `web_ui_ports`:
```json
[
  {"port": 3000, "label": "Platform", "path": "/"},
  {"port": 32400, "label": "Plex Web", "path": "/web"}
]
```

## Feature 3: Visual Topology Map

### Layout
Simple left-to-right flow diagram:

```
Internet ──→ Router ──→ Host (archie) ──→ Docker Bridge ──┬→ A.R.C.H.I.E. Stack
             192.168.1.1  192.168.1.200    172.17.0.1      │   :3000, :5432, :6379
                                                            │
                                                            ├→ Plex Stack
                                                            │   :32400, :32469
                                                            │
                                                            └→ Host Services
                                                                :22 (SSH)
```

### Features
- Each node shows live bandwidth (small number or sparkline)
- Stack nodes use their assigned colors
- Port numbers listed under each stack node
- Web UI ports are underlined/clickable
- Hover on a stack node highlights its connections
- Router IP and Host IP auto-populated from network data

### Implementation
- SVG-based rendering (D3.js or hand-rolled SVG)
- Responsive layout that adjusts to panel width
- Auto-updates with network data refresh

## Feature 4: Connection Grouping by Stack

### How It Works
1. Get active connections from `ss -tnp state established`
2. Map each connection's local port to a stack (via compose port mappings)
3. Group connections under stack headers

### UI Display
Same color-coded grouping as listening ports:
- "A.R.C.H.I.E. Stack — 12 active connections"
- "Plex Stack — 3 active connections"
- "Unassigned — 5 connections"

Each connection shows: Local address, Remote address, Process, PID, Duration (if available).

## Feature 5: Bandwidth Monitoring

### Three Layers of Traffic Data

#### Layer 1: Per-Interface Bandwidth
- **Source**: `/proc/net/dev` (cumulative rx/tx bytes per interface)
- **Collection**: Every 30 seconds in host_monitor.py
- **Calculation**: Delta between snapshots → bytes/sec rate
- **Display**: Interface table gains "RX Rate" and "TX Rate" columns

#### Layer 2: Per-Stack Bandwidth
- **Source**: Docker API `container.stats()` for each container
- **Collection**: Every 30 seconds, aggregate by stack
- **Calculation**: Sum of all container network I/O within a stack
- **Display**: Stack header shows total bandwidth, each container row shows its share

#### Layer 3: Per-Port Bandwidth
- **Source**: `ss -tinp` which reports `bytes_received:N bytes_sent:N` per socket
- **Collection**: Every 30 seconds, aggregate sockets by listening port
- **Calculation**: Delta between snapshots for rate
- **Display**: "In" and "Out" columns in port table (as shown in port-to-stack mockup)

### Historical Data
- Rolling buffer: Last 60 samples (30 minutes at 30-second intervals)
- Mini sparkline charts next to bandwidth numbers
- Click to expand: Shows 30-minute line chart for that port/stack/interface
- Data stored in host_monitor_data.json under `bandwidth_history` key

### Recommended Rollout
1. **Phase 1**: Per-interface and per-stack bandwidth (reliable, low overhead)
2. **Phase 2**: Per-port bandwidth via ss socket stats (more complex, can be noisy)

## Host Monitor Enhancements

### New Function: `get_bandwidth_stats()`
```python
def get_bandwidth_stats():
    """Collect bandwidth data at all three layers"""
    stats = {
        'interfaces': {},     # per-interface rx/tx bytes
        'containers': {},     # per-container network I/O
        'ports': {},          # per-port aggregated socket bytes
        'timestamp': time.time()
    }

    # Layer 1: /proc/net/dev
    # Layer 2: docker stats API
    # Layer 3: ss -tinp socket bytes

    return stats
```

### Rate Calculation
- Store previous snapshot in memory (or JSON)
- Rate = (current_bytes - previous_bytes) / time_delta
- Smooth with exponential moving average to reduce noise

### History Buffer
```json
{
  "bandwidth_history": [
    {
      "timestamp": 1706360400,
      "interfaces": {"eno1": {"rx_bps": 125000, "tx_bps": 45000}},
      "stacks": {"archie": {"rx_bps": 12000, "tx_bps": 45000}},
      "ports": {"3000": {"rx_bps": 12000, "tx_bps": 45000}}
    }
  ]
}
```

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/network` | Full network info (existing, enhanced) |
| GET | `/api/network/ports-by-stack` | Ports grouped by stack with bandwidth |
| GET | `/api/network/topology` | Topology data for visual map |
| GET | `/api/network/bandwidth` | Current bandwidth stats (all layers) |
| GET | `/api/network/bandwidth/history` | Historical bandwidth (last 30 min) |
| GET | `/api/network/connections-by-stack` | Connections grouped by stack |

## Implementation Notes

- Port-to-stack mapping requires Docker tab to be implemented first (needs `docker_stacks` table)
- Bandwidth collection adds ~2 seconds to host_monitor.py cycle (Docker API calls are the slowest part)
- SVG topology map can be built with vanilla JS + SVG, no heavy library needed
- Sparkline charts: lightweight inline SVG, no chart library needed
- Auto-detect web UI: maintain a lookup table of common port → service mappings
- Manual web UI tags are persisted in the `docker_stacks` table `web_ui_ports` JSON field
- Unassigned ports (host-level services like SSH, DNS) shown in a separate "Host Services" group
