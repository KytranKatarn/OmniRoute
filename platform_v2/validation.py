"""
Input Validation Utility Module
Provides validation functions for all API endpoints

Purpose:
- Prevent injection attacks (SQL, XSS, command injection)
- Validate data types and formats
- Sanitize user input
- Provide clear error messages
- Centralized validation logic

Author: A.R.C.H.I.E. Platform
Date: 2026-01-07
"""

import re
from typing import Any, Dict, List, Optional
from datetime import datetime
import json

# Optional bleach import for HTML sanitization
try:
    import bleach

    BLEACH_AVAILABLE = True
except ImportError:
    BLEACH_AVAILABLE = False


# ============================================================================
# VALIDATION EXCEPTIONS
# ============================================================================


class ValidationError(Exception):
    """Base exception for validation errors"""

    def __init__(self, field: str, message: str):
        self.field = field
        self.message = message
        super().__init__(f"{field}: {message}")


class ValidationResult:
    """Result of validation operation"""

    def __init__(
        self,
        valid: bool,
        errors: Optional[Dict[str, str]] = None,
        sanitized_data: Optional[Dict] = None,
    ):
        self.valid = valid
        self.errors = errors or {}
        self.sanitized_data = sanitized_data or {}

    def to_dict(self) -> Dict:
        return {
            "valid": self.valid,
            "errors": self.errors,
            "data": self.sanitized_data if self.valid else None,
        }


# ============================================================================
# STRING VALIDATION
# ============================================================================


def validate_string(
    value: Any,
    field_name: str,
    min_length: int = 0,
    max_length: int = 1000,
    pattern: Optional[str] = None,
    required: bool = True,
) -> str:
    """
    Validate and sanitize string input

    Args:
        value: Input value to validate
        field_name: Name of the field (for error messages)
        min_length: Minimum length (default: 0)
        max_length: Maximum length (default: 1000)
        pattern: Optional regex pattern
        required: Whether field is required (default: True)

    Returns:
        Sanitized string value

    Raises:
        ValidationError: If validation fails
    """
    # Check if value exists
    if value is None or value == "":
        if required:
            raise ValidationError(field_name, "This field is required")
        return ""

    # Convert to string
    if not isinstance(value, str):
        value = str(value)

    # Strip whitespace
    value = value.strip()

    # Check length
    if len(value) < min_length:
        raise ValidationError(field_name, f"Must be at least {min_length} characters")
    if len(value) > max_length:
        raise ValidationError(field_name, f"Must be at most {max_length} characters")

    # Check pattern
    if pattern and not re.match(pattern, value):
        raise ValidationError(field_name, "Invalid format")

    return value


def sanitize_html(html: str, allowed_tags: Optional[List[str]] = None) -> str:
    """
    Sanitize HTML to prevent XSS attacks

    Args:
        html: HTML string to sanitize
        allowed_tags: List of allowed HTML tags (default: safe subset)

    Returns:
        Sanitized HTML string
    """
    if allowed_tags is None:
        allowed_tags = [
            "p",
            "br",
            "strong",
            "em",
            "u",
            "a",
            "ul",
            "ol",
            "li",
            "code",
            "pre",
        ]

    if BLEACH_AVAILABLE:
        return bleach.clean(html, tags=allowed_tags, attributes={"a": ["href", "title"]}, strip=True)
    else:
        # Fallback: Strip all HTML tags
        return re.sub(r"<[^>]+>", "", html)


# ============================================================================
# NUMERIC VALIDATION
# ============================================================================


def validate_integer(
    value: Any,
    field_name: str,
    min_value: Optional[int] = None,
    max_value: Optional[int] = None,
    required: bool = True,
) -> Optional[int]:
    """
    Validate integer input

    Args:
        value: Input value to validate
        field_name: Name of the field
        min_value: Minimum allowed value
        max_value: Maximum allowed value
        required: Whether field is required

    Returns:
        Validated integer value

    Raises:
        ValidationError: If validation fails
    """
    if value is None or value == "":
        if required:
            raise ValidationError(field_name, "This field is required")
        return None

    # Try to convert to int
    try:
        value = int(value)
    except (ValueError, TypeError):
        raise ValidationError(field_name, "Must be a valid integer")

    # Check range
    if min_value is not None and value < min_value:
        raise ValidationError(field_name, f"Must be at least {min_value}")
    if max_value is not None and value > max_value:
        raise ValidationError(field_name, f"Must be at most {max_value}")

    return value


def validate_float(
    value: Any,
    field_name: str,
    min_value: Optional[float] = None,
    max_value: Optional[float] = None,
    required: bool = True,
) -> Optional[float]:
    """Validate float input"""
    if value is None or value == "":
        if required:
            raise ValidationError(field_name, "This field is required")
        return None

    try:
        value = float(value)
    except (ValueError, TypeError):
        raise ValidationError(field_name, "Must be a valid number")

    if min_value is not None and value < min_value:
        raise ValidationError(field_name, f"Must be at least {min_value}")
    if max_value is not None and value > max_value:
        raise ValidationError(field_name, f"Must be at most {max_value}")

    return value


# ============================================================================
# EMAIL & USERNAME VALIDATION
# ============================================================================


def validate_email(email: str, field_name: str = "email", required: bool = True) -> str:
    """
    Validate email address format

    Args:
        email: Email address to validate
        field_name: Field name for error messages
        required: Whether field is required

    Returns:
        Validated email address (lowercased)

    Raises:
        ValidationError: If validation fails
    """
    if not email:
        if required:
            raise ValidationError(field_name, "Email is required")
        return ""

    email = email.strip().lower()

    # Email regex pattern
    pattern = r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$"

    if not re.match(pattern, email):
        raise ValidationError(field_name, "Invalid email format")

    if len(email) > 255:
        raise ValidationError(field_name, "Email too long")

    return email


def validate_username(username: str, field_name: str = "username", required: bool = True) -> str:
    """
    Validate username format

    Args:
        username: Username to validate
        field_name: Field name for error messages
        required: Whether field is required

    Returns:
        Validated username

    Raises:
        ValidationError: If validation fails
    """
    if not username:
        if required:
            raise ValidationError(field_name, "Username is required")
        return ""

    username = username.strip()

    # Username rules: 3-30 chars, alphanumeric + underscore/hyphen
    if len(username) < 3:
        raise ValidationError(field_name, "Username must be at least 3 characters")
    if len(username) > 30:
        raise ValidationError(field_name, "Username must be at most 30 characters")

    pattern = r"^[a-zA-Z0-9_-]+$"
    if not re.match(pattern, username):
        raise ValidationError(
            field_name,
            "Username can only contain letters, numbers, underscores, and hyphens",
        )

    return username


# ============================================================================
# PASSWORD VALIDATION
# ============================================================================


def validate_password(
    password: str,
    field_name: str = "password",
    min_length: int = 8,
    require_uppercase: bool = True,
    require_lowercase: bool = True,
    require_digit: bool = True,
    require_special: bool = False,
) -> str:
    """
    Validate password strength

    Args:
        password: Password to validate
        field_name: Field name for error messages
        min_length: Minimum password length
        require_uppercase: Require at least one uppercase letter
        require_lowercase: Require at least one lowercase letter
        require_digit: Require at least one digit
        require_special: Require at least one special character

    Returns:
        Validated password

    Raises:
        ValidationError: If validation fails
    """
    if not password:
        raise ValidationError(field_name, "Password is required")

    if len(password) < min_length:
        raise ValidationError(field_name, f"Password must be at least {min_length} characters")

    if len(password) > 128:
        raise ValidationError(field_name, "Password too long")

    if require_uppercase and not re.search(r"[A-Z]", password):
        raise ValidationError(field_name, "Password must contain at least one uppercase letter")

    if require_lowercase and not re.search(r"[a-z]", password):
        raise ValidationError(field_name, "Password must contain at least one lowercase letter")

    if require_digit and not re.search(r"\d", password):
        raise ValidationError(field_name, "Password must contain at least one digit")

    if require_special and not re.search(r'[!@#$%^&*(),.?":{}|<>]', password):
        raise ValidationError(field_name, "Password must contain at least one special character")

    return password


# ============================================================================
# URL VALIDATION
# ============================================================================


def validate_url(
    url: str,
    field_name: str = "url",
    required: bool = True,
    allowed_schemes: Optional[List[str]] = None,
) -> str:
    """
    Validate URL format

    Args:
        url: URL to validate
        field_name: Field name for error messages
        required: Whether field is required
        allowed_schemes: List of allowed URL schemes (default: ['http', 'https'])

    Returns:
        Validated URL

    Raises:
        ValidationError: If validation fails
    """
    if not url:
        if required:
            raise ValidationError(field_name, "URL is required")
        return ""

    url = url.strip()

    if allowed_schemes is None:
        allowed_schemes = ["http", "https"]

    # URL pattern
    pattern = r"^(https?|ftp):\/\/[^\s/$.?#].[^\s]*$"

    if not re.match(pattern, url, re.IGNORECASE):
        raise ValidationError(field_name, "Invalid URL format")

    # Check scheme
    scheme = url.split("://")[0].lower()
    if scheme not in allowed_schemes:
        raise ValidationError(field_name, f"URL scheme must be one of: {', '.join(allowed_schemes)}")

    return url


# ============================================================================
# DATE & TIME VALIDATION
# ============================================================================


def validate_date(
    date_str: str,
    field_name: str = "date",
    required: bool = True,
    date_format: str = "%Y-%m-%d",
) -> Optional[datetime]:
    """
    Validate date string

    Args:
        date_str: Date string to validate
        field_name: Field name for error messages
        required: Whether field is required
        date_format: Expected date format (default: YYYY-MM-DD)

    Returns:
        Datetime object

    Raises:
        ValidationError: If validation fails
    """
    if not date_str:
        if required:
            raise ValidationError(field_name, "Date is required")
        return None

    try:
        return datetime.strptime(date_str, date_format)
    except ValueError:
        raise ValidationError(field_name, f"Invalid date format. Expected: {date_format}")


def validate_datetime(
    dt_str: str,
    field_name: str = "datetime",
    required: bool = True,
    dt_format: str = "%Y-%m-%d %H:%M:%S",
) -> Optional[datetime]:
    """Validate datetime string"""
    if not dt_str:
        if required:
            raise ValidationError(field_name, "Datetime is required")
        return None

    try:
        return datetime.strptime(dt_str, dt_format)
    except ValueError:
        raise ValidationError(field_name, f"Invalid datetime format. Expected: {dt_format}")


# ============================================================================
# ENUM VALIDATION
# ============================================================================


def validate_enum(
    value: str,
    field_name: str,
    allowed_values: List[str],
    required: bool = True,
    case_sensitive: bool = False,
) -> str:
    """
    Validate enum/choice value

    Args:
        value: Value to validate
        field_name: Field name for error messages
        allowed_values: List of allowed values
        required: Whether field is required
        case_sensitive: Whether comparison is case sensitive

    Returns:
        Validated value

    Raises:
        ValidationError: If validation fails
    """
    if not value:
        if required:
            raise ValidationError(field_name, "This field is required")
        return ""

    value = value.strip()

    # Case insensitive comparison
    if not case_sensitive:
        value_lower = value.lower()
        allowed_lower = [v.lower() for v in allowed_values]

        if value_lower not in allowed_lower:
            raise ValidationError(field_name, f"Must be one of: {', '.join(allowed_values)}")

        # Return original case from allowed_values
        index = allowed_lower.index(value_lower)
        return allowed_values[index]
    else:
        if value not in allowed_values:
            raise ValidationError(field_name, f"Must be one of: {', '.join(allowed_values)}")

        return value


# ============================================================================
# JSON VALIDATION
# ============================================================================


def validate_json(json_str: str, field_name: str = "json", required: bool = True) -> Optional[Dict]:
    """
    Validate JSON string

    Args:
        json_str: JSON string to validate
        field_name: Field name for error messages
        required: Whether field is required

    Returns:
        Parsed JSON object

    Raises:
        ValidationError: If validation fails
    """
    if not json_str:
        if required:
            raise ValidationError(field_name, "JSON is required")
        return None

    try:
        return json.loads(json_str)
    except json.JSONDecodeError as e:
        raise ValidationError(field_name, f"Invalid JSON: {str(e)}")


# ============================================================================
# BATCH VALIDATION
# ============================================================================


def validate_schema(data: Dict[str, Any], schema: Dict[str, Dict]) -> ValidationResult:
    """
    Validate data against schema

    Args:
        data: Dictionary of input data
        schema: Dictionary defining validation rules for each field

    Schema format:
        {
            'field_name': {
                'type': 'string|integer|float|email|url|enum|json',
                'required': True|False,
                'min_length': int (for strings),
                'max_length': int (for strings),
                'min_value': num (for numbers),
                'max_value': num (for numbers),
                'allowed_values': list (for enums),
                'pattern': str (regex for strings)
            }
        }

    Returns:
        ValidationResult object
    """
    errors = {}
    sanitized_data = {}

    for field_name, rules in schema.items():
        try:
            value = data.get(field_name)
            field_type = rules.get("type", "string")
            required = rules.get("required", False)

            # Validate based on type
            if field_type == "string":
                sanitized_data[field_name] = validate_string(
                    value,
                    field_name,
                    min_length=rules.get("min_length", 0),
                    max_length=rules.get("max_length", 1000),
                    pattern=rules.get("pattern"),
                    required=required,
                )

            elif field_type == "integer":
                sanitized_data[field_name] = validate_integer(
                    value,
                    field_name,
                    min_value=rules.get("min_value"),
                    max_value=rules.get("max_value"),
                    required=required,
                )

            elif field_type == "float":
                sanitized_data[field_name] = validate_float(
                    value,
                    field_name,
                    min_value=rules.get("min_value"),
                    max_value=rules.get("max_value"),
                    required=required,
                )

            elif field_type == "email":
                sanitized_data[field_name] = validate_email(value, field_name, required)

            elif field_type == "username":
                sanitized_data[field_name] = validate_username(value, field_name, required)

            elif field_type == "password":
                sanitized_data[field_name] = validate_password(value, field_name)

            elif field_type == "url":
                sanitized_data[field_name] = validate_url(value, field_name, required)

            elif field_type == "enum":
                sanitized_data[field_name] = validate_enum(
                    value,
                    field_name,
                    allowed_values=rules.get("allowed_values", []),
                    required=required,
                )

            elif field_type == "json":
                sanitized_data[field_name] = validate_json(value, field_name, required)

            elif field_type == "date":
                sanitized_data[field_name] = validate_date(value, field_name, required)

            elif field_type == "datetime":
                sanitized_data[field_name] = validate_datetime(value, field_name, required)

        except ValidationError as e:
            errors[e.field] = e.message

    # Return result
    if errors:
        return ValidationResult(valid=False, errors=errors)
    else:
        return ValidationResult(valid=True, sanitized_data=sanitized_data)


# ============================================================================
# FLASK INTEGRATION
# ============================================================================


def validate_request_json(schema: Dict[str, Dict]):
    """
    Decorator for Flask routes to validate request JSON

    Usage:
        @app.route('/api/users', methods=['POST'])
        @validate_request_json({
            'username': {'type': 'username', 'required': True},
            'email': {'type': 'email', 'required': True},
            'age': {'type': 'integer', 'min_value': 18, 'max_value': 120}
        })
        def create_user():
            # request.validated_data contains sanitized data
            data = request.validated_data
            ...
    """
    from functools import wraps
    from flask import request, jsonify

    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            # Get JSON data
            data = request.get_json()
            if data is None:
                return (
                    jsonify({"success": False, "error": "Request body must be JSON"}),
                    400,
                )

            # Validate schema
            result = validate_schema(data, schema)

            if not result.valid:
                return jsonify({"success": False, "errors": result.errors}), 400

            # Attach validated data to request
            request.validated_data = result.sanitized_data

            return f(*args, **kwargs)

        return decorated_function

    return decorator


# ============================================================================
# TESTING & EXAMPLES
# ============================================================================

if __name__ == "__main__":
    print("=" * 80)
    print("VALIDATION UTILITY TEST")
    print("=" * 80)

    # Test string validation
    try:
        validate_string("test", "name", min_length=2, max_length=10)
        print("✅ String validation passed")
    except ValidationError as e:
        print(f"❌ String validation failed: {e}")

    # Test email validation
    try:
        email = validate_email("user@example.com")
        print(f"✅ Email validation passed: {email}")
    except ValidationError as e:
        print(f"❌ Email validation failed: {e}")

    # Test password validation
    try:
        validate_password("SecurePass123")
        print("✅ Password validation passed")
    except ValidationError as e:
        print(f"❌ Password validation failed: {e}")

    # Test schema validation
    test_data = {
        "username": "john_doe",
        "email": "john@example.com",
        "age": 25,
        "role": "user",
    }

    test_schema = {
        "username": {"type": "username", "required": True},
        "email": {"type": "email", "required": True},
        "age": {"type": "integer", "min_value": 18, "max_value": 120, "required": True},
        "role": {
            "type": "enum",
            "allowed_values": ["user", "admin", "premium"],
            "required": True,
        },
    }

    result = validate_schema(test_data, test_schema)

    if result.valid:
        print("✅ Schema validation passed")
        print(f"   Sanitized data: {result.sanitized_data}")
    else:
        print(f"❌ Schema validation failed: {result.errors}")

    print("\n" + "=" * 80)
