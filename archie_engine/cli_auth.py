"""CLI authentication commands — register and manage hub connection.

Usage:
    from archie_engine.cli_auth import auth_register, auth_set_key, auth_status
    auth_register()       # Interactive device registration
    auth_set_key("archie_xxx")  # Save API key
    auth_status()         # Check connection status
"""

import sys
import logging

from archie_engine.hub_skills import HubSkillClient, DEFAULT_HUB_URL, CONFIG_PATH

logger = logging.getLogger(__name__)


def auth_register(args: list[str] | None = None) -> None:
    """Register this CLI with the hub. Run: archie auth register"""
    device_name = input("Device name (e.g., 'Kyt-Laptop'): ").strip()
    if not device_name:
        print("Device name required.")
        return

    hub_url = input(f"Hub URL [{DEFAULT_HUB_URL}]: ").strip()
    if not hub_url:
        hub_url = DEFAULT_HUB_URL

    client = HubSkillClient(hub_url=hub_url)
    result = client.register_device(device_name)

    if "error" in result:
        print(f"Registration failed: {result['error']}")
        return

    print(f"\nRegistered! Device ID: {result.get('device_id')}")
    print(f"Status: {result.get('status', 'pending')}")
    print(f"\nNext steps:")
    print(f"1. Go to {hub_url}/tools/department-hq -> Devices tab")
    print(f"2. Approve your device")
    print(f"3. Copy the API key and run: archie auth set-key <key>")


def auth_set_key(api_key: str | None = None) -> None:
    """Save an API key. Run: archie auth set-key archie_xxx"""
    if not api_key:
        api_key = input("API key: ").strip()

    if not api_key:
        print("No key provided.")
        return

    if not api_key.startswith("archie_"):
        print("Invalid key format. Keys start with 'archie_'")
        return

    client = HubSkillClient()
    client.save_api_key(api_key)
    print(f"API key saved to {CONFIG_PATH}")

    # Validate by listing skills
    skills = client.list_skills()
    if skills:
        print(f"Connected! {len(skills)} hub skills available.")
    else:
        print("Key saved but couldn't verify. Check hub URL and key.")


def auth_status() -> None:
    """Check connection status. Run: archie auth status"""
    client = HubSkillClient()

    if not client.api_key:
        print("Not authenticated. Run: archie auth register")
        return

    print(f"Hub: {client.hub_url}")
    print(f"Key: {client.api_key[:12]}...")
    print(f"Credentials: {CONFIG_PATH}")

    skills = client.list_skills()
    if skills:
        print(f"Status: Connected ({len(skills)} hub skills available)")
        # Show a few skill names
        names = [s.get("name", "?") for s in skills[:5]]
        print(f"Sample: {', '.join(names)}")
        if len(skills) > 5:
            print(f"  ... and {len(skills) - 5} more")
    else:
        print("Status: Cannot connect or key invalid")


def handle_auth_command(argv: list[str]) -> bool:
    """Handle 'auth' subcommands. Returns True if handled."""
    if not argv or argv[0] != "auth":
        return False

    subcommand = argv[1] if len(argv) > 1 else "status"

    if subcommand == "register":
        auth_register()
    elif subcommand in ("set-key", "setkey"):
        key = argv[2] if len(argv) > 2 else None
        auth_set_key(key)
    elif subcommand == "status":
        auth_status()
    else:
        print(f"Unknown auth command: {subcommand}")
        print("Available: register, set-key, status")
        return False

    return True
