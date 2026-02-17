"""
Code Editor Routes for A.R.C.H.I.E. Platform
Integrates Monaco Editor with AI Bridge
"""

from flask import Blueprint, render_template, request, jsonify
from flask_login import login_required, current_user
import sys

# Add AI Bridge to path
sys.path.insert(0, "/mnt/archie_brain")

try:
    from ai_bridge.archie_bridge import archie_bridge

    AI_BRIDGE_AVAILABLE = True
except ImportError:
    AI_BRIDGE_AVAILABLE = False
    print("⚠️ AI Bridge not available in Code Editor")

code_editor_bp = Blueprint("code_editor", __name__, url_prefix="/tools/code-editor")


@code_editor_bp.route("/")
@login_required
def index():
    """Render the Code Editor interface"""
    return render_template("tools/code_editor.html")


@code_editor_bp.route("/api/ai", methods=["POST"])
@login_required
def ai_chat():
    """AI chat endpoint for code editor"""
    if not AI_BRIDGE_AVAILABLE:
        return jsonify({"success": False, "error": "AI Bridge not available"}), 503

    try:
        data = request.json
        prompt = data.get("prompt", "")
        context = data.get("context", {})

        if not prompt:
            return jsonify({"success": False, "error": "Prompt is required"}), 400

        # Call AI Bridge
        result = archie_bridge(prompt=prompt, context=context, user_id=current_user.id)

        return jsonify(result)

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@code_editor_bp.route("/api/file/save", methods=["POST"])
@login_required
def save_file():
    """Save a file to database"""
    try:
        data = request.json
        filename = data.get("filename")
        content = data.get("content")

        if not filename or content is None:
            return (
                jsonify({"success": False, "error": "Filename and content required"}),
                400,
            )

        # TODO: Save to database
        # For now, store in session or temp storage
        # In production, save to user's workspace in database

        return jsonify({"success": True, "message": f"File {filename} saved successfully"})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@code_editor_bp.route("/api/file/load", methods=["GET"])
@login_required
def load_file():
    """Load a file from database"""
    try:
        filename = request.args.get("filename")

        if not filename:
            return jsonify({"success": False, "error": "Filename required"}), 400

        # TODO: Load from database
        # For now, return mock content
        mock_content = {
            "main.py": '# Welcome to A.R.C.H.I.E. Code Editor\n# Write your code here\n\ndef hello_world():\n    return "Hello, World!"\n\nif __name__ == "__main__":\n    print(hello_world())',
            "utils.py": "# Utility functions\n\ndef add(a, b):\n    return a + b\n\ndef multiply(a, b):\n    return a * b",
            "config.json": '{\n  "name": "my-project",\n  "version": "1.0.0",\n  "author": "A.R.C.H.I.E."\n}',
        }

        content = mock_content.get(filename, "# New file\n")

        return jsonify({"success": True, "content": content, "filename": filename})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@code_editor_bp.route("/api/execute", methods=["POST"])
@login_required
def execute_code():
    """Execute code (placeholder)"""
    data = request.json
    code = data.get("code")

    return jsonify({"success": True, "output": "Code execution not yet implemented", "errors": []})


# ============================================================================
# NATURAL LANGUAGE CODE GENERATION
# ============================================================================

# Import NL Code Generator
try:
    sys.path.insert(0, "/mnt/archie_brain/ai_bridge")
    from nl_code_generator import generate_code_from_nl, NLCodeGenerator

    NL_GENERATOR_AVAILABLE = True
except ImportError:
    NL_GENERATOR_AVAILABLE = False


@code_editor_bp.route("/api/status")
def status():
    """Health check endpoint"""
    return jsonify(
        {
            "module": "code_editor",
            "status": "operational",
            "healthy": True,
            "features": {
                "ai_chat": AI_BRIDGE_AVAILABLE,
                "nl_code_generation": NL_GENERATOR_AVAILABLE,
                "file_operations": True,
                "code_execution": False,
            },
        }
    )


@code_editor_bp.route("/api/nl/generate", methods=["POST"])
@login_required
def nl_generate():
    """
    Generate code from natural language description

    POST body:
    {
        "description": "Create a function that sorts a list",
        "language": "python",  // optional, auto-detected
        "context": {           // optional
            "existing_code": "...",
            "file_path": "..."
        }
    }
    """
    if not NL_GENERATOR_AVAILABLE:
        return (
            jsonify({"success": False, "error": "NL Code Generator not available"}),
            503,
        )

    try:
        data = request.json or {}
        description = data.get("description", "")
        language = data.get("language")
        context = data.get("context")
        file_path = data.get("file_path")

        if not description:
            return jsonify({"success": False, "error": "Description is required"}), 400

        result = generate_code_from_nl(
            description=description,
            context=context,
            language=language,
            file_path=file_path,
        )

        return jsonify(result)

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@code_editor_bp.route("/api/nl/modify", methods=["POST"])
@login_required
def nl_modify():
    """
    Modify existing code based on natural language instructions

    POST body:
    {
        "instruction": "Add error handling to this function",
        "code": "def my_func():\n    return result",
        "language": "python"
    }
    """
    if not NL_GENERATOR_AVAILABLE:
        return (
            jsonify({"success": False, "error": "NL Code Generator not available"}),
            503,
        )

    try:
        data = request.json or {}
        instruction = data.get("instruction", "")
        code = data.get("code", "")
        language = data.get("language", "python")

        if not instruction or not code:
            return (
                jsonify({"success": False, "error": "Instruction and code are required"}),
                400,
            )

        result = generate_code_from_nl(
            description=f"Modify this code: {instruction}",
            context={"existing_code": code},
            language=language,
        )

        return jsonify(result)

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@code_editor_bp.route("/api/nl/fix", methods=["POST"])
@login_required
def nl_fix():
    """
    Fix code issues based on natural language or error message

    POST body:
    {
        "code": "def broken_func():\n    return undefined_var",
        "error": "NameError: name 'undefined_var' is not defined",
        "language": "python"
    }
    """
    if not NL_GENERATOR_AVAILABLE:
        return (
            jsonify({"success": False, "error": "NL Code Generator not available"}),
            503,
        )

    try:
        data = request.json or {}
        code = data.get("code", "")
        error = data.get("error", "")
        language = data.get("language", "python")
        description = data.get("description", "")

        if not code:
            return jsonify({"success": False, "error": "Code is required"}), 400

        fix_description = f"Fix this code"
        if error:
            fix_description += f". Error: {error}"
        if description:
            fix_description += f". Issue: {description}"

        result = generate_code_from_nl(
            description=fix_description,
            context={"existing_code": code, "error": error},
            language=language,
        )

        return jsonify(result)

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@code_editor_bp.route("/api/nl/explain", methods=["POST"])
@login_required
def nl_explain():
    """
    Explain code in natural language

    POST body:
    {
        "code": "def complex_function():\n    ...",
        "language": "python"
    }
    """
    if not NL_GENERATOR_AVAILABLE:
        return (
            jsonify({"success": False, "error": "NL Code Generator not available"}),
            503,
        )

    try:
        data = request.json or {}
        code = data.get("code", "")
        language = data.get("language", "python")

        if not code:
            return jsonify({"success": False, "error": "Code is required"}), 400

        result = generate_code_from_nl(
            description="Explain this code",
            context={"existing_code": code},
            language=language,
        )

        return jsonify(result)

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@code_editor_bp.route("/api/nl/convert", methods=["POST"])
@login_required
def nl_convert():
    """
    Convert code from one language to another

    POST body:
    {
        "code": "function hello() { return 'world'; }",
        "source_language": "javascript",
        "target_language": "python"
    }
    """
    if not NL_GENERATOR_AVAILABLE:
        return (
            jsonify({"success": False, "error": "NL Code Generator not available"}),
            503,
        )

    try:
        data = request.json or {}
        code = data.get("code", "")
        source_lang = data.get("source_language", "javascript")
        target_lang = data.get("target_language", "python")

        if not code:
            return jsonify({"success": False, "error": "Code is required"}), 400

        result = generate_code_from_nl(
            description=f"Convert this {source_lang} code to {target_lang}",
            context={"existing_code": code, "source_language": source_lang},
            language=target_lang,
        )

        return jsonify(result)

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@code_editor_bp.route("/api/nl/templates")
@login_required
def nl_templates():
    """Get available code templates"""
    templates = [
        {
            "id": "flask_route",
            "name": "Flask Route",
            "description": "Create a new Flask API endpoint",
            "example": "Create a GET route /api/users that returns all users",
        },
        {
            "id": "python_function",
            "name": "Python Function",
            "description": "Create a Python function with documentation",
            "example": "Create a function to calculate compound interest",
        },
        {
            "id": "python_class",
            "name": "Python Class",
            "description": "Create a Python class with methods",
            "example": "Create a User class with name, email, and login method",
        },
        {
            "id": "sql_query",
            "name": "SQL Query",
            "description": "Generate SQL queries",
            "example": "Create a query to find users who signed up this month",
        },
        {
            "id": "react_component",
            "name": "React Component",
            "description": "Create a React component",
            "example": "Create a button component that shows a loading spinner",
        },
    ]

    return jsonify({"success": True, "templates": templates})
