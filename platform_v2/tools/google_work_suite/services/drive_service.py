"""
Google Drive Service — file management, document/spreadsheet creation, sharing, and agent automation.
"""

import logging

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
    from datetime import datetime, timedelta  # noqa: PLC0415

    yesterday = datetime.utcnow() - timedelta(hours=24)

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
    date_str = datetime.utcnow().strftime("%Y-%m-%d")
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
