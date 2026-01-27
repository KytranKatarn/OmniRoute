# Docker Tab: Multi-Stack Portainer-Style Management

**Date**: 2026-01-27
**Module**: System Operations → Docker Tab
**Status**: Design Complete — Awaiting Implementation
**Dependencies**: Storage Tab (for drive allocation during stack creation)

---

## Overview

Transform the Docker tab from a single-stack view into a multi-stack management interface similar to Portainer. Users can create, manage, and monitor multiple Docker Compose stacks from the UI. The A.R.C.H.I.E. stack is the system stack with additional safety protections; all other stacks are user-created.

## Stack Storage Layout

```
/mnt/archie_brain/           ← A.R.C.H.I.E. system stack (stays here, NOT moved)
  docker-compose.yml
  .env
  platform_v2/
  ...

/mnt/stacks/                 ← User-created stacks
  plex/
    docker-compose.yml
    .env
    configs/
    storage/                 ← Can be on different drive via mount/symlink
  stack3/
    docker-compose.yml
    .env
  stack4/
    docker-compose.yml
    .env
```

## Database Schema

### `docker_stacks` table

| Column | Type | Description |
|--------|------|-------------|
| id | SERIAL PK | Auto-increment ID |
| name | VARCHAR(50) UNIQUE | Slug name (e.g., `plex`, `homeassistant`) |
| display_name | VARCHAR(100) | Human-friendly name (e.g., "Plex Media Server") |
| directory | VARCHAR(500) | Absolute path to stack directory |
| description | TEXT | Optional description |
| color | VARCHAR(7) | Hex color for UI grouping (e.g., `#E5A00D`) |
| is_system | BOOLEAN DEFAULT FALSE | TRUE only for A.R.C.H.I.E. |
| created_at | TIMESTAMP | Creation timestamp |

The A.R.C.H.I.E. stack is seeded on first run with `is_system=TRUE`.

## UI Layout

### Landing Page: Stack Overview Cards

Grid of cards, one per stack. Each card shows:
- Stack name + color accent
- Status indicator (running/stopped/partial)
- Container count (running/total)
- Quick stats: CPU, Memory, Network I/O
- Quick actions: Start All, Stop All, Restart All
- "SYSTEM" badge on A.R.C.H.I.E. card

Top-right: **"+ New Stack"** button to launch creation wizard.

### Detail View: Stack Drill-Down

Clicking a card opens the detailed stack view with:

**Stack Switcher** — Tabs or sidebar to switch between stacks without going back to overview.

**Detail Sections:**
1. **Containers** — List with status, image, ports, uptime, actions (start/stop/restart/logs/shell)
2. **Images** — Images used by this stack with pull/update actions
3. **Volumes** — Volumes owned by this stack
4. **Networks** — Docker networks for this stack
5. **Compose Editor** — Edit `docker-compose.yml` with syntax highlighting
6. **Environment Editor** — Edit `.env` file
7. **Logs** — Aggregated or per-container log viewer

## Stack Creation Wizard

### Step 1: Name & Description
- Stack name (slug auto-generated)
- Display name
- Description (optional)
- Color picker

### Step 2: Compose File
- Paste or upload `docker-compose.yml`
- Or start from a template (Plex, Home Assistant, etc.)
- Syntax validation before proceeding

### Step 3: Environment Variables
- Parse `.env` references from compose file
- Form fields for each variable
- Sensitive values masked

### Step 4: Storage Allocation (Docker-Storage Bridge)
- Parse volume mounts from compose file
- For each mount, let user choose:
  - Which drive/partition to store data on (from Storage tab's `storage_mounts` table)
  - Auto-create subdirectories
- Example: Plex stack → `/mnt/plex/configs` on SSD, `/mnt/plex/storage` on HDD

### Step 5: Review & Create
- Summary of all settings
- "Create Stack" button
- Creates directory, writes files, optionally starts stack

## Per-Stack Actions

| Action | Non-System Stack | System Stack (A.R.C.H.I.E.) |
|--------|-----------------|------------------------------|
| Start | Simple confirm | Simple confirm |
| Stop | Simple confirm | **Re-auth required** |
| Restart | Simple confirm | **Re-auth required** |
| Pull/Update | Simple confirm | **Re-auth required** |
| Edit Compose | Direct edit | **Re-auth required** |
| Edit .env | Direct edit | **Re-auth required** |
| Delete Stack | Confirm dialog | **Blocked** (cannot delete system stack) |
| View Logs | Direct access | Direct access |

## Safety: Two-Tier Protection

### Tier 1: Simple Confirmation
Standard "Are you sure?" modal for non-destructive or non-system operations.

### Tier 2: Re-Authentication
For destructive operations on the system stack:
- Modal requires current password entry
- Server validates against the user's stored credentials
- 5-minute auth window (subsequent operations skip re-auth within window)
- Logged to audit trail

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/stacks` | List all stacks with status |
| POST | `/api/stacks` | Create new stack |
| GET | `/api/stacks/{name}` | Get stack details |
| PUT | `/api/stacks/{name}` | Update stack config |
| DELETE | `/api/stacks/{name}` | Delete stack (not system) |
| POST | `/api/stacks/{name}/action` | Start/stop/restart/pull |
| GET | `/api/stacks/{name}/compose` | Get compose file content |
| PUT | `/api/stacks/{name}/compose` | Update compose file |
| GET | `/api/stacks/{name}/env` | Get env file content |
| PUT | `/api/stacks/{name}/env` | Update env file |
| GET | `/api/stacks/{name}/logs` | Get stack/container logs |
| GET | `/api/stacks/{name}/containers` | List containers with stats |

## Implementation Notes

- Stack operations use `docker compose -f <path>/docker-compose.yml` with the `--project-directory` flag
- Container stats collected via Docker API (not CLI) for efficiency
- A.R.C.H.I.E. stack auto-detected on first load by checking for `/mnt/archie_brain/docker-compose.yml`
- Stack status polling: every 10 seconds on overview, every 5 seconds on detail view
- Color is used throughout: stack cards, network tab port grouping, topology map nodes
