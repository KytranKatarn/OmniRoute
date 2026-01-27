# Storage Tab: Interactive Disk Management

**Date**: 2026-01-27
**Module**: System Operations → Storage Tab
**Status**: Design Complete — Awaiting Implementation
**Depends On**: Nothing (foundational — Docker tab depends on this)
**Depended On By**: Docker Tab (stack creation storage allocation)

---

## Overview

Transform the Storage tab into a visual, interactive disk management interface inspired by Partition Magic. Features an interactive treemap visualization with supplementary donut/pie charts, full LVM/partition management, new drive detection with setup wizard, and a bridge to the Docker tab for stack storage allocation.

## Current Host Storage State

| Device | Size | Type | Status | Notes |
|--------|------|------|--------|-------|
| sda (SSD) | 465 GB | LVM (ext4) | Mounted at `/` | 86.1 GB used, 375 GB free VG space |
| sdb (HDD) | 1.86 TB | NTFS | Unmounted | Plan: reformat to ext4 for Linux use |

## Visualization: Interactive Treemap

### Primary View: Treemap
- Each drive is a large block
- Partitions shown as proportionally-sized sub-blocks within each drive
- Color coding:
  - Used space: Gradient from green (low) → amber (medium) → red (high)
  - Free VG space: Dashed border, subtle pattern fill
  - Unmounted/foreign: Grey with "setup needed" indicator
  - New/uninitialized drives: Pulsing highlight border
- Click any block to open the **Action Panel** on the right side

### Supplementary Views: Donut/Pie Charts
- Per-drive donut chart showing partition breakdown
- Overall system donut showing all drives
- A.R.C.H.I.E. themed styling (accent colors, clean typography)

### Dashboard Integration
- Per-drive mini summary with progress bars on the main Dashboard tab
- Shows drive label, used/total, percentage bar
- Links to Storage tab for details

## Action Panel (Right Side)

Clicking any partition block opens a contextual action panel showing:

### For Mounted Partitions
- **Info**: Mount point, filesystem, label, capacity, used/free
- **Extend**: Grow partition (if LVM free space available)
- **Shrink**: Reduce partition size (re-auth required)
- **Unmount**: Unmount filesystem (re-auth required)
- **Browse**: View directory listing
- **Set Label**: Rename the partition label

### For LVM Free Space
- **Create New LV**: Create new logical volume
  - Name, size (slider + input), filesystem type
  - Mount point selection
  - Auto-format option

### For Unmounted/Foreign Partitions (e.g., sdb NTFS)
- **Info**: Device, filesystem, size, partition table
- **Format**: Reformat to ext4/xfs/btrfs (re-auth required — destructive)
- **Mount**: Mount at specified path
- **Setup Wizard**: Full guided setup (format → label → mount → directory structure)

### For Uninitialized/New Drives
- **Setup Wizard** (auto-launched):
  1. Name the drive (label)
  2. Choose partition scheme (GPT recommended)
  3. Create partitions (size, type)
  4. Format each partition
  5. Set mount points
  6. Create initial directory structure

## New Drive Detection

- Host monitor detects new block devices not in `storage_mounts` table
- UI shows **pulsing highlight** on the new drive block in the treemap
- Notification banner: "New drive detected: /dev/sdc (2TB) — Click to set up"
- Clicking launches the Setup Wizard

## Safety: Two-Tier Protection

| Operation | Protection Level |
|-----------|-----------------|
| View info, browse | None |
| Extend partition | Simple confirm |
| Create mount point | Simple confirm |
| Create directory | Simple confirm |
| Mount filesystem | Simple confirm |
| Shrink partition | **Re-auth required** |
| Format partition | **Re-auth required** |
| Delete partition | **Re-auth required** |
| Unmount filesystem | **Re-auth required** |

Re-auth uses the same password verification modal as the Docker tab.

## Database Schema

### `storage_mounts` table

| Column | Type | Description |
|--------|------|-------------|
| id | SERIAL PK | Auto-increment ID |
| device | VARCHAR(100) | Device path (e.g., `/dev/sda1`) |
| mount_point | VARCHAR(500) | Mount path (e.g., `/mnt/plex/storage`) |
| filesystem | VARCHAR(50) | Filesystem type (ext4, xfs, ntfs) |
| label | VARCHAR(100) | Human-friendly label |
| capacity_gb | DECIMAL | Total capacity in GB |
| drive_model | VARCHAR(200) | Drive model string |
| is_managed | BOOLEAN DEFAULT TRUE | Whether managed by A.R.C.H.I.E. |
| created_at | TIMESTAMP | When registered |

This table serves as the **bridge to the Docker tab** — during stack creation, the Docker tab queries `storage_mounts` to offer drive/partition choices for volume mounts.

## Docker-Storage Bridge

### During Stack Creation (Docker Tab → Storage)
1. Docker tab parses volume mounts from compose file
2. Queries `storage_mounts` for available managed partitions
3. Presents dropdown: "Store `/mnt/plex/configs` on: [SSD - 375GB free] [HDD - 1.86TB]"
4. Creates subdirectories on selected partition
5. Updates compose file paths if needed

### From Storage Tab → Docker Tab
- Storage tab shows which stacks use each partition
- "Used by: Plex (configs), A.R.C.H.I.E. (platform)" labels on partition blocks
- Prevents unmounting/shrinking partitions actively used by running stacks

## Host Monitor Data Collection

Enhanced `get_storage_info()` in host_monitor.py:

- Block devices: `lsblk -Jb` (JSON output with sizes in bytes)
- Partition details: `blkid` for filesystem type, UUID, label
- LVM info: `pvs`, `vgs`, `lvs` for volume group/logical volume details
- Mount info: `/proc/mounts` or `findmnt -J`
- SMART data (optional): `smartctl` for drive health
- Disk I/O: `/proc/diskstats` for read/write rates

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/storage/drives` | List all drives with partitions |
| GET | `/api/storage/drive/{device}` | Detailed drive info |
| POST | `/api/storage/format` | Format a partition (re-auth) |
| POST | `/api/storage/mount` | Mount a partition |
| POST | `/api/storage/unmount` | Unmount a partition (re-auth) |
| POST | `/api/storage/extend` | Extend LVM partition |
| POST | `/api/storage/shrink` | Shrink LVM partition (re-auth) |
| POST | `/api/storage/create-lv` | Create new logical volume |
| POST | `/api/storage/create-dir` | Create directory on mount |
| GET | `/api/storage/mounts` | List managed mounts (for Docker bridge) |
| GET | `/api/storage/browse/{path}` | Browse directory listing |

## Implementation Notes

- All destructive operations execute via host_monitor.py (runs as root on host)
- Need a command execution channel: host_monitor.py watches a command queue file/DB table
- Alternatively, add a simple HTTP API to host_monitor.py for receiving commands
- Treemap library: Consider D3.js treemap layout or a lightweight alternative
- Donut charts: Chart.js (already may be available) or D3.js
- Real-time updates: Poll every 30 seconds, immediate refresh after operations
- LVM operations: `lvcreate`, `lvextend`, `lvreduce`, `mkfs`, `mount`, `umount`
- NTFS handling: `ntfs-3g` for read, `mkfs.ext4` for reformat
