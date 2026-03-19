"""
A.R.C.H.I.E. Platform - Google Drive Backup Service (shim)
==========================================================

All Google Drive functionality has been consolidated into
``tools.google_work_suite.services.drive_service`` (backup_* functions).

This module re-exports the old names so existing imports keep working.
"""

from tools.google_work_suite.services.drive_service import (
    backup_get_oauth_flow as get_oauth_flow,
    backup_save_oauth_token as save_oauth_token,
    backup_is_oauth_configured as is_oauth_configured,
    backup_get_drive_service as get_drive_service,
    backup_test_connection as test_connection,
    backup_get_storage_quota as get_storage_quota,
    backup_ensure_folder as ensure_backup_folder,
    backup_upload_file as upload_file,
    backup_download_file as download_file,
    backup_list_files as list_backups,
    backup_delete_file as delete_backup,
)

__all__ = [
    "get_oauth_flow",
    "save_oauth_token",
    "is_oauth_configured",
    "get_drive_service",
    "test_connection",
    "get_storage_quota",
    "ensure_backup_folder",
    "upload_file",
    "download_file",
    "list_backups",
    "delete_backup",
]
