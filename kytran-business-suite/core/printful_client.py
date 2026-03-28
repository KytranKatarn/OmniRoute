"""Printful API client for product sync, order submission, and fulfillment tracking."""

import logging
import os
from typing import Optional

import requests

logger = logging.getLogger(__name__)

PRINTFUL_API_BASE = "https://api.printful.com"


class PrintfulClient:
    """Client for the Printful REST API.

    Usage:
        client = PrintfulClient(api_key="your_key")
        products = client.get_catalog_products()
    """

    def __init__(self, api_key: str = None):
        self.api_key = api_key or os.getenv("KBS_PRINTFUL_API_KEY", "")
        self._session = requests.Session()
        self._session.headers.update(
            {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            }
        )

    def _get(self, path: str, params: dict = None) -> dict:
        """Perform a GET request to the Printful API."""
        url = f"{PRINTFUL_API_BASE}{path}"
        resp = requests.get(url, headers=self._session.headers, params=params)
        resp.raise_for_status()
        return resp.json().get("result", resp.json())

    def _post(self, path: str, data: dict = None) -> dict:
        """Perform a POST request to the Printful API."""
        url = f"{PRINTFUL_API_BASE}{path}"
        resp = requests.post(url, headers=self._session.headers, json=data)
        resp.raise_for_status()
        return resp.json().get("result", resp.json())

    # ------------------------------------------------------------------
    # Catalog
    # ------------------------------------------------------------------

    def get_catalog_products(self) -> list:
        """Fetch all available Printful catalog products."""
        return self._get("/products")

    def get_catalog_product(self, product_id: int) -> dict:
        """Fetch a single Printful catalog product with variants."""
        return self._get(f"/products/{product_id}")

    # ------------------------------------------------------------------
    # Sync Products (store-linked products)
    # ------------------------------------------------------------------

    def get_sync_products(self) -> list:
        """Fetch all synced products from the Printful store."""
        return self._get("/store/products")

    def get_sync_product(self, sync_product_id: int) -> dict:
        """Fetch a single synced product with its variants."""
        return self._get(f"/store/products/{sync_product_id}")

    # ------------------------------------------------------------------
    # Orders
    # ------------------------------------------------------------------

    def create_order(self, order_data: dict, confirm: bool = False) -> dict:
        """Submit an order to Printful.

        Args:
            order_data: Dict with 'recipient' and 'items' keys.
            confirm: If True, immediately confirm (charge and produce). Default draft.

        Returns:
            Printful order object with id, status, etc.
        """
        params_path = "/orders"
        if confirm:
            params_path += "?confirm=true"
        return self._post(params_path, data=order_data)

    def get_order(self, order_id: int) -> dict:
        """Fetch a Printful order by ID."""
        return self._get(f"/orders/{order_id}")

    def get_order_by_external_id(self, external_id: str) -> dict:
        """Fetch a Printful order by external (KBS) order ID."""
        return self._get(f"/orders/@{external_id}")

    def cancel_order(self, order_id: int) -> dict:
        """Cancel a Printful order (only if still in draft/pending)."""
        url = f"{PRINTFUL_API_BASE}/orders/{order_id}"
        resp = requests.delete(url, headers=self._session.headers)
        resp.raise_for_status()
        return resp.json().get("result", {})

    # ------------------------------------------------------------------
    # Shipping
    # ------------------------------------------------------------------

    def estimate_shipping(self, recipient: dict, items: list) -> list:
        """Get shipping rate estimates for an order.

        Args:
            recipient: Dict with address fields.
            items: List of item dicts with variant_id and quantity.

        Returns:
            List of shipping rate options.
        """
        return self._post(
            "/shipping/rates",
            data={"recipient": recipient, "items": items},
        )

    # ------------------------------------------------------------------
    # Webhooks (setup)
    # ------------------------------------------------------------------

    def get_webhooks(self) -> dict:
        """Get configured webhook settings."""
        return self._get("/webhooks")

    def set_webhook(self, url: str, types: list = None) -> dict:
        """Configure Printful webhook endpoint.

        Args:
            url: The URL Printful will POST events to.
            types: List of event types to receive. Default: all.
        """
        data = {"url": url}
        if types:
            data["types"] = types
        return self._post("/webhooks", data=data)


def get_printful_client() -> Optional[PrintfulClient]:
    """Factory function that returns a PrintfulClient if API key is configured.

    Returns None if KBS_PRINTFUL_API_KEY is not set.
    """
    api_key = os.getenv("KBS_PRINTFUL_API_KEY", "")
    if not api_key:
        logger.warning("KBS_PRINTFUL_API_KEY not set — Printful integration disabled")
        return None
    return PrintfulClient(api_key=api_key)
