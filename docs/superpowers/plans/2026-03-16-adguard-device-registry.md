# AdGuard Device Registry Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a network device registry in ARCHIE that auto-discovers devices, lets users name/categorize them, and syncs security zone policies to AdGuard for DNS filtering enforcement.

**Architecture:** New `network_devices` table as source of truth. `device_registry_service.py` handles discovery (AdGuard API + ARP), registration, and AdGuard sync. Agent loop polls every 5 min. Clients subtab in AdGuard DNS tab for UI. LCARS tablet modal for registration/edit.

**Tech Stack:** Python/Flask, PostgreSQL, AdGuard Home REST API, psutil (ARP), JavaScript (DOM-based UI)

**Spec:** `docs/superpowers/specs/2026-03-16-adguard-device-registry-design.md`

---

## File Structure

| File | Responsibility |
|------|---------------|
| `database/migrations/172_network_devices.sql` | Table creation, indexes, constraints |
| `platform_v2/tools/security_network/device_registry_service.py` | Core service: discover, register, sync, MAC lookup |
| `platform_v2/tools/security_network/routes.py` | 8 new API endpoints (append to existing) |
| `platform_v2/tools/security_network/security_alerts.py` | Add `new_device` to VALID_ALERT_TYPES |
| `platform_v2/templates/tools/security_network.html` | Clients subtab + registration modal |
| `ai_bridge/agent_loop.py` | `_discover_network_devices()` scheduled job |

---

## Chunk 1: Database + Service Layer

### Task 1: Create migration

**Files:**
- Create: `database/migrations/172_network_devices.sql`

- [ ] **Step 1: Write migration SQL**

```sql
-- 172_network_devices.sql
-- Network device registry for AdGuard integration

CREATE TABLE IF NOT EXISTS network_devices (
    id SERIAL PRIMARY KEY,
    mac_address VARCHAR(17),
    ip_address INET NOT NULL,
    hostname VARCHAR(255),
    friendly_name VARCHAR(255),
    device_type VARCHAR(50),
    owner VARCHAR(100),
    security_zone VARCHAR(20) DEFAULT 'quarantined'
        CHECK (security_zone IN ('trusted', 'family', 'guest', 'iot', 'quarantined')),
    manufacturer VARCHAR(100),
    status VARCHAR(20) DEFAULT 'active'
        CHECK (status IN ('active', 'inactive', 'decommissioned', 'banned')),
    adguard_client_id VARCHAR(100),
    is_registered BOOLEAN DEFAULT FALSE,
    first_seen_at TIMESTAMP DEFAULT NOW(),
    last_seen_at TIMESTAMP DEFAULT NOW(),
    notes TEXT,
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Unique constraints
CREATE UNIQUE INDEX IF NOT EXISTS idx_network_devices_ip ON network_devices (ip_address);
CREATE UNIQUE INDEX IF NOT EXISTS idx_network_devices_mac ON network_devices (mac_address) WHERE mac_address IS NOT NULL;

-- Query indexes
CREATE INDEX IF NOT EXISTS idx_network_devices_zone ON network_devices (security_zone);
CREATE INDEX IF NOT EXISTS idx_network_devices_registered ON network_devices (is_registered);
CREATE INDEX IF NOT EXISTS idx_network_devices_last_seen ON network_devices (last_seen_at);
CREATE INDEX IF NOT EXISTS idx_network_devices_status ON network_devices (status);
```

- [ ] **Step 2: Run migration**

```bash
docker cp database/migrations/172_network_devices.sql archie_database:/tmp/
docker exec archie_database psql -U archie -d archie -f /tmp/172_network_devices.sql
```

- [ ] **Step 3: Verify table exists**

```bash
docker exec archie_database psql -U archie -d archie -c "\d network_devices"
```

- [ ] **Step 4: Commit**

```bash
git add database/migrations/172_network_devices.sql
git commit -m "feat(security): add network_devices table (migration 172)"
```

---

### Task 2: Build device_registry_service.py — core methods

**Files:**
- Create: `platform_v2/tools/security_network/device_registry_service.py`

- [ ] **Step 1: Write the service with DB methods**

The service needs these methods (see spec for full details):
- `__init__()` — takes AdGuard service reference
- `get_device(id)` — single device by ID
- `get_devices(zone=, type=, owner=, online=, status=)` — filtered list
- `get_unregistered()` — is_registered=false
- `get_stats()` — counts by zone, type, online/offline
- `_is_online(last_seen_at)` — true if within 15 minutes

Key patterns:
- Use `from database import get_db_cursor` with `with get_db_cursor(commit=True) as (conn, cur):`
- Use `RealDictCursor` for all queries
- Online threshold: 15 minutes from `last_seen_at`
- Return dicts with serializable timestamps (`.isoformat()`)

- [ ] **Step 2: Test DB methods from Docker**

```bash
docker exec archie_platform python3 -c "
from tools.security_network.device_registry_service import DeviceRegistryService
svc = DeviceRegistryService()
print('Stats:', svc.get_stats())
print('Devices:', svc.get_devices())
print('Unregistered:', svc.get_unregistered())
"
```

- [ ] **Step 3: Commit**

```bash
git add platform_v2/tools/security_network/device_registry_service.py
git commit -m "feat(security): device registry service — DB query methods"
```

---

### Task 3: Add discovery methods to service

**Files:**
- Modify: `platform_v2/tools/security_network/device_registry_service.py`

- [ ] **Step 1: Add discovery methods**

Methods to add:
- `discover_devices()` — main discovery loop:
  1. Check discovery lock (class-level `_discovery_running` flag)
  2. Poll AdGuard `/control/clients` for `auto_clients` (skip if health check fails)
  3. Run `ip neigh show` via subprocess for ARP table
  4. For each discovered IP/MAC:
     - `INSERT INTO network_devices (ip_address, mac_address, hostname, manufacturer, first_seen_at, last_seen_at) VALUES (...) ON CONFLICT (ip_address) DO UPDATE SET last_seen_at=NOW(), mac_address=COALESCE(EXCLUDED.mac_address, network_devices.mac_address) WHERE NOT network_devices.is_registered`
  5. Return list of newly inserted devices (for alerting)
- `mac_vendor_lookup(mac)` — extract first 3 octets, lookup against known prefixes (hardcode top 20: Apple, Samsung, Google, Intel, etc.) or use `metadata` cache
- `_parse_arp_table()` — parse `ip neigh show` output into list of `{ip, mac, state}`

Key: filter out Docker bridge IPs (172.x.x.x), localhost, multicast (ff00::), link-local (fe80::)

- [ ] **Step 2: Test discovery from Docker**

```bash
docker exec archie_platform python3 -c "
from tools.security_network.device_registry_service import DeviceRegistryService
svc = DeviceRegistryService()
new_devices = svc.discover_devices()
print(f'Discovered: {len(new_devices)} new devices')
for d in new_devices:
    print(f'  {d[\"ip_address\"]} MAC={d.get(\"mac_address\",\"?\")} mfr={d.get(\"manufacturer\",\"?\")}')
print(f'Total in DB: {svc.get_stats()}')
"
```

- [ ] **Step 3: Commit**

```bash
git add platform_v2/tools/security_network/device_registry_service.py
git commit -m "feat(security): device discovery — AdGuard + ARP scan + MAC lookup"
```

---

### Task 4: Add registration + AdGuard sync methods

**Files:**
- Modify: `platform_v2/tools/security_network/device_registry_service.py`

- [ ] **Step 1: Add registration and sync methods**

Methods to add:
- `register_device(id, friendly_name, device_type, owner, security_zone, notes=None)`:
  1. Update `network_devices` SET is_registered=true, friendly_name, device_type, owner, security_zone, notes, updated_at
  2. Call `_sync_device_to_adguard(device)`
  3. Return updated device

- `update_device(id, **kwargs)`:
  1. Build dynamic UPDATE from kwargs
  2. If zone changed, re-sync AdGuard
  3. If IP changed, delete old AdGuard client + create new

- `delete_device(id)`:
  1. Get device's adguard_client_id
  2. DELETE from network_devices
  3. Delete from AdGuard `/control/clients/delete`

- `sync_to_adguard()`:
  1. Get all registered devices
  2. Get all AdGuard configured clients
  3. Delete stale AdGuard clients (not in our DB)
  4. Create/update missing ones

- `_sync_device_to_adguard(device)`:
  1. Build AdGuard client payload from `_build_adguard_client(device)`
  2. Try update first, if 404 then add
  3. Update `adguard_client_id` in DB

- `_build_adguard_client(device)`:
  Map zone to AdGuard settings:
  ```python
  ZONE_POLICIES = {
      "trusted": {"filtering_enabled": True, "safesearch": {"enabled": False}, "safebrowsing_enabled": True, "parental_enabled": False, "blocked_services": []},
      "family": {"filtering_enabled": True, "safesearch": {"enabled": True}, "safebrowsing_enabled": True, "parental_enabled": True, "blocked_services": []},
      "guest": {"filtering_enabled": True, "safesearch": {"enabled": True}, "safebrowsing_enabled": True, "parental_enabled": True, "blocked_services": ["facebook", "tiktok", "instagram", "snapchat"]},
      "iot": {"filtering_enabled": True, "safesearch": {"enabled": False}, "safebrowsing_enabled": True, "parental_enabled": False, "blocked_services": ["*"]},
      "quarantined": {"filtering_enabled": True, "safesearch": {"enabled": True}, "safebrowsing_enabled": True, "parental_enabled": True, "blocked_services": ["*"]},
  }
  ```
  Return: `{"name": friendly_name, "ids": [str(ip_address)], "use_global_settings": False, **policy}`

- [ ] **Step 2: Test registration from Docker**

```bash
docker exec archie_platform python3 -c "
from tools.security_network.device_registry_service import DeviceRegistryService
svc = DeviceRegistryService()
# Register a test device (use an actual device ID from discover)
devices = svc.get_unregistered()
if devices:
    d = devices[0]
    result = svc.register_device(d['id'], 'Test Device', 'other', 'Infrastructure', 'trusted')
    print(f'Registered: {result}')
else:
    print('No unregistered devices to test with')
"
```

- [ ] **Step 3: Commit**

```bash
git add platform_v2/tools/security_network/device_registry_service.py
git commit -m "feat(security): device registration + AdGuard zone sync"
```

---

## Chunk 2: API Routes + Agent Loop

### Task 5: Add API endpoints to routes.py

**Files:**
- Modify: `platform_v2/tools/security_network/routes.py` (append after domain management section)

- [ ] **Step 1: Add import and service initialization**

At top of routes.py, add to the existing service import block:
```python
try:
    from tools.security_network.device_registry_service import DeviceRegistryService
    device_registry = DeviceRegistryService()
    DEVICE_REGISTRY_AVAILABLE = True
except Exception:
    device_registry = None
    DEVICE_REGISTRY_AVAILABLE = False
```

- [ ] **Step 2: Add 8 route functions**

Append after the domain management routes section:

```python
# ============================================================================
# DEVICE REGISTRY
# ============================================================================

# GET /api/devices — list all (filterable)
# GET /api/devices/<id> — single device
# GET /api/devices/unregistered — unregistered only
# GET /api/devices/stats — counts
# POST /api/devices/register — register device
# PUT /api/devices/<id> — update device
# DELETE /api/devices/<id> — remove device + AdGuard client
# POST /api/devices/sync — force full AdGuard sync
```

Each route follows existing pattern: `@security_network_bp.route(...)`, `@login_required`, `@admin_required`, try/except with jsonify response.

Note: PUT route for `/api/devices/<int:device_id>` must be defined BEFORE the string path routes to avoid Flask routing conflicts.

- [ ] **Step 3: Test endpoints**

```bash
COOKIE=$(curl -s -c - -X POST http://192.168.1.200:3000/login -d "username=admin&password=Kyt\$13ran2025" -H "Content-Type: application/x-www-form-urlencoded" | grep session | awk '{print $NF}')
curl -s -b "session=$COOKIE" http://192.168.1.200:3000/tools/security-network/api/devices/stats | python3 -m json.tool
curl -s -b "session=$COOKIE" http://192.168.1.200:3000/tools/security-network/api/devices | python3 -m json.tool
```

- [ ] **Step 4: Commit**

```bash
git add platform_v2/tools/security_network/routes.py
git commit -m "feat(security): device registry API endpoints (8 routes)"
```

---

### Task 6: Add new_device alert type + agent loop discovery job

**Files:**
- Modify: `platform_v2/tools/security_network/security_alerts.py`
- Modify: `ai_bridge/agent_loop.py`

- [ ] **Step 1: Add new_device to security_alerts.py**

Add `"new_device"` to the `VALID_ALERT_TYPES` set.

- [ ] **Step 2: Add discovery job to agent_loop.py**

Add scheduler job in the `_register_jobs` method:
```python
self.scheduler.add_job(
    with_app_context(self._discover_network_devices),
    trigger=IntervalTrigger(minutes=5),
    id="agent_network_discovery",
    name="Agent Loop: Network Device Discovery",
    replace_existing=True,
)
```

Add the method:
```python
def _discover_network_devices(self):
    """Discover new network devices via AdGuard + ARP (every 5 min)."""
    try:
        from tools.security_network.device_registry_service import DeviceRegistryService
        from tools.security_network.security_alerts import create_security_alert

        svc = DeviceRegistryService()
        new_devices = svc.discover_devices()

        for device in new_devices:
            ip = device.get("ip_address", "?")
            mac = device.get("mac_address", "?")
            mfr = device.get("manufacturer", "Unknown")
            create_security_alert(
                "new_device",
                f"New device detected: {mfr}",
                f"IP: {ip} | MAC: {mac} | Manufacturer: {mfr}",
                priority="high",
                telegram=True,
            )

        if new_devices:
            logger.info(f"Network discovery: {len(new_devices)} new devices found")
    except Exception as e:
        logger.debug(f"Network discovery failed: {e}")
```

- [ ] **Step 3: Restart and verify job runs**

```bash
docker compose restart archie_platform
# Wait 10 seconds, then check logs
docker logs archie_platform 2>&1 | grep -i "network.*discovery\|new.*device" | tail -5
```

- [ ] **Step 4: Commit**

```bash
git add platform_v2/tools/security_network/security_alerts.py ai_bridge/agent_loop.py
git commit -m "feat(security): network device discovery agent loop job + new_device alerts"
```

---

## Chunk 3: UI — Clients Subtab + Registration Modal

### Task 7: Add Clients subtab to AdGuard DNS tab

**Files:**
- Modify: `platform_v2/templates/tools/security_network.html`

- [ ] **Step 1: Add Clients subtab button**

In the AdGuard DNS tab subtab nav (after dns-rules button), add:
```html
<button class="subtab-btn" data-subtab="dns-clients"><span data-i18n="security_network.clients">Clients</span></button>
```

- [ ] **Step 2: Add Clients subtab content panel**

After the `subtab-dns-rules` div, add the clients panel with:
- Stats bar (4 stat cards: total, online, unregistered, zones)
- Unregistered section (amber banner + table, hidden when count=0)
- Registered devices table with filter bar
- Tables use safe DOM construction (no innerHTML with user data)

- [ ] **Step 3: Add subtab trigger in initSubtabs**

In the `initSubtabs()` function, add:
```javascript
if (st === 'dns-clients') loadDeviceClients();
```

- [ ] **Step 4: Add JavaScript functions**

Add after the domain management JS section:
```javascript
/* ========== Device Registry ========== */
async function loadDeviceClients() { ... }  // Fetches /api/devices + /api/devices/stats, renders both tables
async function loadDeviceStats() { ... }     // Updates stat cards
function openDeviceModal(device) { ... }     // Opens bm- modal for registration/edit
function closeDeviceModal() { ... }          // Closes modal
async function saveDevice() { ... }          // POST register or PUT update
async function deleteDevice(id) { ... }      // DELETE with confirm
async function syncDevicesToAdguard() { ... } // POST /api/devices/sync
```

Key UI details:
- Unregistered table rows: click → openDeviceModal(device) with is_registered=false
- Registered table rows: click → openDeviceModal(device) with is_registered=true
- Zone badges: trusted=#22c55e, family=#3b82f6, guest=#f59e0b, iot=#8b5cf6, quarantined=#ef4444
- Online dot: green if last_seen within 15 min, grey otherwise
- Filter bar: zone dropdown, type dropdown, owner dropdown, online/offline toggle

- [ ] **Step 5: Commit**

```bash
git add platform_v2/templates/tools/security_network.html
git commit -m "feat(security): Clients subtab UI — device list, stats, filters"
```

---

### Task 8: Add LCARS tablet registration/edit modal

**Files:**
- Modify: `platform_v2/templates/tools/security_network.html`

- [ ] **Step 1: Add modal HTML**

Add before the agent automation panel (same location as DNS/proxy edit modals):
```html
<!-- Device Registration/Edit Modal -->
<div class="bm-overlay" id="device-edit-modal" style="--bm-accent:#22c55e;--bm-accent-rgb:34,197,94;">
```

Modal body fields:
- friendly_name (text)
- device_type (select: phone/laptop/desktop/tablet/server/camera/smart_tv/iot/gaming/other)
- owner (select with existing owners + "Add new..." option)
- security_zone (select with color dots: trusted/family/guest/iot/quarantined)
- status (select: active/inactive/decommissioned/banned) — only shown for registered devices
- mac_address (read-only input)
- ip_address (read-only input)
- manufacturer (read-only input)
- notes (textarea)

Actions: Save, Cancel, Delete (only for registered devices, with confirm)

- [ ] **Step 2: Add modal JS functions**

```javascript
function openDeviceModal(device) {
    // Set modal accent color based on zone
    // Pre-fill fields from device data
    // Show/hide delete button based on is_registered
    // Populate owner dropdown from existing owners
}

async function saveDevice() {
    // Collect form values
    // If device.is_registered: PUT /api/devices/<id>
    // Else: POST /api/devices/register with {id, friendly_name, device_type, owner, security_zone}
    // Close modal, reload list
}
```

- [ ] **Step 3: Test full flow**

1. Navigate to Security & Network → AdGuard DNS → Clients
2. Should see any auto-discovered devices from the discovery job
3. Click an unregistered device → modal opens
4. Fill in name, type, owner, zone → Save
5. Device moves to registered table with correct zone badge

- [ ] **Step 4: Commit**

```bash
git add platform_v2/templates/tools/security_network.html
git commit -m "feat(security): LCARS tablet modal for device registration/edit"
```

---

### Task 9: Integration test + final commit

**Files:**
- All files from tasks 1-8

- [ ] **Step 1: Full restart and test**

```bash
docker compose up -d archie_platform
```

- [ ] **Step 2: Verify all endpoints**

```bash
# Stats
curl /api/devices/stats
# List
curl /api/devices
# Unregistered
curl /api/devices/unregistered
# Register one
curl -X POST /api/devices/register -d '{"id":1,"friendly_name":"Test","device_type":"other","owner":"Infrastructure","security_zone":"trusted"}'
# Update
curl -X PUT /api/devices/1 -d '{"security_zone":"family"}'
# Sync
curl -X POST /api/devices/sync
# Delete
curl -X DELETE /api/devices/1
```

- [ ] **Step 3: Verify agent loop discovery runs**

```bash
docker logs archie_platform 2>&1 | grep "network.*discovery" | tail -3
```

- [ ] **Step 4: Verify AdGuard sync**

```bash
docker exec archie_platform python3 -c "
import requests, os
host = os.getenv('ADGUARD_HOST','network_adguard')
port = os.getenv('ADGUARD_PORT','80')
user = os.getenv('ADGUARD_USER','')
pw = os.getenv('ADGUARD_PASS','')
r = requests.get(f'http://{host}:{port}/control/clients', auth=(user,pw), timeout=5)
d = r.json()
print(f'Configured clients: {len(d.get(\"clients\",[]))}')
for c in d.get('clients',[]):
    print(f'  {c[\"name\"]}: ids={c[\"ids\"]}')
"
```

- [ ] **Step 5: Create Dev HQ task and mark complete**

```bash
# Use MCP to create and complete the task
```

- [ ] **Step 6: Final commit + push**

```bash
git add -A
git commit -m "feat(security): AdGuard device registry — complete implementation

- network_devices table (migration 172)
- device_registry_service.py with discovery, registration, AdGuard sync
- 8 API endpoints for device CRUD + sync
- Clients subtab in AdGuard DNS with LCARS tablet modal
- Agent loop discovery job (every 5 min) with Telegram alerts
- Security zones: trusted/family/guest/iot/quarantined
- MAC vendor lookup, online detection, zone badge colors"

git push
```
