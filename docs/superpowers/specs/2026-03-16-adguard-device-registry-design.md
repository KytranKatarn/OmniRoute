# AdGuard Device Registry — Design Spec

**Date**: 2026-03-16
**Project**: #142 Security & Network Overhaul
**Status**: Approved (Rev 2 — post-review fixes)

## Overview

A centralized device registry in ARCHIE that serves as the single source of truth for every device on the network. ARCHIE owns the registry (names, owners, categories, security zones) and pushes client configurations to AdGuard for DNS filtering enforcement. Agents reference devices by friendly name, not raw IPs.

## Data Model

### Table: `network_devices`

| Column | Type | Description |
|--------|------|-------------|
| id | SERIAL PK | Primary key |
| mac_address | VARCHAR(17) NULL | Stable device identifier (nullable — iOS/Android randomize MACs) |
| ip_address | INET NOT NULL | Current IP (updates on discovery, used as AdGuard client ID) |
| hostname | VARCHAR(255) | From DHCP/mDNS if available |
| friendly_name | VARCHAR(255) | User-assigned ("Kytran's iPhone") |
| device_type | VARCHAR(50) | phone/laptop/desktop/tablet/server/camera/smart_tv/iot/gaming/other |
| owner | VARCHAR(100) | Who it belongs to ("Kytran", "Guest", "Infrastructure") |
| security_zone | VARCHAR(20) DEFAULT 'quarantined' | trusted/family/guest/iot/quarantined |
| manufacturer | VARCHAR(100) | Auto-detected from MAC OUI prefix |
| status | VARCHAR(20) DEFAULT 'active' | active/inactive/decommissioned/banned |
| adguard_client_id | VARCHAR(100) | IP-based identifier used in AdGuard (not MAC) |
| is_registered | BOOLEAN DEFAULT FALSE | False = unregistered/new, true = user has named it |
| first_seen_at | TIMESTAMP DEFAULT NOW() | When device first appeared |
| last_seen_at | TIMESTAMP DEFAULT NOW() | Last activity timestamp |
| notes | TEXT | Free text notes |
| metadata | JSONB DEFAULT '{}' | Extra info (OS fingerprint, DHCP hostname, etc.) |
| created_at | TIMESTAMP DEFAULT NOW() | Record creation |
| updated_at | TIMESTAMP DEFAULT NOW() | Last update |

**Indexes**: ip_address (unique), mac_address (unique where not null), security_zone, is_registered, last_seen_at

**Unique constraint**: `UNIQUE NULLS NOT DISTINCT (mac_address)` for non-null MACs, plus `UNIQUE (ip_address)`

**Key behaviors**:
- IP address is the primary identifier for AdGuard sync (AdGuard does not support MAC-based client IDs)
- MAC address is preferred stable identifier when available, but nullable for devices with randomized MACs
- New devices start as `is_registered=false`, `security_zone='quarantined'`, `status='active'`
- Registration pushes client config to AdGuard using IP as client identifier
- When IP changes (DHCP), discovery updates both `network_devices` and re-syncs AdGuard client
- Discovery uses `INSERT ... ON CONFLICT DO UPDATE ... WHERE NOT is_registered` to prevent overwriting user data

**Database pattern**: Use `from database import get_db_cursor` with `with get_db_cursor(commit=True) as (conn, cur):` per project conventions.

**Migration file**: `database/migrations/172_network_devices.sql`

## Security Zones

### AdGuard API Limitations

AdGuard Home does NOT support per-client blocklists. All clients share the same filter lists. Per-client controls available via API:
- `filtering_enabled` (bool) — toggle filtering on/off
- `safesearch` (object) — per-service safe search
- `safebrowsing_enabled` (bool) — malware/phishing protection
- `parental_enabled` (bool) — parental controls
- `blocked_services` (list) — block specific services (facebook, tiktok, etc.)
- `use_global_settings` (bool) — override with client-specific settings

For IoT allowlist-only mode, use AdGuard client-specific user rules: `@@||allowed.domain^$client=192.168.1.x`

### Zone → AdGuard Policy Mapping

| Zone | filtering | safe_search | safebrowsing | parental | blocked_services | notes |
|------|-----------|-------------|-------------|----------|-----------------|-------|
| **trusted** | ON | OFF | ON | OFF | none | Full access with malware protection |
| **family** | ON | ON | ON | ON | configurable | Standard protection + safe search |
| **guest** | ON | ON | ON | ON | social media list | Strict filtering |
| **iot** | ON | OFF | ON | OFF | all | Plus client-specific allowlist rules |
| **quarantined** | ON | ON | ON | ON | all | Plus basic allowlist (activation servers) |

### Quarantine Lite

Quarantined devices get a basic allowlist to prevent completely bricking new phones:
- Apple activation: `albert.apple.com`, `captive.apple.com`, `gs.apple.com`
- Google activation: `connectivitycheck.gstatic.com`, `clients3.google.com`
- Captive portal detection URLs

These are injected as client-specific `@@` rules in AdGuard when a device enters quarantine.

## Auto-Discovery & Sync Flow

### Discovery (agent loop, every 5 minutes)

1. Acquire discovery lock (skip if previous run still active)
2. Poll AdGuard `/control/clients` for auto-discovered clients (skip if AdGuard health check fails, keep ARP scan)
3. ARP scan (`ip neigh show`) for devices not making DNS queries
4. Cross-reference against `network_devices` table by IP first, then MAC
5. New device → `INSERT ... ON CONFLICT (ip_address) DO UPDATE SET last_seen_at=NOW(), mac_address=EXCLUDED.mac_address WHERE NOT network_devices.is_registered`
6. Truly new (no conflict) → insert as unregistered + quarantined + Telegram alert
7. Known device → update `last_seen_at` and `ip_address` if changed

### Registration (user action via UI)

1. User clicks unregistered device → LCARS tablet modal opens
2. Sets friendly_name, device_type, owner, security_zone
3. MAC vendor lookup auto-fills manufacturer (if MAC available)
4. Save → update `network_devices` (is_registered=true) + push to AdGuard `/control/clients/add`
5. AdGuard client gets: name=friendly_name, ids=[ip_address], per-zone settings
6. If zone=iot or quarantined, inject client-specific allowlist rules

### Zone Change (user action)

1. User changes device's security_zone
2. ARCHIE updates `network_devices` table
3. ARCHIE updates AdGuard client config via `/control/clients/update`
4. New zone's filtering/safesearch/parental settings applied immediately
5. If zone changed to/from iot/quarantined, update client-specific user rules

### IP Change (automatic)

1. Discovery detects known MAC at new IP
2. Update `ip_address` in `network_devices`
3. Delete old AdGuard client (old IP), create new one (new IP) with same settings
4. Log IP change in `security_dns_changes` table

## UI: Clients Subtab (in AdGuard DNS tab)

### Layout

**Quick stats bar** (top):
- Total devices | Online now | Unregistered | Per-zone counts

**Unregistered Devices** (amber alert section, only visible when count > 0):
- Banner: "X unregistered devices detected"
- List: IP, MAC, manufacturer, first seen, last seen
- Click row → registration modal

**Registered Devices** (main table):
- Columns: Name, IP, Type, Owner, Zone, Last Seen, Status
- Filter bar: by zone, by type, by owner, by online/offline
- Click row → edit modal (same bm- LCARS tablet modal)
- Zone badge colors: trusted=green, family=blue, guest=amber, iot=purple, quarantined=red
- Online = last_seen_at within 15 minutes

### Registration/Edit Modal (bm- LCARS tablet)

- Friendly name (text input)
- Device type (dropdown: phone/laptop/desktop/tablet/server/camera/smart_tv/iot/gaming/other)
- Owner (dropdown, populated from existing owners + free text)
- Security zone (dropdown with color indicators)
- MAC address (read-only, may show "Unknown" if null)
- IP address (read-only)
- Manufacturer (auto-detected from MAC, read-only)
- Status (dropdown: active/inactive/decommissioned/banned)
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

- New unregistered device: "New device detected: [manufacturer] at [IP] (MAC: [mac])"
- Device quarantined: "Device [name] moved to quarantine — [reason]"
- Zone violations: "IoT device [name] attempting to reach [blocked domain]"

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | /api/devices | List all (filterable: zone, type, owner, online, status) |
| GET | /api/devices/\<id\> | Single device details |
| GET | /api/devices/unregistered | Unregistered devices only |
| GET | /api/devices/stats | Counts by zone, type, online/offline |
| POST | /api/devices/register | Register a device (name, type, owner, zone) |
| PUT | /api/devices/\<id\> | Update device details |
| DELETE | /api/devices/\<id\> | Remove device from registry + AdGuard |
| POST | /api/devices/sync | Force full sync to AdGuard |

## New/Modified Files

### New files
- `platform_v2/tools/security_network/device_registry_service.py` — core service
- `database/migrations/172_network_devices.sql` — table + indexes

### Modified files
- `platform_v2/tools/security_network/routes.py` — add 8 device endpoints
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

- `discover_devices()` — poll AdGuard auto_clients + ARP table, find new devices. Uses discovery lock to prevent overlapping runs. Skips AdGuard poll (keeps ARP) if AdGuard is down.
- `register_device(id, name, type, owner, zone)` — update DB (is_registered=true) + push to AdGuard
- `update_device(id, **kwargs)` — update DB + sync to AdGuard. Re-syncs AdGuard client if IP changed.
- `delete_device(id)` — remove from DB + delete AdGuard client
- `get_device(id)` — single device with full details
- `get_devices(zone=, type=, owner=, online=, status=)` — filtered queries
- `get_unregistered()` — devices where is_registered=false
- `get_stats()` — counts by zone, type, online/offline
- `sync_to_adguard()` — full sync of all registered devices. Deletes stale AdGuard clients, creates missing ones.
- `_sync_device_to_adguard(device)` — push single device's zone policy to AdGuard
- `_build_adguard_client(device)` — map zone → AdGuard client settings
- `_inject_allowlist_rules(device)` — add client-specific `@@` rules for iot/quarantined zones
- `mac_vendor_lookup(mac)` — resolve manufacturer from MAC OUI prefix (local lookup or API fallback)
- `_is_online(last_seen_at)` — true if within 15 minutes
