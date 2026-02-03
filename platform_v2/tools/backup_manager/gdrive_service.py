"""
A.R.C.H.I.E. Platform - Google Drive Backup Service
====================================================

Handles Google Drive API operations for cloud backup storage.
Uses OAuth 2.0 so files are owned by the user's Google account
(service accounts have no storage quota on personal Google Drive).
"""

import os

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload, MediaIoBaseDownload

SCOPES = ["https://www.googleapis.com/auth/drive.file"]
BACKUP_FOLDER_NAME = "ARCHIE-Backups"
TOKEN_PATH = os.environ.get("GDRIVE_TOKEN_PATH", "/app/credentials/gdrive-oauth-token.json")
CLIENT_SECRETS_PATH = os.environ.get("GDRIVE_CLIENT_SECRETS_PATH", "/app/credentials/gdrive-client-secrets.json")


def _load_credentials():
    """Load OAuth credentials from saved token, refreshing if expired."""
    if not os.path.exists(TOKEN_PATH):
        return None

    creds = Credentials.from_authorized_user_file(TOKEN_PATH, SCOPES)

    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
        # Save refreshed token
        with open(TOKEN_PATH, "w") as f:
            f.write(creds.to_json())

    if creds and creds.valid:
        return creds

    return None


def get_oauth_flow():
    """
    Create an OAuth flow for the initial authorization.

    Returns:
        google_auth_oauthlib.flow.Flow instance

    Raises:
        FileNotFoundError: If client secrets file is missing.
    """
    from google_auth_oauthlib.flow import Flow

    if not os.path.exists(CLIENT_SECRETS_PATH):
        raise FileNotFoundError(
            f"OAuth client secrets not found at {CLIENT_SECRETS_PATH}. "
            "Create OAuth credentials in Google Cloud Console → APIs & Services → Credentials, "
            "download the JSON, and place it there."
        )

    flow = Flow.from_client_secrets_file(CLIENT_SECRETS_PATH, scopes=SCOPES)
    return flow


def save_oauth_token(creds):
    """Save OAuth credentials to disk."""
    os.makedirs(os.path.dirname(TOKEN_PATH), exist_ok=True)
    with open(TOKEN_PATH, "w") as f:
        f.write(creds.to_json())


def is_oauth_configured() -> bool:
    """Check if OAuth token exists and is usable."""
    return _load_credentials() is not None


def get_drive_service(service_account_path: str = None):
    """
    Build an authenticated Google Drive API v3 client.

    Prefers OAuth credentials (user-owned files with real storage quota).
    Falls back to service account if OAuth is not configured.

    Returns:
        Google Drive API service resource
    """
    # Prefer OAuth — files are owned by the user with real storage
    creds = _load_credentials()
    if creds:
        return build("drive", "v3", credentials=creds)

    # Fall back to service account (limited: can't own files on personal Drive)
    if not service_account_path:
        service_account_path = os.environ.get(
            "GDRIVE_SERVICE_ACCOUNT_PATH", "/app/credentials/gdrive-service-account.json"
        )

    if os.path.exists(service_account_path):
        from google.oauth2 import service_account as sa

        credentials = sa.Credentials.from_service_account_file(service_account_path, scopes=SCOPES)
        return build("drive", "v3", credentials=credentials)

    raise RuntimeError(
        "No Google Drive credentials configured. "
        "Set up OAuth via Backup Manager → Cloud Backup → Connect Google Drive."
    )


def test_connection(service) -> dict:
    """
    Test that the account can access Drive.

    Returns:
        dict with success status and account info
    """
    try:
        about = service.about().get(fields="user,storageQuota").execute()
        return {
            "success": True,
            "email": about.get("user", {}).get("emailAddress", "unknown"),
            "storage": about.get("storageQuota", {}),
            "auth_type": "oauth" if is_oauth_configured() else "service_account",
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


def get_storage_quota(service) -> dict:
    """
    Get Drive storage usage information.

    Returns:
        dict with usage, limit (in bytes), and formatted strings
    """
    about = service.about().get(fields="storageQuota").execute()
    quota = about.get("storageQuota", {})

    usage = int(quota.get("usage", 0))
    limit = int(quota.get("limit", 0))

    def fmt(b):
        if b >= 1073741824:
            return f"{b / 1073741824:.1f} GB"
        return f"{b / 1048576:.1f} MB"

    return {
        "usage_bytes": usage,
        "limit_bytes": limit,
        "usage_formatted": fmt(usage),
        "limit_formatted": fmt(limit) if limit else "Unlimited",
        "percent_used": round((usage / limit * 100), 1) if limit else 0,
    }


def ensure_backup_folder(service, folder_id: str = None) -> str:
    """
    Find or create the ARCHIE-Backups folder on Drive.

    Args:
        folder_id: If provided, verify this folder exists. Otherwise search/create.

    Returns:
        Folder ID string
    """
    # If we have a saved folder ID, verify it still exists
    if folder_id:
        try:
            folder = service.files().get(fileId=folder_id, fields="id,name,trashed").execute()
            if not folder.get("trashed"):
                return folder["id"]
        except Exception:
            pass  # Folder doesn't exist or was deleted, create a new one

    # Search for existing folder
    query = f"name='{BACKUP_FOLDER_NAME}' and " "mimeType='application/vnd.google-apps.folder' and " "trashed=false"
    results = service.files().list(q=query, fields="files(id,name)", pageSize=1).execute()
    files = results.get("files", [])

    if files:
        return files[0]["id"]

    # Create new folder
    folder_metadata = {
        "name": BACKUP_FOLDER_NAME,
        "mimeType": "application/vnd.google-apps.folder",
    }
    folder = service.files().create(body=folder_metadata, fields="id").execute()
    return folder["id"]


def upload_file(service, file_path: str, folder_id: str, filename: str = None, on_progress=None) -> dict:
    """
    Upload a file to Google Drive with resumable upload.

    Args:
        service: Drive API service
        file_path: Local path to file
        folder_id: Drive folder ID to upload into
        filename: Override filename (defaults to basename)
        on_progress: Optional callback(bytes_sent, total_bytes)

    Returns:
        dict with file id, name, size, webViewLink
    """
    if not filename:
        filename = os.path.basename(file_path)

    file_metadata = {"name": filename, "parents": [folder_id]}

    file_size = os.path.getsize(file_path)

    media = MediaFileUpload(
        file_path, mimetype="application/octet-stream", resumable=True, chunksize=5 * 1024 * 1024  # 5MB chunks
    )

    request = service.files().create(
        body=file_metadata, media_body=media, fields="id,name,size,webViewLink,createdTime"
    )

    response = None
    while response is None:
        status, response = request.next_chunk()
        if status and on_progress:
            on_progress(int(status.resumable_progress), file_size)

    return {
        "id": response["id"],
        "name": response["name"],
        "size": int(response.get("size", 0)),
        "web_link": response.get("webViewLink", ""),
        "created_time": response.get("createdTime", ""),
    }


def download_file(service, file_id: str, output_path: str, on_progress=None) -> str:
    """
    Download a file from Google Drive.

    Args:
        service: Drive API service
        file_id: Drive file ID
        output_path: Local path to save file
        on_progress: Optional callback(bytes_downloaded, total_bytes)

    Returns:
        Path to downloaded file
    """
    # Get file size first
    file_meta = service.files().get(fileId=file_id, fields="size").execute()
    total_size = int(file_meta.get("size", 0))

    request = service.files().get_media(fileId=file_id)
    with open(output_path, "wb") as fout:
        downloader = MediaIoBaseDownload(fout, request, chunksize=5 * 1024 * 1024)
        done = False
        while not done:
            status, done = downloader.next_chunk()
            if status and on_progress:
                on_progress(int(status.resumable_progress), total_size)

    return output_path


def list_backups(service, folder_id: str) -> list:
    """
    List all backup files in the backup folder.

    Returns:
        List of dicts with id, name, size, createdTime, modifiedTime
    """
    query = f"'{folder_id}' in parents and trashed=false"
    all_files = []
    page_token = None

    while True:
        results = (
            service.files()
            .list(
                q=query,
                fields="nextPageToken,files(id,name,size,createdTime,modifiedTime)",
                orderBy="createdTime desc",
                pageSize=100,
                pageToken=page_token,
            )
            .execute()
        )

        for f in results.get("files", []):
            all_files.append(
                {
                    "id": f["id"],
                    "name": f["name"],
                    "size": int(f.get("size", 0)),
                    "created_time": f.get("createdTime", ""),
                    "modified_time": f.get("modifiedTime", ""),
                }
            )

        page_token = results.get("nextPageToken")
        if not page_token:
            break

    return all_files


def delete_backup(service, file_id: str) -> bool:
    """Delete a backup file from Drive."""
    service.files().delete(fileId=file_id).execute()
    return True
