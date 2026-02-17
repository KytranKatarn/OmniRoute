#!/usr/bin/env python3
"""
Register migrated stacks in Archie's docker_stacks table
Run this AFTER deploying the stacks with docker compose
"""

import psycopg2
from psycopg2.extras import RealDictCursor
import json
from datetime import datetime

# Database connection (use Docker network hostname)
DB_CONFIG = {
    "host": "192.168.1.200",
    "port": 5432,
    "database": "archie",
    "user": "archie",
    "password": "archie",
}

# Stacks to register
STACKS = [
    {
        "name": "plex-media-stack",
        "display_name": "Plex Media Server",
        "description": "Plex, Sonarr, Radarr, Prowlarr, Overseerr, SABnzbd",
        "compose_directory": "/mnt/archie_brain/migrations/from-192.168.1.250/compose/plex-media-stack",
        "color": "#E5A00D",  # Plex orange
        "is_system": False,
        "web_ui_ports": [
            {"port": 32400, "label": "Plex", "path": "/web"},
            {"port": 8989, "label": "Sonarr"},
            {"port": 7878, "label": "Radarr"},
            {"port": 9696, "label": "Prowlarr"},
            {"port": 5055, "label": "Overseerr"},
            {"port": 8083, "label": "SABnzbd"},
        ],
    },
    {
        "name": "home-automation-stack",
        "display_name": "Home Assistant",
        "description": "Home automation platform",
        "compose_directory": "/mnt/archie_brain/migrations/from-192.168.1.250/compose/home-automation-stack",
        "color": "#41BDF5",  # Home Assistant blue
        "is_system": False,
        "web_ui_ports": [{"port": 8123, "label": "Home Assistant"}],
    },
    {
        "name": "network-tools-stack",
        "display_name": "Network Tools",
        "description": "AdGuard Home DNS, ntopng network monitor",
        "compose_directory": "/mnt/archie_brain/migrations/from-192.168.1.250/compose/network-tools-stack",
        "color": "#68BC71",  # AdGuard green
        "is_system": False,
        "web_ui_ports": [
            {"port": 5354, "label": "AdGuard Home"},
            {"port": 3001, "label": "ntopng"},
        ],
    },
    {
        "name": "monitoring-stack",
        "display_name": "Monitoring",
        "description": "Dozzle logs, cAdvisor metrics, Nagios alerts",
        "compose_directory": "/mnt/archie_brain/migrations/from-192.168.1.250/compose/monitoring-stack",
        "color": "#9B59B6",  # Purple
        "is_system": False,
        "web_ui_ports": [
            {"port": 8080, "label": "Dozzle"},
            {"port": 8081, "label": "cAdvisor"},
            {"port": 8082, "label": "Nagios"},
        ],
    },
    {
        "name": "reverse-proxy-stack",
        "display_name": "Reverse Proxy",
        "description": "Nginx Proxy Manager with SSL",
        "compose_directory": "/mnt/archie_brain/migrations/from-192.168.1.250/compose/reverse-proxy-stack",
        "color": "#009639",  # Nginx green
        "is_system": False,
        "web_ui_ports": [{"port": 81, "label": "NPM Admin"}],
    },
]


def register_stacks():
    """Register all stacks in database"""
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        cur = conn.cursor(cursor_factory=RealDictCursor)

        for stack in STACKS:
            # Check if stack already exists
            cur.execute(
                "SELECT id FROM docker_stacks WHERE name = %s", (stack["name"],)
            )
            existing = cur.fetchone()

            if existing:
                print(
                    f"  Stack '{stack['name']}' already exists (id={existing['id']}), updating..."
                )
                cur.execute(
                    """
                    UPDATE docker_stacks SET
                        display_name = %s,
                        description = %s,
                        compose_directory = %s,
                        color = %s,
                        is_system = %s,
                        web_ui_ports = %s,
                        updated_at = NOW()
                    WHERE name = %s
                """,
                    (
                        stack["display_name"],
                        stack["description"],
                        stack["compose_directory"],
                        stack["color"],
                        stack["is_system"],
                        json.dumps(stack["web_ui_ports"]),
                        stack["name"],
                    ),
                )
            else:
                print(f"  Registering stack '{stack['name']}'...")
                cur.execute(
                    """
                    INSERT INTO docker_stacks
                    (name, display_name, description, compose_directory, color, is_system, web_ui_ports, created_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, NOW())
                """,
                    (
                        stack["name"],
                        stack["display_name"],
                        stack["description"],
                        stack["compose_directory"],
                        stack["color"],
                        stack["is_system"],
                        json.dumps(stack["web_ui_ports"]),
                    ),
                )

        conn.commit()
        print(f"\n✓ Registered {len(STACKS)} stacks successfully!")

        # List all stacks
        cur.execute("SELECT name, display_name, color FROM docker_stacks ORDER BY name")
        print("\nAll registered stacks:")
        for row in cur.fetchall():
            print(f"  - {row['display_name']} ({row['name']})")

        cur.close()
        conn.close()

    except Exception as e:
        print(f"Error: {e}")
        raise


if __name__ == "__main__":
    print("Registering migrated stacks in Archie database...\n")
    register_stacks()
