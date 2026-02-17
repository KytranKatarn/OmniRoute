"""
Manual Code Applier
Quick utility to apply simple code changes without full AI generation
Used when we know exactly what changes to make

Author: A.R.C.H.I.E. Self-Improvement System
Date: 2026-01-05
"""

import sys

sys.path.insert(0, "/mnt/archie_brain/platform_v2")

from code_application_system import apply_code_changes


def enable_website_builder(proposal_id: int):
    """Enable Website Builder on dashboard"""

    changes = [
        {
            "file_path": "templates/dashboard.html",
            "action": "modify",
            "old_content": """    <!-- Website Builder -->
    <div class="tool-card disabled">
        <div class="tool-icon">🌐</div>
        <div class="tool-title">WEBSITE BUILDER</div>""",
            "new_content": """    <!-- Website Builder -->
    <a href="/tools/website_builder/" class="tool-card">
        <div class="tool-icon">🌐</div>
        <div class="tool-title">WEBSITE BUILDER</div>""",
            "diff": """- <div class="tool-card disabled">
+ <a href="/tools/website_builder/" class="tool-card">""",
            "description": "Enable Website Builder - make it clickable",
        }
    ]

    print(f"📝 Applying Website Builder enablement to proposal #{proposal_id}...")
    result = apply_code_changes(proposal_id, changes)

    print(f"\n✅ Success: {result['success']}")
    print(f"📄 Files modified: {result['files_modified']}")
    print(f"💾 Backup: {result['backup_path']}")

    return result


if __name__ == "__main__":
    if len(sys.argv) > 1:
        proposal_id = int(sys.argv[1])
        enable_website_builder(proposal_id)
    else:
        print("Usage: python manual_code_applier.py <proposal_id>")
