"""Map what the user names to start nodes for a selector.

For now a seed is a symbol name. ``find_seeds`` tries, in order:

1. the exact symbol id (``shop.models.Order.total``);
2. ids that end with the name as whole dotted parts (``Order.total`` or
   ``total``), so ``rder`` never matches ``Order``.

``resolve_seed`` accepts the result only when it is a single symbol and raises
``SeedError`` (with the candidates) otherwise. Open files, stack traces and
keywords as seeds come later.
"""

from __future__ import annotations

from collections.abc import Iterable

from vanrain.graph import CodeGraph


class SeedError(LookupError):
    """A name matched no symbol, or more than one."""

    def __init__(self, name: str, candidates: Iterable[str] = ()):
        self.name = name
        self.candidates = tuple(candidates)
        if not self.candidates:
            msg = f"no symbol matches {name!r}"
        else:
            shown = ", ".join(self.candidates[:10])
            more = f" and {len(self.candidates) - 10} more" if len(self.candidates) > 10 else ""
            msg = f"{name!r} is ambiguous: {shown}{more}"
        super().__init__(msg)


def find_seeds(graph: CodeGraph, name: str) -> list[str]:
    """Symbol ids that ``name`` could mean, sorted. Exact id first and alone."""
    name = name.strip()
    if not name:
        return []
    if name in graph:
        return [name]
    suffix = "." + name
    return sorted(sid for sid in graph.symbols if sid.endswith(suffix))


def resolve_seed(graph: CodeGraph, name: str) -> str:
    """The one symbol ``name`` means, or ``SeedError``."""
    found = find_seeds(graph, name)
    if len(found) != 1:
        raise SeedError(name, found)
    return found[0]


def resolve_seeds(graph: CodeGraph, names: Iterable[str]) -> tuple[str, ...]:
    """``resolve_seed`` for each name, in order, without repeats."""
    out: dict[str, None] = {}
    for name in names:
        out.setdefault(resolve_seed(graph, name))
    return tuple(out)
