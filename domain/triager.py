"""Deterministic static gate for changes with no behavior to simulate."""

import ast
from collections import Counter
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any

from infra.parsing.tree_sitter_adapter import TreeSitterPythonParser


MANIFEST_FILES = frozenset(
    {
        "package.json",
        "package-lock.json",
        "yarn.lock",
        "pnpm-lock.yaml",
        "requirements.txt",
        "requirements-dev.txt",
        "pyproject.toml",
        "poetry.lock",
        "Pipfile",
        "Pipfile.lock",
        "go.mod",
        "go.sum",
        "Cargo.toml",
        "Cargo.lock",
        "Gemfile",
        "Gemfile.lock",
        "composer.json",
        "composer.lock",
        "pom.xml",
        "build.gradle",
        "build.gradle.kts",
        "gradle.lockfile",
    }
)

# Tree-sitter Python node kinds corresponding to SPEC.md's behavioral categories.
BEHAVIORAL_KINDS = frozenset(
    {
        "if_statement",
        "while_statement",
        "for_statement",
        "match_statement",
        "return_statement",
        "raise_statement",
        "try_statement",
        "binary_operator",
        "comparison_operator",
        "integer",
        "float",
        "string",
        "concatenated_string",
        "call",
        "nonlocal_assignment",
        "decorator",
        "decorated_definition",
        "async_function_definition",
        "await",
        "await_expression",
        "with_statement",
    }
)

_TYPE_NODE_KIND = "type"
_TYPE_ANNOTATION_PARENTS = frozenset(
    {
        "assignment",
        "function_definition",
        "typed_default_parameter",
        "typed_dictionary_splat_pattern",
        "typed_parameter",
        "typed_splat_pattern",
    }
)
_ASSIGNMENT_KINDS = frozenset({"assignment", "augmented_assignment"})
_FUNCTION_SCOPE_KINDS = frozenset(
    {"function_definition", "lambda", "generator_expression"}
)


@dataclass(frozen=True)
class TriageVerdict:
    """The deterministic gate's decision and optional user-facing skip reason."""

    proceed: bool
    reason: str | None = None


def triage(
    base_source: str,
    head_source: str,
    changed_files: list[str],
) -> TriageVerdict:
    """Apply the nine Triager Gate rules in their specified order."""
    parser = TreeSitterPythonParser()

    # 1. Parse both versions with Tree-sitter.
    base_tree = parser.parse(base_source, "python")
    head_tree = parser.parse(head_source, "python")

    # 2. Normalize comments, formatting, and string quoting.
    base_normalized = _normalize(base_tree.root_node, base_source)
    head_normalized = _normalize(head_tree.root_node, head_source)

    # 3. Identical normalized ASTs are formatting-only changes.
    if base_normalized == head_normalized:
        return TriageVerdict(proceed=False, reason="formatting only")

    # 4. Identical structure with a consistent identifier substitution is a rename.
    if _alpha_equivalent(
        base_tree.root_node,
        head_tree.root_node,
        base_source,
        head_source,
    ):
        return TriageVerdict(proceed=False, reason="rename only")

    # 5. Manifest-only diffs are dependency bumps.
    if changed_files and all(_is_manifest_file(path) for path in changed_files):
        return TriageVerdict(proceed=False, reason="dependency bump")

    # 6. Ignore annotations and re-parse: equal runtime ASTs are types-only.
    base_runtime_source = _without_type_annotations(base_tree.root_node, base_source)
    head_runtime_source = _without_type_annotations(head_tree.root_node, head_source)
    base_runtime_tree = parser.parse(base_runtime_source, "python")
    head_runtime_tree = parser.parse(head_runtime_source, "python")
    if _normalize(base_runtime_tree.root_node, base_runtime_source) == _normalize(
        head_runtime_tree.root_node,
        head_runtime_source,
    ):
        return TriageVerdict(proceed=False, reason="types only, no runtime effect")

    # 7. Count edits to AST nodes with behavioral significance.
    behavioral_edit_count = _behavioral_edit_count(
        base_tree.root_node,
        head_tree.root_node,
        base_source,
        head_source,
    )

    # 8. A diff with no behavioral AST edits has nothing to simulate.
    if behavioral_edit_count == 0:
        return TriageVerdict(proceed=False, reason="no behavioral edits found")

    # 9. All remaining behavioral edits proceed to the pipeline.
    return TriageVerdict(proceed=True)


def _normalize(node: Any, source: str) -> tuple[Any, ...] | None:
    """Serialize a Tree-sitter AST without comments or formatting trivia."""
    if node.type == "comment":
        return None
    if node.type == "string":
        return ("string", _canonical_string(_node_text(node, source)))

    children = [
        normalized
        for child in node.children
        if (normalized := _normalize(child, source)) is not None
    ]
    if children:
        return (node.type, tuple(children))
    return (node.type, _node_text(node, source))


def _canonical_string(value: str) -> str:
    """Canonicalize equivalent Python string literals regardless of quote style."""
    try:
        literal = ast.literal_eval(value)
    except (SyntaxError, ValueError):
        return value
    return repr(literal) if isinstance(literal, (str, bytes)) else value


def _alpha_equivalent(
    base_node: Any,
    head_node: Any,
    base_source: str,
    head_source: str,
) -> bool:
    """Check whether two trees differ only by a consistent identifier rename."""
    substitutions: dict[str, str] = {}
    reverse_substitutions: dict[str, str] = {}

    def equivalent(left: Any, right: Any) -> bool:
        if left.type != right.type:
            return False
        if left.type == "string":
            return _canonical_string(_node_text(left, base_source)) == _canonical_string(
                _node_text(right, head_source)
            )
        if left.type == _TYPE_NODE_KIND:
            return _normalize(left, base_source) == _normalize(right, head_source)

        left_children = _meaningful_children(left)
        right_children = _meaningful_children(right)
        if left.type == "identifier":
            return _consistent_substitution(
                _node_text(left, base_source),
                _node_text(right, head_source),
                substitutions,
                reverse_substitutions,
            )
        if len(left_children) != len(right_children):
            return False
        if not left_children:
            return _node_text(left, base_source) == _node_text(right, head_source)
        return all(equivalent(child_left, child_right) for child_left, child_right in zip(left_children, right_children))

    return equivalent(base_node, head_node)


def _consistent_substitution(
    base_identifier: str,
    head_identifier: str,
    substitutions: dict[str, str],
    reverse_substitutions: dict[str, str],
) -> bool:
    """Maintain a bijection so unrelated identifier changes cannot alpha-match."""
    mapped = substitutions.get(base_identifier)
    if mapped is not None:
        return mapped == head_identifier
    if head_identifier in reverse_substitutions:
        return False
    substitutions[base_identifier] = head_identifier
    reverse_substitutions[head_identifier] = base_identifier
    return True


def _without_type_annotations(root: Any, source: str) -> str:
    """Remove Tree-sitter type-annotation spans while preserving executable source."""
    spans: list[tuple[int, int]] = []
    for node in _walk(root):
        parent = node.parent
        if (
            node.type != _TYPE_NODE_KIND
            or parent is None
            or parent.type not in _TYPE_ANNOTATION_PARENTS
        ):
            continue

        start = node.start_byte
        siblings = list(parent.children)
        index = siblings.index(node)
        if index > 0 and siblings[index - 1].type in {":", "->"}:
            start = siblings[index - 1].start_byte
        spans.append((start, node.end_byte))

    return _remove_byte_spans(source, spans)


def _remove_byte_spans(source: str, spans: list[tuple[int, int]]) -> str:
    """Remove non-overlapping Tree-sitter byte ranges from UTF-8 source."""
    source_bytes = source.encode("utf-8")
    result = bytearray()
    cursor = 0
    for start, end in sorted(spans):
        if start < cursor:
            continue
        result.extend(source_bytes[cursor:start])
        cursor = end
    result.extend(source_bytes[cursor:])
    return result.decode("utf-8")


def _behavioral_edit_count(
    base_root: Any,
    head_root: Any,
    base_source: str,
    head_source: str,
) -> int:
    """Count added or removed behavioral-node fingerprints across two ASTs."""
    base_nodes = _behavioral_nodes(base_root, base_source)
    head_nodes = _behavioral_nodes(head_root, head_source)
    return sum((base_nodes - head_nodes).values()) + sum((head_nodes - base_nodes).values())


def _behavioral_nodes(root: Any, source: str) -> Counter[tuple[str, tuple[Any, ...]]]:
    """Collect behavioral nodes, treating only stateful assignments as behavioral."""
    nodes: Counter[tuple[str, tuple[Any, ...]]] = Counter()
    for node in _walk(root):
        kind = node.type
        if kind in _ASSIGNMENT_KINDS and _is_nonlocal_assignment(node, source):
            kind = "nonlocal_assignment"
        if kind in BEHAVIORAL_KINDS:
            normalized = _normalize(node, source)
            if normalized is not None:
                nodes[(kind, normalized)] += 1
    return nodes


def _is_nonlocal_assignment(node: Any, source: str) -> bool:
    """Recognize module, attribute, subscript, global, and nonlocal assignments."""
    target = node.child_by_field_name("left")
    if target is None:
        return False
    if target.type in {"attribute", "subscript"}:
        return True

    enclosing_scope = _enclosing_function_scope(node)
    if enclosing_scope is None:
        return True
    if target.type != "identifier":
        return False
    target_name = _node_text(target, source)
    return target_name in _declared_nonlocal_names(enclosing_scope, source)


def _enclosing_function_scope(node: Any) -> Any | None:
    """Return the closest function-like ancestor, if one exists."""
    parent = node.parent
    while parent is not None:
        if parent.type in _FUNCTION_SCOPE_KINDS:
            return parent
        parent = parent.parent
    return None


def _declared_nonlocal_names(scope: Any, source: str) -> set[str]:
    """Find global/nonlocal declarations owned by this function scope."""
    names: set[str] = set()

    def visit(node: Any) -> None:
        if node is not scope and node.type in _FUNCTION_SCOPE_KINDS:
            return
        if node.type in {"global_statement", "nonlocal_statement"}:
            names.update(
                _node_text(child, source)
                for child in node.children
                if child.type == "identifier"
            )
            return
        for child in node.children:
            visit(child)

    visit(scope)
    return names


def _meaningful_children(node: Any) -> list[Any]:
    """Return children excluding comments, which are non-semantic trivia."""
    return [child for child in node.children if child.type != "comment"]


def _walk(root: Any):
    """Yield every node in source order without any model involvement."""
    yield root
    for child in root.children:
        yield from _walk(child)


def _node_text(node: Any, source: str) -> str:
    """Extract a node's original UTF-8 source slice."""
    return source.encode("utf-8")[node.start_byte : node.end_byte].decode("utf-8")


def _is_manifest_file(path: str) -> bool:
    """Check a changed path against the known package-manifest basenames."""
    return PurePosixPath(path).name in MANIFEST_FILES
