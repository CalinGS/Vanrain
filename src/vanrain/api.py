"""The public Python API: what the CLI (and later the MCP server) calls.

Each function takes a repository root or an already built graph and returns
plain data. Nothing here prints; the CLI decides how results look.

    from vanrain import api

    ctx = api.get_context("path/to/repo", ["Order.total"], budget=2000)
    print(ctx.text)

``open_repo`` indexes a repository, keeping a cache in ``.vanrain/`` under the
root unless ``cache=False``. ``get_context`` resolves names to symbols, selects
under the budget and renders markdown. ``find_symbols``, ``links`` and
``repo_stats`` answer the lookups the ``find`` and ``stats`` commands need.
"""

from __future__ import annotations

import os
import time
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

from vanrain.graph import DEFAULT_CACHE, CodeGraph, IndexRun, index
from vanrain.model import EdgeKind, NodeKind, Selection, Symbol
from vanrain.render import render
from vanrain.seeds import SeedError, find_seeds, resolve_seeds
from vanrain.selector import BFSSelector, SelectorConfig, Strategy
from vanrain.text_seeds import seeds_from_text

__all__ = [
    "DEFAULT_BUDGET",
    "DEFAULT_STRATEGY",
    "STRATEGIES",
    "Context",
    "EdgeKind",
    "NodeKind",
    "Link",
    "RepoStats",
    "SeedError",
    "TimedRun",
    "find_symbols",
    "get_context",
    "links",
    "open_repo",
    "repo_stats",
    "seeds_from_text",
]

DEFAULT_BUDGET = 2000
DEFAULT_STRATEGY = Strategy.SIGNATURES_FIRST
#: Strategy names accepted by ``get_context`` (and the CLI's ``--strategy``).
STRATEGIES = tuple(s.value for s in Strategy)


@dataclass
class TimedRun:
    """``IndexRun`` plus how long indexing took and where the cache is."""

    run: IndexRun
    seconds: float
    cache: Path | None

    @property
    def graph(self) -> CodeGraph:
        return self.run.graph

    @property
    def parsed(self) -> list[str]:
        return self.run.parsed

    @property
    def reused(self) -> list[str]:
        return self.run.reused

    @property
    def removed(self) -> list[str]:
        return self.run.removed


def open_repo(root: str | os.PathLike, cache: bool = True) -> TimedRun:
    """Index the repository at ``root``. With ``cache`` the graph is kept in
    ``<root>/.vanrain/cache.json`` and only changed files are parsed again."""
    root = _check_root(root)
    t0 = time.perf_counter()
    run = index(root, cache=DEFAULT_CACHE if cache else None)
    return TimedRun(run, time.perf_counter() - t0, root / DEFAULT_CACHE if cache else None)


@dataclass
class Context:
    """What ``get_context`` returns: the markdown and the selection behind it."""

    text: str
    seeds: tuple[str, ...]
    selection: Selection


def get_context(
    root: str | os.PathLike,
    names: str | Iterable[str],
    budget: int = DEFAULT_BUDGET,
    strategy: str | Strategy = DEFAULT_STRATEGY,
    cache: bool = True,
    graph: CodeGraph | None = None,
) -> Context:
    """Context for the symbols ``names`` within ``budget`` tokens.

    A name is a symbol id or its trailing dotted parts (``Order.total``).
    Raises ``SeedError`` for a name that matches nothing or several symbols,
    ``ValueError`` for no names, a budget below 1 or an unknown strategy.
    Pass ``graph`` to reuse one already built from ``root``.
    """
    names = [names] if isinstance(names, str) else list(names)
    if not names:
        raise ValueError("need at least one symbol name")
    if budget < 1:
        raise ValueError(f"budget must be at least 1 token, not {budget}")
    config = SelectorConfig(strategy=Strategy(strategy))
    root = _check_root(root)
    if graph is None:
        graph = open_repo(root, cache=cache).graph
    seeds = resolve_seeds(graph, names)
    selection = BFSSelector(config).select(graph, list(seeds), budget)
    return Context(render(selection, graph, root), seeds, selection)


def find_symbols(graph: CodeGraph, name: str) -> list[Symbol]:
    """Symbols ``name`` could mean (see ``vanrain.seeds.find_seeds``), sorted by id."""
    return [graph.symbol(sid) for sid in find_seeds(graph, name)]


@dataclass(frozen=True)
class Link:
    """One edge seen from a symbol: ``out`` when the symbol is the source."""

    direction: str  # "out" or "in"
    kind: EdgeKind
    other: str
    confidence: float


def links(graph: CodeGraph, sid: str, min_confidence: float = 0.0) -> list[Link]:
    """The non-CONTAINS edges at ``sid``, outgoing first, in graph order."""
    out, inc = [], []
    for e in graph.neighbours(sid, direction="both", min_confidence=min_confidence):
        if e.kind is EdgeKind.CONTAINS:
            continue
        if e.src == sid:
            out.append(Link("out", e.kind, e.dst, e.confidence))
        else:
            inc.append(Link("in", e.kind, e.src, e.confidence))
    return out + inc


@dataclass
class RepoStats:
    """Size and shape of an indexed repository."""

    files: int
    symbols: int
    edges: int
    symbols_by_kind: dict[NodeKind, int]
    edges_by_kind: dict[EdgeKind, int]
    heuristic_edges: int  # non-CONTAINS edges with confidence < 1
    most_called: list[tuple[str, int]]  # (symbol id, callers), most first
    parsed: int = 0
    reused: int = 0
    seconds: float = 0.0
    cache: Path | None = None
    largest: list[tuple[str, int]] = field(default_factory=list)  # (id, tokens_full)


def repo_stats(run: TimedRun | IndexRun, top: int = 10) -> RepoStats:
    """Counts for ``run``'s graph, with the ``top`` most-called and largest symbols."""
    timed = run if isinstance(run, TimedRun) else None
    base = run.run if timed else run
    graph = base.graph
    edges = graph.edges()
    called = Counter(e.dst for e in edges if e.kind is EdgeKind.CALLS)
    sized = sorted(
        ((s.id, s.tokens_full) for s in graph.symbols.values() if s.kind is not NodeKind.MODULE),
        key=lambda p: (-p[1], p[0]),
    )
    return RepoStats(
        files=len(base.parsed) + len(base.reused),
        symbols=len(graph),
        edges=len(edges),
        symbols_by_kind=dict(Counter(s.kind for s in graph.symbols.values())),
        edges_by_kind=dict(Counter(e.kind for e in edges)),
        heuristic_edges=sum(
            1 for e in edges if e.kind is not EdgeKind.CONTAINS and e.confidence < 1.0
        ),
        most_called=sorted(called.items(), key=lambda p: (-p[1], p[0]))[:top],
        parsed=len(base.parsed),
        reused=len(base.reused),
        seconds=timed.seconds if timed else 0.0,
        cache=timed.cache if timed else None,
        largest=sized[:top],
    )


def _check_root(root: str | os.PathLike) -> Path:
    path = Path(root)
    if not path.is_dir():
        raise NotADirectoryError(f"{path} is not a directory")
    return path
