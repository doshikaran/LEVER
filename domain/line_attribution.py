"""Empirical source-line attribution derived only from generated-driver execution traces."""

import ast
from dataclasses import dataclass
from typing import Any, Literal

from domain.schema import (
    BranchDecision,
    ResponsibleLine,
    TraceAttribution,
    VersionExecutionTrace,
)


class UninstrumentableReferenceError(ValueError):
    """Raised when a reference module cannot receive C-5's Python source transform."""


_BRANCH_TRACE_PREAMBLE = """\
def __lever_branch__(tag, value):
    outcome = bool(value)
    return outcome

def __lever_branch_iter__(tag, iterable):
    for item in iterable:
        __lever_branch__(tag, True)
        yield item
    __lever_branch__(tag, False)

async def __lever_branch_async_iter__(tag, iterable):
    async for item in iterable:
        __lever_branch__(tag, True)
        yield item
    __lever_branch__(tag, False)
"""


class _BranchInstrumenter(ast.NodeTransformer):
    """Wrap Python conditional predicates with deterministic source-location events."""

    @staticmethod
    def _tag(node: ast.AST) -> ast.Constant:
        return ast.Constant(f"{node.lineno}:{node.col_offset}")

    def visit_If(self, node: ast.If) -> ast.If:
        self.generic_visit(node)
        node.test = ast.copy_location(
            ast.Call(
                func=ast.Name(id="__lever_branch__", ctx=ast.Load()),
                args=[self._tag(node), node.test],
                keywords=[],
            ),
            node.test,
        )
        return node

    def visit_While(self, node: ast.While) -> ast.While:
        self.generic_visit(node)
        node.test = ast.copy_location(
            ast.Call(
                func=ast.Name(id="__lever_branch__", ctx=ast.Load()),
                args=[self._tag(node), node.test],
                keywords=[],
            ),
            node.test,
        )
        return node

    def visit_For(self, node: ast.For) -> ast.For:
        self.generic_visit(node)
        node.iter = ast.copy_location(
            ast.Call(
                func=ast.Name(id="__lever_branch_iter__", ctx=ast.Load()),
                args=[self._tag(node), node.iter],
                keywords=[],
            ),
            node.iter,
        )
        return node

    def visit_AsyncFor(self, node: ast.AsyncFor) -> ast.AsyncFor:
        self.generic_visit(node)
        node.iter = ast.copy_location(
            ast.Call(
                func=ast.Name(id="__lever_branch_async_iter__", ctx=ast.Load()),
                args=[self._tag(node), node.iter],
                keywords=[],
            ),
            node.iter,
        )
        return node


def instrument_branch_source(source: str, source_name: str) -> str:
    """Apply C-5's identical conditional-event transform to an instrumentable Python module."""
    if not source_name.endswith(".py"):
        raise UninstrumentableReferenceError(
            f"reference path {source_name!r} is not Python source and cannot be branch-instrumented"
        )
    try:
        tree = ast.parse(source, filename=source_name)
    except SyntaxError as error:
        raise UninstrumentableReferenceError(
            f"reference path {source_name!r} is not parseable Python source and cannot be branch-instrumented"
        ) from error

    transformed = _BranchInstrumenter().visit(tree)
    preamble = ast.parse(_BRANCH_TRACE_PREAMBLE).body
    insertion_index = _preamble_insertion_index(transformed.body)
    transformed.body[insertion_index:insertion_index] = preamble
    ast.fix_missing_locations(transformed)
    return ast.unparse(transformed) + "\n"


def _preamble_insertion_index(body: list[ast.stmt]) -> int:
    """Keep a docstring and mandatory future imports ahead of injected trace helpers."""
    index = 0
    if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
        if isinstance(body[0].value.value, str):
            index = 1
    while (
        index < len(body)
        and isinstance(body[index], ast.ImportFrom)
        and body[index].module == "__future__"
    ):
        index += 1
    return index


def trace_attribution(
    base_trace: dict[str, Any] | None,
    head_trace: dict[str, Any] | None,
    base_source: str,
    head_source: str,
) -> TraceAttribution | None:
    """Pair base/head trace sets and select the first exclusive executed entry line.

    A source line is identified by its executed text, rather than only its line
    number: unrelated files can shift line numbers, and the same numeric line in
    base/head can contain different code.  Candidate lines still originate only
    from ``sys.settrace`` observations.  We enumerate head before base because
    the escape hatch should first surface the changed version when it introduces
    behavior; base-exclusive lines remain the fallback for removals/regressions.
    """
    if base_trace is None or head_trace is None:
        return None

    base = _version_trace(base_trace)
    head = _version_trace(head_trace)
    base_entry = _executed_entry_lines("base", base, base_source)
    head_entry = _executed_entry_lines("head", head, head_source)
    base_text = {line.code for line in base_entry}
    head_text = {line.code for line in head_entry}

    head_only = [line for line in head_entry if line.code not in base_text]
    base_only = [line for line in base_entry if line.code not in head_text]
    responsible = _rank_responsible_line(
        base_only,
        head_only,
        base,
        head,
        base_source,
        head_source,
    )
    return TraceAttribution(base=base, head=head, responsibleLine=responsible)


def _version_trace(raw: dict[str, Any]) -> VersionExecutionTrace:
    """Validate one generated-harness trace without accepting malformed line data."""
    file = raw.get("file")
    executed_lines = raw.get("executed_lines")
    entry_lines = raw.get("entry_lines")
    line_hits = raw.get("line_hits", {})
    raw_branch_decisions = raw.get("branch_decisions", [])
    if not isinstance(file, str) or not isinstance(executed_lines, list) or not isinstance(entry_lines, list):
        raise ValueError("Generated execution trace must contain file, executed_lines, and entry_lines.")
    if not all(isinstance(line, int) and line >= 1 for line in (*executed_lines, *entry_lines)):
        raise ValueError("Generated execution trace lines must be positive integers.")
    if not set(entry_lines).issubset(executed_lines):
        raise ValueError("Generated entry_lines must be a subset of actually executed lines.")
    if not isinstance(line_hits, dict):
        raise ValueError("Generated execution trace line_hits must be a mapping.")
    if not isinstance(raw_branch_decisions, list):
        raise ValueError("Generated execution trace branch_decisions must be a list.")
    normalized_hits: dict[int, int] = {}
    for raw_line, count in line_hits.items():
        try:
            line = int(raw_line)
        except (TypeError, ValueError) as error:
            raise ValueError("Generated execution trace line_hits keys must be line numbers.") from error
        if line < 1 or not isinstance(count, int) or count < 1:
            raise ValueError("Generated execution trace line_hits must contain positive counts.")
        normalized_hits[line] = count
    if not set(normalized_hits).issubset(executed_lines):
        raise ValueError("Generated line_hits must be a subset of actually executed lines.")
    branch_decisions: list[BranchDecision] = []
    for decision in raw_branch_decisions:
        if (
            not isinstance(decision, dict)
            or not isinstance(decision.get("tag"), str)
            or not isinstance(decision.get("outcome"), bool)
        ):
            raise ValueError(
                "Generated execution trace branch_decisions must contain tag/outcome pairs."
            )
        branch_decisions.append(
            BranchDecision(tag=decision["tag"], outcome=decision["outcome"])
        )
    return VersionExecutionTrace(
        file=file,
        executedLines=sorted(set(executed_lines)),
        entryLines=sorted(set(entry_lines)),
        lineHits=normalized_hits,
        branchDecisions=branch_decisions,
    )


def _executed_entry_lines(
    version: Literal["base", "head"],
    trace: VersionExecutionTrace,
    source: str,
) -> list[ResponsibleLine]:
    """Map only dynamic entry-function hits back to their exact versioned source text."""
    source_lines = source.splitlines()
    result: list[ResponsibleLine] = []
    for line in trace.entryLines:
        if line > len(source_lines):
            raise ValueError(f"Trace line {line} is outside the traced source file {trace.file!r}.")
        result.append(
            ResponsibleLine(
                version=version,
                file=trace.file,
                line=line,
                code=source_lines[line - 1].strip(),
            )
        )
    return result


@dataclass(frozen=True)
class _ControlCandidate:
    """One executed control statement plus the count of its taken body entry."""

    line: ResponsibleLine
    body_hits: int
    condition_tokens: frozenset[str]


_CONTROL_NODES = (ast.If, ast.While, ast.For, ast.AsyncFor)
_COUNTERPART_SIMILARITY = 0.2


def _rank_responsible_line(
    base_only: list[ResponsibleLine],
    head_only: list[ResponsibleLine],
    base_trace: VersionExecutionTrace,
    head_trace: VersionExecutionTrace,
    base_source: str,
    head_source: str,
) -> ResponsibleLine | None:
    """Prefer executed branches, ranked by their empirical A/B taken-body delta.

    A plain source-order choice would call an unconditional assignment
    "responsible" for a rewritten function.  Every candidate remains a trace
    hit; AST is used solely to recognize control statements and pair close
    predicates across versions.  The score is derived from the number of times
    each branch's body actually ran for this knob position.
    """
    base_controls = _control_candidates(base_only, base_trace, base_source)
    head_controls = _control_candidates(head_only, head_trace, head_source)
    controls = [*head_controls, *base_controls]
    if not controls:
        # Preserve the original, deterministic head-first fallback when no
        # differing control-flow statement was taken at this position.
        return next(iter(head_only), None) or next(iter(base_only), None)

    def score(candidate: _ControlCandidate, others: list[_ControlCandidate]) -> int:
        matches = [
            other.body_hits
            for other in others
            if _condition_similarity(candidate.condition_tokens, other.condition_tokens)
            >= _COUNTERPART_SIMILARITY
        ]
        if not matches:
            return candidate.body_hits
        return min(abs(candidate.body_hits - matched) for matched in matches)

    ranked = sorted(
        (
            (
                score(candidate, base_controls if candidate.line.version == "head" else head_controls),
                0 if candidate.line.version == "head" else 1,
                candidate.line.line,
                candidate.line,
            )
            for candidate in controls
        ),
        key=lambda item: (-item[0], item[1], item[2]),
    )
    return ranked[0][3]


def _control_candidates(
    lines: list[ResponsibleLine], trace: VersionExecutionTrace, source: str
) -> list[_ControlCandidate]:
    """Return only candidate lines that are actual Python control statements."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    by_line = {line.line: line for line in lines}
    candidates: list[_ControlCandidate] = []
    for node in ast.walk(tree):
        if not isinstance(node, _CONTROL_NODES) or node.lineno not in by_line:
            continue
        body_entry_lines = [statement.lineno for statement in node.body]
        body_hits = sum(trace.lineHits.get(line, 0) for line in body_entry_lines)
        candidates.append(
            _ControlCandidate(
                line=by_line[node.lineno],
                body_hits=body_hits,
                condition_tokens=_condition_tokens(node),
            )
        )
    return candidates


def _condition_tokens(node: ast.stmt) -> frozenset[str]:
    """Extract only AST identifier tokens needed to pair near-equivalent predicates."""
    expression = node.test if isinstance(node, (ast.If, ast.While)) else node.target
    tokens = {
        child.id
        for child in ast.walk(expression)
        if isinstance(child, ast.Name) and child.id != "self"
    }
    tokens.update(
        child.attr
        for child in ast.walk(expression)
        if isinstance(child, ast.Attribute)
    )
    return frozenset(tokens)


def _condition_similarity(left: frozenset[str], right: frozenset[str]) -> float:
    """Use a small structural-token overlap only to find a traced counterpart."""
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)
