# System Operations Module

**Version:** 1.0.0
**Phase:** 78
**Category:** ADMIN
**Route:** `/tools/system-operations`
**Permission:** `admin:system`

---

## Overview

The System Operations module provides comprehensive host machine administration capabilities for the A.R.C.H.I.E. server. It offers real-time monitoring, process management, service control, and storage administration through a unified dashboard.

---

## Features

### Dashboard Tab
- **CPU Usage** - Real-time CPU utilization with per-core breakdown
- **Memory Usage** - RAM and swap usage with progress indicators
- **GPU Status** - NVIDIA GPU monitoring (if available)
- **Disk Overview** - Storage utilization across all mounted volumes
- **System Info** - Hostname, uptime, kernel version, IP addresses
- **Quick Actions** - Process payouts, restart services, view logs

### Storage Tab
- **Mounted Partitions** - Device, mount point, filesystem type, size, usage
- **Unassigned Disks** - Detection with mount action buttons
- **RAID Status** - mdadm RAID array monitoring (if configured)

### Processes Tab
- **Running Processes** - Sortable by CPU%, MEM%, with kill capability
- **Systemd Services** - Status, enabled state, start/stop/restart actions
- **Docker Containers** - Image, status, ports, start/stop/restart actions

### Network Tab
- **Network Interfaces** - Name, IP address, MAC, status, speed
- **Traffic Statistics** - Bytes in/out over time
- **Active Connections** - Top connections by state

---

## API Endpoints

### Read-Only Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/overview` | All system stats combined |
| GET | `/api/cpu` | CPU details + per-core usage |
| GET | `/api/memory` | RAM + swap details |
| GET | `/api/disks` | Partitions, RAID, unassigned disks |
| GET | `/api/processes` | Running processes (sortable) |
| GET | `/api/services` | Systemd services list |
| GET | `/api/docker` | Docker containers |
| GET | `/api/network` | NICs, traffic, connections |
| GET | `/api/history` | Historical metrics for graphs |

### Action Endpoints (Audit Logged)

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/process/<pid>/kill` | Kill process by PID |
| POST | `/api/service/<name>/action` | Start/stop/restart systemd service |
| POST | `/api/docker/<id>/action` | Container start/stop/restart |
| POST | `/api/disk/<device>/mount` | Mount disk |
| POST | `/api/disk/<device>/unmount` | Unmount disk |
| GET | `/api/audit-log` | View operation audit trail |

---

## Security

### Access Control
- **Permission Required:** `admin:system`
- **Minimum Role:** ADMIN
- All actions require authentication

### Audit Logging
Every action is logged to `system_operations_audit` table:
- User ID
- Action type (process_kill, service_restart, disk_mount, etc.)
- Target (PID, service name, device)
- Success/failure status
- Error message (if any)
- IP address
- Timestamp

### Protected Resources
- Cannot kill init (PID 1) or kernel processes
- Warning before stopping critical services (docker, nginx, postgresql)
- Confirmation required for all destructive actions

---

## Database Schema

### Tables

```sql
-- System metrics history (7-day retention)
CREATE TABLE system_metrics_history (
    id SERIAL PRIMARY KEY,
    metric_type VARCHAR(50),  -- cpu, memory, disk, network, gpu
    value DECIMAL(10,2),
    details JSONB,
    recorded_at TIMESTAMP DEFAULT NOW()
);

-- Operation audit log
CREATE TABLE system_operations_audit (
    id SERIAL PRIMARY KEY,
    user_id INTEGER REFERENCES users(id),
    action_type VARCHAR(100),
    target VARCHAR(255),
    details JSONB,
    success BOOLEAN,
    error_message TEXT,
    ip_address VARCHAR(50),
    created_at TIMESTAMP DEFAULT NOW()
);

-- Alert thresholds configuration
CREATE TABLE system_alerts_config (
    id SERIAL PRIMARY KEY,
    metric_type VARCHAR(50),
    threshold_warning DECIMAL(10,2),
    threshold_critical DECIMAL(10,2),
    enabled BOOLEAN DEFAULT TRUE
);
```

---

## File Structure

```
/mnt/archie_brain/platform_v2/tools/system_operations/
    __init__.py              # Blueprint definition
    routes.py                # Flask routes and API endpoints
    system_service.py        # Business logic and system calls

/mnt/archie_brain/platform_v2/templates/tools/
    system_operations.html   # Main UI template

/mnt/archie_brain/database/migrations/
    071_system_operations.sql  # Database schema
```

---

## Dependencies

- **psutil** - Cross-platform system monitoring
- **subprocess** - For systemctl, docker commands
- **Chart.js** - Real-time graphs (CDN)

---

## UI Features

### Theme
- A.R.C.H.I.E. dark theme with red accents
- Consistent with platform design language

### Auto-Refresh
- Toggle auto-refresh (5-second interval)
- Live indicator when active

### Charts
- CPU usage history (1h, 24h, 7d)
- Memory usage history
- Network traffic graphs

### Modals
- Confirmation dialogs for dangerous actions
- Process details modal
- Service details modal

---

## Usage Examples

### Get System Overview
```bash
curl -X GET http://localhost:3000/tools/system-operations/api/overview \
  -H "Cookie: session=<your_session>"
```

### Kill a Process
```bash
curl -X POST http://localhost:3000/tools/system-operations/api/process/12345/kill \
  -H "Content-Type: application/json" \
  -H "Cookie: session=<your_session>" \
  -d '{"confirm": true}'
```

### Restart Docker Container
```bash
curl -X POST http://localhost:3000/tools/system-operations/api/docker/archie_platform/action \
  -H "Content-Type: application/json" \
  -H "Cookie: session=<your_session>" \
  -d '{"action": "restart", "confirm": true}'
```

---

## Troubleshooting

### Module Not Loading
1. Check permission exists in `rbac.py`: `ADMIN_SYSTEM = "admin:system"`
2. Verify module is enabled in `module_registry.py`
3. Check for import errors: `docker logs archie_platform | grep system_operations`

### API Returns 403
- User must have ADMIN role
- User must have `admin:system` permission

### Cannot Kill Process
- Protected processes (init, kernel) cannot be killed
- Requires `confirm: true` in request body

### Docker Actions Not Working
- Ensure Docker socket is mounted in container
- Check Docker service is running on host

### Systemd Services Not Showing
- **Expected behavior** when running in Docker container
- systemctl commands require host access not available in containers
- Use Docker Containers section for container management instead

### LVM Information Not Showing
- LVM commands (pvs, vgs, lvs) require **root privileges** on the host machine
- The host monitor must run as root to collect LVM data
- Install the systemd service with root access:
  ```bash
  # Copy service file
  sudo cp /mnt/archie_brain/scripts/archie-host-monitor.service /etc/systemd/system/

  # Enable and start
  sudo systemctl daemon-reload
  sudo systemctl enable --now archie-host-monitor

  # Check status
  sudo systemctl status archie-host-monitor
  ```
- Once running, LVM data will appear in the Storage tab within 30 seconds

### Host IP Showing Docker Gateway
- Set `HOST_IP` environment variable in docker-compose.yml
- Add `extra_hosts: ["host.docker.internal:host-gateway"]` for discovery
- Current config uses HOST_IP: "192.168.1.200"

---

## Related Modules

- **Bridge** - Node network management
- **Backup Manager** - System backups
- **Consciousness** - Platform monitoring

---

## Changelog

### v1.2.0 (Phase 78.2) - Host Monitor Integration
- Host System Monitor agent (`scripts/host_monitor.py`)
  - Runs on host machine to collect LVM, RAID, systemd services
  - Writes to `host_monitor_data.json` mounted into container
  - Systemd service available: `archie-host-monitor.service`
- History Charts:
  - Load historical CPU/Memory data from database on page load
  - Charts now show stored history, not just live session data
- Services Tab:
  - Shows host systemd services (from host monitor) with HOST badge
  - Shows Docker containers from container
  - Combined view of host and container services
- Setup Instructions:
  ```bash
  # Install host monitor service
  sudo cp /mnt/archie_brain/scripts/archie-host-monitor.service /etc/systemd/system/
  sudo systemctl daemon-reload
  sudo systemctl enable --now archie-host-monitor
  ```

### v1.1.0 (Phase 78.1)
- Enhanced Storage Tab:
  - Parent disk device mapping for each mount point
  - LVM configuration display (VGs, LVs, PVs)
  - Extend LVM volume capability with filesystem resize
  - Actions column for LVM volumes
- Enhanced Network Tab:
  - Host network summary card (hostname, host IP, container IP, gateway, DNS)
  - Detected host interfaces section
  - Container network interfaces with netmask and MTU
  - Improved connection display with process names
- Docker Limitation Notes:
  - Info notice for systemd services unavailability
  - Docker mode badge indicator
- Environment Configuration:
  - HOST_IP environment variable support
  - host.docker.internal resolution via extra_hosts

### v1.0.0 (Phase 78)
- Initial release
- Dashboard with CPU, RAM, disk, GPU monitoring
- Process management with kill capability
- Systemd service control
- Docker container management
- Network interface monitoring
- Full audit logging

---

**Last Updated:** 2026-01-22
**Author:** A.R.C.H.I.E. Platform Team
