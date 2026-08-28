"""
Google Drive Service — file management, document/spreadsheet creation, sharing, and agent automation.

Also contains backup-specific Drive operations (OAuth-based, system-level auth) previously
in backup_manager/gdrive_service.py.  Backup functions are prefixed with ``backup_`` and use
their own credential flow (no account_id).
"""

import logging
import os

from .google_api_service import get_google_client

logger = logging.getLogger(__name__)

_GDOC_MIME = "application/vnd.google-apps.document"
_GSHEET_MIME = "application/vnd.google-apps.spreadsheet"
_GFOLDER_MIME = "application/vnd.google-apps.folder"
_FILE_FIELDS = "id,name,mimeType,size,modifiedTime,parents,webViewLink,iconLink"


def _get_drive(account_id):
    return get_google_client(account_id, "drive", "v3")


def list_files(account_id, folder_id="root", query=None, max_results=50):
    """List files in a folder.  Optionally narrow with a freetext query."""
    try:
        service = _get_drive(account_id)
        q = f"'{folder_id}' in parents and trashed=false"
        if query:
            q += f" and (name contains '{query}' or fullText contains '{query}')"
        result = (
            service.files()
            .list(
                q=q,
                pageSize=max_results,
                fields=f"files({_FILE_FIELDS})",
            )
            .execute()
        )
        return result.get("files", [])
    except Exception as exc:
        logger.error("list_files failed for account %s, folder %s: %s", account_id, folder_id, exc)
        raise


def get_file(account_id, file_id):
    """
    Return file metadata plus a content_preview (first 5000 chars) when possible.
    Exports Google Docs as plain text, Sheets as CSV; downloads other small text files directly.
    """
    try:
        service = _get_drive(account_id)
        meta = service.files().get(fileId=file_id, fields="id,name,mimeType,size,modifiedTime,webViewLink").execute()
        mime = meta.get("mimeType", "")
        content_preview = None

        if mime == _GDOC_MIME:
            raw = service.files().export(fileId=file_id, mimeType="text/plain").execute()
            text = raw.decode("utf-8") if isinstance(raw, bytes) else raw
            content_preview = text[:5000]
        elif mime == _GSHEET_MIME:
            raw = service.files().export(fileId=file_id, mimeType="text/csv").execute()
            text = raw.decode("utf-8") if isinstance(raw, bytes) else raw
            content_preview = text[:5000]
        elif mime.startswith("text/") or mime in ("application/json", "application/xml"):
            size = int(meta.get("size") or 0)
            if size <= 1_000_000:  # 1 MB cap
                raw = service.files().get_media(fileId=file_id).execute()
                text = raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else raw
                content_preview = text[:5000]

        return {"metadata": meta, "content_preview": content_preview}
    except Exception as exc:
        logger.error("get_file failed for account %s, file %s: %s", account_id, file_id, exc)
        raise


def upload_file(account_id, name, content_bytes, mime_type, folder_id="root"):
    """Upload raw bytes as a new Drive file."""
    try:
        from googleapiclient.http import MediaInMemoryUpload

        service = _get_drive(account_id)
        media = MediaInMemoryUpload(content_bytes, mimetype=mime_type)
        result = (
            service.files()
            .create(
                body={"name": name, "parents": [folder_id]},
                media_body=media,
                fields="id,webViewLink",
            )
            .execute()
        )
        logger.info("Uploaded file '%s' (id=%s) for account %s", name, result.get("id"), account_id)
        return {"file_id": result["id"], "web_view_link": result.get("webViewLink")}
    except Exception as exc:
        logger.error("upload_file failed for account %s: %s", account_id, exc)
        raise


def create_document(account_id, title, content="", folder_id="root"):
    """
    Create a new Google Doc.  If content is provided, attempt to insert it via
    the Docs API; skip silently if the Docs API is unavailable.
    """
    try:
        service = _get_drive(account_id)
        result = (
            service.files()
            .create(
                body={"name": title, "mimeType": _GDOC_MIME, "parents": [folder_id]},
                fields="id,webViewLink",
            )
            .execute()
        )
        file_id = result["id"]

        if content:
            try:
                docs_service = get_google_client(account_id, "docs", "v1")
                docs_service.documents().batchUpdate(
                    documentId=file_id,
                    body={
                        "requests": [
                            {
                                "insertText": {
                                    "location": {"index": 1},
                                    "text": content,
                                }
                            }
                        ]
                    },
                ).execute()
            except Exception as docs_exc:
                logger.warning("Could not insert content into doc %s via Docs API: %s", file_id, docs_exc)

        logger.info("Created Google Doc '%s' (id=%s) for account %s", title, file_id, account_id)
        return {"file_id": file_id, "web_view_link": result.get("webViewLink")}
    except Exception as exc:
        logger.error("create_document failed for account %s: %s", account_id, exc)
        raise


def create_spreadsheet(account_id, title, data=None, folder_id="root"):
    """
    Create a new Google Sheet.  If data (list of lists) is provided, write it
    to Sheet1 via the Sheets API.
    """
    try:
        service = _get_drive(account_id)
        result = (
            service.files()
            .create(
                body={"name": title, "mimeType": _GSHEET_MIME, "parents": [folder_id]},
                fields="id,webViewLink",
            )
            .execute()
        )
        file_id = result["id"]

        if data:
            try:
                sheets_service = get_google_client(account_id, "sheets", "v4")
                sheets_service.spreadsheets().values().update(
                    spreadsheetId=file_id,
                    range="Sheet1",
                    valueInputOption="RAW",
                    body={"values": data},
                ).execute()
            except Exception as sheets_exc:
                logger.warning("Could not write data to sheet %s: %s", file_id, sheets_exc)

        logger.info("Created Google Sheet '%s' (id=%s) for account %s", title, file_id, account_id)
        return {"file_id": file_id, "web_view_link": result.get("webViewLink")}
    except Exception as exc:
        logger.error("create_spreadsheet failed for account %s: %s", account_id, exc)
        raise


def share_file(account_id, file_id, email, role="reader"):
    """Share a file with a specific user by email."""
    try:
        service = _get_drive(account_id)
        result = (
            service.permissions()
            .create(
                fileId=file_id,
                body={"type": "user", "role": role, "emailAddress": email},
                fields="id,role,emailAddress",
            )
            .execute()
        )
        logger.info("Shared file %s with %s (role=%s) for account %s", file_id, email, role, account_id)
        return {"permission_id": result["id"], "role": result.get("role"), "email": result.get("emailAddress")}
    except Exception as exc:
        logger.error("share_file failed for account %s, file %s: %s", account_id, file_id, exc)
        raise


def delete_file(account_id, file_id):
    """Move a file to trash (non-destructive delete)."""
    try:
        service = _get_drive(account_id)
        service.files().update(fileId=file_id, body={"trashed": True}).execute()
        logger.info("Trashed file %s for account %s", file_id, account_id)
        return {"success": True, "file_id": file_id}
    except Exception as exc:
        logger.error("delete_file failed for account %s, file %s: %s", account_id, file_id, exc)
        raise


def create_folder(account_id, name, parent_id="root"):
    """Create a Drive folder and return its id."""
    try:
        service = _get_drive(account_id)
        result = (
            service.files()
            .create(
                body={"name": name, "mimeType": _GFOLDER_MIME, "parents": [parent_id]},
                fields="id,webViewLink",
            )
            .execute()
        )
        logger.info("Created folder '%s' (id=%s) for account %s", name, result.get("id"), account_id)
        return {"folder_id": result["id"], "web_view_link": result.get("webViewLink")}
    except Exception as exc:
        logger.error("create_folder failed for account %s: %s", account_id, exc)
        raise


def agent_create_report(account_id, agent_name, title, sections):
    """
    Create a formatted Google Doc report.
    sections: list of {heading: str, body: str}
    Returns file details.
    """
    try:
        content_parts = [f"# {title}\n\nGenerated by {agent_name}\n\n"]
        for section in sections:
            heading = section.get("heading", "")
            body = section.get("body", "")
            content_parts.append(f"## {heading}\n\n{body}\n\n")
        content = "".join(content_parts)
        result = create_document(account_id, title=title, content=content)
        logger.info("agent_create_report: '%s' created for agent %s", title, agent_name)
        return result
    except Exception as exc:
        logger.error("agent_create_report failed for account %s, agent %s: %s", account_id, agent_name, exc)
        raise


def generate_daily_summary(account_id, agent_name):
    """Generate a daily activity summary as a Google Doc."""
    from database import get_db_cursor  # noqa: PLC0415
    from datetime import datetime, timedelta, timezone  # noqa: PLC0415

    yesterday = datetime.now(timezone.utc) - timedelta(hours=24)

    # Gather activity data
    with get_db_cursor() as (conn, cur):
        cur.execute(
            "SELECT COUNT(*) AS cnt FROM google_email_cache WHERE account_id = %s AND cached_at >= %s",
            (account_id, yesterday),
        )
        row = cur.fetchone()
        email_count = row["cnt"] if row else 0

        cur.execute("SELECT display_name FROM google_accounts WHERE id = %s", (account_id,))
        account = cur.fetchone()
        display_name = account["display_name"] if account else agent_name

    # Build summary content
    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    title = f"Daily Summary — {display_name} — {date_str}"

    sections = [
        f"# Daily Summary for {display_name}",
        f"Date: {date_str}",
        "",
        "## Email Activity",
        f"- Emails processed: {email_count}",
        "",
        "## Notes",
        "- Summary auto-generated by A.R.C.H.I.E. Google Work Suite",
    ]
    content = "\n".join(sections)

    result = create_document(account_id, title, content)
    logger.info("generate_daily_summary: created '%s' for account %s", title, account_id)
    return result


def agent_create_spreadsheet_from_data(account_id, agent_name, title, headers, rows):
    """
    Create a Google Sheet with a header row followed by data rows.
    headers: list of column name strings
    rows: list of lists
    Returns file details.
    """
    try:
        data = [headers] + rows
        result = create_spreadsheet(account_id, title=title, data=data)
        logger.info(
            "agent_create_spreadsheet_from_data: '%s' created for agent %s (%d rows)",
            title,
            agent_name,
            len(rows),
        )
        return result
    except Exception as exc:
        logger.error(
            "agent_create_spreadsheet_from_data failed for account %s, agent %s: %s",
            account_id,
            agent_name,
            exc,
        )
        raise


# ---------------------------------------------------------------------------
# Backup Operations (system-level OAuth, no account_id)
# Migrated from backup_manager/gdrive_service.py
# ---------------------------------------------------------------------------

BACKUP_SCOPES = ["https://www.googleapis.com/auth/drive.file"]
BACKUP_FOLDER_NAME = "ARCHIE-Backups"
BACKUP_TOKEN_PATH = os.environ.get("GDRIVE_TOKEN_PATH", "/app/credentials/gdrive-oauth-token.json")
BACKUP_CLIENT_SECRETS_PATH = os.environ.get("GDRIVE_CLIENT_SECRETS_PATH", "/app/credentials/gdrive-client-secrets.json")


def _load_backup_credentials():
    """Load OAuth credentials from saved token, refreshing if expired."""
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials

    if not os.path.exists(BACKUP_TOKEN_PATH):
        return None

    creds = Credentials.from_authorized_user_file(BACKUP_TOKEN_PATH, BACKUP_SCOPES)

    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
        with open(BACKUP_TOKEN_PATH, "w") as f:
            f.write(creds.to_json())

    if creds and creds.valid:
        return creds

    return None


def backup_get_oauth_flow():
    """
    Create an OAuth flow for initial backup authorization.

    Returns:
        google_auth_oauthlib.flow.Flow instance

    Raises:
        FileNotFoundError: If client secrets file is missing.
    """
    from google_auth_oauthlib.flow import Flow

    if not os.path.exists(BACKUP_CLIENT_SECRETS_PATH):
        raise FileNotFoundError(
            f"OAuth client secrets not found at {BACKUP_CLIENT_SECRETS_PATH}. "
            "Create OAuth credentials in Google Cloud Console -> APIs & Services -> Credentials, "
            "download the JSON, and place it there."
        )

    flow = Flow.from_client_secrets_file(BACKUP_CLIENT_SECRETS_PATH, scopes=BACKUP_SCOPES)
    return flow


def backup_save_oauth_token(creds):
    """Save OAuth credentials to disk."""
    os.makedirs(os.path.dirname(BACKUP_TOKEN_PATH), exist_ok=True)
    with open(BACKUP_TOKEN_PATH, "w") as f:
        f.write(creds.to_json())


def backup_is_oauth_configured() -> bool:
    """Check if OAuth token exists and is usable."""
    return _load_backup_credentials() is not None


def backup_get_drive_service(service_account_path: str = None):
    """
    Build an authenticated Google Drive API v3 client for backups.

    Credential source priority:
      1. Work Suite user OAuth (get_google_client) — unified with Gmail/Calendar;
         one reconnect covers both systems. Uses the first google_accounts row
         with `scopes` containing 'drive'. This is the preferred path.
      2. Dedicated backup OAuth token file — legacy per-service install flow.
      3. Service account JSON — blocked by Google policy for personal Drive
         (quota=0) but still works for Workspace Shared Drives.

    Returns:
        Google Drive API service resource
    """
    from googleapiclient.discovery import build

    # (1) Borrow Work Suite credentials if available.
    try:
        from database import get_db_cursor

        with get_db_cursor() as (_, cur):
            cur.execute(
                "SELECT id FROM google_accounts "
                "WHERE (scopes IS NULL OR scopes ILIKE %s) AND refresh_token IS NOT NULL "
                "ORDER BY is_primary DESC, id ASC LIMIT 1",
                ("%drive%",),
            )
            row = cur.fetchone()
        if row:
            account_id = row["id"]
            from .google_api_service import get_google_client

            return get_google_client(account_id, "drive", "v3")
    except Exception as e:
        logger.warning("Work Suite Drive creds unavailable, falling through: %s", e)

    # (2) Legacy backup-dedicated OAuth token file.
    creds = _load_backup_credentials()
    if creds:
        return build("drive", "v3", credentials=creds)

    # (3) Service account — works only for Workspace Shared Drives.
    if not service_account_path:
        service_account_path = os.environ.get(
            "GDRIVE_SERVICE_ACCOUNT_PATH",
            "/app/credentials/gdrive-service-account.json",
        )
    if os.path.exists(service_account_path):
        from google.oauth2 import service_account as sa

        credentials = sa.Credentials.from_service_account_file(service_account_path, scopes=BACKUP_SCOPES)
        return build("drive", "v3", credentials=credentials)

    raise RuntimeError(
        "No Google Drive credentials configured. Connect via "
        "/tools/google-work-suite (preferred — one auth for Gmail + Calendar + Drive) "
        "or Backup Manager -> Cloud Backup -> Connect Google Drive."
    )


def backup_test_connection(service) -> dict:
    """Test that the backup account can access Drive."""
    try:
        about = service.about().get(fields="user,storageQuota").execute()
        return {
            "success": True,
            "email": about.get("user", {}).get("emailAddress", "unknown"),
            "storage": about.get("storageQuota", {}),
            "auth_type": "oauth" if backup_is_oauth_configured() else "service_account",
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


def backup_get_storage_quota(service) -> dict:
    """Get Drive storage usage information for backups."""
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


def backup_ensure_folder(service, folder_id: str = None) -> str:
    """
    Find or create the ARCHIE-Backups folder on Drive.

    Args:
        folder_id: If provided, verify this folder exists. Otherwise search/create.

    Returns:
        Folder ID string
    """
    if folder_id:
        try:
            folder = service.files().get(fileId=folder_id, fields="id,name,trashed").execute()
            if not folder.get("trashed"):
                return folder["id"]
        except Exception:
            pass

    query = f"name='{BACKUP_FOLDER_NAME}' and " "mimeType='application/vnd.google-apps.folder' and " "trashed=false"
    results = service.files().list(q=query, fields="files(id,name)", pageSize=1).execute()
    files = results.get("files", [])

    if files:
        return files[0]["id"]

    folder_metadata = {
        "name": BACKUP_FOLDER_NAME,
        "mimeType": "application/vnd.google-apps.folder",
    }
    folder = service.files().create(body=folder_metadata, fields="id").execute()
    return folder["id"]


def backup_upload_file(service, file_path: str, folder_id: str, filename: str = None, on_progress=None) -> dict:
    """
    Upload a backup file to Google Drive with resumable upload.

    Args:
        service: Drive API service
        file_path: Local path to file
        folder_id: Drive folder ID to upload into
        filename: Override filename (defaults to basename)
        on_progress: Optional callback(bytes_sent, total_bytes)

    Returns:
        dict with file id, name, size, webViewLink

    Raises:
        RuntimeError: Clean, single-line error message suitable for backup_log.
                      Never propagates raw googleapiclient tracebacks.
    """
    from googleapiclient.http import MediaFileUpload

    if not filename:
        filename = os.path.basename(file_path)

    file_metadata = {"name": filename, "parents": [folder_id]}
    file_size = os.path.getsize(file_path)

    media = MediaFileUpload(
        file_path,
        mimetype="application/octet-stream",
        resumable=True,
        chunksize=5 * 1024 * 1024,
    )

    request = service.files().create(
        body=file_metadata,
        media_body=media,
        fields="id,name,size,webViewLink,createdTime",
    )

    response = None
    bytes_sent = 0
    try:
        while response is None:
            status, response = request.next_chunk()
            if status:
                bytes_sent = int(status.resumable_progress)
                if on_progress:
                    on_progress(bytes_sent, file_size)
    except Exception as exc:
        # Translate any googleapiclient / httplib2 error into a clean one-liner
        # so backup_log.error_message is human-readable rather than a raw traceback.
        exc_type = type(exc).__name__
        detail = str(exc).split("\n")[0][:200]
        sent_mb = bytes_sent // (1024 * 1024)
        total_mb = file_size // (1024 * 1024)
        raise RuntimeError(f"GDrive upload failed after {sent_mb}/{total_mb} MB — {exc_type}: {detail}") from exc

    return {
        "id": response["id"],
        "name": response["name"],
        "size": int(response.get("size", 0)),
        "web_link": response.get("webViewLink", ""),
        "created_time": response.get("createdTime", ""),
    }


def backup_list_backup_files(service, folder_id: str) -> list[dict]:
    """List every non-trashed file in the backup folder: [{id, name, size}].

    Used by the Drive-tier retention pruner (scripts/backup/retention_prune.py),
    which needs the full inventory to apply the GFS ladder. Paginated so it does
    not truncate at the default page size.
    """
    out: list[dict] = []
    token = None
    while True:
        resp = (
            service.files()
            .list(
                q=f"'{folder_id}' in parents and trashed=false",
                fields="nextPageToken, files(id, name, size)",
                pageSize=1000,
                pageToken=token,
            )
            .execute()
        )
        out.extend(resp.get("files", []))
        token = resp.get("nextPageToken")
        if not token:
            break
    return out


def backup_download_file(service, file_id: str, output_path: str, on_progress=None) -> str:
    """
    Download a backup file from Google Drive.

    Args:
        service: Drive API service
        file_id: Drive file ID
        output_path: Local path to save file
        on_progress: Optional callback(bytes_downloaded, total_bytes)

    Returns:
        Path to downloaded file
    """
    from googleapiclient.http import MediaIoBaseDownload

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


def backup_list_files(service, folder_id: str) -> list:
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


def backup_delete_file(service, file_id: str) -> bool:
    """Permanently delete a Drive file (bypasses Trash) to reclaim quota.

    The gdrive tier is a quota-bound account (15 GB free tier): trashing does NOT
    free quota — Google counts trashed files for ~30 days — so retention must
    hard-delete to keep the tier bounded, matching how the primary/usb tiers prune
    with rmtree. prune_gdrive only ever passes ids of recognised backup artifacts
    (component in RETENTION, parseable run-dir timestamp), never arbitrary files.
    (An identical shadowed definition carried this docstring until the #F811 pass —
    this, the surviving definition, is the one every import has always received.)
    """
    service.files().delete(fileId=file_id).execute()
    return True
