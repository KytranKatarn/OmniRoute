"""
Code Validator Module
Multi-language syntax validation for AI-generated code

Implements SynCode-inspired validation with:
- Python: ast.parse() + py_compile for syntax checking
- JavaScript: Basic syntax pattern validation
- HTML: html.parser validation
- CSS: Brace matching validation

Author: A.R.C.H.I.E. Code Generation Engine V2
Date: 2026-01-15
"""

import ast
import py_compile
import tempfile
import os
import re
from typing import Dict, List, Optional, NamedTuple
from html.parser import HTMLParser
from html import unescape


class ValidationResult(NamedTuple):
    """Result of code validation"""

    success: bool
    errors: List[str]
    warnings: List[str]
    line_number: Optional[int]
    suggestion: Optional[str]


class HTMLValidator(HTMLParser):
    """Custom HTML parser for validation"""

    def __init__(self):
        super().__init__()
        self.errors = []
        self.tag_stack = []
        self.self_closing = {
            "br",
            "hr",
            "img",
            "input",
            "meta",
            "link",
            "area",
            "base",
            "col",
            "embed",
            "source",
            "track",
            "wbr",
        }

    def handle_starttag(self, tag, attrs):
        if tag.lower() not in self.self_closing:
            self.tag_stack.append((tag, self.getpos()))

    def handle_endtag(self, tag):
        if tag.lower() in self.self_closing:
            return
        if not self.tag_stack:
            self.errors.append(
                f"Unexpected closing tag </{tag}> at line {self.getpos()[0]}"
            )
            return
        expected_tag, pos = self.tag_stack.pop()
        if expected_tag.lower() != tag.lower():
            self.errors.append(
                f"Mismatched tags: expected </{expected_tag}>, got </{tag}> at line {self.getpos()[0]}"
            )

    def check_unclosed(self):
        for tag, pos in self.tag_stack:
            self.errors.append(f"Unclosed tag <{tag}> opened at line {pos[0]}")


class CodeValidator:
    """
    Multi-language syntax validation for AI-generated code.

    Validates code before saving to plan_steps to prevent
    deployment of syntactically invalid code.
    """

    LANGUAGE_EXTENSIONS = {
        ".py": "python",
        ".js": "javascript",
        ".jsx": "javascript",
        ".ts": "typescript",
        ".tsx": "typescript",
        ".html": "html",
        ".htm": "html",
        ".css": "css",
        ".sql": "sql",
        ".json": "json",
    }

    def __init__(self):
        self.validation_stats = {
            "total_validations": 0,
            "python_validations": 0,
            "js_validations": 0,
            "html_validations": 0,
            "failures": 0,
        }

    def detect_language(self, file_path: str) -> str:
        """Detect language from file extension"""
        ext = os.path.splitext(file_path)[1].lower()
        return self.LANGUAGE_EXTENSIONS.get(ext, "unknown")

    def validate(self, code: str, file_path: str) -> ValidationResult:
        """
        Validate code syntax based on file type.

        Args:
            code: The code to validate
            file_path: Path to determine language

        Returns:
            ValidationResult with success status and any errors
        """
        self.validation_stats["total_validations"] += 1
        language = self.detect_language(file_path)

        if language == "python":
            return self.validate_python(code)
        elif language in ("javascript", "typescript"):
            return self.validate_javascript(code)
        elif language == "html":
            return self.validate_html(code)
        elif language == "css":
            return self.validate_css(code)
        elif language == "json":
            return self.validate_json(code)
        elif language == "sql":
            return self.validate_sql(code)
        else:
            # Unknown language - skip validation with warning
            return ValidationResult(
                success=True,
                errors=[],
                warnings=[f"No validator for {language} files - skipping syntax check"],
                line_number=None,
                suggestion=None,
            )

    def validate_python(self, code: str) -> ValidationResult:
        """
        Validate Python code using ast.parse() and py_compile.

        This catches:
        - SyntaxError
        - IndentationError
        - TabError
        - Other compile-time errors
        """
        self.validation_stats["python_validations"] += 1
        errors = []
        warnings = []

        # Step 1: AST parsing (catches most errors quickly)
        try:
            ast.parse(code)
        except SyntaxError as e:
            self.validation_stats["failures"] += 1
            return ValidationResult(
                success=False,
                errors=[f"SyntaxError: {e.msg}"],
                warnings=[],
                line_number=e.lineno,
                suggestion=self._suggest_python_fix(e),
            )
        except IndentationError as e:
            self.validation_stats["failures"] += 1
            return ValidationResult(
                success=False,
                errors=[f"IndentationError: {e.msg}"],
                warnings=[],
                line_number=e.lineno,
                suggestion="Check indentation - ensure consistent use of spaces (not tabs)",
            )
        except TabError as e:
            self.validation_stats["failures"] += 1
            return ValidationResult(
                success=False,
                errors=[f"TabError: {e.msg}"],
                warnings=[],
                line_number=e.lineno,
                suggestion="Mixed tabs and spaces - convert all indentation to spaces",
            )

        # Step 2: py_compile for edge cases AST might miss
        try:
            with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
                f.write(code)
                temp_path = f.name

            py_compile.compile(temp_path, doraise=True)
            os.unlink(temp_path)
        except py_compile.PyCompileError as e:
            self.validation_stats["failures"] += 1
            # Extract line number from error message
            line_match = re.search(r"line (\d+)", str(e))
            line_num = int(line_match.group(1)) if line_match else None

            return ValidationResult(
                success=False,
                errors=[f"CompileError: {str(e)}"],
                warnings=[],
                line_number=line_num,
                suggestion="Check for encoding issues or invalid syntax",
            )
        except Exception as e:
            # Clean up temp file if it exists
            if "temp_path" in locals() and os.path.exists(temp_path):
                os.unlink(temp_path)

        # Step 3: Additional checks for common issues
        warnings.extend(self._check_python_warnings(code))

        return ValidationResult(
            success=True,
            errors=[],
            warnings=warnings,
            line_number=None,
            suggestion=None,
        )

    def _suggest_python_fix(self, error: SyntaxError) -> str:
        """Suggest fix based on common Python syntax errors"""
        msg = str(error.msg).lower() if error.msg else ""

        if "expected" in msg and ":" in msg:
            return "Missing colon after if/for/while/def/class statement"
        elif "unexpected indent" in msg:
            return "Remove extra indentation or check previous line for missing colon"
        elif "unindent" in msg:
            return "Indentation doesn't match any outer block - check alignment"
        elif "invalid syntax" in msg:
            return "Check for typos, missing parentheses, or invalid operators"
        elif "unterminated string" in msg:
            return "Missing closing quote for string literal"
        elif "unmatched" in msg:
            return "Missing closing bracket, parenthesis, or brace"
        else:
            return f"Check syntax at line {error.lineno}"

    def _check_python_warnings(self, code: str) -> List[str]:
        """Check for potential issues that aren't errors"""
        warnings = []
        lines = code.split("\n")

        for i, line in enumerate(lines, 1):
            # Check for very long lines
            if len(line) > 200:
                warnings.append(f"Line {i} is very long ({len(line)} chars)")

            # Check for bare except
            if re.match(r"\s*except\s*:", line):
                warnings.append(
                    f"Line {i}: Bare 'except:' clause - consider specifying exception type"
                )

        return warnings

    def validate_javascript(self, code: str) -> ValidationResult:
        """
        Validate JavaScript/TypeScript syntax.

        Uses pattern matching for basic validation:
        - Balanced braces/brackets/parentheses
        - Common syntax patterns
        """
        self.validation_stats["js_validations"] += 1
        errors = []
        warnings = []

        # Check balanced delimiters
        balance_result = self._check_balanced_delimiters(code)
        if not balance_result["balanced"]:
            self.validation_stats["failures"] += 1
            return ValidationResult(
                success=False,
                errors=[balance_result["error"]],
                warnings=[],
                line_number=balance_result.get("line"),
                suggestion=balance_result.get("suggestion", "Check bracket matching"),
            )

        # Check for common JS syntax errors
        lines = code.split("\n")
        for i, line in enumerate(lines, 1):
            stripped = line.strip()

            # Check for incomplete arrow functions
            if re.search(r"=>\s*$", stripped) and not stripped.endswith("{"):
                errors.append(f"Line {i}: Incomplete arrow function - missing body")

            # Check for unclosed template literals
            if stripped.count("`") % 2 != 0:
                warnings.append(f"Line {i}: Unclosed template literal")

        if errors:
            self.validation_stats["failures"] += 1
            return ValidationResult(
                success=False,
                errors=errors,
                warnings=warnings,
                line_number=None,
                suggestion="Check for syntax errors",
            )

        return ValidationResult(
            success=True,
            errors=[],
            warnings=warnings,
            line_number=None,
            suggestion=None,
        )

    def _check_balanced_delimiters(self, code: str) -> Dict:
        """Check if braces, brackets, and parentheses are balanced"""
        stack = []
        pairs = {")": "(", "]": "[", "}": "{"}
        openers = set(pairs.values())
        closers = set(pairs.keys())

        # Track position
        line_num = 1

        # Skip strings and comments
        in_string = None
        in_comment = False
        in_multiline_comment = False
        prev_char = ""

        for i, char in enumerate(code):
            if char == "\n":
                line_num += 1
                in_comment = False
                prev_char = char
                continue

            # Handle string detection
            if char in ('"', "'", "`") and not in_comment and not in_multiline_comment:
                if in_string == char and prev_char != "\\":
                    in_string = None
                elif in_string is None:
                    in_string = char
                prev_char = char
                continue

            # Skip if in string
            if in_string:
                prev_char = char
                continue

            # Handle comments
            if prev_char == "/" and char == "/":
                in_comment = True
            elif prev_char == "/" and char == "*":
                in_multiline_comment = True
            elif prev_char == "*" and char == "/" and in_multiline_comment:
                in_multiline_comment = False

            if in_comment or in_multiline_comment:
                prev_char = char
                continue

            # Check delimiters
            if char in openers:
                stack.append((char, line_num))
            elif char in closers:
                if not stack:
                    return {
                        "balanced": False,
                        "error": f"Unexpected '{char}' at line {line_num}",
                        "line": line_num,
                        "suggestion": f"Remove extra '{char}' or add matching opener",
                    }
                expected, open_line = stack.pop()
                if expected != pairs[char]:
                    return {
                        "balanced": False,
                        "error": f"Mismatched '{pairs[char]}' (line {open_line}) and '{char}' (line {line_num})",
                        "line": line_num,
                        "suggestion": f"Check bracket matching between lines {open_line} and {line_num}",
                    }

            prev_char = char

        if stack:
            unclosed, line = stack[-1]
            return {
                "balanced": False,
                "error": f"Unclosed '{unclosed}' at line {line}",
                "line": line,
                "suggestion": f"Add closing '{dict(zip(openers, closers))[unclosed]}' for opener at line {line}",
            }

        return {"balanced": True}

    def validate_html(self, code: str) -> ValidationResult:
        """
        Validate HTML syntax using HTMLParser.

        Checks for:
        - Mismatched tags
        - Unclosed tags
        - Invalid HTML structure
        """
        self.validation_stats["html_validations"] += 1

        validator = HTMLValidator()
        try:
            validator.feed(code)
            validator.check_unclosed()
        except Exception as e:
            self.validation_stats["failures"] += 1
            return ValidationResult(
                success=False,
                errors=[f"HTML parsing error: {str(e)}"],
                warnings=[],
                line_number=None,
                suggestion="Check HTML structure for invalid characters or syntax",
            )

        if validator.errors:
            self.validation_stats["failures"] += 1
            return ValidationResult(
                success=False,
                errors=validator.errors,
                warnings=[],
                line_number=None,
                suggestion="Fix tag matching issues",
            )

        return ValidationResult(
            success=True, errors=[], warnings=[], line_number=None, suggestion=None
        )

    def validate_css(self, code: str) -> ValidationResult:
        """
        Validate CSS syntax.

        Basic validation for:
        - Balanced braces
        - Basic selector/property syntax
        """
        # Check balanced braces
        balance_result = self._check_balanced_delimiters(code)
        if not balance_result["balanced"]:
            self.validation_stats["failures"] += 1
            return ValidationResult(
                success=False,
                errors=[balance_result["error"]],
                warnings=[],
                line_number=balance_result.get("line"),
                suggestion=balance_result.get("suggestion", "Check brace matching"),
            )

        return ValidationResult(
            success=True, errors=[], warnings=[], line_number=None, suggestion=None
        )

    def validate_json(self, code: str) -> ValidationResult:
        """Validate JSON syntax"""
        import json

        try:
            json.loads(code)
            return ValidationResult(
                success=True, errors=[], warnings=[], line_number=None, suggestion=None
            )
        except json.JSONDecodeError as e:
            self.validation_stats["failures"] += 1
            return ValidationResult(
                success=False,
                errors=[f"JSON error: {e.msg}"],
                warnings=[],
                line_number=e.lineno,
                suggestion="Check for trailing commas, missing quotes, or invalid values",
            )

    def validate_sql(self, code: str) -> ValidationResult:
        """
        Basic SQL syntax validation.

        Checks for:
        - Balanced parentheses
        - Basic keyword patterns
        """
        # Check balanced parentheses
        balance_result = self._check_balanced_delimiters(code)
        if not balance_result["balanced"]:
            self.validation_stats["failures"] += 1
            return ValidationResult(
                success=False,
                errors=[balance_result["error"]],
                warnings=[],
                line_number=balance_result.get("line"),
                suggestion=balance_result.get(
                    "suggestion", "Check parenthesis matching"
                ),
            )

        # Check for unclosed strings
        single_quotes = code.count("'") - code.count("\\'")
        if single_quotes % 2 != 0:
            return ValidationResult(
                success=False,
                errors=["Unclosed string literal (single quote)"],
                warnings=[],
                line_number=None,
                suggestion="Check for missing closing quote",
            )

        return ValidationResult(
            success=True, errors=[], warnings=[], line_number=None, suggestion=None
        )

    def get_stats(self) -> Dict:
        """Get validation statistics"""
        return self.validation_stats.copy()


# Convenience function
def validate_code(code: str, file_path: str) -> ValidationResult:
    """Validate code syntax based on file type"""
    validator = CodeValidator()
    return validator.validate(code, file_path)


if __name__ == "__main__":
    # Test the validator
    validator = CodeValidator()

    # Test Python validation
    print("=" * 60)
    print("Testing Python Validation")
    print("=" * 60)

    # Valid Python
    valid_python = """
def hello():
    print("Hello, World!")
    return True
"""
    result = validator.validate(valid_python, "test.py")
    print(f"Valid Python: {result.success}")

    # Invalid Python (IndentationError)
    invalid_python = """
def hello():
print("Hello")
"""
    result = validator.validate(invalid_python, "test.py")
    print(f"Invalid Python: {result.success}, Errors: {result.errors}")

    # Test JavaScript validation
    print("\n" + "=" * 60)
    print("Testing JavaScript Validation")
    print("=" * 60)

    valid_js = """
function hello() {
    console.log("Hello");
    return { success: true };
}
"""
    result = validator.validate(valid_js, "test.js")
    print(f"Valid JS: {result.success}")

    # Invalid JS (unbalanced braces)
    invalid_js = """
function hello() {
    console.log("Hello");
"""
    result = validator.validate(invalid_js, "test.js")
    print(f"Invalid JS: {result.success}, Errors: {result.errors}")

    print("\n" + "=" * 60)
    print(f"Stats: {validator.get_stats()}")
