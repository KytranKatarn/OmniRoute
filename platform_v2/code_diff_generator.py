"""
Code Diff Generator for A.R.C.H.I.E. Improvement Proposals
Generates before/after previews of code changes for review before deployment

Supports:
- Multiple file changes in one proposal
- Side-by-side diff display
- Syntax highlighting hints
- Change statistics (lines added/removed/modified)
"""
import difflib
import os
import json
from typing import Dict, List, Optional, Tuple
from datetime import datetime
import hashlib


class CodeDiffGenerator:
    """
    Generates and manages code diffs for improvement proposals.

    Diff Format (JSON):
    {
        "files": [
            {
                "path": "/path/to/file.py",
                "language": "python",
                "before": "old content",
                "after": "new content",
                "diff": "unified diff string",
                "stats": {
                    "lines_added": 10,
                    "lines_removed": 5,
                    "lines_modified": 3
                }
            }
        ],
        "summary": {
            "total_files": 2,
            "total_added": 25,
            "total_removed": 10,
            "total_modified": 8
        },
        "generated_at": "2026-01-02T..."
    }
    """

    def __init__(self):
        self.language_map = {
            '.py': 'python',
            '.js': 'javascript',
            '.jsx': 'javascript',
            '.ts': 'typescript',
            '.tsx': 'typescript',
            '.sql': 'sql',
            '.html': 'html',
            '.css': 'css',
            '.json': 'json',
            '.md': 'markdown',
            '.sh': 'bash',
            '.yml': 'yaml',
            '.yaml': 'yaml'
        }

    def generate_diff(
        self,
        file_changes: List[Dict[str, str]],
        context_lines: int = 3
    ) -> Dict:
        """
        Generate a comprehensive diff for multiple file changes.

        Args:
            file_changes: List of dicts with 'path', 'before', 'after'
            context_lines: Number of context lines in diff (default 3)

        Returns:
            Complete diff structure with files and summary

        Example:
            file_changes = [
                {
                    'path': '/app/routes.py',
                    'before': 'def old_function():\n    pass',
                    'after': 'def new_function():\n    return True'
                }
            ]
        """
        files_diff = []
        total_added = 0
        total_removed = 0
        total_modified = 0

        for file_change in file_changes:
            file_path = file_change.get('path', 'unknown')
            before_content = file_change.get('before', '')
            after_content = file_change.get('after', '')

            # Detect language from extension
            language = self._detect_language(file_path)

            # Generate unified diff
            before_lines = before_content.splitlines(keepends=True)
            after_lines = after_content.splitlines(keepends=True)

            diff_lines = list(difflib.unified_diff(
                before_lines,
                after_lines,
                fromfile=f'a{file_path}',
                tofile=f'b{file_path}',
                n=context_lines
            ))

            diff_string = ''.join(diff_lines)

            # Calculate statistics
            stats = self._calculate_stats(diff_lines)

            total_added += stats['lines_added']
            total_removed += stats['lines_removed']
            total_modified += stats['lines_modified']

            files_diff.append({
                'path': file_path,
                'language': language,
                'before': before_content,
                'after': after_content,
                'diff': diff_string,
                'stats': stats,
                'checksum_before': self._checksum(before_content),
                'checksum_after': self._checksum(after_content)
            })

        return {
            'files': files_diff,
            'summary': {
                'total_files': len(files_diff),
                'total_added': total_added,
                'total_removed': total_removed,
                'total_modified': total_modified
            },
            'generated_at': datetime.now().isoformat()
        }

    def generate_html_diff(
        self,
        before_content: str,
        after_content: str,
        file_path: str = 'file'
    ) -> str:
        """
        Generate an HTML side-by-side diff.

        Args:
            before_content: Original content
            after_content: Modified content
            file_path: File path for display

        Returns:
            HTML string with side-by-side diff
        """
        before_lines = before_content.splitlines()
        after_lines = after_content.splitlines()

        differ = difflib.HtmlDiff(wrapcolumn=80)
        html = differ.make_table(
            before_lines,
            after_lines,
            fromdesc=f'Before: {file_path}',
            todesc=f'After: {file_path}',
            context=True,
            numlines=3
        )

        return html

    def apply_diff_to_file(
        self,
        file_path: str,
        diff_content: str,
        dry_run: bool = True
    ) -> Dict:
        """
        Apply a diff to an actual file.

        Args:
            file_path: Path to the file to modify
            diff_content: The new content to write
            dry_run: If True, don't actually write (default True)

        Returns:
            {'success': True, 'path': '...', 'backed_up': True}
        """
        if not os.path.exists(file_path):
            return {
                'success': False,
                'error': f'File not found: {file_path}'
            }

        # Read current content
        with open(file_path, 'r') as f:
            current_content = f.read()

        if dry_run:
            return {
                'success': True,
                'dry_run': True,
                'path': file_path,
                'message': 'Dry run - no changes made'
            }

        # Create backup
        backup_path = f"{file_path}.backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        with open(backup_path, 'w') as f:
            f.write(current_content)

        # Write new content
        with open(file_path, 'w') as f:
            f.write(diff_content)

        return {
            'success': True,
            'path': file_path,
            'backed_up': backup_path,
            'message': 'File updated successfully'
        }

    def _detect_language(self, file_path: str) -> str:
        """Detect programming language from file extension"""
        _, ext = os.path.splitext(file_path)
        return self.language_map.get(ext.lower(), 'text')

    def _calculate_stats(self, diff_lines: List[str]) -> Dict:
        """Calculate diff statistics from unified diff lines"""
        added = 0
        removed = 0
        modified = 0

        for line in diff_lines:
            if line.startswith('+') and not line.startswith('+++'):
                added += 1
            elif line.startswith('-') and not line.startswith('---'):
                removed += 1

        # Estimate modified lines (pairs of +/-)
        modified = min(added, removed)

        return {
            'lines_added': added,
            'lines_removed': removed,
            'lines_modified': modified
        }

    def _checksum(self, content: str) -> str:
        """Generate checksum for content verification"""
        return hashlib.md5(content.encode()).hexdigest()


# ============================================================================
# CONVENIENCE FUNCTIONS
# ============================================================================

def generate_proposal_diff(file_changes: List[Dict]) -> Dict:
    """Quick function to generate diff for a proposal"""
    generator = CodeDiffGenerator()
    return generator.generate_diff(file_changes)


def create_simple_diff(file_path: str, before: str, after: str) -> Dict:
    """Create a simple single-file diff"""
    generator = CodeDiffGenerator()
    return generator.generate_diff([{
        'path': file_path,
        'before': before,
        'after': after
    }])


# ============================================================================
# TESTING
# ============================================================================

if __name__ == '__main__':
    print("Code Diff Generator - Test Mode")
    print("=" * 60)

    # Test with sample Python code change
    before = """def calculate_total(items):
    total = 0
    for item in items:
        total += item.price
    return total
"""

    after = """def calculate_total(items, tax_rate=0.0):
    subtotal = sum(item.price for item in items)
    tax = subtotal * tax_rate
    return subtotal + tax
"""

    generator = CodeDiffGenerator()
    result = generator.generate_diff([{
        'path': '/app/calculations.py',
        'before': before,
        'after': after
    }])

    print("\nGenerated Diff:")
    print("-" * 60)
    print(f"Files: {result['summary']['total_files']}")
    print(f"Lines Added: {result['summary']['total_added']}")
    print(f"Lines Removed: {result['summary']['total_removed']}")
    print(f"\nDiff Preview:")
    print(result['files'][0]['diff'])

    print("\n✅ Code Diff Generator loaded successfully!")
