# COMs Tab — Agent Channels Panel Design Spec
**Date:** 2026-05-12 | **Status:** Approved | **Author:** Claude + Kytran

---

## Problem

Module chat overlays (W.A.R.D.E.N., V.I.G.I.L., R.E.S.O.L.V.E., P.R.O.B.E., B.A.S.E.) each create persistent `moduleKey` channels in `unified_conversations`, but they're only accessible from the bubble on each module page. There's no central view — you have to navigate to each module to see what its agent said.

The COMs tab already shows Telegram + Director Reports. Adding Agent Channels completes the trifecta: module agent chat, broadcast comms, and director triage — all in one place.

---

## Solution: Agent Channels Panel in COMs Tab

New section in the COMs tab that lists all moduleKey team channels with last message preview, unread count, and inline chat. Clicking a channel opens a chat panel within COMs — no page navigation required.

---

## UI Layout

```
┌─ COMMUNICATIONS ────────────────────────────────────────────┐
│  TOTAL MESSAGES │ TELEGRAM │ PLATFORM CHAT │ DIRECTOR REPORTS │
├──────────────────────────────────────────────────────────────┤
│  AGENT CHANNELS                               [NEW SECTION]  │
│  ┌──────────────────────────────────────────────────────┐   │
│  │ 🖥 B.A.S.E.      KSO Operations     "Scan complete"  ● 3│   │
│  │ 🛡 V.I.G.I.L.   Security Network   "Compliance: 94%" ● 1│   │
│  │ 🔧 W.A.R.D.E.N. Backup Manager     "Retention clean"   │   │
│  │ 🔬 P.R.O.B.E.   Repair Bay         "PR #655 reviewed" ● 2│   │
│  │ 📋 R.E.S.O.L.V.E. Account Center  "New invite sent"    │   │
│  │ 📧 R.E.S.O.L.V.E. Email HQ        "42 triaged"         │   │
│  └──────────────────────────────────────────────────────┘   │
│                                                              │
│  ┌── inline chat panel (slides in when channel clicked) ──┐  │
│  │  [agent portrait] [message history] [input box]        │  │
│  └─────────────────────────────────────────────────────────┘  │
├──────────────────────────────────────────────────────────────┤
│  RECENT MESSAGES (Telegram)  │  DIRECTOR REPORTS             │
└──────────────────────────────────────────────────────────────┘
```

---

## Components

### 1. New COMs sub-section: Agent Channels

Added to `tools/department_hq/templates/coms_tab.html` (or equivalent partial) as a new `<section>` above the existing Recent Messages / Director Reports columns.

**Channel list item displays:**
- Agent portrait thumbnail (from `/api/public/directory`)
- Agent acronym (B.A.S.E., V.I.G.I.L., etc.)
- Module label (KSO Operations, Security Network, etc.)
- Last message preview (truncated 60 chars)
- Unread count badge
- Last activity timestamp (relative: "2m ago")

### 2. New API endpoint: `GET /tools/department-hq/api/coms/agent-channels`

Returns all moduleKey team channels with metadata:
```json
{
  "channels": [
    {
      "module_key": "kso_system_operations",
      "module_label": "KSO Operations",
      "agent_name": "B.A.S.E.",
      "agent_id": 139,
      "agent_portrait": "/assets/portraits/base.jpg",
      "conversation_id": 42,
      "last_message": "Compliance scan completed. Score: 91%.",
      "last_message_at": "2026-05-12T15:30:00Z",
      "unread_count": 3
    }
  ]
}
```

**Data source:** `unified_conversations` WHERE `module_key IS NOT NULL` AND `team_id = 1`, joined with last message from `unified_messages`.

### 3. Inline chat panel

When a channel row is clicked:
- Slides in a panel on the right side of the COMs tab (same pattern as Director Reports detail panel)
- Loads the conversation via existing `GET /api/v1/chat/conversations/{id}/messages`
- Send button POSTs to existing `POST /api/v1/chat/message` with `conversation_id`
- Reuses existing archie-chat CSS (`ac-overlay-*` classes or equivalent)
- Auto-marks messages as read on open

### 4. Auto-registration of new channels

When a new module chat overlay is added (DHQ → A.R.C.H.I.E., Consciousness → C.O.D.E.X., Agent Academy → F.O.R.G.E.), its `moduleKey` channel is auto-created on first open via the existing `/api/v1/chat/channel` endpoint. It auto-appears in the Agent Channels list on next page load — no manual registration needed.

---

## Module Key Registry

Known `moduleKey` values and their agents (from `reference_module-agent-assignments.md`, KB #265608):

| moduleKey | Agent | Module Label |
|-----------|-------|-------------|
| `backup_manager` | W.A.R.D.E.N. #363 | Backup Manager |
| `security_network` | V.I.G.I.L. #3 | Security Network |
| `account_center` | R.E.S.O.L.V.E. #142 | Account Center |
| `email_manager` | R.E.S.O.L.V.E. #142 | Email Manager |
| `repair_bay` | P.R.O.B.E. #340 | Repair Bay |
| `platform_main` | A.R.C.H.I.E. #2 | Platform |
| `kso_system_operations` | B.A.S.E. #139 | KSO Operations |
| `department_hq` | A.R.C.H.I.E. #2 | Department HQ *(pending)* |
| `consciousness` | C.O.D.E.X. #146 | Consciousness *(pending)* |
| `agent_academy` | F.O.R.G.E. #136 | Agent Academy *(pending)* |

---

## Telegram Connection (full circle)

When an agent sends a message in a module channel AND the message contains an action trigger (compliance finding, repair proposal, welfare alert), the existing Telegram notification fires. The COMs tab shows both the module chat message (in Agent Channels) AND the Telegram notification (in Recent Messages) — two views of the same event.

---

## Files to Create/Modify

| File | Action |
|------|--------|
| `platform_v2/tools/department_hq/coms_routes.py` | MODIFY — add `GET /api/coms/agent-channels` endpoint |
| `platform_v2/tools/department_hq/templates/` (COMs partial) | MODIFY — add Agent Channels section above existing columns |
| `platform_v2/static/js/department_hq*.js` or coms JS | MODIFY — channel list render + inline panel open/close |
| `platform_v2/static/css/department_hq*.css` | MODIFY — channel list + inline panel styles |

No new tables. No new services. Uses existing `unified_conversations`, `unified_messages`, and archie-chat API.

---

## Tier Gate

Agent Channels panel visible to ADMIN+ users only (same as COMs tab today). No per-tier gate on channel visibility — all channels accessible to any admin. Individual module chats remain business+ gated at the module level.

---

## Out of Scope

- Push notifications for new channel messages (follow-up)
- Channel muting / notification preferences (follow-up)
- Cross-channel search (follow-up)
- Showing agent typing indicator (follow-up)
