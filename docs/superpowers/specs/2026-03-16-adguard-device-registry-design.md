# AdGuard Device Registry — Design Spec

**Date**: 2026-03-16
**Project**: #142 Security & Network Overhaul
**Status**: Approved

## Overview

A centralized device registry in ARCHIE that serves as the single source of truth for every device on the network. ARCHIE owns the registry (names, owners, categories, security zones) and pushes client configurations to AdGuard for DNS filtering enforcement. Agents reference devices by friendly name, not raw IPs.

## Data Model

### Table: `network_devices`

| Column | Type | Description |
|--------|------|-------------|
| id | SERIAL PK | Primary key |
| mac_address | VARCHAR(17) UNIQUE | Stable device identifier (XX:XX:XX:XX:XX:XX) |
| ip_address | INET | Current IP (updates on discovery) |
| hostname | VARCHAR(255) | From DHCP/mDNS if available |
| friendly_name | VARCHAR(255) | User-assigned ("Kytran's iPhone") |
| device_type | VARCHAR(50) | phone/laptop/desktop/tablet/server/camera/smart_tv/iot/gaming/other |
| owner | VARCHAR(100) | Who it belongs to ("Kytran", "Guest", "Infrastructure") |
| security_zone | VARCHAR(20) | trusted/family/guest/iot/quarantined |
| adguard_client_id | VARCHAR(100) | AdGuard configured client name (null if not synced) |
| is_registered | BOOLEAN DEFAULT FALSE | False = unregistered/new, true = user has named it |
| first_seen_at | TIMESTAMP DEFAULT NOW() | When device first appeared |
| last_seen_at | TIMESTAMP DEFAULT NOW() | Last activity timestamp |
| notes | TEXT | Free text notes |
| metadata | JSONB DEFAULT '{}' | Extra info (manufacturer, OS fingerprint, etc.) |
| created_at | TIMESTAMP DEFAULT NOW() | Record creation |
| updated_at | TIMESTAMP DEFAULT NOW() | Last update |

**Indexes**: mac_address (unique), security_zone, is_registered, last_seen_at

**Key behaviors**:
- MAC address is the stable identifier (IPs change via DHCP)
- New devices start as `is_registered=false`, `security_zone='quarantined'`
- Registration pushes client config to AdGuard
- Each zone maps to an AdGuard filtering profile

## Security Zones

| Zone | Who | AdGuard Policy |
|------|-----|---------------|
| **trusted** | Owner's personal devices | Minimal blocklist, no safe search |
| **family** | Household members' devices | Standard blocklist + safe search enabled |
| **guest** | Visitors' devices | Strict blocklist + safe search + time limits |
| **iot** | Cameras, smart home, smart TVs | Allowlist-only (block everything except known domains) |
| **quarantined** | Unknown/new devices | Block all DNS, Telegram alert |

## Auto-Discovery & Sync Flow

### Discovery (agent loop, every 5 minutes)

1. Poll AdGuard `/control/clients` for auto-discovered clients
2. ARP scan (`ip neigh show`) for devices not making DNS queries
3. Cross-reference against `network_devices` table by MAC address
4. New MAC → insert as unregistered + quarantined + Telegram alert
5. Known MAC → update `last_seen_at` and `ip_address` if changed

### Registration (user action via UI)

1. User clicks unregistered device → LCARS tablet modal opens
2. Sets friendly_name, device_type, owner, security_zone
3. MAC vendor lookup auto-fills manufacturer in metadata
4. Save → insert/update `network_devices` + push to AdGuard `/control/clients/add`
5. AdGuard client gets: name, IDs (IP), tags (device_type, zone), filtering profile

### Zone Change (user action)

1. User changes device's security_zone
2. ARCHIE updates `network_devices` table
3. ARCHIE updates AdGuard client config via `/control/clients/update`
4. New zone's filtering profile takes effect immediately

## UI: Clients Subtab (in AdGuard DNS tab)

### Layout

**Quick stats bar** (top):
- Total devices | Online now | Unregistered | Per-zone counts

**Unregistered Devices** (amber alert section, only visible when count > 0):
- Banner: "X unregistered devices detected"
- List: IP, MAC, manufacturer, first seen, last seen, query count
- Click row → registration modal

**Registered Devices** (main table):
- Columns: Name, IP, Type, Owner, Zone, Last Seen, Status
- Filter bar: zone, type, owner, online/offline
- Click row → edit modal (same bm- LCARS tablet modal)
- Zone badge colors: trusted=green, family=blue, guest=amber, iot=purple, quarantined=red
- Online = last_seen_at within 15 minutes

### Registration/Edit Modal (bm- LCARS tablet)

- Friendly name (text input)
- Device type (dropdown: phone/laptop/desktop/tablet/server/camera/smart_tv/iot/gaming/other)
- Owner (dropdown, populated from existing owners + free text)
- Security zone (dropdown with color indicators)
- MAC address (read-only)
- IP address (read-only)
- Manufacturer (auto-detected from MAC, read-only)
- Notes (textarea)
- Actions: Save, Delete (with confirm), Cancel

## Agent Integration

### SECURITY station agent (Sentry)

- References devices by friendly_name in reports and alerts
- Flags anomalies per device ("Camera.Driveway querying unexpected Chinese domains")
- Can auto-quarantine devices exceeding threat thresholds
- Includes device context in Telegram alerts

### Bridge dispatcher

- Security jobs include device context (name, type, zone, owner)
- Scan results reference device names, not raw IPs

### Telegram alerts

- New unregistered device: "New device detected: [MAC] [manufacturer] at [IP]"
- Device quarantined: "Device [name] moved to quarantine — [reason]"
- Zone violations: "IoT device [name] attempting to reach [blocked domain]"

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | /api/devices | List all (filterable: zone, type, owner, online) |
| GET | /api/devices/unregistered | Unregistered devices only |
| GET | /api/devices/stats | Counts by zone, type, online/offline |
| POST | /api/devices/register | Register a device (name, type, owner, zone) |
| PUT | /api/devices/\<id\> | Update device details |
| DELETE | /api/devices/\<id\> | Remove device from registry |
| POST | /api/devices/sync | Force full sync to AdGuard |

## New/Modified Files

### New files
- `platform_v2/tools/security_network/device_registry_service.py` — core service
- `database/migrations/XXX_network_devices.sql` — table + indexes

### Modified files
- `platform_v2/tools/security_network/routes.py` — add 7 device endpoints
- `platform_v2/templates/tools/security_network.html` — add Clients subtab to AdGuard DNS
- `ai_bridge/agent_loop.py` — add `_discover_network_devices()` job (every 5 min)
- `platform_v2/tools/security_network/security_alerts.py` — add `new_device` alert type

## Out of Scope

- Router DHCP configuration (manual step by user)
- VLAN/network segmentation (hardware/router level)
- Captive portal for guests (future feature)
- Per-device bandwidth monitoring (System Ops concern)
- IoT allowlist curation (future — requires research per device type)

## Service: `device_registry_service.py`

### Methods

- `discover_devices()` — poll AdGuard auto_clients + ARP table, find new MACs
- `register_device(mac, name, type, owner, zone)` — save to DB + push to AdGuard
- `update_device(id, **kwargs)` — update DB + sync to AdGuard
- `delete_device(id)` — remove from DB + AdGuard
- `get_devices(zone=, type=, owner=, online=)` — filtered queries
- `get_unregistered()` — devices where is_registered=false
- `get_stats()` — counts by zone, type, online/offline
- `sync_to_adguard()` — full sync of all registered devices
- `mac_vendor_lookup(mac)` — resolve manufacturer from MAC OUI prefix
- `_is_online(last_seen_at)` — true if within 15 minutes
