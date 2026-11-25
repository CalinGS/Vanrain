"""Turn a Selection into markdown the LLM reads.

Layout: a title, one line saying what was selected, then one section per file
(files ordered by their nearest symbol, then path), each holding one code
block with the file's symbols in line order. Every symbol starts with a
comment line giving its id and line span::

    # Context for shop.checkout.checkout

    5 symbols (1 full, 4 signatures), 96 of 100 tokens. ...

    ## shop/checkout.py

    ```python
    # shop.checkout.checkout L10-14
    def checkout(items: list[Item], discount: float = 0.0) -> float:
        ...
    ```

``FULL`` items show their source, dedented. ``SIGNATURE`` items show
``Symbol.signature`` followed by ``...`` where the body would be. Items inside
a ``FULL`` item are not repeated. Output depends only on the selection, the
graph and the files, so it is deterministic.
"""

from __future__ import annotations

import os
import textwrap
from pathlib import Path

from vanrain.graph import CodeGraph
from vanrain.model import Detail, NodeKind, Selection, SelectionItem, Symbol
from vanrain.selector.base import ancestors, item_header

_FENCE_LANG = {".py": "python", ".pyi": "python", ".ts": "typescript", ".go": "go"}


def render(selection: Selection, graph: CodeGraph, root: str | os.PathLike) -> str:
    """Markdown for ``selection``. Source is read from the files under ``root``."""
    root = Path(root)
    title = ", ".join(selection.seeds)
    out = [f"# Context for {title}", ""]
    if not selection.items:
        out.append(f"Nothing fits in a budget of {selection.budget} tokens.")
        return "\n".join(out) + "\n"

    full = sum(i.detail is Detail.FULL for i in selection.items)
    out.append(
        f"{len(selection.items)} symbols ({full} full, {len(selection.items) - full} signatures), "
        f"{selection.tokens_used} of {selection.budget} tokens. "
        "Symbols ending in `...` are signatures only; their bodies are left out."
    )

    full_ids = {i.symbol for i in selection.items if i.detail is Detail.FULL}
    by_file: dict[str, list[tuple[Symbol, SelectionItem]]] = {}
    for item in selection.items:
        if full_ids.intersection(ancestors(graph, item.symbol)):
            continue  # shown inside its ancestor
        sym = graph.symbol(item.symbol)
        by_file.setdefault(sym.file, []).append((sym, item))

    files = sorted(by_file, key=lambda f: (min(i.distance for _, i in by_file[f]), f))
    reader = _SourceReader(root)
    for file in files:
        lang = _FENCE_LANG.get(Path(file).suffix, "")
        blocks = [
            _symbol_block(sym, item, reader)
            for sym, item in sorted(by_file[file], key=lambda p: (p[0].span[0], p[0].id))
        ]
        out += ["", f"## {file}", "", f"```{lang}", "\n\n".join(blocks), "```"]
    return "\n".join(out) + "\n"


def _symbol_block(sym: Symbol, item: SelectionItem, reader: _SourceReader) -> str:
    head = item_header(sym)
    if item.detail is Detail.FULL:
        source = reader.lines(sym.file, sym.span)
        if source is not None:
            return f"{head}\n{textwrap.dedent(source).rstrip()}"
        head += " (source not found, signature only)"
    return f"{head}\n{_signature(sym)}" if sym.signature else head


def _signature(sym: Symbol) -> str:
    sig = sym.signature.rstrip()
    if sym.kind is NodeKind.MODULE:
        return sig
    if sig.endswith(":"):
        return sig + " ..."
    return sig + "\n    ..."


class _SourceReader:
    """Reads files once each; ``None`` when a file or span is missing."""

    def __init__(self, root: Path):
        self.root = root
        self._files: dict[str, list[str] | None] = {}

    def lines(self, file: str, span: tuple[int, int]) -> str | None:
        if file not in self._files:
            try:
                text = (self.root / file).read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                self._files[file] = None
            else:
                self._files[file] = text.splitlines()
        lines = self._files[file]
        start, end = span
        if lines is None or start < 1 or end > len(lines) or start > end:
            return None
        return "\n".join(lines[start - 1 : end]) + "\n"
