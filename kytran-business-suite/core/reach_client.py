"""Hostinger Reach email marketing API client.

Provides contact management, segment operations, and campaign sending
through the Hostinger Reach REST API.

Usage:
    from core.reach_client import ReachClient
    client = ReachClient(api_url="https://api.hostinger.com/reach/v1", api_key="key")
    contacts = client.list_contacts()
"""

import logging

import requests

logger = logging.getLogger(__name__)


class ReachClient:
    """Client for the Hostinger Reach email marketing API.

    Args:
        api_url: Base URL for the Reach API.
        api_key: API key for authentication.
    """

    def __init__(self, api_url, api_key):
        self.api_url = api_url.rstrip("/")
        self.api_key = api_key

    def _headers(self):
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def _get(self, path, params=None):
        resp = requests.get(
            f"{self.api_url}{path}",
            headers=self._headers(),
            params=params,
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()

    def _post(self, path, data=None):
        resp = requests.post(
            f"{self.api_url}{path}",
            headers=self._headers(),
            json=data,
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()

    def _delete(self, path):
        resp = requests.delete(
            f"{self.api_url}{path}",
            headers=self._headers(),
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json() if resp.content else {}

    # ------------------------------------------------------------------
    # Contacts
    # ------------------------------------------------------------------

    def list_contacts(self, page=1, per_page=50):
        """List contacts from the Reach account.

        Args:
            page: Page number.
            per_page: Items per page.

        Returns:
            Dict with contacts list and pagination info.
        """
        return self._get("/contacts", params={"page": page, "per_page": per_page})

    def create_contact(self, email, name=None, fields=None):
        """Create a new contact.

        Args:
            email: Contact email address.
            name: Optional contact name.
            fields: Optional dict of custom fields.

        Returns:
            Dict with created contact data.
        """
        data = {"email": email}
        if name:
            data["name"] = name
        if fields:
            data["fields"] = fields
        return self._post("/contacts", data=data)

    def delete_contact(self, contact_id):
        """Delete a contact by ID.

        Args:
            contact_id: Reach contact ID.

        Returns:
            Empty dict on success.
        """
        return self._delete(f"/contacts/{contact_id}")

    # ------------------------------------------------------------------
    # Segments
    # ------------------------------------------------------------------

    def list_segments(self):
        """List contact segments.

        Returns:
            Dict with segments list.
        """
        return self._get("/segments")

    def create_segment(self, name, conditions=None):
        """Create a new contact segment.

        Args:
            name: Segment name.
            conditions: Optional filter conditions.

        Returns:
            Dict with created segment data.
        """
        data = {"name": name}
        if conditions:
            data["conditions"] = conditions
        return self._post("/segments", data=data)

    def get_segment(self, segment_id):
        """Get segment details.

        Args:
            segment_id: Reach segment ID.

        Returns:
            Dict with segment data.
        """
        return self._get(f"/segments/{segment_id}")

    # ------------------------------------------------------------------
    # Profiles (sender identities)
    # ------------------------------------------------------------------

    def list_profiles(self):
        """List sender profiles.

        Returns:
            Dict with profiles list.
        """
        return self._get("/profiles")

    # ------------------------------------------------------------------
    # Sync helpers
    # ------------------------------------------------------------------

    def sync_crm_contacts(self, contacts):
        """Sync a list of CRM contacts to Reach.

        Args:
            contacts: List of dicts with 'email' and optional 'name', 'fields'.

        Returns:
            Dict with created/updated counts.
        """
        created = 0
        errors = 0
        for contact in contacts:
            try:
                self.create_contact(
                    email=contact["email"],
                    name=contact.get("name"),
                    fields=contact.get("fields"),
                )
                created += 1
            except Exception as e:
                logger.warning("Failed to sync contact %s: %s", contact.get("email"), e)
                errors += 1

        return {"created": created, "errors": errors, "total": len(contacts)}
