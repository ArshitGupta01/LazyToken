"""Lightweight ES module/CommonJS specifier extraction, not symbol resolution."""

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
    import ast

    try:
        tree = ast.parse(body)
    except SyntaxError:
        return []
    modules = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add("." * node.level + node.module)
    return sorted(modules)
