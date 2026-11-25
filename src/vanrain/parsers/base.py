"""Parser interface: file -> ParseResult.

One parser per language. A parser sees one file at a time and knows nothing
about the rest of the repository: it reports symbols, the edges it can see
without looking elsewhere (CONTAINS), the names its imports bind, and every
other use of a name as an unresolved ``Reference``. The resolver links them.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterable
from pathlib import Path
from typing import ClassVar

from vanrain.model import ParseResult

# Directory names parse_repo never descends into.
IGNORED_DIRS = frozenset(
    {"__pycache__", "node_modules", "venv", "env", "build", "dist", "site-packages"}
)


class Parser(ABC):
    """Turns one source file into a ``ParseResult``."""

    #: File suffixes this parser handles, e.g. ``(".py",)``.
    extensions: ClassVar[tuple[str, ...]] = ()

    @abstractmethod
    def module_id(self, path: str) -> str:
        """Module id for a POSIX path relative to the repository root."""

    @abstractmethod
    def parse(self, path: str, source: str) -> ParseResult:
        """Parse ``source``, the text of the file at ``path``.

        ``path`` is a POSIX path relative to the repository root. Must not
        raise on invalid source: return what can be recovered instead.
        """

    def parse_file(self, root: Path, path: str) -> ParseResult:
        text = (Path(root) / path).read_text(encoding="utf-8", errors="replace")
        return self.parse(path, text)


def iter_source_files(root: Path, extensions: Iterable[str]) -> list[str]:
    """Repo-relative POSIX paths of files with the given suffixes, sorted."""
    root = Path(root)
    exts = tuple(extensions)
    found = []
    for path in root.rglob("*"):
        rel = path.relative_to(root)
        if any(p.startswith(".") or p in IGNORED_DIRS for p in rel.parts[:-1]):
            continue
        if path.is_file() and path.suffix in exts:
            found.append(rel.as_posix())
    return sorted(found)


def parse_repo(root: Path, parsers: Iterable[Parser] | None = None) -> list[ParseResult]:
    """Parse every file under ``root`` that one of ``parsers`` handles."""
    if parsers is None:
        from vanrain.parsers.python_ast import PythonParser

        parsers = [PythonParser()]
    by_ext: dict[str, Parser] = {}
    for parser in parsers:
        for ext in parser.extensions:
            by_ext.setdefault(ext, parser)
    return [
        by_ext[Path(rel).suffix].parse_file(root, rel)
        for rel in iter_source_files(root, by_ext)
    ]
