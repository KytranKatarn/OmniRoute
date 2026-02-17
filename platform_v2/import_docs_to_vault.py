#!/usr/bin/env python3
"""
Import existing /docs/ markdown files into Obsidian vault structure
Creates frontmatter, organizes by category, preserves content
Phase 3 - Knowledge Architecture Unification
"""

import os
import shutil
import re
from pathlib import Path
from datetime import datetime

DOCS_DIR = "/mnt/archie_brain/docs/"
VAULT_DIR = "/mnt/archie_brain/knowledge/"

# Category mapping based on filename patterns
CATEGORY_MAPPINGS = {
    "ADMIN": "Development",
    "AGENT": "Agents",
    "API": "APIs",
    "CONSCIOUSNESS": "Core",
    "PERSONALITY": "Core",
    "FEATURE": "Features",
    "WORKFLOW": "Workflows",
    "MASTER": "Core",
    "PHASE": "Development",
    "BACKUP": "Operations",
    "DEPLOYMENT": "Operations",
    "TESTING": "Development",
    "AI_POWERED": "Features",
    "BUILDER": "Features",
    "IMPROVEMENTS": "Development",
    "OPTIMIZATION": "Development",
    "SYSTEM": "Core",
    "GUIDE": "Documentation",
    "REFERENCE": "Documentation",
}


def determine_category(filename):
    """Determine category from filename"""
    filename_upper = filename.upper()

    for pattern, category in CATEGORY_MAPPINGS.items():
        if pattern in filename_upper:
            return category

    return "Documentation"  # Default category


def extract_title_from_content(content):
    """Extract title from first # heading or return None"""
    match = re.search(r"^#\s+(.+)$", content, re.MULTILINE)
    if match:
        return match.group(1).strip()
    return None


def generate_tags(filename, category):
    """Generate tags from filename and category"""
    tags = []

    # Add category as tag
    tags.append(category.lower())

    # Add filename-based tags (split by underscore, lowercase)
    name_parts = Path(filename).stem.lower().split("_")
    tags.extend([part for part in name_parts if len(part) > 3])  # Only meaningful parts

    # Always add 'documentation' tag
    tags.append("documentation")

    # Remove duplicates
    return list(set(tags))


def add_frontmatter(filepath, category):
    """Add YAML frontmatter to existing markdown file"""
    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()

    # Check if frontmatter already exists
    if content.startswith("---"):
        print(f"  ⚠️  Frontmatter already exists, skipping: {Path(filepath).name}")
        return content

    # Extract title from content or use filename
    title = extract_title_from_content(content)
    if not title:
        title = Path(filepath).stem.replace("_", " ")

    # Generate tags
    tags = generate_tags(Path(filepath).name, category)

    # Create frontmatter
    frontmatter = f"""---
title: "{title}"
category: {category}
tags: [{', '.join(tags)}]
created: {datetime.now().isoformat()}
source: /docs/
migrated: true
---

"""

    return frontmatter + content


def import_docs():
    """Import all /docs/ files to vault"""
    stats = {"imported": 0, "skipped": 0, "errors": 0, "categories": {}}

    print(f"\n{'='*70}")
    print("IMPORTING /docs/ TO OBSIDIAN VAULT")
    print(f"{'='*70}\n")
    print(f"Source: {DOCS_DIR}")
    print(f"Destination: {VAULT_DIR}\n")

    # Get all markdown files
    if not os.path.exists(DOCS_DIR):
        print(f"❌ Error: {DOCS_DIR} does not exist")
        return stats

    md_files = [f for f in os.listdir(DOCS_DIR) if f.endswith(".md")]
    print(f"Found {len(md_files)} markdown files to import\n")

    for filename in sorted(md_files):
        try:
            # Determine category from filename
            category = determine_category(filename)

            # Track category stats
            stats["categories"][category] = stats["categories"].get(category, 0) + 1

            # Read original file
            src_path = os.path.join(DOCS_DIR, filename)

            # Add frontmatter
            content_with_frontmatter = add_frontmatter(src_path, category)

            # Create destination directory
            dest_dir = os.path.join(VAULT_DIR, category)
            os.makedirs(dest_dir, exist_ok=True)

            # Write to vault
            dest_path = os.path.join(dest_dir, filename)

            # Check if file already exists
            if os.path.exists(dest_path):
                print(f"  ⚠️  File already exists, skipping: {filename}")
                stats["skipped"] += 1
                continue

            with open(dest_path, "w", encoding="utf-8") as f:
                f.write(content_with_frontmatter)

            stats["imported"] += 1
            print(f"  ✅ {filename} → {category}/")

        except Exception as e:
            stats["errors"] += 1
            print(f"  ❌ Error importing {filename}: {e}")

    return stats


def print_summary(stats):
    """Print import summary"""
    print(f"\n{'='*70}")
    print("IMPORT SUMMARY")
    print(f"{'='*70}\n")
    print(f"✅ Imported: {stats['imported']}")
    print(f"⚠️  Skipped: {stats['skipped']}")
    print(f"❌ Errors: {stats['errors']}")

    if stats["categories"]:
        print("\nFiles by Category:")
        for category, count in sorted(stats["categories"].items(), key=lambda x: x[1], reverse=True):
            print(f"  {category}: {count}")

    print(f"\n{'='*70}")
    print("Next steps:")
    print("1. Run: docker exec archie_platform python3 /mnt/archie_brain/platform_v2/knowledge_vault_indexer.py")
    print("2. Check vault at: http://192.168.1.200:3000/tools/obsidian-vault/")
    print(f"{'='*70}\n")


if __name__ == "__main__":
    print("Starting /docs/ import to Obsidian vault...")
    stats = import_docs()
    print_summary(stats)

    if stats["errors"] > 0:
        exit(1)
    else:
        exit(0)
