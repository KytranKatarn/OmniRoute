"""
Social Media OAuth Handler
==========================
OAuth 2.0 flows for Instagram and TikTok.

Handles:
- Authorization URL generation
- Code exchange for tokens
- Token refresh
- Token revocation
- Account disconnection

Author: A.R.C.H.I.E. Platform
Date: 2026-01-17
"""

import os
import secrets
import logging
import requests
from datetime import datetime, timedelta
from typing import Dict, Optional, Tuple
from urllib.parse import urlencode

import psycopg2
from psycopg2.extras import RealDictCursor

from .encryption import encrypt_token, decrypt_token

logger = logging.getLogger(__name__)


def get_db_connection():
    """Get database connection."""
    return psycopg2.connect(
        host=os.getenv('DB_HOST', 'archie_database'),
        port=os.getenv('DB_PORT', '5432'),
        database=os.getenv('DB_NAME', 'archie'),
        user=os.getenv('DB_USER', 'archie'),
        password=os.getenv('DB_PASSWORD', '')
    )


# =============================================================================
# PLATFORM CONFIGURATION
# =============================================================================

def get_platform_config(platform: str) -> Optional[Dict]:
    """
    Get platform OAuth configuration from database.

    Args:
        platform: Platform name (instagram, tiktok, etc.)

    Returns:
        Platform config dict or None
    """
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    try:
        cur.execute("""
            SELECT * FROM social_platform_config
            WHERE platform = %s AND enabled = TRUE
        """, (platform,))
        config = cur.fetchone()
        return dict(config) if config else None
    finally:
        cur.close()
        conn.close()


def get_env_credentials(platform: str) -> Dict:
    """
    Get OAuth credentials from environment variables.

    Checks for:
    - {PLATFORM}_APP_ID or {PLATFORM}_CLIENT_ID
    - {PLATFORM}_APP_SECRET or {PLATFORM}_CLIENT_SECRET
    - {PLATFORM}_REDIRECT_URI

    Args:
        platform: Platform name (instagram, tiktok)

    Returns:
        Dict with client_id, client_secret, redirect_uri
    """
    platform_upper = platform.upper()

    # Instagram uses APP_ID/APP_SECRET (via Facebook)
    # TikTok uses CLIENT_KEY/CLIENT_SECRET
    client_id = (
        os.getenv(f'{platform_upper}_APP_ID') or
        os.getenv(f'{platform_upper}_CLIENT_ID') or
        os.getenv(f'{platform_upper}_CLIENT_KEY')
    )

    client_secret = (
        os.getenv(f'{platform_upper}_APP_SECRET') or
        os.getenv(f'{platform_upper}_CLIENT_SECRET')
    )

    redirect_uri = os.getenv(f'{platform_upper}_REDIRECT_URI')

    return {
        'client_id': client_id,
        'client_secret': client_secret,
        'redirect_uri': redirect_uri
    }


# =============================================================================
# INSTAGRAM OAUTH (via Facebook Graph API)
# =============================================================================

class InstagramOAuth:
    """Instagram OAuth 2.0 handler via Facebook Graph API."""

    SCOPES = [
        'instagram_basic',
        'instagram_content_publish',
        'instagram_manage_insights',
        'pages_show_list',
        'pages_read_engagement',
    ]

    API_VERSION = 'v18.0'
    AUTH_URL = f'https://www.facebook.com/{API_VERSION}/dialog/oauth'
    TOKEN_URL = f'https://graph.facebook.com/{API_VERSION}/oauth/access_token'
    GRAPH_URL = f'https://graph.facebook.com/{API_VERSION}'

    def __init__(self):
        """Initialize with credentials from environment."""
        creds = get_env_credentials('instagram')
        self.client_id = creds['client_id']
        self.client_secret = creds['client_secret']
        self.redirect_uri = creds['redirect_uri']

    def is_configured(self) -> bool:
        """Check if Instagram OAuth is properly configured."""
        return all([self.client_id, self.client_secret, self.redirect_uri])

    def get_authorization_url(self, state: str = None) -> Tuple[str, str]:
        """
        Generate Instagram authorization URL.

        Args:
            state: Optional CSRF state token (generated if not provided)

        Returns:
            Tuple of (authorization_url, state_token)
        """
        if not self.is_configured():
            raise ValueError("Instagram OAuth not configured. Set INSTAGRAM_APP_ID, INSTAGRAM_APP_SECRET, INSTAGRAM_REDIRECT_URI")

        state = state or secrets.token_urlsafe(32)

        params = {
            'client_id': self.client_id,
            'redirect_uri': self.redirect_uri,
            'scope': ','.join(self.SCOPES),
            'response_type': 'code',
            'state': state,
        }

        auth_url = f"{self.AUTH_URL}?{urlencode(params)}"
        return auth_url, state

    def exchange_code(self, code: str) -> Dict:
        """
        Exchange authorization code for access token.

        Args:
            code: Authorization code from callback

        Returns:
            Dict with access_token, token_type, expires_in
        """
        params = {
            'client_id': self.client_id,
            'client_secret': self.client_secret,
            'redirect_uri': self.redirect_uri,
            'code': code,
        }

        response = requests.get(self.TOKEN_URL, params=params, timeout=30)
        response.raise_for_status()

        data = response.json()

        if 'error' in data:
            raise ValueError(f"OAuth error: {data.get('error', {}).get('message', 'Unknown error')}")

        return data

    def get_long_lived_token(self, short_token: str) -> Dict:
        """
        Exchange short-lived token for long-lived token (60 days).

        Args:
            short_token: Short-lived access token

        Returns:
            Dict with access_token, token_type, expires_in
        """
        params = {
            'grant_type': 'fb_exchange_token',
            'client_id': self.client_id,
            'client_secret': self.client_secret,
            'fb_exchange_token': short_token,
        }

        response = requests.get(self.TOKEN_URL, params=params, timeout=30)
        response.raise_for_status()

        return response.json()

    def refresh_token(self, access_token: str) -> Dict:
        """
        Refresh a long-lived token (extends expiration).

        Note: Instagram tokens can only be refreshed if they're at least
        24 hours old and less than 60 days old.

        Args:
            access_token: Current long-lived token

        Returns:
            Dict with new access_token and expires_in
        """
        params = {
            'grant_type': 'ig_refresh_token',
            'access_token': access_token,
        }

        response = requests.get(f"{self.GRAPH_URL}/refresh_access_token", params=params, timeout=30)
        response.raise_for_status()

        return response.json()

    def get_user_profile(self, access_token: str) -> Dict:
        """
        Get the user's Instagram account info.

        Returns the Instagram Business Account or Creator Account.

        Args:
            access_token: Valid access token

        Returns:
            Dict with id, username, profile_picture_url, followers_count, etc.
        """
        # First, get Facebook pages connected to the user
        pages_response = requests.get(
            f"{self.GRAPH_URL}/me/accounts",
            params={'access_token': access_token},
            timeout=30
        )
        pages_response.raise_for_status()
        pages_data = pages_response.json()

        if not pages_data.get('data'):
            raise ValueError("No Facebook Pages found. Instagram Business/Creator account requires a connected Page.")

        # Get Instagram account connected to the first page
        page = pages_data['data'][0]
        page_id = page['id']
        page_token = page.get('access_token', access_token)

        ig_response = requests.get(
            f"{self.GRAPH_URL}/{page_id}",
            params={
                'fields': 'instagram_business_account{id,username,profile_picture_url,followers_count,media_count}',
                'access_token': page_token,
            },
            timeout=30
        )
        ig_response.raise_for_status()
        ig_data = ig_response.json()

        ig_account = ig_data.get('instagram_business_account')
        if not ig_account:
            raise ValueError("No Instagram Business/Creator account found on this Page.")

        return {
            'platform_user_id': ig_account.get('id'),
            'username': ig_account.get('username'),
            'profile_picture_url': ig_account.get('profile_picture_url'),
            'followers_count': ig_account.get('followers_count', 0),
            'media_count': ig_account.get('media_count', 0),
            'page_id': page_id,
            'page_token': page_token,
        }


# =============================================================================
# TIKTOK OAUTH
# =============================================================================

class TikTokOAuth:
    """TikTok OAuth 2.0 handler via TikTok Content API."""

    SCOPES = [
        'user.info.basic',
        'video.publish',
        'video.list',
    ]

    AUTH_URL = 'https://www.tiktok.com/v2/auth/authorize/'
    TOKEN_URL = 'https://open.tiktokapis.com/v2/oauth/token/'
    API_URL = 'https://open.tiktokapis.com/v2'

    def __init__(self):
        """Initialize with credentials from environment."""
        creds = get_env_credentials('tiktok')
        self.client_key = creds['client_id']  # TikTok calls it client_key
        self.client_secret = creds['client_secret']
        self.redirect_uri = creds['redirect_uri']

    def is_configured(self) -> bool:
        """Check if TikTok OAuth is properly configured."""
        return all([self.client_key, self.client_secret, self.redirect_uri])

    def get_authorization_url(self, state: str = None) -> Tuple[str, str]:
        """
        Generate TikTok authorization URL.

        Args:
            state: Optional CSRF state token (generated if not provided)

        Returns:
            Tuple of (authorization_url, state_token)
        """
        if not self.is_configured():
            raise ValueError("TikTok OAuth not configured. Set TIKTOK_CLIENT_KEY, TIKTOK_CLIENT_SECRET, TIKTOK_REDIRECT_URI")

        state = state or secrets.token_urlsafe(32)

        params = {
            'client_key': self.client_key,
            'scope': ','.join(self.SCOPES),
            'response_type': 'code',
            'redirect_uri': self.redirect_uri,
            'state': state,
        }

        auth_url = f"{self.AUTH_URL}?{urlencode(params)}"
        return auth_url, state

    def exchange_code(self, code: str) -> Dict:
        """
        Exchange authorization code for tokens.

        Args:
            code: Authorization code from callback

        Returns:
            Dict with access_token, refresh_token, expires_in, open_id
        """
        data = {
            'client_key': self.client_key,
            'client_secret': self.client_secret,
            'code': code,
            'grant_type': 'authorization_code',
            'redirect_uri': self.redirect_uri,
        }

        response = requests.post(
            self.TOKEN_URL,
            data=data,
            headers={'Content-Type': 'application/x-www-form-urlencoded'},
            timeout=30
        )
        response.raise_for_status()

        result = response.json()

        if result.get('error'):
            raise ValueError(f"TikTok OAuth error: {result.get('error_description', result.get('error'))}")

        return result

    def refresh_token(self, refresh_token: str) -> Dict:
        """
        Refresh access token using refresh token.

        Args:
            refresh_token: The refresh token

        Returns:
            Dict with new access_token, refresh_token, expires_in
        """
        data = {
            'client_key': self.client_key,
            'client_secret': self.client_secret,
            'grant_type': 'refresh_token',
            'refresh_token': refresh_token,
        }

        response = requests.post(
            self.TOKEN_URL,
            data=data,
            headers={'Content-Type': 'application/x-www-form-urlencoded'},
            timeout=30
        )
        response.raise_for_status()

        return response.json()

    def get_user_profile(self, access_token: str) -> Dict:
        """
        Get TikTok user profile.

        Args:
            access_token: Valid access token

        Returns:
            Dict with open_id, display_name, avatar_url, etc.
        """
        response = requests.get(
            f"{self.API_URL}/user/info/",
            params={'fields': 'open_id,union_id,avatar_url,display_name,follower_count,following_count,likes_count'},
            headers={'Authorization': f'Bearer {access_token}'},
            timeout=30
        )
        response.raise_for_status()

        result = response.json()
        user_data = result.get('data', {}).get('user', {})

        return {
            'platform_user_id': user_data.get('open_id'),
            'username': user_data.get('display_name'),
            'profile_picture_url': user_data.get('avatar_url'),
            'followers_count': user_data.get('follower_count', 0),
        }


# =============================================================================
# TOKEN MANAGEMENT
# =============================================================================

def store_oauth_token(
    account_id: int,
    platform: str,
    access_token: str,
    refresh_token: str = None,
    expires_in: int = None,
    scopes: list = None
) -> int:
    """
    Store encrypted OAuth tokens in database.

    Args:
        account_id: Social account ID
        platform: Platform name
        access_token: Access token to encrypt and store
        refresh_token: Optional refresh token
        expires_in: Token lifetime in seconds
        scopes: List of granted scopes

    Returns:
        Token record ID
    """
    conn = get_db_connection()
    cur = conn.cursor()

    try:
        # Calculate expiration time
        expires_at = None
        if expires_in:
            expires_at = datetime.now() + timedelta(seconds=expires_in)

        # Encrypt tokens
        access_encrypted = encrypt_token(access_token)
        refresh_encrypted = encrypt_token(refresh_token) if refresh_token else None

        # Upsert token record
        cur.execute("""
            INSERT INTO social_oauth_tokens (
                account_id, platform, access_token_encrypted, refresh_token_encrypted,
                expires_at, scopes, updated_at
            ) VALUES (%s, %s, %s, %s, %s, %s, NOW())
            ON CONFLICT (account_id) DO UPDATE SET
                access_token_encrypted = EXCLUDED.access_token_encrypted,
                refresh_token_encrypted = EXCLUDED.refresh_token_encrypted,
                expires_at = EXCLUDED.expires_at,
                scopes = EXCLUDED.scopes,
                updated_at = NOW()
            RETURNING id
        """, (
            account_id, platform, access_encrypted, refresh_encrypted,
            expires_at, scopes
        ))

        token_id = cur.fetchone()[0]
        conn.commit()

        logger.info(f"Stored OAuth token for account {account_id} ({platform})")
        return token_id

    finally:
        cur.close()
        conn.close()


def get_oauth_token(account_id: int) -> Optional[Dict]:
    """
    Retrieve and decrypt OAuth tokens for an account.

    Args:
        account_id: Social account ID

    Returns:
        Dict with access_token, refresh_token, expires_at, scopes
        or None if not found
    """
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    try:
        cur.execute("""
            SELECT * FROM social_oauth_tokens
            WHERE account_id = %s
        """, (account_id,))

        record = cur.fetchone()
        if not record:
            return None

        return {
            'id': record['id'],
            'account_id': record['account_id'],
            'platform': record['platform'],
            'access_token': decrypt_token(record['access_token_encrypted']),
            'refresh_token': decrypt_token(record['refresh_token_encrypted']) if record['refresh_token_encrypted'] else None,
            'expires_at': record['expires_at'],
            'scopes': record['scopes'],
            'is_expired': record['expires_at'] and record['expires_at'] < datetime.now(),
            'expires_soon': record['expires_at'] and record['expires_at'] < datetime.now() + timedelta(days=7),
        }

    finally:
        cur.close()
        conn.close()


def delete_oauth_token(account_id: int) -> bool:
    """
    Delete OAuth tokens for an account.

    Args:
        account_id: Social account ID

    Returns:
        True if deleted, False if not found
    """
    conn = get_db_connection()
    cur = conn.cursor()

    try:
        cur.execute("""
            DELETE FROM social_oauth_tokens
            WHERE account_id = %s
            RETURNING id
        """, (account_id,))

        deleted = cur.fetchone() is not None
        conn.commit()

        if deleted:
            logger.info(f"Deleted OAuth token for account {account_id}")

        return deleted

    finally:
        cur.close()
        conn.close()


def get_expiring_tokens(days: int = 7) -> list:
    """
    Get tokens expiring within specified days.

    Args:
        days: Number of days to check

    Returns:
        List of token records with account info
    """
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    try:
        cur.execute("""
            SELECT t.*, a.platform_username, a.account_name
            FROM social_oauth_tokens t
            JOIN social_accounts a ON t.account_id = a.id
            WHERE t.expires_at IS NOT NULL
            AND t.expires_at < NOW() + INTERVAL '%s days'
            AND t.expires_at > NOW()
            ORDER BY t.expires_at
        """, (days,))

        return cur.fetchall()

    finally:
        cur.close()
        conn.close()


# =============================================================================
# JOB LOGGING
# =============================================================================

def log_oauth_job(
    job_type: str,
    status: str,
    account_id: int = None,
    error_message: str = None,
    platform_response: dict = None,
    duration_ms: int = None
) -> int:
    """
    Log an OAuth-related job execution.

    Args:
        job_type: 'authorize', 'refresh_token', 'revoke'
        status: 'started', 'success', 'failed'
        account_id: Related account ID
        error_message: Error details if failed
        platform_response: Raw API response
        duration_ms: Execution time

    Returns:
        Log record ID
    """
    conn = get_db_connection()
    cur = conn.cursor()

    try:
        cur.execute("""
            INSERT INTO social_job_logs (
                job_type, status, account_id, error_message,
                platform_response, duration_ms
            ) VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING id
        """, (
            job_type, status, account_id, error_message,
            psycopg2.extras.Json(platform_response) if platform_response else None,
            duration_ms
        ))

        log_id = cur.fetchone()[0]
        conn.commit()
        return log_id

    finally:
        cur.close()
        conn.close()
