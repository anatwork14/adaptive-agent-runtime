"""Code symbol extraction and lookup index."""

import ast
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional


@dataclass
class CodeSymbol:
    name: str
    kind: str  # class, function, method
    path: str
    start_line: int
    end_line: int


class SymbolIndex:
    """Extracts and queries symbols (functions, classes) from repository source files."""

    def __init__(self) -> None:
        self._symbols_by_name: Dict[str, List[CodeSymbol]] = {}

    def index_python_file(self, rel_path: str, content: str) -> None:
        try:
            tree = ast.parse(content)
        except Exception:
            return

        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                sym = CodeSymbol(
                    name=node.name,
                    kind="class",
                    path=rel_path,
                    start_line=node.lineno,
                    end_line=getattr(node, "end_lineno", node.lineno),
                )
                self._symbols_by_name.setdefault(node.name, []).append(sym)

            elif isinstance(node, ast.FunctionDef):
                sym = CodeSymbol(
                    name=node.name,
                    kind="function",
                    path=rel_path,
                    start_line=node.lineno,
                    end_line=getattr(node, "end_lineno", node.lineno),
                )
                self._symbols_by_name.setdefault(node.name, []).append(sym)

    def lookup_symbol(self, symbol_name: str) -> List[CodeSymbol]:
        """Lookup definitions of symbol_name across indexed repository files."""
        # Support dotted lookups like AuthClient.login
        parts = symbol_name.split(".")
        exact_target = parts[-1]
        return self._symbols_by_name.get(exact_target, [])

    def clear(self) -> None:
        self._symbols_by_name.clear()
