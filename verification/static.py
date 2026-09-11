"""Static analysis and code syntax verification."""

import ast
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional


@dataclass
class StaticCheckResult:
    passed: bool
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    files_checked: int = 0


class StaticVerifier:
    """Performs static checks, syntax validation, and basic lint checks on Python files."""

    def __init__(self, workspace_path: str | Path) -> None:
        self.workspace_path = Path(workspace_path).resolve()

    def verify_syntax(self, files: Optional[List[str]] = None) -> StaticCheckResult:
        """Verify python syntax for given files or all python files in workspace."""
        errors: List[str] = []
        warnings: List[str] = []
        checked_count = 0

        target_files: List[Path] = []
        if files:
            for f in files:
                p = (self.workspace_path / f).resolve()
                if p.exists() and p.suffix == ".py":
                    target_files.append(p)
        else:
            for root, _, filenames in os.walk(self.workspace_path):
                # Ignore .git, .arc, .venv
                if any(ignored in root for ignored in [".git", ".arc", ".venv", "__pycache__"]):
                    continue
                for fname in filenames:
                    if fname.endswith(".py"):
                        target_files.append(Path(root) / fname)

        for py_file in target_files:
            checked_count += 1
            try:
                content = py_file.read_text(encoding="utf-8")
                ast.parse(content, filename=str(py_file))
            except SyntaxError as e:
                errors.append(f"SyntaxError in {py_file.relative_to(self.workspace_path)}:{e.lineno}: {e.msg}")
            except Exception as e:
                errors.append(f"Error parsing {py_file.relative_to(self.workspace_path)}: {str(e)}")

        return StaticCheckResult(
            passed=len(errors) == 0,
            errors=errors,
            warnings=warnings,
            files_checked=checked_count,
        )
