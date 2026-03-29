"""Load skills from ARCHIE Hub knowledge base (github_skills table).

Fetches adapted GitHub skills via the Hub's search_knowledge_brief API
and converts them to local CLI Skill objects with a 'hub:' prefix.

These are distinct from the /archie-* branded skills served by Department HQ.
Hub KB skills come from the github_skills pipeline (259+ entries from 51 repos).

Usage:
    loader = HubKBSkillLoader("http://192.168.1.200:3000", api_key="...")
    skills = await loader.load_skills()
    # Returns Skill objects with names like "hub:prompt-engineer", "hub:skill-creator"
"""

import logging
import aiohttp
from typing import List, Optional
from .skill import Skill

logger = logging.getLogger(__name__)


class HubKBSkillLoader:
    """Fetch adapted skills from ARCHIE Hub knowledge base and convert to CLI Skill objects."""

    def __init__(self, hub_url: str, api_key: str = ""):
        self.hub_url = hub_url.rstrip("/")
        self.api_key = api_key
        self._cache: List[Skill] | None = None

    async def load_skills(self, limit: int = 50, use_cache: bool = True) -> List[Skill]:
        """Fetch skills from Hub's knowledge base and convert to Skill objects.

        Queries the search_knowledge_brief endpoint for github_file entries
        that contain skill definitions. Results are cached to avoid repeated
        network calls during a session.
        """
        if use_cache and self._cache is not None:
            return self._cache

        skills: List[Skill] = []
        try:
            headers = {"Content-Type": "application/json"}
            if self.api_key:
                headers["Authorization"] = f"Bearer {self.api_key}"

            async with aiohttp.ClientSession() as session:
                # Query knowledge base for skill-type github files
                async with session.post(
                    f"{self.hub_url}/api/v1/tools/search_knowledge_brief",
                    json={
                        "query": "skill command tool agent",
                        "types": ["github_file"],
                        "limit": limit,
                    },
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=30),
                ) as resp:
                    if resp.status != 200:
                        logger.warning(
                            "Hub KB skill fetch returned %d", resp.status
                        )
                        return []
                    data = await resp.json()

                results = data.get("result", {}).get("results", [])
                for entry in results:
                    skill = self._convert_to_skill(entry)
                    if skill:
                        skills.append(skill)

            self._cache = skills
            logger.info("Loaded %d skills from Hub knowledge base", len(skills))
        except aiohttp.ClientError as e:
            logger.warning("Hub KB skill fetch network error: %s", e)
        except Exception as e:
            logger.warning("Failed to load Hub KB skills: %s", e)
        return skills

    def _convert_to_skill(self, entry: dict) -> Optional[Skill]:
        """Convert a knowledge base entry to a Skill object."""
        title = entry.get("title", "")
        content = entry.get("content", "")

        if not title or not content:
            return None

        # Generate a command name from the title
        name = self._slugify(title)
        if not name or len(name) < 2:
            return None

        # Extract description from first meaningful line of content
        description = self._extract_description(content)

        return Skill(
            name=f"hub:{name}",
            description=description or f"Community skill: {name}",
            body=content,
            arguments=[],
            source="hub",
        )

    @staticmethod
    def _slugify(title: str) -> str:
        """Convert a title into a clean command slug."""
        name = title.lower().replace(" ", "-").replace("_", "-")
        # Strip common path prefixes from GitHub file titles
        for prefix in [
            "skills/",
            "skill-",
            "readme",
            "tools/",
            "examples/",
            "docs/",
        ]:
            if name.startswith(prefix):
                name = name[len(prefix) :]
        # Strip file extensions
        for ext in [".md", ".txt", ".json", ".yaml", ".yml"]:
            if name.endswith(ext):
                name = name[: -len(ext)]
        # Clean up separators
        name = name.strip("-").strip("/")
        # Collapse multiple hyphens
        while "--" in name:
            name = name.replace("--", "-")
        return name

    @staticmethod
    def _extract_description(content: str) -> str:
        """Extract a short description from the first meaningful line."""
        for line in content.strip().split("\n"):
            line = line.strip().lstrip("#").strip()
            if line and not line.startswith("---") and not line.startswith("```"):
                return line[:120]
        return ""

    def invalidate_cache(self) -> None:
        """Clear the skill cache to force a re-fetch."""
        self._cache = None
