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


def walk_function_calls(node, exclude_lambdas=True):
    """Walk only the immediate statements/expressions of this function body without descending into nested functions, classes, or lambdas."""
    body = getattr(node, "body", [])
    queue = list(body) if isinstance(body, list) else ([body] if body is not None else [])
    while queue:
        child = queue.pop(0)
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            # Explicitly do NOT descend into nested function or class bodies
            continue
        if exclude_lambdas and isinstance(child, ast.Lambda):
            # Explicitly do NOT descend into nested lambda bodies
            continue
        if isinstance(child, ast.Call):
            yield child
        queue.extend(ast.iter_child_nodes(child))


def find_nested_lambdas(node):
    """Find lambda definitions within this function body without crossing nested function/class boundaries."""
    body = getattr(node, "body", [])
    queue = list(body) if isinstance(body, list) else ([body] if body is not None else [])
    while queue:
        child = queue.pop(0)
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        if isinstance(child, ast.Lambda):
            yield child
        queue.extend(ast.iter_child_nodes(child))


def python_calls(body):
    """Extract call relationships (caller_symbol -> callee_name) with shallow body walking and receiver resolution."""
    try:
        tree = ast.parse(body)
    except Exception:
        return []
    calls = []

    # Pass 0: Extract module-level imports
    imported_symbols = {}
    for node in tree.body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                imported_symbols[alias.asname or alias.name] = alias.name
        elif isinstance(node, ast.ImportFrom):
            mod_prefix = ("." * node.level) + (node.module or "")
            for alias in node.names:
                target = f"{mod_prefix}.{alias.name}" if mod_prefix else alias.name
                imported_symbols[alias.asname or alias.name] = target

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
        for arg in getattr(getattr(func_node, "args", None), "args", []):
            if arg.annotation and isinstance(arg.annotation, ast.Name):
                local_types[arg.arg] = arg.annotation.id
        body_stmts = getattr(func_node, "body", [])
        if isinstance(body_stmts, list):
            for stmt in body_stmts:
                if isinstance(stmt, ast.Assign):
                    for target in stmt.targets:
                        if isinstance(target, ast.Name):
                            if isinstance(stmt.value, ast.Call) and isinstance(
                                stmt.value.func, ast.Name
                            ):
                                local_types[target.id] = stmt.value.func.id
        return local_types

    def record_calls(func_node, caller_names, class_name="", is_lambda=False):
        local_types = extract_local_types(func_node)
        caller_line = getattr(func_node, "lineno", 0)
        for call_node in walk_function_calls(func_node, exclude_lambdas=not is_lambda):
            callee_name = None
            receiver = ""
            resolved = None
            confidence = "provisional"
            resolution_method = "unresolved"

            if isinstance(call_node.func, ast.Attribute):
                callee_name = call_node.func.attr
                val = call_node.func.value
                if isinstance(val, ast.Name):
                    receiver = val.id
                    if receiver in ("self", "cls") and class_name:
                        resolved = f"{class_name}.{callee_name}"
                        confidence = "exact"
                        resolution_method = "explicit_class"
                    elif receiver in local_types:
                        inferred_cls = local_types[receiver]
                        resolved = f"{inferred_cls}.{callee_name}"
                        confidence = "exact"
                        resolution_method = "inferred_type"
                    elif receiver in imported_symbols:
                        resolved = f"{receiver}.{callee_name}"
                        confidence = "exact"
                        resolution_method = "explicit_import"
                    elif receiver:
                        resolved = f"{receiver}.{callee_name}"
                        confidence = "exact" if receiver[0].isupper() else "provisional"
                        resolution_method = (
                            "explicit_class" if receiver[0].isupper() else "untyped_receiver"
                        )
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
                        resolution_method = "inferred_type"
                    else:
                        resolved = f"{attr_name}.{callee_name}"
                        confidence = "provisional"
                        resolution_method = "untyped_receiver"
                elif (
                    isinstance(val, ast.Call)
                    and isinstance(val.func, ast.Name)
                    and val.func.id == "super"
                ):
                    receiver = "super"
                    if class_name:
                        resolved = f"{class_name}.{callee_name}"
                        confidence = "exact"
                        resolution_method = "explicit_class"
            elif isinstance(call_node.func, ast.Name):
                callee_name = call_node.func.id
                receiver = ""
                resolved = callee_name
                confidence = "exact"
                resolution_method = (
                    "explicit_import" if callee_name in imported_symbols else "lexical_scope"
                )

            if callee_name and isinstance(callee_name, str):
                resolved_final = resolved or callee_name
                for caller in caller_names:
                    calls.append(
                        {
                            "caller_symbol": caller,
                            "caller_line": caller_line,
                            "callee_name": callee_name,
                            "receiver": receiver,
                            "resolved_callee": resolved_final,
                            "confidence": confidence,
                            "resolution_method": resolution_method,
                            "line": call_node.lineno,
                        }
                    )

        if not is_lambda:
            for lmb_node in find_nested_lambdas(func_node):
                lambda_callers = [f"{caller}.<lambda>" for caller in caller_names]
                record_calls(lmb_node, lambda_callers, class_name=class_name, is_lambda=True)

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


JS_CONTROL_FLOW = {"if", "for", "while", "switch", "catch", "with"}
JS_KEYWORDS = {
    "if",
    "for",
    "while",
    "switch",
    "catch",
    "with",
    "function",
    "return",
    "typeof",
    "instanceof",
    "void",
    "delete",
    "throw",
    "new",
    "yield",
    "await",
    "import",
    "export",
    "default",
    "else",
    "super",
    "this",
}


def javascript_symbols(body):
    """Extract symbols for JavaScript/TypeScript: functions, classes, methods, interfaces, types, enums, and namespaces."""
    symbols = []
    class_stack = []

    re_class = re.compile(
        r"^\s*(?:export\s+)?(?:default\s+)?(?:abstract\s+)?class\s+([a-zA-Z0-9_$]+)"
    )
    re_decl = re.compile(
        r"^\s*(?:export\s+)?(?:default\s+)?(?:interface|type|enum|namespace)\s+([a-zA-Z0-9_$]+)"
    )
    re_func = re.compile(
        r"^\s*(?:export\s+)?(?:default\s+)?(?:async\s+)?function(?:\s+([a-zA-Z0-9_$]+)|\s*\()"
    )
    re_arrow = re.compile(
        r"^\s*(?:export\s+)?(?:const|let|var)\s+([a-zA-Z0-9_$]+)\s*=\s*(?:async\s*)?(?:\([^)]*\)|[a-zA-Z0-9_$]+)\s*=>"
    )
    re_method = re.compile(
        r"^\s*(?:(?:public|private|protected|static|readonly|async|override)\s+)*(?:get\s+|set\s+)?([a-zA-Z0-9_$]+)\s*(?:<[^>]+>)?\s*\([^)]*\)\s*(?::\s*[^{;]+)?\s*[\{;]"
    )

    for n, line in enumerate(body.splitlines(), 1):
        clean = re.sub(r"//.*$", "", line)
        clean = re.sub(r"([\"'`])(?:\\.|(?!\1)[\s\S])*?\1", '""', clean)
        stripped = clean.strip()
        if not stripped or stripped.startswith("/*") or stripped.startswith("*"):
            continue

        m_cls = re_class.search(clean)
        if m_cls:
            cls_name = m_cls.group(1)
            symbols.append((cls_name, n))
            class_stack.append({"name": cls_name, "brace_depth": 0})

        m_decl = re_decl.search(clean)
        if m_decl:
            symbols.append((m_decl.group(1), n))

        m_fn = re_func.search(clean)
        if m_fn and m_fn.group(1):
            symbols.append((m_fn.group(1), n))

        m_arrow = re_arrow.search(clean)
        if m_arrow:
            symbols.append((m_arrow.group(1), n))

        if class_stack:
            current_cls = class_stack[-1]["name"]
            m_meth = re_method.search(clean)
            if m_meth and not m_cls and not m_fn:
                m_name = m_meth.group(1)
                if m_name not in JS_CONTROL_FLOW:
                    symbols.append((m_name, n))
                    symbols.append((f"{current_cls}.{m_name}", n))

        open_b = clean.count("{")
        close_b = clean.count("}")
        if class_stack:
            class_stack[-1]["brace_depth"] += open_b - close_b
            if class_stack[-1]["brace_depth"] <= 0 and (open_b > 0 or close_b > 0):
                class_stack.pop()

    return symbols


def javascript_calls(body):
    """Extract call relationships (caller_symbol -> callee_name) for JavaScript and TypeScript."""
    calls = []
    lines = body.splitlines()

    imported_symbols = set()
    for line in lines:
        m_named = re.findall(r"import\s+\{([^}]+)\}\s+from", line)
        for group in m_named:
            for item in group.split(","):
                sym = item.strip().split(" as ")[-1].strip()
                if sym:
                    imported_symbols.add(sym)
        m_default = re.search(r"import\s+([a-zA-Z0-9_$]+)\s+from", line)
        if m_default:
            imported_symbols.add(m_default.group(1))

    class_stack = []
    func_stack = []
    brace_depth = 0

    re_class = re.compile(
        r"^\s*(?:export\s+)?(?:default\s+)?(?:abstract\s+)?class\s+([a-zA-Z0-9_$]+)"
    )
    re_func = re.compile(
        r"^\s*(?:export\s+)?(?:default\s+)?(?:async\s+)?function(?:\s+([a-zA-Z0-9_$]+)|\s*\()"
    )
    re_arrow = re.compile(
        r"^\s*(?:export\s+)?(?:const|let|var)\s+([a-zA-Z0-9_$]+)\s*=\s*(?:async\s*)?(?:\([^)]*\)|[a-zA-Z0-9_$]+)\s*=>"
    )
    re_method = re.compile(
        r"^\s*(?:(?:public|private|protected|static|readonly|async|override)\s+)*(?:get\s+|set\s+)?([a-zA-Z0-9_$]+)\s*(?:<[^>]+>)?\s*\([^)]*\)\s*(?::\s*[^{;]+)?\s*[\{;]"
    )
    re_call = re.compile(r"(?:([a-zA-Z0-9_$]+(?:\.[a-zA-Z0-9_$]+)?)\.)?([a-zA-Z0-9_$]+)\s*\(")

    for lineno, line in enumerate(lines, 1):
        clean_line = re.sub(r"//.*$", "", line)
        clean_line = re.sub(r"([\"'`])(?:\\.|(?!\1)[\s\S])*?\1", '""', clean_line)

        stripped = clean_line.strip()
        if not stripped:
            continue

        m_cls = re_class.search(clean_line)
        pending_class = m_cls.group(1) if m_cls else None

        m_fn = re_func.search(clean_line)
        m_arr = re_arrow.search(clean_line)
        m_meth = None

        if class_stack:
            curr_cls = class_stack[-1][0]
            m_meth_candidate = re_method.search(clean_line)
            if m_meth_candidate and not m_cls and not m_fn:
                name = m_meth_candidate.group(1)
                if name not in JS_CONTROL_FLOW:
                    m_meth = f"{curr_cls}.{name}"

        pending_func = None
        if m_meth:
            pending_func = m_meth
        elif m_fn and m_fn.group(1):
            pending_func = m_fn.group(1)
        elif m_arr:
            pending_func = m_arr.group(1)

        if func_stack:
            curr_func = func_stack[-1][0]
            curr_cls = class_stack[-1][0] if class_stack else ""
            for match in re_call.finditer(clean_line):
                recv = match.group(1) or ""
                callee = match.group(2)
                if callee in JS_KEYWORDS or (not recv and callee == curr_func.split(".")[-1]):
                    continue
                if m_meth and callee == m_meth.split(".")[-1]:
                    continue
                if m_fn and callee == m_fn.group(1):
                    continue

                resolved = None
                confidence = "provisional"
                method = "untyped_receiver"

                if recv in ("this", "super"):
                    resolved = f"{curr_cls}.{callee}" if curr_cls else callee
                    confidence = "exact"
                    method = "explicit_class"
                elif recv in imported_symbols:
                    resolved = f"{recv}.{callee}"
                    confidence = "exact"
                    method = "explicit_import"
                elif recv and recv[0].isupper():
                    resolved = f"{recv}.{callee}"
                    confidence = "exact"
                    method = "explicit_class"
                elif not recv:
                    resolved = callee
                    confidence = "exact"
                    method = "explicit_import" if callee in imported_symbols else "lexical_scope"
                else:
                    resolved = f"{recv}.{callee}"

                calls.append(
                    {
                        "caller_symbol": curr_func,
                        "caller_line": func_stack[-1][1],
                        "callee_name": callee,
                        "receiver": recv,
                        "resolved_callee": resolved,
                        "confidence": confidence,
                        "resolution_method": method,
                        "line": lineno,
                    }
                )

        open_b = clean_line.count("{")
        close_b = clean_line.count("}")

        if pending_class and open_b > 0:
            class_stack.append((pending_class, brace_depth + 1))
        if pending_func and open_b > 0:
            func_stack.append((pending_func, brace_depth + 1))

        brace_depth += open_b - close_b

        while func_stack and brace_depth < func_stack[-1][1]:
            func_stack.pop()
        while class_stack and brace_depth < class_stack[-1][1]:
            class_stack.pop()

    return calls
