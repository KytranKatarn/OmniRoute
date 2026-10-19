"""Reconcile stale code_issues against the current source (#5004).

WHY THIS EXISTS
`code_issues.status` has not been reconciled in over two months. Measured 2026-07-20:

    open   2230   (growing)
    resolved 142  newest row 2026-04-21   <- set only by a manual UI action
    fixed     72  newest row 2026-05-12

Nothing re-checks whether an open finding still exists, so the queue keeps serving findings
that were fixed long ago by unrelated work. Issue #7846 is the proof: it claims
"doc/routes.py line 178 exceeds 120 characters", was created 2026-05-12, and line 178 is now
49 characters. The engine still picked it up on 2026-07-19 and burned an autonomous build
cycle discovering there was nothing to fix.

That also makes the backlog SIZE meaningless, which in turn makes the #4989 drain-yield
numbers meaningless: you cannot compute a fix rate against a denominator full of ghosts.

WHAT IT DOES
Re-validates open findings against the file on disk and marks the provably-gone ones
``resolved_stale``. Deliberately conservative — a finding is only closed when we can READ
the file and DISPROVE the finding. Anything else is left strictly alone:

    verdict False (provably gone)  -> resolved_stale
    verdict True  (still there)    -> untouched
    verdict None  (no checker)     -> untouched, counted as unverifiable
    file missing / synthetic label -> untouched, counted separately

A missing file is NOT treated as "resolved": path resolution can fail for reasons that have
nothing to do with the finding, and silently closing findings on an unreadable path would
hide real work. Deleting a file is handled by the scanner, not here.

NOTE ON DUPLICATION: the equivalent checker in the engine is archie_engine/fix_efficacy.py
(#5003). The platform cannot import from the archie-code repo, so the line-length rule is
restated here. Keep the two in step — both are deliberately tiny and dependency-free.
"""

import ast
import io
import logging
import re

from database import get_db_cursor

logger = logging.getLogger(__name__)

RESOLVED_STALE = "resolved_stale"

# "Line exceeds 120 characters (124)" / "line exceeds 120 chars"
_LINE_LEN_RE = re.compile(r"line\s+exceeds\s+(\d+)\s+char", re.IGNORECASE)

# The three detectors that dominate this table after line-length.
_PRINT_RE = re.compile(r"print statement found", re.IGNORECASE)
_TODO_RE = re.compile(r"todo\s*/\s*fixme", re.IGNORECASE)
_BARE_EXCEPT_RE = re.compile(r"bare except", re.IGNORECASE)

# flake8-style code Repair Bay stores on a pyflakes finding ("F401 'os' imported but unused").
_PYFLAKES_CODE_RE = re.compile(r"\b(?:F\d{3}|PYFLAKES)\b", re.IGNORECASE)

# Security issue checkers (bandit-style findings).
_SECURITY_SQL_INJECTION_RE = re.compile(r"potential\s+sql\s+injection", re.IGNORECASE)
_SECURITY_HARDCODED_SECRET_RE = re.compile(
    r"hardcoded\s+secret|hardcoded\s+password|hardcoded\s+key|database\s+password\s+is\s+hardcoded|password\s+is\s+stored\s+in\s+plain\s+text|hardcoded\s+ip",
    re.IGNORECASE,
)
_SECURITY_SUBPROCESS_RE = re.compile(
    r"subprocess.*elevated|subprocess.*shell.*true|subprocess.*run.*without.*check", re.IGNORECASE
)
_SECURITY_DB_CRED_RE = re.compile(
    r"database\s+credential|_get_db_password|environment\s+variable.*database|database\s+password", re.IGNORECASE
)
_SECURITY_INSECURE_REF_RE = re.compile(
    r"insecure\s+direct\s+object\s+reference|direct\s+object\s+reference", re.IGNORECASE
)
_SECURITY_OS_ENV_RE = re.compile(
    r"os\.getenv|environment\s+variable.*without\s+default|missing\s+default", re.IGNORECASE
)
_SECURITY_OS_FDOPEN_RE = re.compile(r"os\.fdopen|fdopen", re.IGNORECASE)
_SECURITY_EXCEPTION_HANDLING_RE = re.compile(
    r"exception\s+handling|bare\s+except|catching\s+all\s+exceptions", re.IGNORECASE
)
_SECURITY_LOGGING_RE = re.compile(r"logging.*exception|exc_info|exception.*logging", re.IGNORECASE)

# Bandit rule code → checker function mapping.
# When a finding carries an `issue_code` (e.g., "B608"), we dispatch directly
# instead of relying on message text matching. This is more reliable and
# enables the checker to be line-precise.
_BANDIT_CHECKERS: dict[str, callable] = {}


def _register_bandit_checker(rule_code: str, fn: callable) -> None:
    """Register a checker for a bandit rule code (e.g., 'B608')."""
    _BANDIT_CHECKERS[rule_code.upper()] = fn


# ============================================================
# Bandit rule → checker mappings (line-precise when line_number provided)
# ============================================================


def _bandit_b608_hardcoded_sql(file_text: str, line_number: int = None) -> bool | None:
    """B608: Hardcoded SQL expressions - check for string formatting in SQL."""
    return _check_sql_injection_at_line(file_text, line_number)


def _bandit_b602_subprocess_shell(file_text: str, line_number: int = None) -> bool | None:
    """B602: subprocess call with shell=True."""
    return _check_subprocess_at_line(file_text, line_number)


def _bandit_b108_hardcoded_password(file_text: str, line_number: int = None) -> bool | None:
    """B108: Hardcoded password string."""
    return _check_hardcoded_secret_at_line(file_text, line_number)


def _bandit_b105_hardcoded_password_string(file_text: str, line_number: int = None) -> bool | None:
    """B105: Hardcoded password string."""
    return _check_hardcoded_secret_at_line(file_text, line_number)


def _bandit_b104_hardcoded_binding(file_text: str, line_number: int = None) -> bool | None:
    """B104: Hardcoded binding address."""
    return _check_hardcoded_secret_at_line(file_text, line_number)


def _bandit_b106_hardcoded_password_funcarg(file_text: str, line_number: int = None) -> bool | None:
    """B106: Hardcoded password in function argument."""
    return _check_hardcoded_secret_at_line(file_text, line_number)


def _bandit_b107_hardcoded_password_default(file_text: str, line_number: int = None) -> bool | None:
    """B107: Hardcoded password default value."""
    return _check_hardcoded_secret_at_line(file_text, line_number)


def _bandit_b322_input_validation(file_text: str, line_number: int = None) -> bool | None:
    """B322: Input validation - generic pattern."""
    if line_number:
        return _check_sql_injection_at_line(file_text, line_number)
    return None


def _bandit_b311_random(file_text: str, line_number: int = None) -> bool | None:
    """B311: Standard pseudo-random generators are not suitable for security/cryptographic purposes."""
    if line_number:
        lines = (file_text or "").splitlines()
        if line_number < 1 or line_number > len(lines):
            return None
        line = lines[line_number - 1]
        import re

        if re.search(r"random\.(random|randint|choice|uniform)", line):
            return True
    return False


def _bandit_b303_md5(file_text: str, line_number: int = None) -> bool | None:
    """B303: Use of insecure hash (MD5)."""
    if line_number:
        lines = (file_text or "").splitlines()
        if line_number < 1 or line_number > len(lines):
            return None
        line = lines[line_number - 1]
        if re.search(r"hashlib\.md5|md5\s*\(", line):
            return True
    return False


def _bandit_b304_cipher_modes(file_text: str, line_number: int = None) -> bool | None:
    """B304: Cipher modes - ECB mode is insecure."""
    if line_number:
        lines = (file_text or "").splitlines()
        if line_number < 1 or line_number > len(lines):
            return None
        line = lines[line_number - 1]
        if re.search(r"\.ECB\b|MODE_ECB", line):
            return True
    return False


# Register bandit checkers
_register_bandit_checker("B608", _bandit_b608_hardcoded_sql)
_register_bandit_checker("B602", _bandit_b602_subprocess_shell)
_register_bandit_checker("B108", _bandit_b108_hardcoded_password)
_register_bandit_checker("B105", _bandit_b105_hardcoded_password_string)
_register_bandit_checker("B104", _bandit_b104_hardcoded_binding)
_register_bandit_checker("B106", _bandit_b106_hardcoded_password_funcarg)
_register_bandit_checker("B107", _bandit_b107_hardcoded_password_default)
_register_bandit_checker("B322", _bandit_b322_input_validation)
_register_bandit_checker("B311", _bandit_b311_random)
_register_bandit_checker("B303", _bandit_b303_md5)
_register_bandit_checker("B304", _bandit_b304_cipher_modes)

# ============================================================
# Line-precise security checkers (use line_number when available)
# ============================================================


def _check_sql_injection_at_line(file_text: str, line_number: int) -> bool | None:
    """Check if the specific line has a SQL injection pattern.

    Returns True (vulnerable), False (safe/parameterized), None (unverifiable).

    Looks for:
    - execute/executemany with f-string, string concatenation, or format()
    - Cursor execute with string interpolation (% operator on query string)

    SAFE patterns (return False):
    - Parameterized queries: cursor.execute("SELECT ... %s", params) - %s is DB-API placeholder
    - Literal query strings with no interpolation
    """
    import re

    try:
        tree = ast.parse(file_text or "")
    except (SyntaxError, ValueError):
        return None

    lines = (file_text or "").splitlines()
    if line_number < 1 or line_number > len(lines):
        return None

    target_line = lines[line_number - 1].strip()

    # Quick text-based check first for the exact line
    # Skip lines that are clearly parameterized queries (DB-API %s placeholders)
    if re.search(r'\.(execute|executemany)\s*\(\s*["\'][^"\']*%\w+[^"\']*["\']\s*,', target_line, re.IGNORECASE):
        # Pattern: execute("... %s ...", params) - parameterized query, SAFE
        return False

    vulnerable_patterns = [
        r'\.execute\s*\(\s*f["\']',  # f-string in execute
        r"\.execute\s*\(\s*[^)]*\+[^)]*\)",  # string concatenation
        r"\.execute\s*\(\s*[^)]*\.format\s*\(",  # .format() in execute
        r'\.executemany\s*\(\s*f["\']',  # f-string in executemany
        r"\.executemany\s*\(\s*[^)]*\+[^)]*\)",  # concatenation in executemany
        r"\.executemany\s*\(\s*[^)]*\.format\s*\(",  # .format() in executemany
        # % operator on query string (not DB-API placeholder) - check AST below
    ]

    for pattern in vulnerable_patterns:
        if re.search(pattern, target_line, re.IGNORECASE):
            return True

    # Also check the AST for execute/executemany calls on this line
    for node in ast.walk(ast.parse(file_text or "")):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in ("execute", "executemany")
            and hasattr(node, "lineno")
            and node.lineno == line_number
        ):

            query = node.args[0] if node.args else None
            if query is None:
                return None

            # Check if the query is a parameterized literal (SAFE)
            if isinstance(query, ast.Constant) and isinstance(query.value, str):
                # Check if the string contains only DB-API placeholders (%s, %d, etc.)
                # and no actual string formatting
                sql = query.value
                # If the string has %s/%d placeholders but NO % formatting operator in the AST,
                # it's a parameterized query (SAFE)
                return False

            # Check for f-string (UNSAFE - string interpolation)
            if isinstance(query, ast.JoinedStr):
                return True

            # Check for string interpolation % (UNSAFE) - using % operator on query string
            if isinstance(query, ast.BinOp) and isinstance(query.op, ast.Mod):
                # This is "query % params" - UNSAFE string formatting
                return True

            # Check for .format() (UNSAFE - string formatting)
            if isinstance(query, ast.Call) and isinstance(query.func, ast.Attribute) and query.func.attr == "format":
                return True

            # Check for string concatenation with variables (UNSAFE)
            if isinstance(query, ast.BinOp) and isinstance(query.op, ast.Add):

                def _is_literal_string(node):
                    if isinstance(node, ast.Constant):
                        return isinstance(node.value, str)
                    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
                        return _is_literal_string(node.left) and _is_literal_string(node.right)
                    return False

                if not _is_literal_string(query):
                    return True

            # If we can't prove it's safe, assume vulnerable
            return True

    return None  # No execute/executemany on this line


def _check_hardcoded_secret_at_line(file_text: str, line_number: int) -> bool | None:
    """Check if the specific line has a hardcoded secret pattern."""
    lines = (file_text or "").splitlines()
    if line_number < 1 or line_number > len(lines):
        return None
    line = lines[line_number - 1]
    import re

    patterns = [
        r'password\s*[=:]\s*["\'][^"\']{8,}["\']',
        r'api[_-]?key\s*[=:]\s*["\'][^"\']{16,}["\']',
        r'secret\s*[=:]\s*["\'][^"\']{16,}["\']',
        r'token\s*[=:]\s*["\'][^"\']{16,}["\']',
        r"\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b",
    ]
    for pattern in patterns:
        if re.search(pattern, line, re.IGNORECASE):
            return True
    return False


def _check_subprocess_at_line(file_text: str, line_number: int) -> bool | None:
    """Check if the specific line has subprocess shell=True or unchecked return code."""
    lines = (file_text or "").splitlines()
    if line_number < 1 or line_number > len(lines):
        return None
    line = lines[line_number - 1]
    # Check for shell=True in subprocess call
    if re.search(r"subprocess\.(run|Popen|call)\s*\([^)]*shell\s*=\s*True", line, re.IGNORECASE):
        return True
    # Check for run without check=True
    if re.search(r"subprocess\.run\s*\([^)]*(?<!check\s*=\s*True)", line, re.IGNORECASE):
        return True
    return False


def _check_db_cred_at_line(file_text: str, line_number: int) -> bool | None:
    """Check if the specific line has database credential access patterns."""
    lines = (file_text or "").splitlines()
    if line_number < 1 or line_number > len(lines):
        return None
    line = lines[line_number - 1]
    patterns = [
        r"_get_db_password\s*\(",
        r'os\.getenv\s*\(\s*["\'].*PASSWORD["\']',
        r'os\.getenv\s*\(\s*["\'].*DATABASE["\']',
        r'database.*password.*["\']',
    ]
    for pattern in patterns:
        if re.search(pattern, line, re.IGNORECASE):
            return True
    return False


def _check_os_env_at_line(file_text: str, line_number: int) -> bool | None:
    """Check if the specific line has os.getenv without default."""
    lines = (file_text or "").splitlines()
    if line_number < 1 or line_number > len(lines):
        return None
    line = lines[line_number - 1]
    # Check for os.getenv without default value
    if re.search(r'os\.getenv\s*\(\s*["\'][^"\']+["\']\s*\)', line):
        return True
    return False


def _check_os_fdopen_at_line(file_text: str, line_number: int) -> bool | None:
    """Check if the specific line uses os.fdopen."""
    lines = (file_text or "").splitlines()
    if line_number < 1 or line_number > len(lines):
        return None
    line = lines[line_number - 1]
    if re.search(r"os\.fdopen|fdopen\s*\(", line):
        return True
    return False


def _check_bare_except_at_line(file_text: str, line_number: int) -> bool | None:
    """Check if the specific line has a bare except handler."""
    try:
        tree = ast.parse(file_text or "")
    except (SyntaxError, ValueError):
        return None
    for node in ast.walk(ast.parse(file_text or "")):
        if (
            isinstance(node, ast.ExceptHandler)
            and node.type is None
            and hasattr(node, "lineno")
            and node.lineno == line_number
        ):
            return True
    return False


def _parse(file_text: str):
    """AST for the source, or None when it does not parse.

    None means "cannot verify" — never "the finding is gone". A file that fails to parse
    must leave its findings open rather than have them silently closed.
    """
    try:
        return ast.parse(file_text or "")
    except (SyntaxError, ValueError):
        return None


# Findings sometimes arrive without a code — recognise pyflakes' own wording too.
_PYFLAKES_PHRASES = (
    "imported but unused",
    "assigned to but never used",
    "undefined name",
    "redefinition of unused",
    "f-string is missing placeholders",
    "unable to detect undefined names",
)


def _pyflakes_findings(file_text: str):
    """(messages, ok) — pyflakes' own text for this source.

    ok is False when the source could not be analysed at all (pyflakes missing, or the file
    does not parse). A syntax error must NEVER read as "the finding is gone": pyflakes emits
    nothing but the syntax error itself, which would otherwise look like a clean file and
    close a finding that is still very much there.
    """
    try:
        from pyflakes.api import check as pyflakes_check
        from pyflakes.reporter import Reporter
    except ImportError:
        return [], False

    out, err = io.StringIO(), io.StringIO()
    try:
        pyflakes_check(file_text or "", "target", Reporter(out, err))
    except Exception:
        return [], False
    if err.getvalue().strip():  # syntax error / unparseable
        return [], False
    return out.getvalue().splitlines(), True


def _needle_from_message(message: str) -> str:
    """Strip the flake8 code prefix, leaving pyflakes' own wording.

    Repair Bay stores "F401 'os' imported but unused"; pyflakes itself emits
    "target:1:1 'os' imported but unused" — no code. Comparing the descriptive tail is what
    makes the two comparable.
    """
    text = _PYFLAKES_CODE_RE.sub("", (message or "").strip(), count=1).strip()
    # ruff quotes names with BACKTICKS (`os`); pyflakes emits 'os'. Without unifying the
    # quoting, every ruff-sourced row read as "provably gone" while still present — the
    # reconciler archived it daily and the next audit recreated it (2026-08-27 oscillator).
    text = text.replace("`", "'")
    return text.strip(" -:")


def finding_still_reproduces(message: str, file_text: str, line_number=None):
    """Does the finding described by ``message`` still hold for ``file_text``?

    Returns True (still present), False (provably gone), or None (no deterministic checker).
    None must never be treated as "gone" — this function decides whether a row gets CLOSED.

    ``line_number`` (optional) makes the line-length check precise instead of whole-file.
    Omitting it preserves the original whole-file behaviour.

    Mirrors archie_engine/fix_efficacy.py (#5003). The platform cannot import from the
    archie-code repo, so the rules are restated. KEEP THE TWO IN STEP.
    """
    if (message or "").startswith("LARGE_FILE "):
        # Match the Python-module scanner's threshold and newline counting.
        # The stored detail is a historical size, not the current threshold.
        return (file_text or "").count("\n") + 1 > 600

    if (message or "").startswith("SQL_INJECTION_RISK"):
        from services.code_health_checks import sql_finding_present

        return sql_finding_present(file_text)

    if (message or "").startswith(("DIRECT_OLLAMA", "DIRECT_CLOUD")):
        from services.code_health_checks import direct_call_present

        names = ("call_ollama",) if message.startswith("DIRECT_OLLAMA") else ("call_claude_api", "call_openai_api")
        return direct_call_present(file_text, names)

    # Interface-sweep proposals often survive a corrected import because the
    # generic checker cannot recognize them. Only prove REMOVAL here: keeping
    # the same import means unknown, not a claim that runtime resolution works.
    import_match = re.match(
        r"^(?:WRONG_ROOT_IMPORT|WRONG_SUBMODULE_IMPORT) import (?:from )?'([^']+)'",
        message or "",
    )
    symbol_match = re.match(r"^MISSING_SYMBOL '([^']+)' is not exported by '([^']+)'", message or "")
    if import_match or symbol_match:
        tree = _parse(file_text)
        if tree is None:
            return None
        module = import_match.group(1) if import_match else symbol_match.group(2)
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.level == 0 and node.module == module:
                if import_match or any(alias.name == symbol_match.group(1) for alias in node.names):
                    return None
            if import_match and isinstance(node, ast.Import):
                if any(alias.name == module for alias in node.names):
                    return None
        return False

    m = _LINE_LEN_RE.search(message or "")
    if m:
        try:
            limit = int(m.group(1))
        except ValueError:
            return None
        lines = (file_text or "").splitlines()

        # LINE-PRECISE when we have a usable line number.
        #
        # The whole-file rule ("does this file violate the limit ANYWHERE?") is safe but
        # wildly imprecise on clustered findings: ai_bridge/agent_loop.py carries 422
        # line-length findings while the file actually has FIFTEEN long lines. One survivor
        # kept all 422 open, so the backlog reported 28x its real debt and its size meant
        # nothing — which defeats the point of reconciling at all.
        #
        # TRADE-OFF, stated plainly: if a file was reformatted and the long line MOVED, the
        # cited line is now short and this closes the finding while the problem persists
        # elsewhere. That is acceptable because the scanner re-files it at its new line on the
        # next run, whereas the inflation is permanent and silent. Falls back to the whole-file
        # rule whenever the line number is missing or out of range.
        if line_number and 1 <= int(line_number) <= len(lines):
            return len(lines[int(line_number) - 1]) > limit
        return any(len(ln) > limit for ln in lines)

    msg = message or ""

    # --- the detectors that actually dominate this table (measured 2026-07-20) -------------
    # print 1129 · line-length 725 · SQL injection 275 · TODO/FIXME 31 · secret 10 · bare-except 6
    # Each ignores the stored line NUMBER for the same reason line-length does: unrelated edits
    # shift lines, so the honest question is whether the FILE still exhibits the problem. That
    # biases toward KEEPING findings open, the safe direction for something that closes rows.
    if _PRINT_RE.search(msg):
        tree = _parse(file_text)
        if tree is None:
            return None
        return any(
            isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "print" for n in ast.walk(tree)
        )

    if _BARE_EXCEPT_RE.search(msg):
        tree = _parse(file_text)
        if tree is None:
            return None
        return any(isinstance(n, ast.ExceptHandler) and n.type is None for n in ast.walk(tree))

    if _TODO_RE.search(msg):
        # Deliberately a plain substring scan, not a comment-aware parse: a TODO inside a
        # string still reads as "the marker is present", which keeps the finding open.
        text = file_text or ""
        return ("TODO" in text) or ("FIXME" in text)

    if _PYFLAKES_CODE_RE.search(msg) or any(p in msg.lower() for p in _PYFLAKES_PHRASES):
        needle = _needle_from_message(msg)
        if len(needle) < 8:  # nothing distinctive left to compare
            return None
        findings, ok = _pyflakes_findings(file_text)
        if not ok:
            return None
        # Per-finding match: an unrelated warning elsewhere in the file must not mask a
        # genuine fix, and must not keep a dead finding alive.
        return any(needle in line for line in findings)

    # Security issue checkers (bandit-style findings) — LINE PRECISE
    # First check if we have a bandit rule code (issue_code) for direct dispatch
    issue_code = None
    # Try to extract bandit rule code from message (format: "B608: ..." or "[B608] ...")
    bandit_code_match = re.match(r"^([A-Z]\d{3})[:\]\s]", msg)
    if bandit_code_match:
        issue_code = bandit_code_match.group(1).upper()
        if issue_code in _BANDIT_CHECKERS:
            # Dispatch to bandit-specific checker with line precision
            return _BANDIT_CHECKERS[issue_code](file_text, line_number)

    # SQL injection - LINE PRECISE: check the specific line for SQL injection patterns
    if _SECURITY_SQL_INJECTION_RE.search(msg):
        if line_number:
            return _check_sql_injection_at_line(file_text, line_number)
        # Fallback to whole-file checker if no line number
        from services.code_health_checks import sql_finding_present

        return sql_finding_present(file_text)

    # Hardcoded secrets / passwords / keys / IPs - LINE PRECISE
    if _SECURITY_HARDCODED_SECRET_RE.search(msg):
        if line_number:
            return _check_hardcoded_secret_at_line(file_text, line_number)
        # Fallback to whole-file checker
        tree = _parse(file_text)
        if tree is None:
            return None
        source = file_text or ""
        patterns = [
            r'password\s*[=:]\s*["\'][^"\']{8,}["\']',
            r'api[_-]?key\s*[=:]\s*["\'][^"\']{16,}["\']',
            r'secret\s*[=:]\s*["\'][^"\']{16,}["\']',
            r'token\s*[=:]\s*["\'][^"\']{16,}["\']',
            r"\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b",
        ]
        for pattern in patterns:
            if re.search(pattern, source, re.IGNORECASE):
                return True
        return False

    # Subprocess security issues - LINE PRECISE
    if _SECURITY_SUBPROCESS_RE.search(msg):
        if line_number:
            return _check_subprocess_at_line(file_text, line_number)
        # Fallback to whole-file checker
        tree = _parse(file_text)
        if tree is None:
            return None
        return any(
            isinstance(n, ast.Call)
            and isinstance(n.func, ast.Attribute)
            and n.func.attr in ("run", "Popen", "call")
            and any(
                isinstance(kw, ast.keyword)
                and kw.arg in ("shell", "check")
                and isinstance(kw.value, ast.Constant)
                and kw.value.value is True
                for kw in n.keywords
            )
            for n in ast.walk(tree)
        )

    # Database credential / password handling - LINE PRECISE
    if _SECURITY_DB_CRED_RE.search(msg):
        if line_number:
            return _check_db_cred_at_line(file_text, line_number)
        # Fallback to whole-file checker
        tree = _parse(file_text)
        if tree is None:
            return None
        source = file_text or ""
        patterns = [
            r"_get_db_password\s*\(",
            r'os\.getenv\s*\(\s*["\'].*PASSWORD["\']',
            r'os\.getenv\s*\(\s*["\'].*DATABASE["\']',
            r'database.*password.*["\']',
        ]
        for pattern in patterns:
            if re.search(pattern, source, re.IGNORECASE):
                return True
        return False

    # Insecure direct object reference
    if _SECURITY_INSECURE_REF_RE.search(msg):
        # Can't reliably disprove without context; keep open
        return None

    # os.getenv / environment variable issues - LINE PRECISE
    if _SECURITY_OS_ENV_RE.search(msg):
        if line_number:
            return _check_os_env_at_line(file_text, line_number)
        # Fallback to whole-file checker
        tree = _parse(file_text)
        if tree is None:
            return None
        return any(
            isinstance(n, ast.Call)
            and isinstance(n.func, ast.Attribute)
            and n.func.attr == "getenv"
            and isinstance(n.func.value, ast.Name)
            and n.func.value.id == "os"
            for n in ast.walk(tree)
        )

    # os.fdopen usage - LINE PRECISE
    if _SECURITY_OS_FDOPEN_RE.search(msg):
        if line_number:
            return _check_os_fdopen_at_line(file_text, line_number)
        # Fallback to whole-file checker
        tree = _parse(file_text)
        if tree is None:
            return None
        return any(
            isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "fdopen"
            for n in ast.walk(tree)
        )

    # Exception handling issues - LINE PRECISE
    if _SECURITY_EXCEPTION_HANDLING_RE.search(msg):
        if line_number:
            return _check_bare_except_at_line(file_text, line_number)
        # Fallback to whole-file checker
        tree = _parse(file_text)
        if tree is None:
            return None
        return any(isinstance(n, ast.ExceptHandler) and n.type is None for n in ast.walk(tree))

    # Logging issues
    if _SECURITY_LOGGING_RE.search(msg):
        # Can't reliably check; keep open
        return None

    # #6054 -- LAST resort, deliberately scoped to messages NO checker recognised.
    # code_issues #8393 ('performance' prose at line 25847 of a 744-line file) had no
    # deterministic checker, so it returned None here and stayed open forever -- until
    # the engine pulled it and answered with a destructive rewrite (PR #2861). For an
    # unrecognised message the cited line is the ONLY evidence we have, and a line
    # beyond EOF is proof the anchor is dead (the caller skips unreadable files before
    # calling, so file_text is a real read). Recognised classes keep their own
    # fallbacks -- the line-length whole-file rule above stays authoritative, per
    # test_out_of_range_line_falls_back_to_whole_file.
    if line_number:
        try:
            _ln = int(line_number)
        except (TypeError, ValueError):
            _ln = 0
        if _ln > 0 and _ln > len((file_text or "").splitlines()):
            return False

    return None


# --- proposal-side reconciliation (#5004) --------------------------------------------------
# The Consciousness > Code Health tab's Department Orchestration panel reads
# improvement_proposals (source='code_health_audit'), NOT code_issues. Reconciling only
# code_issues therefore never moved the number anyone actually looks at.

# Proposal `detail` carries the finding text WITH a trailing "(line 1008)" that the tool
# itself never emits. Leaving it on makes every pyflakes needle fail to match, so every such
# proposal reads as "gone". Measured: stripping it moved the tally from 385-gone/0-present
# (impossible) to 331-gone/281-present. A 0-present result is the tell that a matcher is
# broken, not that a queue is clean.
_TRAILING_LINE_RE = re.compile(r"\s*\(line \d+\)\s*$")

PROPOSAL_STALE_REASON = "stale:finding_resolved"


def proposal_message(issue_code: str, detail: str) -> str:
    """Finding text for a proposal, normalised for the checkers."""
    joined = " ".join(x for x in (issue_code or "", detail or "") if x).strip()
    return _TRAILING_LINE_RE.sub("", joined).strip()


def finding_fingerprint(issue_code: str, detail: str) -> str:
    """Detector-neutral identity for a finding: code prefix stripped, quoting unified,
    trailing '(line N)' removed. Equal fingerprints mean the SAME defect reported by
    different detectors (ruff F401 vs the static PYFLAKES tier) — the identity that
    creation-time dedup in audit_pipeline keys on, so twin rows for one finding can
    no longer be minted (the 11235/11259 double, 2026-08-27)."""
    return _needle_from_message(proposal_message(issue_code, detail))


def _read_proposal_file(runtime_file: str, file_path: str):
    """Source for a proposal. ``runtime_file`` is the absolute path the scanner already
    resolved, so it is tried first; ``file_path`` falls back through the pipeline's shared
    resolver. Returns None when neither can be read — which never closes anything."""
    import os

    if runtime_file and os.path.isfile(runtime_file):
        try:
            with open(runtime_file, "r", encoding="utf-8", errors="replace") as fh:
                return fh.read()
        except OSError:
            pass
    text, _reason = _read_source(file_path)
    return text


def reconcile_open_proposals(limit: int = 3000, dry_run: bool = True, statuses=("approved",), module_name=None) -> dict:
    """Archive code-health proposals whose finding provably no longer reproduces.

    Same conservative contract as reconcile_open_issues: a proposal is archived ONLY when the
    file can be read AND the finding disproved. Unreadable, unparseable, or no-checker all
    leave the row untouched. dry_run=True by default.

    Archives rather than inventing a status — it matches the existing sweep convention
    (metadata archived_by / archive_reason / archived_at), so provenance stays uniform with
    the #2333 unfixable-path archiver.
    """
    stats = {
        "examined": 0,
        "stale": 0,
        "still_present": 0,
        "unverifiable": 0,
        "unreadable": 0,
        "archived": 0,
        "cards_cancelled": 0,
        "dry_run": dry_run,
        "samples": [],
        "unverifiable_samples": [],
    }

    module_filter = ""
    params = [list(statuses)]
    if module_name:
        module_filter = """AND (module_name = %s OR metadata->>'module_name' = %s
                            OR metadata->>'file_path' LIKE %s
                            OR metadata->>'file_path' LIKE %s)"""
        # Escape LIKE metacharacters in module keys (e.g. family_tree).
        escaped = module_name.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        params.extend([module_name, module_name, f"platform_v2/tools/{escaped}/%", f"[APP_CORE]/tools/{escaped}/%"])
    params.append(limit)
    with get_db_cursor(commit=False) as (conn, cur):
        cur.execute(
            f"""SELECT id,
                      metadata->>'issue_code'      AS issue_code,
                      metadata->>'bandit_issue_code' AS bandit_issue_code,
                      metadata->>'detail'       AS detail,
                      metadata->>'runtime_file' AS runtime_file,
                      metadata->>'file_path'    AS file_path,
                      metadata->>'line'         AS line
               FROM improvement_proposals
               WHERE status = ANY(%s)
                 AND metadata->>'source' = 'code_health_audit'
                 {module_filter}
               ORDER BY id
               LIMIT %s""",
            tuple(params),
        )
        rows = cur.fetchall()

    cache: dict = {}
    to_archive: list = []

    for row in rows:
        stats["examined"] += 1
        key = row["runtime_file"] or row["file_path"]
        if key not in cache:
            cache[key] = _read_proposal_file(row["runtime_file"], row["file_path"])
        text = cache[key]
        if text is None:
            stats["unreadable"] += 1
            continue

        line_no = None
        raw_line = (row["line"] or "").strip()
        if raw_line.isdigit():
            line_no = int(raw_line)

        # Use bandit_issue_code for bandit checker dispatch (e.g., B608, B602)
        bandit_code = row.get("bandit_issue_code")
        msg_for_checker = proposal_message((bandit_code or row["issue_code"]), row["detail"])
        verdict = finding_still_reproduces(msg_for_checker, text, line_no)
        if verdict is None:
            stats["unverifiable"] += 1
            if len(stats["unverifiable_samples"]) < 10:
                stats["unverifiable_samples"].append(
                    {
                        "id": row["id"],
                        "code": row.get("bandit_issue_code") or row["issue_code"],
                        "detail": (row["detail"] or "")[:70],
                    }
                )
        elif verdict:
            stats["still_present"] += 1
        else:
            stats["stale"] += 1
            to_archive.append(row["id"])
            if len(stats["samples"]) < 5:
                stats["samples"].append(
                    {
                        "id": row["id"],
                        "code": row.get("bandit_issue_code") or row["issue_code"],
                        "detail": (row["detail"] or "")[:70],
                    }
                )

    if to_archive and not dry_run:
        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                """UPDATE improvement_proposals
                   SET status = 'archived',
                       metadata = COALESCE(metadata, '{}'::jsonb) || jsonb_build_object(
                           'archived_by',   'reconciler_5004',
                           'archive_reason', %s,
                           'archived_at',    NOW()::text,
                           'fix_verified',   true)
                   WHERE id = ANY(%s) AND status = ANY(%s)""",
                (PROPOSAL_STALE_REASON, to_archive, list(statuses)),
            )
            stats["archived"] = cur.rowcount
            # An archived proposal's approval cards die WITH it — otherwise a
            # stale ready_for_review twin keeps a live deploy_approve card that
            # the owner can tap only to hit the sandbox gate's "patch does not
            # apply" (6 taps burned on already-fixed findings, 2026-08-28).
            cur.execute(
                """UPDATE autonomy_approval_queue
                   SET status = 'cancelled',
                       rejected_reason = 'proposal archived: finding no longer reproduces (reconciler_5004)',
                       updated_at = NOW()
                   WHERE status = 'pending'
                     AND action_type IN ('deploy_approve', 'improvement_approve_red')
                     AND action_data->>'proposal_id' = ANY(%s)""",
                ([str(pid) for pid in to_archive],),
            )
            stats["cards_cancelled"] = cur.rowcount
        logger.info(
            "[proposal-reconciler] archived %d stale proposal(s) of %d (%d approval card(s) cancelled)",
            stats["archived"],
            stats["examined"],
            stats["cards_cancelled"],
        )
    else:
        logger.info(
            "[proposal-reconciler] dry-run: %d stale / %d examined (%d present, %d unverifiable, %d unreadable)",
            stats["stale"],
            stats["examined"],
            stats["still_present"],
            stats["unverifiable"],
            stats["unreadable"],
        )
        if stats["unverifiable_samples"]:
            logger.info(
                "[proposal-reconciler] unverifiable samples: %s",
                stats["unverifiable_samples"],
            )
    return stats


def _read_source(file_path: str):
    """(text, reason) — text is None when the file can't be read. Reuses the pipeline's
    single source of truth for path resolution + #4979 path containment."""
    try:
        from services.audit_pipeline import resolve_proposal_source
    except Exception as exc:  # pragma: no cover - import guard
        return None, f"resolver unavailable: {exc}"

    abs_path, _display, status = resolve_proposal_source(file_path)
    if status != "ok" or not abs_path:
        return None, status
    try:
        with open(abs_path, "r", encoding="utf-8", errors="replace") as fh:
            return fh.read(), "ok"
    except OSError as exc:
        return None, f"unreadable: {exc}"


def reconcile_open_issues(limit: int = 500, dry_run: bool = True) -> dict:
    """Re-validate open findings; close the provably-gone ones.

    ``dry_run=True`` (the default) changes nothing and reports what WOULD be closed, so the
    job can be inspected before it is ever allowed to write.
    """
    stats = {
        "examined": 0,
        "stale": 0,
        "still_present": 0,
        "unverifiable": 0,
        "unreadable": 0,
        "closed": 0,
        "dry_run": dry_run,
        "samples": [],
    }

    with get_db_cursor(commit=False) as (conn, cur):
        cur.execute(
            """SELECT id, file_path, message, line_number
               FROM code_issues
               WHERE status = 'open' AND file_path IS NOT NULL
               ORDER BY id
               LIMIT %s""",
            (limit,),
        )
        rows = cur.fetchall()

    # Cache per file: one read serves every finding in that file (agent_loop.py alone has 485).
    cache: dict = {}
    to_close: list = []

    for row in rows:
        stats["examined"] += 1
        fp = row["file_path"]
        if fp not in cache:
            cache[fp] = _read_source(fp)
        text, reason = cache[fp]
        if text is None:
            stats["unreadable"] += 1
            continue
        verdict = finding_still_reproduces(row["message"] or "", text, row.get("line_number"))
        if verdict is None:
            stats["unverifiable"] += 1
        elif verdict:
            stats["still_present"] += 1
        else:
            stats["stale"] += 1
            to_close.append(row["id"])
            if len(stats["samples"]) < 5:
                stats["samples"].append(
                    {"id": row["id"], "file": fp, "line": row["line_number"], "message": (row["message"] or "")[:70]}
                )

    if to_close and not dry_run:
        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                """UPDATE code_issues
                   SET status = %s, fixed_by = 'reconciler', fixed_at = NOW()
                   WHERE id = ANY(%s) AND status = 'open'""",
                (RESOLVED_STALE, to_close),
            )
            stats["closed"] = cur.rowcount
        logger.info(
            "[code-issue-reconciler] closed %d stale finding(s) of %d examined", stats["closed"], stats["examined"]
        )
    else:
        logger.info(
            "[code-issue-reconciler] dry-run: %d stale / %d examined (%d still present, %d unverifiable)",
            stats["stale"],
            stats["examined"],
            stats["still_present"],
            stats["unverifiable"],
        )
    return stats


# ============================================================
# Event-driven reconciler trigger (for PR merge / file change)
# ============================================================


def enqueue_reconciler_for_files(file_paths: list[str], dry_run: bool = False) -> dict:
    """Event-driven trigger: enqueue reconciler for specific files.

    Call this after a PR merge, file write, or engine fix to immediately
    re-validate findings in the changed files instead of waiting for the
    hourly batch. This dramatically reduces the "stale finding" window.

    Args:
        file_paths: List of file paths (relative to repo root) to re-validate.
        dry_run: If True, report what would be closed without writing.

    Returns:
        Stats dict with closed/still_present counts for the given files.
    """
    stats = {
        "examined": 0,
        "stale": 0,
        "still_present": 0,
        "unverifiable": 0,
        "unreadable": 0,
        "closed": 0,
        "dry_run": dry_run,
        "samples": [],
    }

    # Normalize file paths
    normalized = [fp.lstrip("./") for fp in file_paths if fp]
    if not normalized:
        return stats

    placeholders = ",".join(["%s"] * len(normalized))
    with get_db_cursor(commit=False) as (conn, cur):
        cur.execute(
            f"""SELECT id, file_path, message, line_number
               FROM code_issues
               WHERE status = 'open'
                 AND file_path IS NOT NULL
                 AND file_path IN ({placeholders})""",
            tuple(normalized),
        )
        rows = cur.fetchall()

    if not rows:
        return stats

    cache: dict = {}
    to_close: list = []

    for row in rows:
        stats["examined"] += 1
        fp = row["file_path"]
        if fp not in cache:
            cache[fp] = _read_source(fp)
        text, reason = cache[fp]
        if text is None:
            stats["unreadable"] += 1
            continue
        verdict = finding_still_reproduces(row["message"] or "", text, row.get("line_number"))
        if verdict is None:
            stats["unverifiable"] += 1
        elif verdict:
            stats["still_present"] += 1
        else:
            stats["stale"] += 1
            to_close.append(row["id"])
            if len(stats["samples"]) < 5:
                stats["samples"].append(
                    {"id": row["id"], "file": fp, "line": row["line_number"], "message": (row["message"] or "")[:70]}
                )

    if to_close and not dry_run:
        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                """UPDATE code_issues
                   SET status = %s, fixed_by = 'reconciler', fixed_at = NOW()
                   WHERE id = ANY(%s) AND status = 'open'""",
                (RESOLVED_STALE, to_close),
            )
            stats["closed"] = cur.rowcount
        logger.info(
            "[code-issue-reconciler:event] closed %d stale finding(s) of %d examined for files: %s",
            stats["closed"],
            stats["examined"],
            ", ".join(normalized),
        )
    else:
        logger.info(
            "[code-issue-reconciler:event] dry-run: %d stale / %d examined (%d still present, %d unverifiable)",
            stats.get("stale", 0),
            stats["examined"],
            stats["still_present"],
            stats["unverifiable"],
        )
    return stats


def reconcile_open_issues_for_files(file_paths: list[str], dry_run: bool = True) -> dict:
    """Convenience wrapper for manual/CLI use: run reconciler on specific files.

    Unlike enqueue_reconciler_for_files, this uses the same batch logic as the
    hourly job but restricted to the given file paths. Useful for CLI/debug.
    """
    return enqueue_reconciler_for_files(file_paths, dry_run=dry_run)
