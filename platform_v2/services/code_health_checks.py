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


def sql_finding_present(source):
    """Disprove an inline SQL finding only when all visible executions are literal.

    True keeps interpolated queries open. None keeps unparseable source, dynamic
    execution, query variables/builders and indirect execute references open.
    No SQL executions is unknown: moving SQL elsewhere must not manufacture proof.
    """
    try:
        tree = ast.parse(source)
        compile(tree, "<sql-finding>", "exec")
    except (SyntaxError, ValueError, TypeError):
        return None
    nodes = list(ast.walk(tree))
    dynamic_names = {"exec", "eval", "compile", "getattr", "setattr", "globals", "locals", "vars"}
    for node in nodes:
        if isinstance(node, ast.ImportFrom):
            if any(alias.name == "*" for alias in node.names):
                return None
            for alias in node.names:
                if alias.name in dynamic_names | {"execute", "executemany"}:
                    dynamic_names.add(alias.asname or alias.name)
    if any(
        isinstance(node, ast.Name)
        and isinstance(node.ctx, ast.Load)
        and node.id in dynamic_names
        or isinstance(node, ast.Attribute)
        and node.attr in dynamic_names
        for node in nodes
    ):
        return None
    calls = [
        node
        for node in nodes
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in ("execute", "executemany")
    ]
    if not calls:
        return None
    direct_refs = {id(call.func) for call in calls}
    unknown = any(
        isinstance(node, ast.Attribute)
        and node.attr in ("execute", "executemany")
        and id(node) not in direct_refs
        or isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id in ("execute", "executemany")
        for node in nodes
    )
    for call in calls:
        query = call.args[0] if call.args else None
        if isinstance(query, ast.JoinedStr) or isinstance(query, ast.BinOp) and isinstance(query.op, ast.Mod):
            return True
        if not isinstance(query, ast.Constant) or not isinstance(query.value, str):
            unknown = True
    return None if unknown else False
