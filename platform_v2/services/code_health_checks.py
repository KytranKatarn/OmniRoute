"""Pure, conservative checks shared by audit and repair verification."""

import ast


def direct_call_present(source, names):
    """Detect named provider calls, ignoring scanner strings and comments.

    Return None for invalid Python so a repair is never closed on a parse error.
    Track explicit import aliases as well as qualified calls.
    """
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError, TypeError):
        return None
    # Dynamic execution can turn a string into a real call. Keep it unknown
    # rather than treating every string as harmless in such a module.
    if any(
        isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id in ("exec", "eval")
        for n in ast.walk(tree)
    ):
        return None
    aliases = set(names)
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            for alias in node.names:
                if alias.name in names:
                    aliases.add(alias.asname or alias.name)
    return any(
        isinstance(node, ast.Call)
        and (
            isinstance(node.func, ast.Name)
            and node.func.id in aliases
            or isinstance(node.func, ast.Attribute)
            and node.func.attr in names
        )
        for node in ast.walk(tree)
    )
