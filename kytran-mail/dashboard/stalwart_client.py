"""Stalwart Mail Server API client."""

import os

import requests
from requests.auth import HTTPBasicAuth

STALWART_URL = os.environ.get("STALWART_API_URL", "https://localhost:443")
ADMIN_USER = "admin"
ADMIN_PASS = os.environ.get("MAIL_ADMIN_PASSWORD", "")


def _auth():
    return HTTPBasicAuth(ADMIN_USER, ADMIN_PASS)


def _get(path, params=None):
    try:
        resp = requests.get(
            f"{STALWART_URL}{path}",
            params=params,
            auth=_auth(),
            verify=False,
            timeout=10,
        )
        resp.raise_for_status()
        return resp.json().get("data", resp.json())
    except requests.RequestException as e:
        return {"error": str(e)}


def _post(path, data):
    try:
        resp = requests.post(
            f"{STALWART_URL}{path}",
            json=data,
            auth=_auth(),
            verify=False,
            timeout=10,
        )
        resp.raise_for_status()
        return resp.json() if resp.text else {"success": True}
    except requests.RequestException as e:
        return {"error": str(e)}


def _patch(path, data):
    try:
        resp = requests.patch(
            f"{STALWART_URL}{path}",
            json=data,
            auth=_auth(),
            verify=False,
            timeout=10,
        )
        resp.raise_for_status()
        return resp.json() if resp.text else {"success": True}
    except requests.RequestException as e:
        return {"error": str(e)}


def _delete(path):
    try:
        resp = requests.delete(
            f"{STALWART_URL}{path}",
            auth=_auth(),
            verify=False,
            timeout=10,
        )
        resp.raise_for_status()
        return {"success": True}
    except requests.RequestException as e:
        return {"error": str(e)}


def get_server_status():
    result = _get("/api/principal", params={"limit": 1})
    if "error" in result:
        return {"online": False, "error": result["error"]}
    return {"online": True}


def list_mailboxes():
    result = _get("/api/principal", params={"type": "individual", "limit": 100})
    if "error" in result:
        return []
    items = result.get("items", [])
    mailboxes = []
    for item in items:
        mailboxes.append({
            "id": item.get("id"),
            "name": item.get("name", ""),
            "email": item.get("emails", ""),
            "display_name": item.get("description", ""),
            "roles": item.get("roles", []),
            "quota_used": item.get("usedQuota", 0),
            "enabled": "user" in item.get("roles", []),
        })
    return mailboxes


def create_mailbox(name, display_name, password, quota_mb=0):
    domain = os.environ.get("MAIL_DOMAIN", "kytranempowerment.com")
    data = {
        "type": "individual",
        "name": name,
        "description": display_name,
        "secrets": [password],
        "emails": [f"{name}@{domain}"],
        "roles": ["user"],
    }
    if quota_mb > 0:
        data["quota"] = quota_mb * 1024 * 1024
    return _post("/api/principal", data)


def delete_mailbox(name):
    return _delete(f"/api/principal/{name}")


def reset_password(name, new_password):
    return _patch(f"/api/principal/{name}", {"secrets": [new_password]})


def toggle_mailbox(name, enabled):
    roles = ["user"] if enabled else []
    return _patch(f"/api/principal/{name}", {"roles": roles})


def get_queue_status():
    result = _get("/api/queue/messages", params={"limit": 100})
    if "error" in result:
        return {"pending": 0, "error": result["error"]}
    items = result.get("items", []) if isinstance(result, dict) else []
    return {"pending": len(items), "items": items[:10]}
