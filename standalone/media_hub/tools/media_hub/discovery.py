"""
Media Hub Service Discovery
===========================
Auto-discovers API keys and configuration from service config files.
"""

import os
import re
import json
import base64
import logging
from typing import Optional, Dict, Any
from xml.etree import ElementTree as ET

try:
    import configparser
except ImportError:
    configparser = None

logger = logging.getLogger(__name__)


# Config file paths for each service
CONFIG_PATHS = {
    "plex": "/mnt/Plex/config/plex/Library/Application Support/Plex Media Server/Preferences.xml",
    # ⚠️ The three *arr configs moved to /mnt/data2 (physical /dev/sdf) on
    # 2026-07-29 — /mnt/Plex is /dev/sdb, which has 1760 uncorrectable sectors
    # and had already corrupted Sonarr's DB and all 4 of its backups (#5384).
    # The inconsistency with their siblings below is DELIBERATE: those still
    # live on /mnt/Plex and are a pending follow-up, not an oversight.
    # Keep in step with media-stack/docker-compose.yml AND scripts/host_monitor.py
    # — all three hardcode these paths, and a partial change breaks *arr
    # auto-discovery silently (nothing raises; the API key comes back empty).
    "sonarr": "/mnt/data2/plex-config/sonarr/config.xml",
    "radarr": "/mnt/data2/plex-config/radarr/config.xml",
    "prowlarr": "/mnt/data2/plex-config/prowlarr/config.xml",
    "overseerr": "/mnt/Plex/config/overseerr/settings.json",
    "jellyseerr": "/mnt/Plex/config/jellyseerr/settings.json",
    "sabnzbd": "/mnt/Plex/config/sabnzbd/sabnzbd.ini",
    "jellyfin": "/mnt/Plex/config/jellyfin/config/system.xml",
}


def discover_plex_token(config_path: Optional[str] = None) -> Optional[str]:
    """
    Discover Plex token from Preferences.xml.

    Args:
        config_path: Override default config path

    Returns:
        Plex authentication token or None
    """
    path = config_path or CONFIG_PATHS["plex"]

    try:
        if not os.path.exists(path):
            logger.warning(f"Plex config not found at {path}")
            return None

        tree = ET.parse(path)
        root = tree.getroot()

        # Token is in the Preferences element attributes
        token = root.get("PlexOnlineToken")
        if token:
            logger.info("Successfully discovered Plex token")
            return token

        # Alternative attribute name
        token = root.get("PlexOnlineHome")
        if token:
            return token

        logger.warning("Plex token not found in config")
        return None

    except ET.ParseError as e:
        logger.error(f"Failed to parse Plex config XML: {e}")
        return None
    except Exception as e:
        logger.error(f"Error discovering Plex token: {e}")
        return None


def discover_arr_api_key(service: str, config_path: Optional[str] = None) -> Optional[str]:
    """
    Discover API key from Sonarr/Radarr/Prowlarr config.xml.

    Args:
        service: Service name ('sonarr', 'radarr', 'prowlarr')
        config_path: Override default config path

    Returns:
        API key or None
    """
    path = config_path or CONFIG_PATHS.get(service)
    if not path:
        logger.error(f"Unknown service: {service}")
        return None

    try:
        if not os.path.exists(path):
            logger.warning(f"{service} config not found at {path}")
            return None

        tree = ET.parse(path)
        root = tree.getroot()

        # API key is in <ApiKey> element
        api_key_elem = root.find(".//ApiKey")
        if api_key_elem is not None and api_key_elem.text:
            logger.info(f"Successfully discovered {service} API key")
            return api_key_elem.text

        logger.warning(f"{service} API key not found in config")
        return None

    except ET.ParseError as e:
        logger.error(f"Failed to parse {service} config XML: {e}")
        return None
    except Exception as e:
        logger.error(f"Error discovering {service} API key: {e}")
        return None


def discover_overseerr_api_key(config_path: Optional[str] = None) -> Optional[str]:
    """
    Discover Overseerr/Jellyseerr API key from settings.json.

    Args:
        config_path: Override default config path

    Returns:
        API key or None
    """
    path = config_path or CONFIG_PATHS["overseerr"]

    try:
        if not os.path.exists(path):
            logger.warning(f"Overseerr config not found at {path}")
            return None

        with open(path, "r") as f:
            settings = json.load(f)

        # API key is in main.apiKey (base64 encoded)
        main = settings.get("main", {})
        api_key_b64 = main.get("apiKey")

        if api_key_b64:
            # Decode base64
            try:
                api_key = base64.b64decode(api_key_b64).decode("utf-8")
                logger.info("Successfully discovered Overseerr API key")
                return api_key
            except Exception:
                # May not be base64 encoded in some versions
                logger.info("Overseerr API key not base64 encoded, using as-is")
                return api_key_b64

        logger.warning("Overseerr API key not found in config")
        return None

    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse Overseerr config JSON: {e}")
        return None
    except Exception as e:
        logger.error(f"Error discovering Overseerr API key: {e}")
        return None


def discover_sabnzbd_api_key(config_path: Optional[str] = None) -> Optional[str]:
    """
    Discover SABnzbd API key from sabnzbd.ini.

    Args:
        config_path: Override default config path

    Returns:
        API key or None
    """
    path = config_path or CONFIG_PATHS["sabnzbd"]

    try:
        if not os.path.exists(path):
            logger.warning(f"SABnzbd config not found at {path}")
            return None

        # SABnzbd uses INI format
        if configparser:
            config = configparser.ConfigParser()
            config.read(path)

            # API key is in [misc] section
            if "misc" in config and "api_key" in config["misc"]:
                api_key = config["misc"]["api_key"]
                logger.info("Successfully discovered SABnzbd API key")
                return api_key
        else:
            # Fallback: parse manually
            with open(path, "r") as f:
                content = f.read()

            match = re.search(r"^api_key\s*=\s*(.+)$", content, re.MULTILINE)
            if match:
                logger.info("Successfully discovered SABnzbd API key (manual parse)")
                return match.group(1).strip()

        logger.warning("SABnzbd API key not found in config")
        return None

    except Exception as e:
        logger.error(f"Error discovering SABnzbd API key: {e}")
        return None


def discover_jellyfin_api_key(config_path: Optional[str] = None) -> Optional[str]:
    """
    Note: Jellyfin API keys must be created manually via the admin dashboard.
    This function checks if Jellyfin is installed and returns guidance.

    Args:
        config_path: Override default config path

    Returns:
        None (Jellyfin keys must be created manually)
    """
    path = config_path or CONFIG_PATHS["jellyfin"]

    if os.path.exists(os.path.dirname(path)):
        logger.info("Jellyfin installation detected. API key must be created manually.")
        logger.info("Go to Jellyfin Dashboard > API Keys > Add")
        return None

    logger.info("Jellyfin not detected")
    return None


def discover_all_api_keys() -> Dict[str, Dict[str, Any]]:
    """
    Discover API keys for all supported services.

    Returns:
        Dictionary with service configurations
    """
    results = {}

    # Plex
    plex_token = discover_plex_token()
    results["plex"] = {
        "found": plex_token is not None,
        "api_key": plex_token,
        "config_path": CONFIG_PATHS["plex"],
        "port": 32400,
    }

    # Sonarr
    sonarr_key = discover_arr_api_key("sonarr")
    results["sonarr"] = {
        "found": sonarr_key is not None,
        "api_key": sonarr_key,
        "config_path": CONFIG_PATHS["sonarr"],
        "port": 8989,
    }

    # Radarr
    radarr_key = discover_arr_api_key("radarr")
    results["radarr"] = {
        "found": radarr_key is not None,
        "api_key": radarr_key,
        "config_path": CONFIG_PATHS["radarr"],
        "port": 7878,
    }

    # Prowlarr
    prowlarr_key = discover_arr_api_key("prowlarr")
    results["prowlarr"] = {
        "found": prowlarr_key is not None,
        "api_key": prowlarr_key,
        "config_path": CONFIG_PATHS["prowlarr"],
        "port": 9696,
    }

    # Overseerr
    overseerr_key = discover_overseerr_api_key()
    results["overseerr"] = {
        "found": overseerr_key is not None,
        "api_key": overseerr_key,
        "config_path": CONFIG_PATHS["overseerr"],
        "port": 5055,
    }

    # SABnzbd
    sabnzbd_key = discover_sabnzbd_api_key()
    results["sabnzbd"] = {
        "found": sabnzbd_key is not None,
        "api_key": sabnzbd_key,
        "config_path": CONFIG_PATHS["sabnzbd"],
        "port": 8083,
    }

    # Jellyfin (requires manual setup)
    jellyfin_path = CONFIG_PATHS.get("jellyfin", "")
    jellyfin_installed = os.path.exists(os.path.dirname(jellyfin_path))
    results["jellyfin"] = {
        "found": False,
        "api_key": None,
        "config_path": jellyfin_path,
        "port": 8096,
        "note": ("API key must be created manually in Jellyfin Dashboard" if jellyfin_installed else "Not installed"),
    }

    return results


if __name__ == "__main__":
    """Test discovery when run directly"""
    print("Testing Media Hub Service Discovery...")
    print("=" * 60)

    results = discover_all_api_keys()

    for service, info in results.items():
        status = "FOUND" if info["found"] else "NOT FOUND"
        print(f"\n{service.upper()}:")
        print(f"  Status: {status}")
        print(f"  Config: {info['config_path']}")
        print(f"  Port: {info['port']}")
        if info.get("note"):
            print(f"  Note: {info['note']}")
        if info["found"] and info["api_key"]:
            # Show only first/last 4 chars for security
            key = info["api_key"]
            masked = f"{key[:4]}...{key[-4:]}" if len(key) > 8 else "****"
            print(f"  API Key: {masked}")
