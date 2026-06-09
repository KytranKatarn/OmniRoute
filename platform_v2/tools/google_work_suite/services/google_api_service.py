"""
Google API Service — OAuth flow, token encryption, account management.
"""

import logging
import os
import secrets

from cryptography.fernet import Fernet

from database import get_db_cursor

logger = logging.getLogger(__name__)

SCOPES = [
    "openid",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/userinfo.profile",
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/drive",
]

FERNET_KEY = os.environ.get("GOOGLE_TOKEN_ENCRYPTION_KEY")
_fernet = None


def _get_fernet():
    global _fernet
    if _fernet is None:
        if not FERNET_KEY:
            raise RuntimeError("GOOGLE_TOKEN_ENCRYPTION_KEY must be set in .env for Google Work Suite")
        _fernet = Fernet(FERNET_KEY.encode() if isinstance(FERNET_KEY, str) else FERNET_KEY)
    return _fernet


def _encrypt(text):
    if not text:
        return None
    return _get_fernet().encrypt(text.encode()).decode()


def _decrypt(text):
    if not text:
        return None
    return _get_fernet().decrypt(text.encode()).decode()


def _build_client_config(client_id, client_secret, redirect_uri):
    return {
        "web": {
            "client_id": client_id,
            "client_secret": client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": [redirect_uri],
        }
    }


def get_auth_url(owner_type, owner_id):
    """Generate Google OAuth authorization URL with CSRF state token."""
    from google_auth_oauthlib.flow import Flow

    client_id = os.environ.get("GOOGLE_CLIENT_ID")
    client_secret = os.environ.get("GOOGLE_CLIENT_SECRET")
    redirect_uri = os.environ.get("GOOGLE_REDIRECT_URI")

    if not all([client_id, client_secret, redirect_uri]):
        raise RuntimeError("GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, and GOOGLE_REDIRECT_URI must be set in .env")

    client_config = _build_client_config(client_id, client_secret, redirect_uri)
    flow = Flow.from_client_config(client_config, scopes=SCOPES, redirect_uri=redirect_uri)

    state = f"{owner_type}:{owner_id}:{secrets.token_hex(16)}"
    auth_url, _ = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        state=state,
        prompt="consent",
    )
    # Return code_verifier so caller can store it in session for callback
    return auth_url, state, flow.code_verifier


def handle_callback(code, state, code_verifier=None):
    """Exchange OAuth code for tokens, store encrypted in DB."""
    from google_auth_oauthlib.flow import Flow
    from googleapiclient.discovery import build

    parts = state.split(":", 2)
    if len(parts) != 3:
        raise ValueError("Invalid OAuth state parameter")
    owner_type, owner_id, _nonce = parts

    client_id = os.environ.get("GOOGLE_CLIENT_ID")
    client_secret = os.environ.get("GOOGLE_CLIENT_SECRET")
    redirect_uri = os.environ.get("GOOGLE_REDIRECT_URI")

    client_config = _build_client_config(client_id, client_secret, redirect_uri)
    flow = Flow.from_client_config(client_config, scopes=SCOPES, redirect_uri=redirect_uri, state=state)
    if code_verifier:
        flow.code_verifier = code_verifier
    flow.fetch_token(code=code)
    creds = flow.credentials

    # Resolve connected email address
    gmail_service = build("gmail", "v1", credentials=creds)
    profile = gmail_service.users().getProfile(userId="me").execute()
    email = profile["emailAddress"]

    permission_level = "full" if owner_type == "agent" else "draft_only"

    encrypted_access = _encrypt(creds.token)
    encrypted_refresh = _encrypt(creds.refresh_token)

    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            """
            INSERT INTO google_accounts
                (owner_type, owner_id, email, access_token, refresh_token,
                 token_expiry, scopes, permission_level)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (email) DO UPDATE SET
                owner_type      = EXCLUDED.owner_type,
                owner_id        = EXCLUDED.owner_id,
                access_token    = EXCLUDED.access_token,
                refresh_token   = EXCLUDED.refresh_token,
                token_expiry    = EXCLUDED.token_expiry,
                scopes          = EXCLUDED.scopes,
                permission_level= EXCLUDED.permission_level,
                updated_at      = NOW()
            RETURNING id
            """,
            (
                owner_type,
                owner_id,
                email,
                encrypted_access,
                encrypted_refresh,
                creds.expiry,
                ",".join(creds.scopes or SCOPES),
                permission_level,
            ),
        )
        row = cur.fetchone()
        account_id = row["id"] if isinstance(row, dict) else row[0]

    logger.info("Google account connected: %s (owner=%s:%s)", email, owner_type, owner_id)
    return {"success": True, "account_id": account_id, "email": email}


def get_google_client(account_id, api_name, api_version):
    """Return an authenticated Google API client for any service, refreshing token if needed."""
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build

    with get_db_cursor() as (conn, cur):
        cur.execute(
            "SELECT access_token, refresh_token, token_expiry " "FROM google_accounts WHERE id = %s",
            (account_id,),
        )
        row = cur.fetchone()

    if not row:
        raise ValueError(f"Google account {account_id} not found")

    access_token = _decrypt(row["access_token"])
    refresh_tok = _decrypt(row["refresh_token"])
    expiry = row["token_expiry"]
    client_id = os.environ.get("GOOGLE_CLIENT_ID")
    client_secret = os.environ.get("GOOGLE_CLIENT_SECRET")

    creds = Credentials(
        token=access_token,
        refresh_token=refresh_tok,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=client_id,
        client_secret=client_secret,
        scopes=SCOPES,
    )
    # Manually set expiry so the library knows whether to refresh
    if expiry:
        creds.expiry = expiry

    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        new_encrypted = _encrypt(creds.token)
        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                "UPDATE google_accounts SET access_token=%s, token_expiry=%s, updated_at=NOW() WHERE id=%s",
                (new_encrypted, creds.expiry, account_id),
            )

    return build(api_name, api_version, credentials=creds)


def get_gmail_client(account_id):
    """Return an authenticated Gmail API client, refreshing token if needed."""
    return get_google_client(account_id, "gmail", "v1")


def refresh_token(account_id):
    """Force-refresh the access token for an account."""
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials

    with get_db_cursor() as (conn, cur):
        cur.execute(
            "SELECT access_token, refresh_token, token_expiry " "FROM google_accounts WHERE id = %s",
            (account_id,),
        )
        row = cur.fetchone()

    if not row:
        raise ValueError(f"Google account {account_id} not found")

    access_token = _decrypt(row["access_token"])
    refresh_tok = _decrypt(row["refresh_token"])
    client_id = os.environ.get("GOOGLE_CLIENT_ID")
    client_secret = os.environ.get("GOOGLE_CLIENT_SECRET")

    creds = Credentials(
        token=access_token,
        refresh_token=refresh_tok,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=client_id,
        client_secret=client_secret,
        scopes=SCOPES,
    )
    creds.refresh(Request())

    new_encrypted = _encrypt(creds.token)
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            "UPDATE google_accounts SET access_token=%s, token_expiry=%s, updated_at=NOW() WHERE id=%s",
            (new_encrypted, creds.expiry, account_id),
        )
    logger.info("Refreshed token for account %s", account_id)


def list_accounts(owner_type=None, owner_id=None):
    """Return google_accounts rows without tokens."""
    with get_db_cursor() as (conn, cur):
        query = (
            "SELECT id, owner_type, owner_id, email, permission_level, scopes, "
            "last_sync_at, created_at, updated_at FROM google_accounts WHERE 1=1"
        )
        params = []
        if owner_type:
            query += " AND owner_type = %s"
            params.append(owner_type)
        if owner_id:
            query += " AND owner_id = %s"
            params.append(owner_id)
        query += " ORDER BY created_at DESC"
        cur.execute(query, params)
        return [dict(row) for row in cur.fetchall()]


def get_account(account_id):
    """Single account lookup — no tokens returned."""
    with get_db_cursor() as (conn, cur):
        cur.execute(
            "SELECT id, owner_type, owner_id, email, permission_level, scopes, "
            "last_sync_at, created_at, updated_at FROM google_accounts WHERE id = %s",
            (account_id,),
        )
        row = cur.fetchone()
        if not row:
            return None
        return dict(row)


def disconnect_account(account_id, owner_type, owner_id):
    """Verify ownership then permanently remove account credentials."""
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            "DELETE FROM google_accounts WHERE id=%s AND owner_type=%s AND owner_id=%s RETURNING id",
            (account_id, owner_type, owner_id),
        )
        deleted = cur.fetchone()
    if not deleted:
        raise PermissionError(f"Account {account_id} not found or does not belong to {owner_type}:{owner_id}")
    logger.info("Disconnected Google account %s (owner=%s:%s)", account_id, owner_type, owner_id)
    return {"success": True}
