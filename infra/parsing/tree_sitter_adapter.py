"""Tree-sitter implementation of the domain code-parser port."""

from typing import Any

import tree_sitter_python
from tree_sitter import Language, Parser

from domain.ports import CodeParser


class TreeSitterPythonParser(CodeParser):
    """Parses Python source into Tree-sitter syntax trees."""

    def __init__(self) -> None:
        self._parser = Parser(Language(tree_sitter_python.language()))

    def parse(self, source: str, language: str) -> Any:
        """Return the Tree-sitter parse tree for supported Python source."""
        if language not in {"python", "py"}:
            raise ValueError(f"Unsupported language: {language}")
        return self._parser.parse(source.encode("utf-8"))
