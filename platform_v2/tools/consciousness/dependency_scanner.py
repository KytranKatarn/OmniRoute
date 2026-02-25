"""
Dependency Scanner - GitHub Intelligence Module

Parses package.json and requirements.txt files, checks npm/PyPI registries
for latest versions, and queries GitHub Security Advisories for vulnerabilities.
"""

import re
import json
import logging
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests

logger = logging.getLogger(__name__)

# Timeout for registry API calls
REGISTRY_TIMEOUT = 10


class DependencyScanner:
    """Scans dependency files for outdated packages and vulnerabilities."""

    def __init__(self, github_token=None):
        self.github_token = github_token
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "ARCHIE-DependencyScanner/1.0"})

    def parse_package_json(self, content):
        """Extract dependencies from package.json content.

        Returns list of {'package': str, 'current_version': str, 'ecosystem': 'npm'}
        """
        try:
            data = json.loads(content)
        except (json.JSONDecodeError, TypeError):
            logger.warning("Failed to parse package.json")
            return []

        deps = []
        for section in ("dependencies", "devDependencies"):
            for name, version_spec in (data.get(section) or {}).items():
                # Strip version prefixes: ^, ~, >=, etc.
                clean = re.sub(r"^[\^~>=<]*", "", version_spec.strip())
                deps.append(
                    {
                        "package": name,
                        "current_version": clean or version_spec,
                        "ecosystem": "npm",
                    }
                )
        return deps

    def parse_requirements_txt(self, content):
        """Extract dependencies from requirements.txt content.

        Handles ==, >=, ~=, <=, bare packages, and comments/blank lines.
        Returns list of {'package': str, 'current_version': str, 'ecosystem': 'pypi'}
        """
        deps = []
        for line in content.splitlines():
            line = line.strip()
            if not line or line.startswith("#") or line.startswith("-"):
                continue
            # Match: package[extras]==version, package>=version, package~=version, bare package
            match = re.match(r"^([A-Za-z0-9_.-]+)(?:\[.*?\])?\s*(?:([=~<>!]+)\s*(.+?))?$", line)
            if match:
                name = match.group(1)
                version = (match.group(3) or "").strip()
                deps.append(
                    {
                        "package": name,
                        "current_version": version,
                        "ecosystem": "pypi",
                    }
                )
        return deps

    def check_npm_package(self, name):
        """Check npm registry for latest version.

        Returns {'latest_version': str, 'deprecated': str|None} or None on failure.
        """
        try:
            resp = self.session.get(
                f"https://registry.npmjs.org/{name}/latest",
                timeout=REGISTRY_TIMEOUT,
            )
            if resp.status_code != 200:
                return None
            data = resp.json()
            return {
                "latest_version": data.get("version", ""),
                "deprecated": data.get("deprecated"),
            }
        except Exception as e:
            logger.debug(f"npm check failed for {name}: {e}")
            return None

    def check_pypi_package(self, name):
        """Check PyPI for latest version.

        Returns {'latest_version': str} or None on failure.
        """
        try:
            resp = self.session.get(
                f"https://pypi.org/pypi/{name}/json",
                timeout=REGISTRY_TIMEOUT,
            )
            if resp.status_code != 200:
                return None
            data = resp.json()
            return {
                "latest_version": data.get("info", {}).get("version", ""),
            }
        except Exception as e:
            logger.debug(f"PyPI check failed for {name}: {e}")
            return None

    def check_vulnerabilities(self, name, ecosystem):
        """Query GitHub Security Advisory DB via GraphQL.

        Returns list of {'id': str, 'severity': str, 'vulnerable_range': str, 'patched_version': str}
        """
        if not self.github_token:
            return []

        gh_ecosystem = "NPM" if ecosystem == "npm" else "PIP"
        query = """
        query($ecosystem: SecurityAdvisoryEcosystem, $package: String) {
          securityVulnerabilities(ecosystem: $ecosystem, package: $package, first: 10) {
            nodes {
              advisory { ghsaId summary severity }
              vulnerableVersionRange
              firstPatchedVersion { identifier }
            }
          }
        }
        """
        try:
            resp = self.session.post(
                "https://api.github.com/graphql",
                json={
                    "query": query,
                    "variables": {"ecosystem": gh_ecosystem, "package": name},
                },
                headers={"Authorization": f"Bearer {self.github_token}"},
                timeout=REGISTRY_TIMEOUT,
            )
            if resp.status_code != 200:
                return []
            data = resp.json()
            nodes = data.get("data", {}).get("securityVulnerabilities", {}).get("nodes", [])
            vulns = []
            for node in nodes:
                adv = node.get("advisory", {})
                vulns.append(
                    {
                        "id": adv.get("ghsaId", ""),
                        "severity": adv.get("severity", "UNKNOWN"),
                        "summary": adv.get("summary", ""),
                        "vulnerable_range": node.get("vulnerableVersionRange", ""),
                        "patched_version": (node.get("firstPatchedVersion") or {}).get("identifier", ""),
                    }
                )
            return vulns
        except Exception as e:
            logger.debug(f"Vulnerability check failed for {name}: {e}")
            return []

    def _check_single_dep(self, dep):
        """Check a single dependency for updates and vulnerabilities."""
        name = dep["package"]
        ecosystem = dep["ecosystem"]

        # Check registry
        if ecosystem == "npm":
            registry_info = self.check_npm_package(name)
        else:
            registry_info = self.check_pypi_package(name)

        latest = (registry_info or {}).get("latest_version", "")
        deprecated = (registry_info or {}).get("deprecated")
        current = dep["current_version"]
        has_update = bool(latest and current and latest != current)

        # Check vulnerabilities
        vulns = self.check_vulnerabilities(name, ecosystem)

        return {
            "package": name,
            "current_version": current,
            "latest_version": latest,
            "ecosystem": ecosystem,
            "has_update": has_update,
            "deprecated": deprecated,
            "vulnerabilities": vulns,
        }

    def scan_dependency_file(self, content, file_type, source):
        """Orchestrate full scan of a dependency file.

        Args:
            content: Raw file content
            file_type: 'package.json' or 'requirements.txt'
            source: Identifier like 'owner/repo' or 'local/platform_v2'

        Returns structured scan result dict.
        """
        if file_type == "package.json":
            deps = self.parse_package_json(content)
        elif file_type == "requirements.txt":
            deps = self.parse_requirements_txt(content)
        else:
            return {"source": source, "error": f"Unknown file type: {file_type}"}

        if not deps:
            return {
                "source": source,
                "file_type": file_type,
                "scanned_at": datetime.now(timezone.utc).isoformat(),
                "packages_scanned": 0,
                "updates_available": 0,
                "vulnerabilities_found": 0,
                "critical_count": 0,
                "high_count": 0,
                "dependencies": [],
            }

        # Check all deps concurrently (max 5 threads to avoid rate limits)
        results = []
        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = {executor.submit(self._check_single_dep, d): d for d in deps}
            for future in as_completed(futures):
                try:
                    results.append(future.result())
                except Exception as e:
                    dep = futures[future]
                    logger.warning(f"Failed checking {dep['package']}: {e}")
                    results.append(
                        {
                            "package": dep["package"],
                            "current_version": dep["current_version"],
                            "latest_version": "",
                            "ecosystem": dep["ecosystem"],
                            "has_update": False,
                            "deprecated": None,
                            "vulnerabilities": [],
                        }
                    )

        updates = sum(1 for r in results if r["has_update"])
        all_vulns = [v for r in results for v in r["vulnerabilities"]]
        critical = sum(1 for v in all_vulns if v["severity"] == "CRITICAL")
        high = sum(1 for v in all_vulns if v["severity"] == "HIGH")

        return {
            "source": source,
            "file_type": file_type,
            "scanned_at": datetime.now(timezone.utc).isoformat(),
            "packages_scanned": len(results),
            "updates_available": updates,
            "vulnerabilities_found": len(all_vulns),
            "critical_count": critical,
            "high_count": high,
            "dependencies": results,
        }
