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
            else:
                visit(
                    [
                        child
                        for child in ast.iter_child_nodes(node)
                        if not isinstance(child, ast.expr)
                    ],
                    prefix,
                )

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


LANGUAGE_CAPABILITIES = {
    "python": {
        "language": "python",
        "extensions": [".py"],
        "tier": "ast",
        "features": {
            "symbol_extraction": True,
            "qualified_symbols": True,
            "import_extraction": True,
            "relative_imports": True,
            "call_graph": True,
            "super_resolution": True,
            "attribute_inference": True,
            "local_type_inference": True,
        },
        "confidence_model": "calibrated_ast",
        "supported_confidence_levels": ["exact", "inferred", "provisional"],
        "description": "Full Python standard library AST parsing with scope-aware call graph, inheritance resolution, and attribute inference.",
    },
    "javascript": {
        "language": "javascript",
        "extensions": [".js", ".jsx"],
        "tier": "syntactic_regex",
        "features": {
            "symbol_extraction": True,
            "qualified_symbols": True,
            "import_extraction": True,
            "relative_imports": False,
            "call_graph": True,
            "super_resolution": False,
            "attribute_inference": False,
            "local_type_inference": False,
        },
        "confidence_model": "syntactic_regex",
        "supported_confidence_levels": ["syntactic", "heuristic", "provisional"],
        "description": "Syntactic regex with brace-depth scope tracking. Call graph reflects syntactic token co-occurrence, not semantic type resolution.",
    },
    "typescript": {
        "language": "typescript",
        "extensions": [".ts", ".tsx"],
        "tier": "syntactic_regex",
        "features": {
            "symbol_extraction": True,
            "qualified_symbols": True,
            "import_extraction": True,
            "relative_imports": False,
            "call_graph": True,
            "super_resolution": False,
            "attribute_inference": False,
            "local_type_inference": False,
        },
        "confidence_model": "syntactic_regex",
        "supported_confidence_levels": ["syntactic", "heuristic", "provisional"],
        "description": "Syntactic regex supporting interfaces, types, enums, namespaces, and brace-depth scope tracking. Explicit syntactic confidence levels.",
    },
    "kotlin": {
        "language": "kotlin",
        "extensions": [".kt", ".kts"],
        "tier": "line_pattern",
        "features": {
            "symbol_extraction": True,
            "qualified_symbols": False,
            "import_extraction": True,
            "relative_imports": False,
            "call_graph": False,
            "super_resolution": False,
            "attribute_inference": False,
            "local_type_inference": False,
        },
        "confidence_model": "pattern_heuristic",
        "supported_confidence_levels": ["provisional"],
        "description": "Single-line regex matching for top-level declarations and imports; no call graph or inheritance resolution.",
    },
    "java": {
        "language": "java",
        "extensions": [".java"],
        "tier": "line_pattern",
        "features": {
            "symbol_extraction": True,
            "qualified_symbols": False,
            "import_extraction": True,
            "relative_imports": False,
            "call_graph": False,
            "super_resolution": False,
            "attribute_inference": False,
            "local_type_inference": False,
        },
        "confidence_model": "pattern_heuristic",
        "supported_confidence_levels": ["provisional"],
        "description": "Single-line regex matching for class/method declarations and package imports.",
    },
    "swift": {
        "language": "swift",
        "extensions": [".swift"],
        "tier": "line_pattern",
        "features": {
            "symbol_extraction": True,
            "qualified_symbols": False,
            "import_extraction": True,
            "relative_imports": False,
            "call_graph": False,
            "super_resolution": False,
            "attribute_inference": False,
            "local_type_inference": False,
        },
        "confidence_model": "pattern_heuristic",
        "supported_confidence_levels": ["provisional"],
        "description": "Single-line regex matching for Swift protocols, structs, classes, functions, and imports.",
    },
    "go": {
        "language": "go",
        "extensions": [".go"],
        "tier": "line_pattern",
        "features": {
            "symbol_extraction": True,
            "qualified_symbols": False,
            "import_extraction": True,
            "relative_imports": False,
            "call_graph": False,
            "super_resolution": False,
            "attribute_inference": False,
            "local_type_inference": False,
        },
        "confidence_model": "pattern_heuristic",
        "supported_confidence_levels": ["provisional"],
        "description": "Single-line regex matching for Go functions, structs, interfaces, and imports.",
    },
    "rust": {
        "language": "rust",
        "extensions": [".rs"],
        "tier": "line_pattern",
        "features": {
            "symbol_extraction": True,
            "qualified_symbols": False,
            "import_extraction": True,
            "relative_imports": False,
            "call_graph": False,
            "super_resolution": False,
            "attribute_inference": False,
            "local_type_inference": False,
        },
        "confidence_model": "pattern_heuristic",
        "supported_confidence_levels": ["provisional"],
        "description": "Single-line regex matching for Rust traits, structs, impls, fns, and use statements.",
    },
    "csharp": {
        "language": "csharp",
        "extensions": [".cs"],
        "tier": "line_pattern",
        "features": {
            "symbol_extraction": True,
            "qualified_symbols": False,
            "import_extraction": True,
            "relative_imports": False,
            "call_graph": False,
            "super_resolution": False,
            "attribute_inference": False,
            "local_type_inference": False,
        },
        "confidence_model": "pattern_heuristic",
        "supported_confidence_levels": ["provisional"],
        "description": "Single-line regex matching for C# namespaces, classes, interfaces, and using statements.",
    },
    "sql": {
        "language": "sql",
        "extensions": [".sql"],
        "tier": "line_pattern",
        "features": {
            "symbol_extraction": True,
            "qualified_symbols": False,
            "import_extraction": False,
            "relative_imports": False,
            "call_graph": False,
            "super_resolution": False,
            "attribute_inference": False,
            "local_type_inference": False,
        },
        "confidence_model": "pattern_heuristic",
        "supported_confidence_levels": ["provisional"],
        "description": "Line-level regex matching for table and view definitions.",
    },
    "gradle": {
        "language": "gradle",
        "extensions": [".gradle"],
        "tier": "line_pattern",
        "features": {
            "symbol_extraction": True,
            "qualified_symbols": False,
            "import_extraction": True,
            "relative_imports": False,
            "call_graph": False,
            "super_resolution": False,
            "attribute_inference": False,
            "local_type_inference": False,
        },
        "confidence_model": "pattern_heuristic",
        "supported_confidence_levels": ["provisional"],
        "description": "Build script regex matching for plugins and dependencies.",
    },
    "document": {
        "language": "document",
        "extensions": [".md", ".html", ".css", ".scss", ".json", ".yml", ".yaml", ".toml"],
        "tier": "text_only",
        "features": {
            "symbol_extraction": False,
            "qualified_symbols": False,
            "import_extraction": False,
            "relative_imports": False,
            "call_graph": False,
            "super_resolution": False,
            "attribute_inference": False,
            "local_type_inference": False,
        },
        "confidence_model": "none",
        "supported_confidence_levels": [],
        "description": "Content indexed for full-text search and file digest tracking; no symbol or call graph extraction.",
    },
}


def get_language_capabilities(target=None):
    if not target:
        return LANGUAGE_CAPABILITIES
    target_clean = str(target).lower().strip()
    if target_clean in LANGUAGE_CAPABILITIES:
        return LANGUAGE_CAPABILITIES[target_clean]
    ext = target_clean if target_clean.startswith(".") else f".{target_clean}"
    for lang, spec in LANGUAGE_CAPABILITIES.items():
        if ext in spec["extensions"]:
            return spec
    # Graceful fallback for unknown extension: line_pattern tier
    return {
        "language": target_clean.lstrip("."),
        "extensions": [ext],
        "tier": "line_pattern",
        "features": {
            "symbol_extraction": False,
            "qualified_symbols": False,
            "import_extraction": False,
            "relative_imports": False,
            "call_graph": False,
            "super_resolution": False,
            "attribute_inference": False,
            "local_type_inference": False,
        },
        "confidence_model": "pattern_heuristic",
        "supported_confidence_levels": ["provisional"],
        "description": f"Fallback pattern matching for {ext} files.",
    }


def language_for_file(path):
    p = str(path).lower()
    suffix = "." + p.rsplit(".", 1)[-1] if "." in p else ""
    for lang, spec in LANGUAGE_CAPABILITIES.items():
        if suffix in spec["extensions"]:
            return lang
    return "document"


def _extract_name(node):
    """Recursively extract dotted name from Name, Attribute, or Subscript node."""
    if node is None:
        return None
    if isinstance(node, ast.Name):
        return node.id
    elif isinstance(node, ast.Attribute):
        parent = _extract_name(node.value)
        return f"{parent}.{node.attr}" if parent else node.attr
    elif isinstance(node, ast.Subscript):
        return _extract_name(node.value)
    return None


def extract_type_from_annotation(node):
    """Extract class/type name from an annotation node (Name, Attribute, Subscript, BinOp)."""
    if node is None:
        return None
    if isinstance(node, ast.Name):
        return node.id
    elif isinstance(node, ast.Attribute):
        return node.attr
    elif isinstance(node, ast.Subscript):
        val_name = getattr(node.value, "id", "") or getattr(node.value, "attr", "")
        slice_node = getattr(node, "slice", None)
        if isinstance(slice_node, (ast.Name, ast.Attribute)):
            return extract_type_from_annotation(slice_node)
        elif isinstance(slice_node, ast.Tuple):
            for elem in slice_node.elts:
                t = extract_type_from_annotation(elem)
                if t and t not in ("None", "NoneType"):
                    return t
        elif slice_node is not None:
            return extract_type_from_annotation(slice_node)
    elif isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
        left = extract_type_from_annotation(node.left)
        if left and left not in ("None", "NoneType"):
            return left
        return extract_type_from_annotation(node.right)
    return None


def extract_type_from_expr(node):
    """Extract instantiated class name from an assignment expression."""
    if node is None:
        return None
    if isinstance(node, ast.Call):
        func = node.func
        if isinstance(func, ast.Name):
            return func.id
        elif isinstance(func, ast.Attribute):
            return func.attr
    return None


def walk_local_stmts(node):
    """Walk statements in function body without descending into nested functions or classes."""
    body = getattr(node, "body", [])
    if isinstance(body, list):
        for child in body:
            yield child
            if isinstance(child, (ast.If, ast.While, ast.For, ast.AsyncFor)):
                yield from walk_local_stmts(child)
                for orelse in getattr(child, "orelse", []):
                    yield orelse
                    if isinstance(
                        orelse,
                        (
                            ast.If,
                            ast.While,
                            ast.For,
                            ast.AsyncFor,
                            ast.Try,
                            ast.With,
                            ast.AsyncWith,
                        ),
                    ):
                        yield from walk_local_stmts(orelse)
            elif isinstance(child, (ast.With, ast.AsyncWith)):
                yield from walk_local_stmts(child)
            elif isinstance(child, ast.Try):
                yield from walk_local_stmts(child)
                for h in child.handlers:
                    yield from walk_local_stmts(h)
                for orelse in child.orelse:
                    yield from walk_local_stmts(orelse)
                for f in child.finalbody:
                    yield from walk_local_stmts(f)


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

    # Pass 1: Extract class hierarchy and class attributes
    class_hierarchy = {}
    class_attrs = {}

    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            bases = []
            for b in node.bases:
                b_name = _extract_name(b)
                if b_name:
                    bases.append(b_name)
            methods = set()
            properties = set()
            attrs = {}

            # Class-level annotations (AnnAssign) and assignments (Assign)
            for item in node.body:
                if isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name):
                    t = extract_type_from_annotation(item.annotation) or extract_type_from_expr(
                        item.value
                    )
                    if t:
                        attrs[item.target.id] = t
                elif isinstance(item, ast.Assign):
                    t = extract_type_from_expr(item.value)
                    if t:
                        for target in item.targets:
                            if isinstance(target, ast.Name):
                                attrs[target.id] = t
                elif isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    methods.add(item.name)
                    # Check @property
                    is_prop = False
                    for dec in getattr(item, "decorator_list", []):
                        d_name = _extract_name(dec)
                        if d_name == "property":
                            is_prop = True
                            properties.add(item.name)
                            break
                    if is_prop:
                        t = extract_type_from_annotation(item.returns)
                        if not t:
                            for stmt in walk_local_stmts(item):
                                if isinstance(stmt, ast.Return):
                                    t = extract_type_from_expr(
                                        stmt.value
                                    ) or extract_type_from_annotation(
                                        getattr(stmt.value, "annotation", None)
                                    )
                                    if t:
                                        break
                        if t:
                            attrs[item.name] = t

                    # Inspect method body for self.<attr> assignments across all methods
                    for stmt in walk_local_stmts(item):
                        if isinstance(stmt, ast.Assign):
                            t = extract_type_from_expr(stmt.value)
                            if t:
                                for target in stmt.targets:
                                    if (
                                        isinstance(target, ast.Attribute)
                                        and isinstance(target.value, ast.Name)
                                        and target.value.id == "self"
                                    ):
                                        attrs[target.attr] = t
                        elif isinstance(stmt, ast.AnnAssign):
                            if (
                                isinstance(stmt.target, ast.Attribute)
                                and isinstance(stmt.target.value, ast.Name)
                                and stmt.target.value.id == "self"
                            ):
                                t = extract_type_from_annotation(
                                    stmt.annotation
                                ) or extract_type_from_expr(stmt.value)
                                if t:
                                    attrs[stmt.target.attr] = t

            class_hierarchy[node.name] = {
                "bases": bases,
                "methods": methods,
                "properties": properties,
                "full_name": node.name,
            }
            class_attrs[node.name] = attrs

    def resolve_super_target(start_class, callee_name):
        """Accurately resolve super().callee to parent class across local AST hierarchy and external bases."""
        if start_class not in class_hierarchy:
            return callee_name, "provisional", "unresolved_super"

        bases = class_hierarchy[start_class]["bases"]
        if not bases:
            if callee_name in ("__init__", "__new__", "__repr__", "__str__", "__eq__", "__hash__"):
                return f"object.{callee_name}", "exact", "super_resolution"
            return callee_name, "provisional", "unresolved_super_base"

        def linearize(name, seen):
            if name in seen or name not in class_hierarchy:
                return None
            parents = class_hierarchy[name]["bases"]
            sequences = []
            for parent in parents:
                order = linearize(parent, seen | {name})
                if order is None:
                    return None
                sequences.append(order)
            sequences.append(list(parents))
            result = [name]
            while any(sequences):
                sequences = [s for s in sequences if s]
                candidate = next(
                    (s[0] for s in sequences if all(s[0] not in other[1:] for other in sequences)),
                    None,
                )
                if candidate is None:
                    return None
                result.append(candidate)
                for sequence in sequences:
                    if sequence[0] == candidate:
                        sequence.pop(0)
            return result

        order = linearize(start_class, set())
        if order is not None:
            for base in order[1:]:
                if callee_name in class_hierarchy[base]["methods"]:
                    return f"{base}.{callee_name}", "exact", "super_resolution"
            return f"{bases[0]}.{callee_name}", "provisional", "unresolved_super_method"

        queue = list(bases)
        visited = set()
        external_candidates = []

        while queue:
            base = queue.pop(0)
            short_base = base.split(".")[-1]
            lookup_base = (
                base
                if base in class_hierarchy
                else (short_base if short_base in class_hierarchy else None)
            )

            if lookup_base and lookup_base not in visited:
                visited.add(lookup_base)
                if callee_name in class_hierarchy[lookup_base]["methods"]:
                    return (
                        f"{lookup_base}.{callee_name}",
                        "provisional",
                        "multiple_inheritance_ambiguous",
                    )
                queue.extend(class_hierarchy[lookup_base]["bases"])
            elif base not in visited and base != "object":
                visited.add(base)
                external_candidates.append(base)

        if len(external_candidates) == 1:
            ext = external_candidates[0]
            resolved_ext = ext.split(".")[-1]
            return f"{resolved_ext}.{callee_name}", "inferred", "super_resolution"
        elif len(external_candidates) > 1:
            first_ext = external_candidates[0].split(".")[-1]
            return f"{first_ext}.{callee_name}", "provisional", "multiple_inheritance_ambiguous"

        first_base = bases[0].split(".")[-1]
        return f"{first_base}.{callee_name}", "provisional", "unresolved_super_method"

    def extract_local_types(func_node):
        local_types = {}
        for arg in getattr(getattr(func_node, "args", None), "args", []):
            t = extract_type_from_annotation(arg.annotation)
            if t:
                local_types[arg.arg] = t
        for stmt in walk_local_stmts(func_node):
            if isinstance(stmt, ast.Assign):
                t = extract_type_from_expr(stmt.value)
                if t:
                    for target in stmt.targets:
                        if isinstance(target, ast.Name):
                            local_types[target.id] = t
            elif isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
                t = extract_type_from_annotation(stmt.annotation) or extract_type_from_expr(
                    stmt.value
                )
                if t:
                    local_types[stmt.target.id] = t
            elif isinstance(stmt, (ast.With, ast.AsyncWith)):
                for item in stmt.items:
                    if item.optional_vars and isinstance(item.optional_vars, ast.Name):
                        t = extract_type_from_expr(item.context_expr)
                        if t:
                            local_types[item.optional_vars.id] = t
        return local_types

    def record_calls(func_node, caller_names, class_name="", is_lambda=False):
        local_types = extract_local_types(func_node)
        arguments = getattr(func_node, "args", None)
        bound_names = set()
        if arguments:
            bound_names.update(
                arg.arg for arg in arguments.posonlyargs + arguments.args + arguments.kwonlyargs
            )
            bound_names.update(arg.arg for arg in (arguments.vararg, arguments.kwarg) if arg)
        for stmt in walk_local_stmts(func_node):
            bound_names.update(
                node.id
                for node in ast.walk(stmt)
                if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store)
            )
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
                        if callee_name in class_hierarchy.get(class_name, {}).get("methods", set()):
                            resolved = f"{class_name}.{callee_name}"
                        else:
                            resolved, _, _ = resolve_super_target(class_name, callee_name)
                        confidence = "inferred"
                        resolution_method = "inferred_type"
                    elif receiver in local_types:
                        inferred_cls = local_types[receiver]
                        resolved = f"{inferred_cls}.{callee_name}"
                        confidence = "inferred"
                        resolution_method = "inferred_type"
                    elif receiver in imported_symbols and receiver not in bound_names:
                        resolved = f"{receiver}.{callee_name}"
                        confidence = "exact"
                        resolution_method = "explicit_import"
                    elif receiver:
                        resolved = f"{receiver}.{callee_name}"
                        confidence = (
                            "inferred"
                            if receiver[0].isupper() and receiver not in bound_names
                            else "provisional"
                        )
                        resolution_method = (
                            "explicit_class"
                            if receiver[0].isupper() and receiver not in bound_names
                            else "untyped_receiver"
                        )
                elif (
                    isinstance(val, ast.Attribute)
                    and isinstance(val.value, ast.Name)
                    and val.value.id == "self"
                ):
                    attr_name = val.attr
                    receiver = f"self.{attr_name}"
                    store_cls = class_attrs.get(class_name, {}).get(attr_name)
                    if not store_cls and class_name in class_hierarchy:
                        for b in class_hierarchy[class_name]["bases"]:
                            short_b = b.split(".")[-1]
                            store_cls = class_attrs.get(b, {}).get(attr_name) or class_attrs.get(
                                short_b, {}
                            ).get(attr_name)
                            if store_cls:
                                break
                    if store_cls:
                        resolved = f"{store_cls}.{callee_name}"
                        confidence = "inferred"
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
                    start_cls = class_name
                    if val.args and isinstance(val.args[0], ast.Name):
                        start_cls = val.args[0].id
                    if class_name:
                        resolved, confidence, resolution_method = resolve_super_target(
                            start_cls, callee_name
                        )
            elif isinstance(call_node.func, ast.Name):
                if call_node.func.id == "super":
                    continue
                callee_name = call_node.func.id
                receiver = ""
                resolved = callee_name
                confidence = (
                    "inferred"
                    if callee_name in imported_symbols and callee_name not in bound_names
                    else "provisional"
                )
                resolution_method = (
                    "explicit_import"
                    if callee_name in imported_symbols and callee_name not in bound_names
                    else "lexical_scope"
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
            else:
                visit(
                    [
                        child
                        for child in ast.iter_child_nodes(node)
                        if not isinstance(child, ast.expr)
                    ],
                    prefix,
                    class_name,
                )

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

JS_BUILTINS = {
    "Math",
    "JSON",
    "Object",
    "Array",
    "Promise",
    "String",
    "Number",
    "Boolean",
    "RegExp",
    "Date",
    "Error",
    "Map",
    "Set",
    "WeakMap",
    "WeakSet",
    "Symbol",
    "Reflect",
    "Proxy",
    "Intl",
    "Console",
    "console",
    "process",
    "Buffer",
}

JS_GLOBAL_FUNCS = {
    "fetch",
    "setTimeout",
    "clearTimeout",
    "setInterval",
    "clearInterval",
    "setImmediate",
    "clearImmediate",
    "require",
    "parseInt",
    "parseFloat",
    "encodeURI",
    "decodeURI",
    "encodeURIComponent",
    "decodeURIComponent",
    "isNaN",
    "isFinite",
}


def javascript_symbols(body):
    """Extract symbols for JavaScript/TypeScript: functions, classes, methods, interfaces, types, enums, and namespaces."""
    symbols = []
    class_stack = []

    re_class = re.compile(
        r"^\s*(?:export\s+)?(?:default\s+)?(?:abstract\s+)?class\s+([a-zA-Z0-9_$]+)(?:\s+extends\s+([a-zA-Z0-9_$]+))?"
    )
    re_decl = re.compile(
        r"^\s*(?:export\s+)?(?:default\s+)?(?:interface|type|enum|namespace)\s+([a-zA-Z0-9_$]+)"
    )
    re_func = re.compile(
        r"^\s*(?:export\s+)?(?:default\s+)?(?:async\s+)?function(?:\s+([a-zA-Z0-9_$]+)|\s*\()"
    )
    re_arrow = re.compile(
        r"^\s*(?:export\s+)?(?:const|let|var)\s+([a-zA-Z0-9_$]+)\s*(?::\s*.*?\s*)?=\s*(?:async\s*)?(?:\([^)]*\)|[a-zA-Z0-9_$]+)\s*=>"
    )
    re_method = re.compile(
        r"^\s*(?:(?:public|private|protected|static|readonly|async|override)\s+)*(?:get\s+|set\s+)?([a-zA-Z0-9_$]+)\s*(?:<[^>]+>)?\s*\([^)]*\)\s*(?::\s*[^{;]+)?\s*[\{;]"
    )

    token = re.compile(r'(["\'`])(?:\\.|(?!\1)[\s\S])*?\1|//[^\n]*|/\*[\s\S]*?\*/')
    masked = token.sub(lambda m: re.sub(r"[^\n]", " ", m.group(0)), body)
    for n, clean in enumerate(masked.splitlines(), 1):
        stripped = clean.strip()
        if not stripped or stripped.startswith("/*") or stripped.startswith("*"):
            continue

        m_cls = re_class.search(clean)
        if m_cls:
            cls_name = m_cls.group(1)
            symbols.append((cls_name, n))
            class_stack.append({"name": cls_name, "brace_depth": 0})
            after_open = clean.find("{", m_cls.end())
            if after_open >= 0:
                inline_method = re_method.search(clean[after_open + 1 :])
                if inline_method and inline_method.group(1) not in JS_CONTROL_FLOW:
                    symbols.extend(
                        [(inline_method.group(1), n), (f"{cls_name}.{inline_method.group(1)}", n)]
                    )

        m_decl = re_decl.search(clean)
        if m_decl:
            symbols.append((m_decl.group(1), n))

        m_fn = re_func.search(clean)
        if m_fn and m_fn.group(1):
            symbols.append((m_fn.group(1), n))

        m_arrow = re_arrow.search(clean)
        if m_arrow:
            symbols.append((m_arrow.group(1), n))

        if class_stack and class_stack[-1]["brace_depth"] == 1:
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


class JSClassFrame:
    def __init__(self, name, base, depth):
        self.name = name
        self.base = base
        self.depth = depth

    def __getitem__(self, idx):
        if idx == 0:
            return self.name
        if idx == 1:
            return self.depth
        raise IndexError(idx)

    def get(self, key, default=None):
        if key == "name":
            return self.name
        if key == "base":
            return self.base
        if key == "depth":
            return self.depth
        return default


def javascript_calls(body):
    """Extract call relationships (caller_symbol -> callee_name) for JavaScript and TypeScript with calibrated confidence."""
    calls = []
    # Preserve line numbers while masking comments and literals.
    token = re.compile(r'(["\'`])(?:\\.|(?!\1)[\s\S])*?\1|//[^\n]*|/\*[\s\S]*?\*/')
    masked = token.sub(lambda m: re.sub(r"[^\n]", " ", m.group(0)), body)
    lines = body.splitlines()
    clean_lines = masked.splitlines()

    imported_symbols = set()
    local_classes = {}
    local_functions = set()

    re_class = re.compile(
        r"^\s*(?:export\s+)?(?:default\s+)?(?:abstract\s+)?class\s+([a-zA-Z0-9_$]+)(?:\s+extends\s+([a-zA-Z0-9_$]+))?"
    )
    re_func = re.compile(
        r"^\s*(?:export\s+)?(?:default\s+)?(?:async\s+)?function(?:\s+([a-zA-Z0-9_$]+)|\s*\()"
    )
    re_arrow = re.compile(
        r"^\s*(?:export\s+)?(?:const|let|var)\s+([a-zA-Z0-9_$]+)\s*(?::\s*.*?\s*)?=\s*(?:async\s*)?(?:\([^)]*\)|[a-zA-Z0-9_$]+)\s*=>"
    )
    re_method = re.compile(
        r"^\s*(?:(?:public|private|protected|static|readonly|async|override)\s+)*(?:get\s+|set\s+)?([a-zA-Z0-9_$]+)\s*(?:<[^>]+>)?\s*\([^)]*\)\s*(?::\s*[^{;]+)?\s*[\{;]"
    )
    re_call = re.compile(r"(?:([a-zA-Z0-9_$]+(?:\.[a-zA-Z0-9_$]+)?)\.)?([a-zA-Z0-9_$]+)\s*\(")

    for line, clean in zip(lines, clean_lines):
        import_line = line if re.match(r"^\s*import\b", clean) else ""
        m_named = re.findall(r"import\s+(?:[a-zA-Z0-9_$]+\s*,\s*)?\{([^}]+)\}\s+from", import_line)
        for group in m_named:
            for item in group.split(","):
                sym = item.strip().split(" as ")[-1].strip()
                if sym:
                    imported_symbols.add(sym)
        m_default = re.search(r"import\s+([a-zA-Z0-9_$]+)\s*(?:,|\s+from)", import_line)
        if m_default:
            imported_symbols.add(m_default.group(1))

        m_cls_pre = re_class.search(clean)
        if m_cls_pre:
            local_classes[m_cls_pre.group(1)] = m_cls_pre.group(2)
        m_fn_pre = re_func.search(clean)
        if m_fn_pre and m_fn_pre.group(1):
            local_functions.add(m_fn_pre.group(1))
        m_arr_pre = re_arrow.search(clean)
        if m_arr_pre and m_arr_pre.group(1):
            local_functions.add(m_arr_pre.group(1))

    class_stack = []
    func_stack = []
    brace_depth = 0

    for lineno, clean_line in enumerate(clean_lines, 1):

        stripped = clean_line.strip()
        if not stripped:
            continue

        m_cls = re_class.search(clean_line)
        pending_class = m_cls.group(1) if m_cls else None
        pending_base = m_cls.group(2) if m_cls else None

        m_fn = re_func.search(clean_line)
        m_arr = re_arrow.search(clean_line)
        m_meth = None

        if class_stack and brace_depth == class_stack[-1].depth:
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

        open_b = clean_line.count("{")
        close_b = clean_line.count("}")
        if pending_class and open_b > 0:
            class_stack.append(JSClassFrame(pending_class, pending_base, brace_depth + 1))
        if pending_func and open_b > 0:
            func_stack.append((pending_func, brace_depth + 1, lineno))

        concise_arrow = bool(m_arr and open_b == 0)
        if func_stack or concise_arrow:
            curr_func = pending_func if concise_arrow else func_stack[-1][0]
            curr_cls = class_stack[-1][0] if class_stack else ""
            for match in re_call.finditer(clean_line):
                recv = match.group(1) or ""
                callee = match.group(2)
                if callee in JS_KEYWORDS or callee in JS_CONTROL_FLOW:
                    continue
                if m_meth and match.start(2) == m_meth_candidate.start(1):
                    continue
                if m_fn and match.start(2) == m_fn.start(1):
                    continue

                resolved = None
                confidence = "provisional"
                method = "untyped_receiver"

                if recv == "super":
                    base_cls = class_stack[-1].get("base") if class_stack else None
                    if base_cls:
                        resolved = f"{base_cls}.{callee}"
                        confidence = "syntactic"
                        method = "super_parent_class"
                    else:
                        resolved = callee
                        confidence = "provisional"
                        method = "unresolved_super"
                elif recv == "this":
                    if curr_cls:
                        resolved = f"{curr_cls}.{callee}"
                        confidence = "syntactic"
                        method = "explicit_class"
                    else:
                        resolved = callee
                        confidence = "provisional"
                        method = "untyped_receiver"
                elif recv in imported_symbols:
                    resolved = f"{recv}.{callee}"
                    confidence = "syntactic"
                    method = "explicit_import"
                elif recv in JS_BUILTINS:
                    resolved = f"{recv}.{callee}"
                    confidence = "provisional"
                    method = "builtin"
                elif recv and recv[0].isupper():
                    if recv in local_classes:
                        resolved = f"{recv}.{callee}"
                        confidence = "syntactic"
                        method = "explicit_class"
                    else:
                        resolved = f"{recv}.{callee}"
                        confidence = "heuristic"
                        method = "pascal_case_heuristic"
                elif not recv:
                    if callee in imported_symbols:
                        resolved = callee
                        confidence = "syntactic"
                        method = "explicit_import"
                    elif callee in local_functions:
                        resolved = callee
                        confidence = "syntactic"
                        method = "lexical_scope"
                    elif callee in JS_GLOBAL_FUNCS:
                        resolved = callee
                        confidence = "provisional"
                        method = "builtin_global"
                    else:
                        resolved = callee
                        confidence = "provisional"
                        method = "unresolved_global"
                else:
                    resolved = f"{recv}.{callee}"
                    confidence = "provisional"
                    method = "untyped_receiver"

                calls.append(
                    {
                        "caller_symbol": curr_func,
                        "caller_line": lineno if concise_arrow else func_stack[-1][2],
                        "callee_name": callee,
                        "receiver": recv,
                        "resolved_callee": resolved,
                        "confidence": confidence,
                        "resolution_method": method,
                        "line": lineno,
                    }
                )

        brace_depth += open_b - close_b

        while func_stack and brace_depth < func_stack[-1][1]:
            func_stack.pop()
        while class_stack and brace_depth < class_stack[-1][1]:
            class_stack.pop()

    return calls
