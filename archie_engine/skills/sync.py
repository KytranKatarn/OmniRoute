"""Sync skills from Hub knowledge base to local community directory."""

import os
import logging
import asyncio
import aiohttp
from pathlib import Path

logger = logging.getLogger(__name__)


class SkillSyncService:
    """Periodically sync adapted skills from Hub to local .md files."""

    def __init__(self, hub_url: str, api_key: str, skills_dir: str):
        self.hub_url = hub_url.rstrip("/")
        self.api_key = api_key
        self.skills_dir = Path(skills_dir) / "hub"
        self.skills_dir.mkdir(parents=True, exist_ok=True)

    async def sync(self) -> int:
        """Fetch skills from Hub and write to local .md files. Returns count synced."""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{self.hub_url}/api/v1/tools/search_knowledge_brief",
                    json={
                        "query": "adapted skill command",
                        "types": ["github_file"],
                        "limit": 100,
                    },
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    timeout=aiohttp.ClientTimeout(total=30),
                ) as resp:
                    if resp.status != 200:
                        logger.warning("Hub sync failed: HTTP %d", resp.status)
                        return 0
                    data = await resp.json()
                    results = data.get("result", {}).get("results", [])
        except Exception as e:
            logger.warning("Hub sync error: %s", e)
            return 0

        count = 0
        for entry in results:
            title = entry.get("title", "")
            content = entry.get("content", "")
            if not title or not content:
                continue

            # Generate filename from title
            slug = (
                title.lower().replace(" ", "-").replace("/", "-").replace("_", "-")
            )
            slug = slug.strip("-")[:60]
            if not slug:
                continue

            filepath = self.skills_dir / f"{slug}.md"
            filepath.write_text(content, encoding="utf-8")
            count += 1

        logger.info("Synced %d skills from Hub to %s", count, self.skills_dir)
        return count

    async def start_loop(self, interval_seconds: int = 3600):
        """Run sync every interval_seconds (default: 1 hour)."""
        while True:
            await self.sync()
            await asyncio.sleep(interval_seconds)
