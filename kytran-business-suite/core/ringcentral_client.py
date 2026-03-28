"""RingCentral API client for call log retrieval and SMS sending."""

import logging
import time

import requests

logger = logging.getLogger(__name__)


class RingCentralClient:
    """Client for the RingCentral REST API.

    Authentication uses JWT grant type. Access tokens are cached and
    refreshed automatically when expired.

    Args:
        server_url: RingCentral API base URL (e.g. https://platform.ringcentral.com).
        client_id: OAuth app client ID.
        client_secret: OAuth app client secret.
        jwt_token: JWT credential for authentication.
        account_id: Account ID (default "~" for the authenticated account).
    """

    def __init__(self, server_url, client_id, client_secret, jwt_token, account_id="~"):
        self.server_url = server_url.rstrip("/")
        self.client_id = client_id
        self.client_secret = client_secret
        self.jwt_token = jwt_token
        self.account_id = account_id
        self._access_token = None
        self._token_expires_at = 0

    def _get_access_token(self):
        """Obtain or refresh an access token using JWT grant."""
        if self._access_token and time.time() < self._token_expires_at:
            return self._access_token

        resp = requests.post(
            f"{self.server_url}/restapi/oauth/token",
            data={
                "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
                "assertion": self.jwt_token,
            },
            auth=(self.client_id, self.client_secret),
            timeout=30,
        )
        resp.raise_for_status()
        body = resp.json()
        self._access_token = body["access_token"]
        self._token_expires_at = time.time() + body.get("expires_in", 3600) - 60
        return self._access_token

    def _headers(self):
        """Return Authorization headers with a valid access token."""
        token = self._get_access_token()
        return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    def get_call_log(self, date_from, date_to, per_page=100):
        """Fetch call log records for the account.

        Args:
            date_from: ISO date string (e.g. "2026-03-27").
            date_to: ISO date string (e.g. "2026-03-28").
            per_page: Max records per request (default 100).

        Returns:
            List of call record dicts from RingCentral.
        """
        resp = requests.get(
            f"{self.server_url}/restapi/v1.0/account/{self.account_id}/call-log",
            headers=self._headers(),
            params={
                "dateFrom": f"{date_from}T00:00:00.000Z",
                "dateTo": f"{date_to}T23:59:59.999Z",
                "perPage": per_page,
                "view": "Detailed",
            },
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json().get("records", [])

    def send_sms(self, from_number, to_number, message):
        """Send an SMS message via RingCentral.

        Args:
            from_number: Sender phone number (must be a RingCentral number).
            to_number: Recipient phone number.
            message: Text message content.

        Returns:
            Dict with message ID and status from RingCentral.
        """
        resp = requests.post(
            f"{self.server_url}/restapi/v1.0/account/{self.account_id}/extension/~/sms",
            headers=self._headers(),
            json={
                "from": {"phoneNumber": from_number},
                "to": [{"phoneNumber": to_number}],
                "text": message,
            },
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()

    def get_sms_log(self, date_from, date_to, per_page=100):
        """Fetch SMS message log for the account.

        Args:
            date_from: ISO date string.
            date_to: ISO date string.
            per_page: Max records per request.

        Returns:
            List of SMS record dicts from RingCentral.
        """
        resp = requests.get(
            f"{self.server_url}/restapi/v1.0/account/{self.account_id}/extension/~/message-store",
            headers=self._headers(),
            params={
                "dateFrom": f"{date_from}T00:00:00.000Z",
                "dateTo": f"{date_to}T23:59:59.999Z",
                "messageType": "SMS",
                "perPage": per_page,
            },
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json().get("records", [])
