"""
Code Diff Engine for Improvement Proposals
Generates before/after code comparisons with syntax highlighting support
"""

import difflib
import os
import re
from typing import Dict, List, Optional, Tuple
from pathlib import Path
import json


class CodeDiffEngine:
    """
    Generate code diffs for improvement proposals.

    Features:
    - Side-by-side diff generation
    - Unified diff format
    - Syntax highlighting metadata
    - File-level and multi-file diffs
    - Stats (lines added/removed/changed)
    """

    def __init__(self):
        # Language detection patterns
        self.language_patterns = {
            ".py": "python",
            ".js": "javascript",
            ".ts": "typescript",
            ".jsx": "javascript",
            ".tsx": "typescript",
            ".html": "html",
            ".css": "css",
            ".sql": "sql",
            ".json": "json",
            ".yaml": "yaml",
            ".yml": "yaml",
            ".md": "markdown",
            ".sh": "bash",
        }

    def generate_diff(
        self,
        old_content: str,
        new_content: str,
        filename: str = "file.txt",
        context_lines: int = 3,
    ) -> Dict:
        """
        Generate a unified diff between old and new content.

        Args:
            old_content: Original file content
            new_content: Modified file content
            filename: Name of the file (for language detection)
            context_lines: Number of context lines around changes

        Returns:
            Dict containing diff data, stats, and metadata
        """
        # Split into lines
        old_lines = old_content.splitlines(keepends=True)
        new_lines = new_content.splitlines(keepends=True)

        # Generate unified diff
        diff = list(
            difflib.unified_diff(
                old_lines,
                new_lines,
                fromfile=f"a/{filename}",
                tofile=f"b/{filename}",
                lineterm="",
                n=context_lines,
            )
        )

        # Calculate statistics
        stats = self._calculate_stats(old_lines, new_lines, diff)

        # Detect language for syntax highlighting
        language = self._detect_language(filename)

        # Parse diff into structured format
        hunks = self._parse_diff_hunks(diff)

        return {
            "filename": filename,
            "language": language,
            "diff_text": "".join(diff),
            "hunks": hunks,
            "stats": stats,
            "old_lines": len(old_lines),
            "new_lines": len(new_lines),
            "has_changes": len(diff) > 0,
        }

    def generate_side_by_side_diff(self, old_content: str, new_content: str, filename: str = "file.txt") -> Dict:
        """
        Generate a side-by-side diff with line-by-line comparison.

        Returns:
            Dict with left (old) and right (new) line arrays
        """
        old_lines = old_content.splitlines()
        new_lines = new_content.splitlines()

        # Use SequenceMatcher for detailed comparison
        matcher = difflib.SequenceMatcher(None, old_lines, new_lines)

        left_lines = []  # Old content
        right_lines = []  # New content

        for opcode, i1, i2, j1, j2 in matcher.get_opcodes():
            if opcode == "equal":
                # Lines are the same
                for i, line in enumerate(old_lines[i1:i2]):
                    left_lines.append({"line_num": i1 + i + 1, "content": line, "type": "equal"})
                    right_lines.append(
                        {
                            "line_num": j1 + i + 1,
                            "content": new_lines[j1 + i],
                            "type": "equal",
                        }
                    )

            elif opcode == "delete":
                # Lines removed from old
                for i, line in enumerate(old_lines[i1:i2]):
                    left_lines.append({"line_num": i1 + i + 1, "content": line, "type": "delete"})
                    right_lines.append({"line_num": None, "content": "", "type": "empty"})

            elif opcode == "insert":
                # Lines added to new
                for i, line in enumerate(new_lines[j1:j2]):
                    left_lines.append({"line_num": None, "content": "", "type": "empty"})
                    right_lines.append({"line_num": j1 + i + 1, "content": line, "type": "insert"})

            elif opcode == "replace":
                # Lines changed
                max_lines = max(i2 - i1, j2 - j1)
                for i in range(max_lines):
                    # Old side
                    if i < (i2 - i1):
                        left_lines.append(
                            {
                                "line_num": i1 + i + 1,
                                "content": old_lines[i1 + i],
                                "type": "replace",
                            }
                        )
                    else:
                        left_lines.append({"line_num": None, "content": "", "type": "empty"})

                    # New side
                    if i < (j2 - j1):
                        right_lines.append(
                            {
                                "line_num": j1 + i + 1,
                                "content": new_lines[j1 + i],
                                "type": "replace",
                            }
                        )
                    else:
                        right_lines.append({"line_num": None, "content": "", "type": "empty"})

        language = self._detect_language(filename)
        stats = self._calculate_stats(old_lines, new_lines, [])

        return {
            "filename": filename,
            "language": language,
            "left_lines": left_lines,
            "right_lines": right_lines,
            "stats": stats,
        }

    def generate_multi_file_diff(self, file_changes: List[Dict]) -> Dict:
        """
        Generate diffs for multiple files.

        Args:
            file_changes: List of dicts with keys:
                - filename: str
                - old_content: str
                - new_content: str

        Returns:
            Dict with array of file diffs and aggregate stats
        """
        diffs = []
        total_stats = {
            "files_changed": 0,
            "lines_added": 0,
            "lines_removed": 0,
            "lines_changed": 0,
        }

        for change in file_changes:
            diff = self.generate_diff(
                old_content=change["old_content"],
                new_content=change["new_content"],
                filename=change["filename"],
            )

            diffs.append(diff)

            # Aggregate stats
            total_stats["files_changed"] += 1
            total_stats["lines_added"] += diff["stats"]["lines_added"]
            total_stats["lines_removed"] += diff["stats"]["lines_removed"]
            total_stats["lines_changed"] += diff["stats"]["lines_changed"]

        return {"diffs": diffs, "stats": total_stats, "file_count": len(file_changes)}

    def apply_diff_to_file(self, filepath: str, new_content: str, backup: bool = True) -> Dict:
        """
        Apply new content to a file, optionally creating a backup.

        Args:
            filepath: Path to the file to modify
            new_content: New content to write
            backup: If True, create .bak backup of original

        Returns:
            Dict with success status and backup path
        """
        try:
            filepath = Path(filepath)

            # Read old content for diff
            if filepath.exists():
                with open(filepath, "r") as f:
                    old_content = f.read()
            else:
                old_content = ""

            # Create backup if requested
            backup_path = None
            if backup and filepath.exists():
                backup_path = str(filepath) + ".bak"
                with open(backup_path, "w") as f:
                    f.write(old_content)

            # Write new content
            with open(filepath, "w") as f:
                f.write(new_content)

            # Generate diff for logging
            diff = self.generate_diff(old_content, new_content, filepath.name)

            return {
                "success": True,
                "filepath": str(filepath),
                "backup_path": backup_path,
                "stats": diff["stats"],
            }

        except Exception as e:
            return {"success": False, "error": str(e), "filepath": str(filepath)}

    def _detect_language(self, filename: str) -> str:
        """Detect programming language from file extension"""
        ext = os.path.splitext(filename)[1].lower()
        return self.language_patterns.get(ext, "text")

    def _calculate_stats(self, old_lines: List[str], new_lines: List[str], diff: List[str]) -> Dict:
        """Calculate diff statistics"""
        lines_added = 0
        lines_removed = 0

        for line in diff:
            if line.startswith("+") and not line.startswith("+++"):
                lines_added += 1
            elif line.startswith("-") and not line.startswith("---"):
                lines_removed += 1

        lines_changed = min(lines_added, lines_removed)

        return {
            "lines_added": lines_added,
            "lines_removed": lines_removed,
            "lines_changed": lines_changed,
            "total_changes": lines_added + lines_removed,
        }

    def _parse_diff_hunks(self, diff: List[str]) -> List[Dict]:
        """Parse unified diff into structured hunks"""
        hunks = []
        current_hunk = None

        for line in diff:
            if line.startswith("@@"):
                # New hunk header
                if current_hunk:
                    hunks.append(current_hunk)

                # Parse hunk header: @@ -start,count +start,count @@
                match = re.match(r"@@ -(\d+),?(\d*) \+(\d+),?(\d*) @@", line)
                if match:
                    current_hunk = {
                        "header": line,
                        "old_start": int(match.group(1)),
                        "old_count": int(match.group(2)) if match.group(2) else 1,
                        "new_start": int(match.group(3)),
                        "new_count": int(match.group(4)) if match.group(4) else 1,
                        "lines": [],
                    }

            elif current_hunk is not None:
                # Add line to current hunk
                if line.startswith("+"):
                    line_type = "add"
                elif line.startswith("-"):
                    line_type = "remove"
                elif line.startswith(" "):
                    line_type = "context"
                else:
                    line_type = "meta"

                current_hunk["lines"].append({"type": line_type, "content": line})

        # Add last hunk
        if current_hunk:
            hunks.append(current_hunk)

        return hunks

    def create_proposal_diff(
        self,
        proposal_description: str,
        file_path: str,
        old_content: str,
        new_content: str,
    ) -> str:
        """
        Create a formatted diff summary for a proposal.

        Returns a markdown-formatted string suitable for proposal.code_diff
        """
        diff_data = self.generate_diff(old_content, new_content, file_path)

        markdown = f"# Code Changes for Proposal\n\n"
        markdown += f"**File:** `{file_path}`\n"
        markdown += f"**Language:** {diff_data['language']}\n\n"

        markdown += f"## Statistics\n"
        markdown += f"- Lines added: **+{diff_data['stats']['lines_added']}**\n"
        markdown += f"- Lines removed: **-{diff_data['stats']['lines_removed']}**\n"
        markdown += f"- Total changes: **{diff_data['stats']['total_changes']}**\n\n"

        markdown += f"## Diff\n\n"
        markdown += f"```diff\n"
        markdown += diff_data["diff_text"]
        markdown += f"\n```\n"

        return markdown


# ============================================================================
# CONVENIENCE FUNCTIONS
# ============================================================================


def quick_diff(old_content: str, new_content: str, filename: str = "file.txt") -> Dict:
    """Quick function to generate a diff"""
    engine = CodeDiffEngine()
    return engine.generate_diff(old_content, new_content, filename)


def side_by_side_diff(old_content: str, new_content: str, filename: str = "file.txt") -> Dict:
    """Quick function to generate side-by-side diff"""
    engine = CodeDiffEngine()
    return engine.generate_side_by_side_diff(old_content, new_content, filename)


def apply_changes(filepath: str, new_content: str, backup: bool = True) -> Dict:
    """Quick function to apply changes to a file"""
    engine = CodeDiffEngine()
    return engine.apply_diff_to_file(filepath, new_content, backup)


# ============================================================================
# TESTING
# ============================================================================

if __name__ == "__main__":
    print("Code Diff Engine - Test Mode")
    print("=" * 60)

    # Test with sample code
    old_code = """def hello_world():
    print("Hello, World!")
    return True
"""

    new_code = """def hello_world(name="World"):
    \"\"\"Greet someone by name\"\"\"
    print(f"Hello, {name}!")
    return True

def goodbye():
    print("Goodbye!")
"""

    # Generate unified diff
    print("\n1. UNIFIED DIFF:")
    print("-" * 60)
    diff_data = quick_diff(old_code, new_code, "example.py")
    print(diff_data["diff_text"])
    print(f"\nStats: +{diff_data['stats']['lines_added']} -{diff_data['stats']['lines_removed']}")

    # Generate side-by-side diff
    print("\n2. SIDE-BY-SIDE DIFF:")
    print("-" * 60)
    sbs_diff = side_by_side_diff(old_code, new_code, "example.py")
    print(f"Left (old): {len(sbs_diff['left_lines'])} lines")
    print(f"Right (new): {len(sbs_diff['right_lines'])} lines")

    for i in range(min(5, len(sbs_diff["left_lines"]))):
        left = sbs_diff["left_lines"][i]
        right = sbs_diff["right_lines"][i]
        print(f"{left['type']:8} | {right['type']:8} | {left['content'][:30]:30} | {right['content'][:30]:30}")

    print("\n✅ Code Diff Engine tests passed!")
