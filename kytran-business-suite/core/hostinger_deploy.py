"""Hostinger static site deployment service.

Zips generated HTML/CSS pages and deploys to Hostinger hosting.
Falls back to stub mode (records deployment record) when API key is not configured.
"""

import io
import logging
import zipfile

import requests

logger = logging.getLogger(__name__)


class DeploymentError(Exception):
    """Raised when deployment to Hostinger fails."""

    pass


def build_site_zip(pages: list[dict], code_mode_files: list[dict] | None = None) -> bytes:
    """Build a ZIP archive from pages or code-mode files.

    Args:
        pages: List of dicts with 'slug' and 'content' keys (visual mode).
        code_mode_files: List of dicts with 'path', 'content', 'is_directory' keys (code mode).
               When provided, pages are ignored.

    Returns:
        bytes: The ZIP file as bytes.
    """
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        if code_mode_files is not None:
            for f in code_mode_files:
                if f.get("is_directory"):
                    continue
                path = f.get("path", "file.html")
                content = f.get("content", "")
                zf.writestr(path, content)
        else:
            for page in pages:
                slug = page.get("slug", "page")
                content = page.get("content", "")
                filename = f"{slug}.html"
                zf.writestr(filename, content)

    return buffer.getvalue()


def deploy_to_hostinger(
    zip_bytes: bytes,
    domain: str,
    hostinger_api_key: str,
    hostinger_api_url: str = "https://api.hostinger.com",
) -> dict:
    """Deploy a static site ZIP to Hostinger hosting.

    Args:
        zip_bytes: The ZIP archive bytes to deploy.
        domain: Target domain for deployment.
        hostinger_api_key: Hostinger API bearer token.
        hostinger_api_url: Hostinger API base URL.

    Returns:
        dict with keys: status, url, message

    Raises:
        DeploymentError: If the Hostinger API call fails.
    """
    if not hostinger_api_key:
        # Stub mode — record the deployment intent without actually deploying
        logger.warning(
            "Hostinger API key not configured — using stub deployment for %s", domain
        )
        return {
            "status": "pending_manual",
            "url": f"https://{domain}",
            "message": "Deployment recorded. Configure HOSTINGER_API_KEY to enable automatic deployment.",
        }

    try:
        response = requests.post(
            f"{hostinger_api_url}/v1/hosting/static/deploy",
            files={"archive": ("site.zip", zip_bytes, "application/zip")},
            data={"domain": domain},
            headers={"Authorization": f"Bearer {hostinger_api_key}"},
            timeout=120,
        )
        response.raise_for_status()
    except requests.exceptions.Timeout:
        raise DeploymentError(f"Hostinger deployment timed out for {domain}")
    except Exception as exc:
        raise DeploymentError(f"Hostinger deployment failed: {exc}")

    data = response.json()
    return {
        "status": data.get("status", "deployed"),
        "url": data.get("url", f"https://{domain}"),
        "message": data.get("message", "Site deployed successfully"),
    }
