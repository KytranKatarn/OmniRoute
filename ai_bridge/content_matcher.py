"""
Content Matcher Module
Verifies that old_content exists in target file before saving to plan_steps

Prevents the "silent append" bug where non-matching old_content
causes the system to corrupt files by appending instead of replacing.

Features:
- Exact substring matching
- Whitespace-normalized matching (fallback)
- Fuzzy matching with suggestions
- Line number detection for matches

Author: A.R.C.H.I.E. Code Generation Engine V2
Date: 2026-01-15
"""

import os
import re
import difflib
from typing import Dict, List, Optional, NamedTuple, Tuple


class FuzzyMatch(NamedTuple):
    """A fuzzy match result"""

    content: str
    similarity: float
    line_start: int
    line_end: int
    preview: str


class MatchResult(NamedTuple):
    """Result of content matching"""

    match_found: bool
    match_type: Optional[str]  # 'exact', 'normalized', 'fuzzy'
    location: Optional[Tuple[int, int]]  # (start_line, end_line)
    matched_content: Optional[str]  # The actual content that matched
    suggestions: List[str]
    error: Optional[str]


class ContentMatcher:
    """
    Verifies that old_content exists in target file before saving to plan_steps.

    Prevents silent corruption by ensuring exact or near-exact matches
    before any file modification is allowed.
    """

    def __init__(self, fuzzy_threshold: float = 0.85):
        """
        Initialize content matcher.

        Args:
            fuzzy_threshold: Minimum similarity ratio for fuzzy matches (0.0-1.0)
        """
        self.fuzzy_threshold = fuzzy_threshold
        self.match_stats = {
            "total_checks": 0,
            "exact_matches": 0,
            "normalized_matches": 0,
            "fuzzy_suggestions": 0,
            "no_matches": 0,
        }

    def verify_old_content(
        self,
        file_path: str,
        old_content: str,
        allow_normalized: bool = True,
        allow_fuzzy: bool = True,
    ) -> MatchResult:
        """
        Check if old_content exists in the target file.

        Args:
            file_path: Path to the file to check
            old_content: Content that should exist in the file
            allow_normalized: Allow whitespace-normalized matching
            allow_fuzzy: Provide fuzzy match suggestions if no exact match

        Returns:
            MatchResult with match status and details
        """
        self.match_stats["total_checks"] += 1

        # Validate inputs
        if not old_content or not old_content.strip():
            return MatchResult(
                match_found=False,
                match_type=None,
                location=None,
                matched_content=None,
                suggestions=[],
                error="old_content is empty or whitespace-only",
            )

        # Read file content
        try:
            file_content = self._read_file(file_path)
        except FileNotFoundError:
            return MatchResult(
                match_found=False,
                match_type=None,
                location=None,
                matched_content=None,
                suggestions=[],
                error=f"File not found: {file_path}",
            )
        except Exception as e:
            return MatchResult(
                match_found=False,
                match_type=None,
                location=None,
                matched_content=None,
                suggestions=[],
                error=f"Error reading file: {str(e)}",
            )

        # Step 1: Exact match
        if old_content in file_content:
            self.match_stats["exact_matches"] += 1
            location = self._find_location(file_content, old_content)
            return MatchResult(
                match_found=True,
                match_type="exact",
                location=location,
                matched_content=old_content,
                suggestions=[],
                error=None,
            )

        # Step 2: Whitespace-normalized match
        if allow_normalized:
            normalized_result = self._try_normalized_match(file_content, old_content)
            if normalized_result["found"]:
                self.match_stats["normalized_matches"] += 1
                return MatchResult(
                    match_found=True,
                    match_type="normalized",
                    location=normalized_result["location"],
                    matched_content=normalized_result["matched_content"],
                    suggestions=["Matched after whitespace normalization"],
                    error=None,
                )

        # Step 3: Fuzzy match suggestions
        suggestions = []
        if allow_fuzzy:
            fuzzy_matches = self._find_fuzzy_matches(file_content, old_content)
            if fuzzy_matches:
                self.match_stats["fuzzy_suggestions"] += 1
                for match in fuzzy_matches[:3]:  # Top 3 suggestions
                    suggestions.append(
                        f"Similar content at lines {match.line_start}-{match.line_end} "
                        f"({match.similarity:.0%} similar): {match.preview}"
                    )

        # No match found
        self.match_stats["no_matches"] += 1
        return MatchResult(
            match_found=False,
            match_type=None,
            location=None,
            matched_content=None,
            suggestions=suggestions,
            error="old_content not found in file",
        )

    def _read_file(self, file_path: str) -> str:
        """Read file content with multiple path resolution attempts"""
        # Try multiple possible paths (Docker vs host)
        possible_paths = [file_path]

        if file_path.startswith("platform_v2/"):
            rel_path = file_path[len("platform_v2/") :]
            possible_paths.extend(
                [f"/app/{rel_path}", f"/mnt/archie_brain/platform_v2/{rel_path}"]
            )
        elif file_path.startswith("ai_bridge/"):
            rel_path = file_path[len("ai_bridge/") :]
            possible_paths.append(f"/mnt/archie_brain/ai_bridge/{rel_path}")
        elif not file_path.startswith("/"):
            possible_paths.extend(
                [
                    f"/app/{file_path}",
                    f"/mnt/archie_brain/platform_v2/{file_path}",
                    f"/mnt/archie_brain/{file_path}",
                ]
            )

        for path in possible_paths:
            if os.path.exists(path):
                with open(path, "r", encoding="utf-8") as f:
                    return f.read()

        raise FileNotFoundError(f"File not found at any of: {possible_paths}")

    def _find_location(self, file_content: str, target: str) -> Tuple[int, int]:
        """Find the line numbers where target appears in file_content"""
        index = file_content.index(target)
        before = file_content[:index]
        start_line = before.count("\n") + 1
        end_line = start_line + target.count("\n")
        return (start_line, end_line)

    def _try_normalized_match(self, file_content: str, old_content: str) -> Dict:
        """
        Try to match with whitespace normalization.

        Normalizes:
        - Trailing whitespace on each line
        - Multiple consecutive blank lines → single blank line
        - Tabs → 4 spaces (configurable)
        """
        normalized_old = self._normalize_whitespace(old_content)
        normalized_file = self._normalize_whitespace(file_content)

        if normalized_old in normalized_file:
            # Found normalized match - now find the actual content in original file
            # We need to return the original (non-normalized) content for replacement
            actual_content = self._find_original_content(
                file_content, normalized_file, normalized_old
            )
            if actual_content:
                location = self._find_location(file_content, actual_content)
                return {
                    "found": True,
                    "location": location,
                    "matched_content": actual_content,
                }

        return {"found": False}

    def _normalize_whitespace(self, content: str) -> str:
        """Normalize whitespace for comparison"""
        lines = content.split("\n")
        normalized_lines = []

        for line in lines:
            # Convert tabs to 4 spaces
            line = line.replace("\t", "    ")
            # Strip trailing whitespace
            line = line.rstrip()
            normalized_lines.append(line)

        # Join and collapse multiple blank lines
        result = "\n".join(normalized_lines)
        result = re.sub(r"\n{3,}", "\n\n", result)

        return result

    def _find_original_content(
        self, original_file: str, normalized_file: str, normalized_target: str
    ) -> Optional[str]:
        """
        Find the original (non-normalized) content that matches the normalized target.

        This is necessary because we need to return the actual file content
        for the replacement to work correctly.
        """
        # Find position in normalized file
        norm_index = normalized_file.index(normalized_target)
        norm_end = norm_index + len(normalized_target)

        # Count newlines to find approximate position
        norm_before = normalized_file[:norm_index]
        start_line = norm_before.count("\n")

        norm_in_target = normalized_target.count("\n")
        end_line = start_line + norm_in_target

        # Extract original lines
        original_lines = original_file.split("\n")
        target_lines = original_lines[start_line : end_line + 1]

        return "\n".join(target_lines)

    def _find_fuzzy_matches(
        self, file_content: str, target: str, max_results: int = 5
    ) -> List[FuzzyMatch]:
        """
        Find content in file that is similar to target.

        Uses difflib.SequenceMatcher for similarity scoring.
        """
        matches = []
        file_lines = file_content.split("\n")
        target_lines = target.split("\n")
        target_line_count = len(target_lines)

        # Slide window through file
        for i in range(len(file_lines) - target_line_count + 1):
            window = "\n".join(file_lines[i : i + target_line_count])

            # Calculate similarity
            similarity = difflib.SequenceMatcher(None, target, window).ratio()

            if similarity >= self.fuzzy_threshold:
                preview = window[:50].replace("\n", " ").strip()
                if len(window) > 50:
                    preview += "..."

                matches.append(
                    FuzzyMatch(
                        content=window,
                        similarity=similarity,
                        line_start=i + 1,
                        line_end=i + target_line_count,
                        preview=preview,
                    )
                )

        # Sort by similarity descending
        matches.sort(key=lambda m: m.similarity, reverse=True)

        return matches[:max_results]

    def get_normalized_content(self, file_path: str, old_content: str) -> Optional[str]:
        """
        If old_content doesn't match exactly but matches after normalization,
        return the actual file content that should be used for replacement.

        This allows the code generation engine to correct the old_content
        before saving to plan_steps.
        """
        result = self.verify_old_content(
            file_path, old_content, allow_normalized=True, allow_fuzzy=False
        )

        if result.match_found and result.match_type == "normalized":
            return result.matched_content

        return None

    def get_stats(self) -> Dict:
        """Get matching statistics"""
        return self.match_stats.copy()


# Convenience functions
def verify_content(file_path: str, old_content: str) -> MatchResult:
    """Verify that old_content exists in file"""
    matcher = ContentMatcher()
    return matcher.verify_old_content(file_path, old_content)


def find_matching_content(file_path: str, old_content: str) -> Optional[str]:
    """
    Find the actual file content that matches old_content.

    Returns the exact content from the file if found (useful when
    old_content has minor whitespace differences).
    """
    matcher = ContentMatcher()
    result = matcher.verify_old_content(file_path, old_content)

    if result.match_found:
        return result.matched_content

    return None


if __name__ == "__main__":
    # Test the content matcher
    matcher = ContentMatcher()

    print("=" * 60)
    print("Testing Content Matcher")
    print("=" * 60)

    # Create a test file
    test_content = """
def hello():
    print("Hello, World!")
    return True

def goodbye():
    print("Goodbye!")
    return False
"""

    test_file = "/tmp/test_content_matcher.py"
    with open(test_file, "w") as f:
        f.write(test_content)

    # Test exact match
    print("\n1. Testing exact match:")
    exact_target = 'def hello():\n    print("Hello, World!")\n    return True'
    result = matcher.verify_old_content(test_file, exact_target)
    print(f"   Match found: {result.match_found}")
    print(f"   Match type: {result.match_type}")
    print(f"   Location: {result.location}")

    # Test normalized match (with trailing whitespace)
    print("\n2. Testing normalized match:")
    normalized_target = (
        'def hello():  \n    print("Hello, World!")  \n    return True  '
    )
    result = matcher.verify_old_content(test_file, normalized_target)
    print(f"   Match found: {result.match_found}")
    print(f"   Match type: {result.match_type}")

    # Test fuzzy match
    print("\n3. Testing fuzzy match:")
    fuzzy_target = (
        'def hello():\n    print("Hello World")\n    return True'  # Missing comma
    )
    result = matcher.verify_old_content(test_file, fuzzy_target)
    print(f"   Match found: {result.match_found}")
    print(f"   Suggestions: {result.suggestions}")

    # Test no match
    print("\n4. Testing no match:")
    no_match_target = "def nonexistent():\n    pass"
    result = matcher.verify_old_content(test_file, no_match_target)
    print(f"   Match found: {result.match_found}")
    print(f"   Error: {result.error}")

    # Clean up
    os.unlink(test_file)

    print("\n" + "=" * 60)
    print(f"Stats: {matcher.get_stats()}")
