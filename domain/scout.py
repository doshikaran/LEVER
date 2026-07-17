"""Pure, bounded static analysis for selecting a callable change surface."""

import ast
import logging
import re
from collections import deque
from dataclasses import dataclass
from typing import Any, Iterable

from domain.schema import (
    AstNodeRef,
    DepEntry,
    DependencyLedger,
    EntryPoint,
    ScopedChangeSet,
)


MAX_REACH_DEPTH = 2
MAX_LEDGER_VISITED_NODES = 10_000
_LOGGER = logging.getLogger(__name__)
_FUNCTION_KINDS = frozenset({"function_definition", "lambda"})
_PARAMETER_KINDS = frozenset(
    {
        "identifier",
        "default_parameter",
        "dictionary_splat_pattern",
        "list_splat_pattern",
        "typed_default_parameter",
        "typed_dictionary_splat_pattern",
        "typed_parameter",
        "typed_splat_pattern",
    }
)
_PLAIN_TYPE_NAMES = frozenset(
    {
        "Any",
        "Annotated",
        "bool",
        "bytes",
        "dict",
        "float",
        "frozenset",
        "int",
        "Iterable",
        "list",
        "Literal",
        "Mapping",
        "None",
        "object",
        "Optional",
        "Sequence",
        "set",
        "str",
        "tuple",
        "Union",
    }
)
_LIVE_PARAMETER_NAMES = frozenset(
    {"app", "connection", "context", "db", "engine", "request", "response", "session", "socket"}
)
_LIVE_TYPE_MARKERS = frozenset(
    {
        "aiohttp",
        "asgi",
        "connection",
        "cursor",
        "django",
        "engine",
        "fastapi",
        "flask",
        "httprequest",
        "httpresponse",
        "request",
        "response",
        "session",
        "socket",
        "sqlalchemy",
        "starlette",
        "wsgi",
    }
)
_CLOCK_MARKERS = frozenset({"clock", "datetime", "monotonic", "perf_counter", "sleep", "time"})
_RANDOM_MARKERS = frozenset({"choice", "rand", "random", "secrets", "shuffle", "uuid"})
_NETWORK_MARKERS = frozenset(
    {"aiohttp", "fetch", "http", "requests", "socket", "urllib", "websocket"}
)
_DB_MARKERS = frozenset(
    {"cursor", "database", "db", "execute", "query", "redis", "sql", "sqlalchemy"}
)
_IO_MARKERS = frozenset(
    {"file", "input", "open", "print", "read", "read_text", "write", "write_text"}
)
_NATIVE_MARKERS = frozenset({"cffi", "ctypes", "ffi", "native", "subprocess"})


@dataclass(frozen=True)
class _FunctionInfo:
    """Static facts about one function or method from a Tree-sitter AST."""

    qualified_name: str
    node: Any
    source: str
    scope_depth: int


def scout(
    base_source: str,
    head_source: str,
    base_ast: Any,
    head_ast: Any,
) -> ScopedChangeSet:
    """Scope a real code change using only Tree-sitter traversal and matching."""
    base_root = _root_node(base_ast)
    head_root = _root_node(head_ast)
    base_functions = _functions_by_name(base_root, base_source)
    head_functions = _functions_by_name(head_root, head_source)
    changed_functions = _changed_functions(base_functions, head_functions)
    changed_nodes = [_node_ref(function) for function in changed_functions]

    call_graph = _build_call_graph(head_functions)
    reachable_functions, reach_depth = _reachable_functions(
        changed_functions,
        head_functions,
        call_graph,
    )

    entry_point, blocked_reasons = _select_entry_point(
        changed_functions,
        _dataclass_names(head_root, head_source),
    )
    if entry_point is None:
        return ScopedChangeSet(
            changed_nodes=changed_nodes,
            reachable_nodes=[_node_ref(function) for function in reachable_functions],
            reach_depth=reach_depth,
            unscopable=True,
            reason=_unscopable_reason(changed_functions, blocked_reasons),
        )

    imports = _build_import_graph(head_root, head_source)
    ledger = _dependency_ledger(entry_point, head_functions, imports)
    return ScopedChangeSet(
        entry_point=EntryPoint(
            fn=entry_point.qualified_name,
            signature=_signature(entry_point),
        ),
        changed_nodes=changed_nodes,
        reachable_nodes=[_node_ref(function) for function in reachable_functions],
        dependency_ledger=ledger,
        reach_depth=reach_depth,
    )


def _root_node(ast_or_root: Any) -> Any:
    """Accept either a Tree-sitter Tree or its root node."""
    return getattr(ast_or_root, "root_node", ast_or_root)


def _functions_by_name(root: Any, source: str) -> dict[str, _FunctionInfo]:
    """Index module, class, and nested functions by their qualified names."""
    functions: dict[str, _FunctionInfo] = {}

    def visit(node: Any, classes: tuple[str, ...], functions_in_scope: tuple[str, ...]) -> None:
        if node.type == "class_definition":
            name = _field_text(node, "name", source)
            next_classes = (*classes, name) if name else classes
            for child in node.children:
                visit(child, next_classes, functions_in_scope)
            return

        if node.type in _FUNCTION_KINDS:
            name = _field_text(node, "name", source) or "<lambda>"
            qualified_name = ".".join((*classes, *functions_in_scope, name))
            functions[qualified_name] = _FunctionInfo(
                qualified_name=qualified_name,
                node=node,
                source=source,
                scope_depth=len(classes) + len(functions_in_scope),
            )
            for child in node.children:
                visit(child, classes, (*functions_in_scope, name))
            return

        for child in node.children:
            visit(child, classes, functions_in_scope)

    visit(root, (), ())
    return functions


def _changed_functions(
    base_functions: dict[str, _FunctionInfo],
    head_functions: dict[str, _FunctionInfo],
) -> list[_FunctionInfo]:
    """Find added, removed, and structurally changed functions and methods."""
    changed: list[_FunctionInfo] = []
    for name in sorted(set(base_functions) | set(head_functions)):
        base_function = base_functions.get(name)
        head_function = head_functions.get(name)
        if base_function is None:
            changed.append(head_function)
        elif head_function is None:
            changed.append(base_function)
        elif _fingerprint(base_function.node, base_function.source) != _fingerprint(
            head_function.node,
            head_function.source,
        ):
            changed.append(head_function)
    return changed


def _fingerprint(node: Any, source: str) -> tuple[Any, ...] | None:
    """Create a formatting-insensitive Tree-sitter node fingerprint."""
    if node.type == "comment":
        return None
    if node.type == "string":
        return ("string", _canonical_string(_node_text(node, source)))

    children = [
        child_fingerprint
        for child in node.children
        if (child_fingerprint := _fingerprint(child, source)) is not None
    ]
    if children:
        return (node.type, tuple(children))
    return (node.type, _node_text(node, source))


def _canonical_string(value: str) -> str:
    """Treat equivalent string quote styles as the same static source value."""
    try:
        literal = ast.literal_eval(value)
    except (SyntaxError, ValueError):
        return value
    return repr(literal) if isinstance(literal, (str, bytes)) else value


def _build_call_graph(functions: dict[str, _FunctionInfo]) -> dict[str, set[str]]:
    """Build a local static call graph between known functions and methods."""
    graph: dict[str, set[str]] = {name: set() for name in functions}
    for function in functions.values():
        for call_name in _call_names(function.node, function.source):
            resolved = _resolve_local_call(call_name, function, functions)
            if resolved is not None:
                graph[function.qualified_name].add(resolved)
    return graph


def _reachable_functions(
    changed_functions: list[_FunctionInfo],
    head_functions: dict[str, _FunctionInfo],
    call_graph: dict[str, set[str]],
) -> tuple[list[_FunctionInfo], int]:
    """Walk changed call surfaces, stopping permanently after depth two."""
    reachable: list[_FunctionInfo] = []
    seen: set[str] = set()
    queue: deque[tuple[str, int]] = deque(
        (function.qualified_name, 0)
        for function in changed_functions
        if function.qualified_name in head_functions
    )
    max_depth = 0

    while queue:
        name, depth = queue.popleft()
        if name in seen:
            continue
        seen.add(name)
        function = head_functions[name]
        reachable.append(function)
        max_depth = max(max_depth, depth)
        if depth == MAX_REACH_DEPTH:
            continue
        for dependency in sorted(call_graph.get(name, ())):
            queue.append((dependency, depth + 1))

    return reachable, max_depth


def _select_entry_point(
    changed_functions: list[_FunctionInfo],
    dataclasses: set[str],
) -> tuple[_FunctionInfo | None, list[str]]:
    """Choose the outermost changed plain-data callable, never a constructor."""
    blocked_reasons: list[str] = []
    for function in sorted(
        changed_functions,
        key=lambda item: (item.scope_depth, item.node.start_byte),
    ):
        if function.qualified_name.endswith(".__init__"):
            blocked_reasons.append(f"`{function.qualified_name}` is a constructor")
            continue
        plain, reason = _has_plain_data_signature(function, dataclasses)
        if plain:
            return function, blocked_reasons
        blocked_reasons.append(reason)
    return None, blocked_reasons


def _has_plain_data_signature(
    function: _FunctionInfo,
    dataclasses: set[str],
) -> tuple[bool, str]:
    """Reject framework/live-object inputs while permitting data and dataclasses."""
    parameters = function.node.child_by_field_name("parameters")
    if parameters is None:
        return True, ""

    for parameter in parameters.children:
        if not parameter.is_named or parameter.type not in _PARAMETER_KINDS:
            continue
        name = _parameter_name(parameter, function.source)
        if name in {"self", "cls", None}:
            continue
        annotation = _parameter_annotation(parameter, function.source)
        if name.lower() in _LIVE_PARAMETER_NAMES:
            return (
                False,
                f"`{function.qualified_name}` requires live framework parameter `{name}`",
            )
        if annotation and not _is_plain_annotation(annotation, dataclasses):
            return (
                False,
                f"`{function.qualified_name}` requires non-plain parameter `{name}: {annotation}`",
            )
    return True, ""


def _dataclass_names(root: Any, source: str) -> set[str]:
    """Find locally declared dataclasses accepted in entry-point signatures."""
    names: set[str] = set()
    for node in _walk(root):
        if node.type != "decorated_definition":
            continue
        decorator_text = " ".join(
            _node_text(child, source)
            for child in node.children
            if child.type == "decorator"
        )
        class_node = next((child for child in node.children if child.type == "class_definition"), None)
        if class_node is not None and "dataclass" in decorator_text:
            name = _field_text(class_node, "name", source)
            if name:
                names.add(name)
    return names


def _is_plain_annotation(annotation: str, dataclasses: set[str]) -> bool:
    """Accept primitive/container/dataclass annotations and reject live frameworks."""
    names = set(re.findall(r"[A-Za-z_]\w*", annotation))
    lowered = {name.lower() for name in names}
    if lowered & _LIVE_TYPE_MARKERS:
        return False
    return names <= (_PLAIN_TYPE_NAMES | dataclasses)


def _dependency_ledger(
    entry_point: _FunctionInfo,
    functions: dict[str, _FunctionInfo],
    imports: dict[str, str],
) -> DependencyLedger:
    """Classify direct and transitive calls from the selected entry point."""
    entries: dict[tuple[str, int], DepEntry] = {}
    queue: deque[tuple[_FunctionInfo, int]] = deque([(entry_point, 0)])
    visited: set[str] = set()

    while queue:
        function, depth = queue.popleft()
        if function.qualified_name in visited:
            continue
        if len(visited) >= MAX_LEDGER_VISITED_NODES:
            _LOGGER.warning(
                "Dependency ledger stopped after %d visited functions; remaining dependencies may be omitted",
                MAX_LEDGER_VISITED_NODES,
            )
            break
        visited.add(function.qualified_name)
        for call_name in _call_names(function.node, function.source):
            dependency_depth = depth + 1
            local_name = _resolve_local_call(call_name, function, functions)
            if local_name is not None:
                entries[(local_name, dependency_depth)] = DepEntry(
                    name=local_name,
                    kind="pure",
                    depth=dependency_depth,
                )
                queue.append((functions[local_name], dependency_depth))
                continue

            resolved_name = _resolve_import_alias(call_name, imports)
            entries[(resolved_name, dependency_depth)] = DepEntry(
                name=resolved_name,
                kind=_classify_dependency(resolved_name),
                depth=dependency_depth,
            )

    return DependencyLedger(entries=sorted(entries.values(), key=lambda entry: (entry.depth, entry.name)))


def _build_import_graph(root: Any, source: str) -> dict[str, str]:
    """Map imported local aliases to the modules they statically name."""
    imports: dict[str, str] = {}
    for node in _walk(root):
        text = _node_text(node, source)
        if node.type == "import_statement":
            for module, alias in re.findall(r"([\w.]+)(?:\s+as\s+(\w+))?", text.removeprefix("import ")):
                imports[alias or module.split(".")[0]] = module
        elif node.type == "import_from_statement":
            match = re.match(r"from\s+([\w.]+)\s+import\s+(.+)", text)
            if match:
                module, imported = match.groups()
                for name, alias in re.findall(r"(\w+)(?:\s+as\s+(\w+))?", imported):
                    imports[alias or name] = f"{module}.{name}"
    return imports


def _resolve_local_call(
    call_name: str,
    caller: _FunctionInfo,
    functions: dict[str, _FunctionInfo],
) -> str | None:
    """Resolve straightforward same-module function and method calls."""
    if call_name in functions:
        return call_name
    if "." not in call_name:
        matches = [name for name in functions if name.split(".")[-1] == call_name]
        return matches[0] if len(matches) == 1 else None
    if call_name.startswith("self."):
        class_prefix = caller.qualified_name.rsplit(".", 1)[0]
        candidate = f"{class_prefix}.{call_name.split('.', 1)[1]}"
        return candidate if candidate in functions else None
    return call_name if call_name in functions else None


def _resolve_import_alias(call_name: str, imports: dict[str, str]) -> str:
    """Expand the first component of an imported alias for classification."""
    first, separator, rest = call_name.partition(".")
    module = imports.get(first, first)
    return f"{module}{separator}{rest}" if separator else module


def _classify_dependency(name: str) -> str:
    """Classify a static call by deterministic module and operation markers."""
    lowered = name.lower()
    if _contains_marker(lowered, _CLOCK_MARKERS):
        return "clock"
    if _contains_marker(lowered, _RANDOM_MARKERS):
        return "random"
    if _contains_marker(lowered, _NETWORK_MARKERS):
        return "network"
    if _contains_marker(lowered, _DB_MARKERS):
        return "db"
    if _contains_marker(lowered, _IO_MARKERS):
        return "io"
    if _contains_marker(lowered, _NATIVE_MARKERS):
        return "native"
    return "pure"


def _contains_marker(name: str, markers: Iterable[str]) -> bool:
    """Match complete dotted-name components to avoid substring false positives."""
    components = set(re.split(r"[^a-z0-9_]+", name))
    return bool(components & set(markers))


def _call_names(node: Any, source: str) -> list[str]:
    """Return the statically named call targets inside a function subtree."""
    names: list[str] = []
    for descendant in _walk(node):
        if descendant is node or descendant.type != "call":
            continue
        function = descendant.child_by_field_name("function")
        if function is not None:
            names.append(_node_text(function, source))
    return names


def _parameter_name(parameter: Any, source: str) -> str | None:
    """Extract the first identifier used as a parameter binding."""
    if parameter.type == "identifier":
        return _node_text(parameter, source)
    identifier = next((node for node in _walk(parameter) if node.type == "identifier"), None)
    return _node_text(identifier, source) if identifier is not None else None


def _parameter_annotation(parameter: Any, source: str) -> str | None:
    """Extract an optional Tree-sitter type annotation for one parameter."""
    annotation = next((node for node in _walk(parameter) if node.type == "type"), None)
    return _node_text(annotation, source) if annotation is not None else None


def _signature(function: _FunctionInfo) -> str:
    """Render a compact static signature suitable for downstream diagnostics."""
    parameters = function.node.child_by_field_name("parameters")
    parameter_text = _node_text(parameters, function.source) if parameters else "()"
    return_type = function.node.child_by_field_name("return_type")
    suffix = f" -> {_node_text(return_type, function.source)}" if return_type else ""
    return f"{function.qualified_name}{parameter_text}{suffix}"


def _node_ref(function: _FunctionInfo) -> AstNodeRef:
    """Convert a selected function node to its serializable source reference."""
    return AstNodeRef(
        kind=function.node.type,
        name=function.qualified_name,
        start_byte=function.node.start_byte,
        end_byte=function.node.end_byte,
    )


def _unscopable_reason(
    changed_functions: list[_FunctionInfo],
    blocked_reasons: list[str],
) -> str:
    """Return a specific human-readable explanation rather than a silent failure."""
    if blocked_reasons:
        return f"No changed function accepts only plain data: {blocked_reasons[0]}."
    if not changed_functions:
        return "No callable function changed, so there is no plain-data entry point to run."
    return "No changed function accepts only plain data."


def _field_text(node: Any, field_name: str, source: str) -> str | None:
    """Read a named Tree-sitter field as UTF-8 source text."""
    child = node.child_by_field_name(field_name)
    return _node_text(child, source) if child is not None else None


def _walk(root: Any):
    """Yield a Tree-sitter node and all of its descendants in source order."""
    yield root
    for child in root.children:
        yield from _walk(child)


def _node_text(node: Any, source: str) -> str:
    """Extract a Tree-sitter node's UTF-8 source slice."""
    return source.encode("utf-8")[node.start_byte : node.end_byte].decode("utf-8")
