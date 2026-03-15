#!/bin/bash
# Backup Configuration — Updated 2026-03-15
# Primary daily backups: /mnt/data2/backups/ (1.8TB, plenty of space)
# USB weekly backups: /mnt/external-backup/ (57GB, 1 copy per week)
# Pre-change snapshots: /mnt/data2/backups/pre-change/ (before code deploys)

export BACKUP_PRIMARY_DIR="/mnt/data2/backups"
export BACKUP_USB_DIR="/mnt/external-backup"
export BACKUP_PRECHANGE_DIR="/mnt/data2/backups/pre-change"
export BACKUP_RETENTION_DAILY=30    # keep 30 daily backups
export BACKUP_RETENTION_WEEKLY=12   # keep 12 weekly on USB (3 months)
export BACKUP_RETENTION_PRECHANGE=20 # keep 20 pre-change snapshots
