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


def python_calls(body):
    """Extract call relationships (caller_symbol -> callee_name) for impact analysis with arbitrary nesting."""
    try:
        tree = ast.parse(body)
    except Exception:
        return []
    calls = []

    def record_calls(func_node, caller_names):
        for sub in ast.walk(func_node):
            if isinstance(sub, ast.Call):
                callee = None
                if isinstance(sub.func, ast.Attribute):
                    callee = sub.func.attr
                elif isinstance(sub.func, ast.Name):
                    callee = sub.func.id
                if callee and isinstance(callee, str):
                    for name in caller_names:
                        calls.append((name, callee, sub.lineno))

    def visit(nodes, prefix=""):
        for node in nodes:
            if isinstance(node, ast.ClassDef):
                full_name = f"{prefix}{node.name}"
                visit(node.body, prefix=f"{full_name}.")
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                full_name = f"{prefix}{node.name}"
                names = [node.name]
                if prefix:
                    names.append(full_name)
                record_calls(node, names)
                visit(node.body, prefix=f"{full_name}.")

    visit(tree.body)
    return calls


def javascript_symbols(body):
    """Extract symbols for JavaScript/TypeScript: functions, classes, and exported bindings."""
    patterns = (
        r"^\s*(?:export\s+)?(?:async\s+)?function\s+([a-zA-Z0-9_$]+)",
        r"^\s*(?:export\s+)?class\s+([a-zA-Z0-9_$]+)",
        r"^\s*(?:export\s+)?(?:const|let|var)\s+([a-zA-Z0-9_$]+)\s*=\s*(?:async\s*)?(?:\([^)]*\)|[a-zA-Z0-9_$]+)\s*=>",
    )
    symbols = []
    for n, line in enumerate(body.splitlines(), 1):
        for pat in patterns:
            m = re.match(pat, line)
            if m:
                symbols.append((m.group(1), n))
                break
    return symbols
