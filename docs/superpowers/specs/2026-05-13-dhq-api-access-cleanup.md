# DHQ API Access Tab Cleanup

**Date:** 2026-05-13
**Tab:** Department HQ → API Access (panel-devices)
**Scope:** Replace browser-native confirm()/prompt() with LCARS modals; delete dead test device.

---

## Context

The API Access tab manages `registered_devices` — external tools (KSO, KBS, standalones) that register for API keys to call the platform. The backend is complete. The UI works but uses banned primitives:

- `confirm()` in `denyDevice()` and `revokeDevice()` — platform convention: no native browser dialogs
- `prompt()` in `approveDevice()` — shows API key once; must be a proper modal with copy button

One dead test device (id=1, revoked, 0 requests) needs to be purged.

---

## Changes

### 1. DB — Delete dead test device

```sql
DELETE FROM registered_devices WHERE id = 1;
```

Run once via migration or direct exec. No migration file needed (data cleanup, no schema change).

### 2. HTML — Three modals in panel-devices

Add inside `<div class="dhq-panel" id="panel-devices">`, after `devicesContent` div:

**Modal A — Deny confirm** (`id="deviceDenyModal"`)
- Red accent (`#ef4444`)
- Header: "DENY DEVICE"
- Body: device name + "This device will be denied access."
- Footer: CONFIRM (red) + CANCEL

**Modal B — Revoke confirm** (`id="deviceRevokeModal"`)
- Red accent (`#ef4444`)
- Header: "REVOKE ACCESS"
- Body: device name + "This device will lose all access immediately."
- Footer: CONFIRM (red) + CANCEL

**Modal C — API Key display** (`id="deviceKeyModal"`)
- Cyan accent (`#00e5ff`)
- Header: "API KEY ISSUED"
- Body: warning "This key will not be shown again." + monospace key box
- Footer: COPY KEY button + CLOSE button

All three use the platform LCARS modal pattern:
```html
<div class="bm-overlay" id="...">
  <div class="bm-shell">
    <div class="bm-frame" style="--bm-accent: #COLOR;">
      <div class="bm-content">
        <div class="bm-header">...</div>
        <div class="bm-body">...</div>
        <div class="bm-footer">...</div>
      </div>
    </div>
  </div>
</div>
```

### 3. JS — Rewrite three functions in department-hq.js

**`denyDevice(deviceId, deviceName)`** — opens `#deviceDenyModal`, stores pending action, executes on CONFIRM.

**`revokeDevice(deviceId, deviceName)`** — opens `#deviceRevokeModal`, same pattern.

**`approveDevice(deviceId)`** — on success, opens `#deviceKeyModal` with the returned `api_key`. COPY KEY calls `navigator.clipboard.writeText(key)` and updates button text to "COPIED ✓".

Modals close via CANCEL/CLOSE or clicking the `bm-overlay` background.

The `loadDevices()` render loop must pass `deviceName` to `denyDevice()` and `revokeDevice()` so the modal body can display it.

---

## Out of Scope

- Changes to backend routes (complete and correct)
- Changes to `loadDevices()` rendering logic beyond passing device name
- New device registration flow (not triggered from this tab)
- Usage stats / last_seen display (no data yet)

---

## Testing

1. Open DHQ → API Access tab — empty state visible (test device deleted)
2. Register a test device via `POST /api/auth/register` with `{device_name: "test", device_type: "cli"}`
3. Device appears with status=pending
4. Click Approve → `#deviceKeyModal` opens with a key in monospace box
5. Click COPY KEY → button changes to "COPIED ✓", clipboard has the key
6. Click CLOSE → modal dismisses, device reloads as approved
7. Click Revoke → `#deviceRevokeModal` opens with device name
8. Click CANCEL → modal closes, no action
9. Click Revoke again → CONFIRM → device becomes revoked
10. No `confirm()` or `prompt()` native dialogs appear at any point
