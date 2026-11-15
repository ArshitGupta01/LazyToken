"""Lightweight AST symbol and import extraction with structural call analysis."""

import ast
import re


def javascript_imports(body):
    # Mask comments while retaining strings so named, default and multiline imports work.
    token = re.compile(r"([\"'`])(?:\\.|(?!\1)[\s\S])*?\1|//[^\n]*|/\*[\s\S]*?\*/")
    clean = token.sub(lambda m: m.group(0) if m.group(1) else " " * len(m.group(0)), body)
    code = token.sub(lambda m: " " * len(m.group(0)), body)
    # shortcut: template interpolation is not parsed; use a JS parser if it becomes required.
    patterns = (
        r"\b(?:import|export)\s+(?:type\s+)?[^;\"']*?\bfrom\s*[\"']([^\"']+)[\"']",
        r"\bimport\s*[\"']([^\"']+)[\"']",
        r"\b(?:require|import)\s*\(\s*[\"']([^\"']+)[\"']\s*\)",
    )
    return sorted(
        {
            match.group(1)
            for pattern in patterns
            for match in re.finditer(pattern, clean)
            if code[match.start() :].startswith(("import", "export", "require"))
            and (not code[: match.start()].rstrip().endswith("."))
        }
    )


def python_imports(body):
    try:
        tree = ast.parse(body)
    except SyntaxError:
        return []
    modules = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                modules.add("." * node.level + node.module)
            elif node.level:
                for alias in node.names:
                    modules.add("." * node.level + alias.name)
    return sorted(modules)


def python_symbols(body):
    """Extract AST symbols for Python code: classes, functions, and class methods with arbitrary nesting."""
    try:
        tree = ast.parse(body)
    except Exception:
        return []
    symbols = []

    def visit(nodes, prefix=""):
        for node in nodes:
            if isinstance(node, ast.ClassDef):
                full_name = f"{prefix}{node.name}"
                symbols.append((node.name, node.lineno))
                if prefix:
                    symbols.append((full_name, node.lineno))
                visit(node.body, prefix=f"{full_name}.")
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                full_name = f"{prefix}{node.name}"
                symbols.append((node.name, node.lineno))
                if prefix:
                    symbols.append((full_name, node.lineno))
                visit(node.body, prefix=f"{full_name}.")

    visit(tree.body)
    return symbols


def walk_function_calls(node):
    """Walk only the immediate statements/expressions of this function body without descending into nested functions or classes."""
    queue = list(ast.iter_child_nodes(node))
    while queue:
        child = queue.pop(0)
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            # Explicitly do NOT descend into nested function or class bodies
            continue
        if isinstance(child, ast.Call):
            yield child
        queue.extend(ast.iter_child_nodes(child))


def python_calls(body):
    """Extract call relationships (caller_symbol -> callee_name) with shallow body walking and receiver resolution."""
    try:
        tree = ast.parse(body)
    except Exception:
        return []
    calls = []

    # Pass 1: Extract class attributes initialized in __init__ (e.g. self.store = TokenStore())
    class_attrs = {}
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            class_attrs[node.name] = {}
            for item in node.body:
                if (
                    isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))
                    and item.name == "__init__"
                ):
                    for stmt in item.body:
                        if isinstance(stmt, ast.Assign):
                            for target in stmt.targets:
                                if (
                                    isinstance(target, ast.Attribute)
                                    and isinstance(target.value, ast.Name)
                                    and target.value.id == "self"
                                ):
                                    if isinstance(stmt.value, ast.Call) and isinstance(
                                        stmt.value.func, ast.Name
                                    ):
                                        class_attrs[node.name][target.attr] = stmt.value.func.id

    def extract_local_types(func_node):
        local_types = {}
        for arg in func_node.args.args:
            if arg.annotation and isinstance(arg.annotation, ast.Name):
                local_types[arg.arg] = arg.annotation.id
        for stmt in getattr(func_node, "body", []):
            if isinstance(stmt, ast.Assign):
                for target in stmt.targets:
                    if isinstance(target, ast.Name):
                        if isinstance(stmt.value, ast.Call) and isinstance(
                            stmt.value.func, ast.Name
                        ):
                            local_types[target.id] = stmt.value.func.id
        return local_types

    def record_calls(func_node, caller_names, class_name=""):
        local_types = extract_local_types(func_node)
        for call_node in walk_function_calls(func_node):
            callee_name = None
            receiver = ""
            resolved = None
            confidence = "provisional"

            if isinstance(call_node.func, ast.Attribute):
                callee_name = call_node.func.attr
                val = call_node.func.value
                if isinstance(val, ast.Name):
                    receiver = val.id
                    if receiver in ("self", "cls") and class_name:
                        resolved = f"{class_name}.{callee_name}"
                        confidence = "exact"
                    elif receiver in local_types:
                        inferred_cls = local_types[receiver]
                        resolved = f"{inferred_cls}.{callee_name}"
                        confidence = "exact"
                    elif receiver:
                        resolved = f"{receiver}.{callee_name}"
                        confidence = "exact" if receiver[0].isupper() else "provisional"
                elif (
                    isinstance(val, ast.Attribute)
                    and isinstance(val.value, ast.Name)
                    and val.value.id == "self"
                ):
                    attr_name = val.attr
                    receiver = f"self.{attr_name}"
                    store_cls = class_attrs.get(class_name, {}).get(attr_name)
                    if store_cls:
                        resolved = f"{store_cls}.{callee_name}"
                        confidence = "exact"
                    else:
                        resolved = f"{attr_name}.{callee_name}"
                        confidence = "provisional"
                elif (
                    isinstance(val, ast.Call)
                    and isinstance(val.func, ast.Name)
                    and val.func.id == "super"
                ):
                    receiver = "super"
                    if class_name:
                        resolved = f"{class_name}.{callee_name}"
                        confidence = "exact"
            elif isinstance(call_node.func, ast.Name):
                callee_name = call_node.func.id
                receiver = ""
                resolved = callee_name
                confidence = "exact"

            if callee_name and isinstance(callee_name, str):
                resolved_final = resolved or callee_name
                for caller in caller_names:
                    calls.append(
                        {
                            "caller_symbol": caller,
                            "callee_name": callee_name,
                            "receiver": receiver,
                            "resolved_callee": resolved_final,
                            "confidence": confidence,
                            "line": call_node.lineno,
                        }
                    )

    def visit(nodes, prefix="", class_name=""):
        for node in nodes:
            if isinstance(node, ast.ClassDef):
                full_name = f"{prefix}{node.name}"
                visit(node.body, prefix=f"{full_name}.", class_name=node.name)
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                full_name = f"{prefix}{node.name}"
                names = [full_name] if prefix else [node.name]
                record_calls(node, names, class_name=class_name)
                visit(node.body, prefix=f"{full_name}.", class_name=class_name)

    visit(tree.body)
    return calls


def javascript_symbols(body):
    """Extract symbols for JavaScript/TypeScript: functions, classes, methods, interfaces, and types."""
    symbols = []
    class_stack = []

    re_class = re.compile(r"^\s*(?:export\s+)?(?:default\s+)?class\s+([a-zA-Z0-9_$]+)")
    re_interface = re.compile(
        r"^\s*(?:export\s+)?(?:default\s+)?(?:interface|type)\s+([a-zA-Z0-9_$]+)"
    )
    re_func = re.compile(
        r"^\s*(?:export\s+)?(?:default\s+)?(?:async\s+)?function(?:\s+([a-zA-Z0-9_$]+)|\s*\()"
    )
    re_arrow = re.compile(
        r"^\s*(?:export\s+)?(?:const|let|var)\s+([a-zA-Z0-9_$]+)\s*=\s*(?:async\s*)?(?:\([^)]*\)|[a-zA-Z0-9_$]+)\s*=>"
    )
    re_method = re.compile(
        r"^\s*(?:(?:public|private|protected|static|readonly|async)\s+)*(?:get\s+|set\s+)?([a-zA-Z0-9_$]+)\s*\([^)]*\)\s*(?::\s*[^{]+)?\s*\{"
    )

    for n, line in enumerate(body.splitlines(), 1):
        stripped = line.strip()
        if not stripped or stripped.startswith("//") or stripped.startswith("/*"):
            continue

        m_cls = re_class.search(line)
        if m_cls:
            cls_name = m_cls.group(1)
            symbols.append((cls_name, n))
            class_stack.append({"name": cls_name, "brace_depth": 0})

        m_iface = re_interface.search(line)
        if m_iface:
            symbols.append((m_iface.group(1), n))

        m_fn = re_func.search(line)
        if m_fn and m_fn.group(1):
            symbols.append((m_fn.group(1), n))

        m_arrow = re_arrow.search(line)
        if m_arrow:
            symbols.append((m_arrow.group(1), n))

        if class_stack:
            current_cls = class_stack[-1]["name"]
            m_meth = re_method.search(line)
            if m_meth and not m_cls and not m_fn:
                m_name = m_meth.group(1)
                if m_name not in ("if", "for", "while", "switch", "catch"):
                    symbols.append((m_name, n))
                    symbols.append((f"{current_cls}.{m_name}", n))

        open_b = line.count("{")
        close_b = line.count("}")
        if class_stack:
            class_stack[-1]["brace_depth"] += open_b - close_b
            if class_stack[-1]["brace_depth"] <= 0 and (open_b > 0 or close_b > 0):
                class_stack.pop()

    return symbols
