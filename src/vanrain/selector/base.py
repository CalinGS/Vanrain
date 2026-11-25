"""Selector interface: graph + seeds + budget -> Selection.

A selector works in two steps:

1. ``rank`` orders the symbols reachable from the seeds, nearest first, each
   with its hop distance. This is the part strategies differ in (BFS now,
   Dijkstra with edge weights or personalised PageRank later).
2. ``fill`` walks that ranking and decides, under the token budget, which
   symbols to show and at which detail: ``Detail.FULL`` (whole source),
   ``Detail.SIGNATURE``, or nothing. All selectors share it.

Everything a later milestone may tune lives in ``SelectorConfig``: the fill
strategy, a weight per (edge kind, direction), a confidence floor, a distance
limit and which kinds of symbol may be shown in full.

Token accounting
----------------
A symbol costs ``Symbol.tokens_full`` at ``FULL`` and ``Symbol.tokens_sig`` at
``SIGNATURE``, plus the comment line the renderer puts above it
(``item_header``, counted with ``tokens.count_tokens``). ``Selection.tokens_used``
is the sum over the items and never exceeds the budget. The title line and
the per-file headings and fences are not counted (about 40 tokens plus 10 per
file).

A ``FULL`` item already shows everything it contains (a class shows its
methods), so a selection never holds an item together with one of its
ancestors at ``FULL``: upgrading a symbol to ``FULL`` drops its selected
descendants and refunds their tokens.
"""

from __future__ import annotations

import math
from abc import ABC, abstractmethod
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType

from vanrain.graph import CodeGraph
from vanrain.model import Detail, Edge, EdgeKind, NodeKind, Selection, SelectionItem, Symbol
from vanrain.tokens import count_tokens

DIRECTIONS = ("out", "in")
#: Weight of any (edge kind, direction) not named in ``SelectorConfig.edge_weights``.
DEFAULT_WEIGHT = 1.0
#: Kinds that may be shown in full. A module in full is its whole file, which
#: is what Vanrain is meant to avoid, so modules are shown in full only when
#: they are seeds.
DEFAULT_UPGRADE_KINDS = frozenset({NodeKind.CLASS, NodeKind.FUNCTION, NodeKind.METHOD})


class Strategy(str, Enum):
    """How ``fill`` spends the budget along the ranking.

    SIGNATURES_FIRST (default)
        Give every ranked symbol its signature while it fits, then upgrade
        symbols to full source with what is left, nearest first. Breadth before
        depth: in the detail test (research/detail-test-results.md) it showed
        as much of the needed code as signatures only, and never less.
    FULL_FIRST
        Walk the ranking once and give each symbol full source if it fits,
        else its signature if that fits, else nothing (the starter script's
        "greedy fill with detail downgrade").
    SIGNATURES_ONLY
        Never show full source (except seeds, see ``SelectorConfig.seeds_full``).

    With ``seeds_full`` (the default) every strategy first shows the seeds in
    full, as the detail test did with its target.
    """

    SIGNATURES_FIRST = "signatures_first"
    FULL_FIRST = "full_first"
    SIGNATURES_ONLY = "signatures_only"


@dataclass(frozen=True)
class SelectorConfig:
    """Everything a selector may be tuned on. Immutable; compare with ``==``.

    ``edge_weights`` maps ``(EdgeKind, "out" | "in")`` to a cost of following
    that kind of edge in that direction ("out" goes from ``src`` to ``dst``).
    Missing pairs cost ``DEFAULT_WEIGHT``; ``math.inf`` means never follow.
    Plain BFS only uses the weights to decide what to follow; weighted
    selectors use them as distances.
    """

    strategy: Strategy = Strategy.SIGNATURES_FIRST
    edge_weights: Mapping[tuple[EdgeKind, str], float] = field(default_factory=dict)
    min_confidence: float = 0.0
    max_distance: int | None = None  # in hops; None for no limit
    upgrade_kinds: frozenset[NodeKind] = DEFAULT_UPGRADE_KINDS
    # Show the seeds in full before anything else, whatever the strategy (a
    # seed too big for the budget falls back to its signature). The seeds are
    # what the agent is working on, so their bodies are the most useful.
    seeds_full: bool = True

    def __post_init__(self) -> None:
        weights = {}
        for (kind, direction), w in self.edge_weights.items():
            if direction not in DIRECTIONS:
                raise ValueError(f"direction must be one of {DIRECTIONS}, not {direction!r}")
            if math.isnan(w) or w < 0:
                raise ValueError(f"edge weight must be >= 0, not {w!r}")
            weights[(EdgeKind(kind), direction)] = float(w)
        if self.max_distance is not None and self.max_distance < 0:
            raise ValueError("max_distance must be >= 0")
        object.__setattr__(self, "edge_weights", MappingProxyType(weights))
        object.__setattr__(self, "strategy", Strategy(self.strategy))
        object.__setattr__(self, "upgrade_kinds", frozenset(NodeKind(k) for k in self.upgrade_kinds))

    def weight(self, kind: EdgeKind, direction: str) -> float:
        return self.edge_weights.get((kind, direction), DEFAULT_WEIGHT)


@dataclass(frozen=True)
class Step:
    """One edge a traversal may follow from a symbol."""

    to: str  # the symbol at the other end
    edge: Edge
    direction: str  # "out" when following src -> dst, "in" when dst -> src
    weight: float


def steps(graph: CodeGraph, sid: str, config: SelectorConfig) -> Iterator[Step]:
    """Edges out of ``sid`` in both directions that ``config`` lets a traversal
    follow, in ``CodeGraph.neighbours`` order (deterministic)."""
    for e in graph.neighbours(sid, direction="both", min_confidence=config.min_confidence):
        direction, to = ("out", e.dst) if e.src == sid else ("in", e.src)
        w = config.weight(e.kind, direction)
        if not math.isinf(w):
            yield Step(to, e, direction, w)


def ancestors(graph: CodeGraph, sid: str) -> list[str]:
    """The symbols that contain ``sid``, innermost first."""
    out: list[str] = []
    seen = {sid}
    while True:
        parents = graph.neighbours(sid, [EdgeKind.CONTAINS], "in")
        if not parents or parents[0].src in seen:
            return out
        sid = parents[0].src
        seen.add(sid)
        out.append(sid)


def item_header(sym: Symbol) -> str:
    """The comment line the renderer puts above a symbol."""
    return f"# {sym.id} L{sym.span[0]}-{sym.span[1]}"


def symbol_cost(graph: CodeGraph, sid: str, detail: Detail) -> int:
    """Tokens showing ``sid`` at ``detail`` costs, header line included."""
    sym = graph.symbol(sid)
    body = sym.tokens_full if detail is Detail.FULL else sym.tokens_sig
    return body + count_tokens(item_header(sym))


def item_cost(graph: CodeGraph, item: SelectionItem) -> int:
    """Tokens an item costs at its detail level, header line included."""
    return symbol_cost(graph, item.symbol, item.detail)


class Selector(ABC):
    """Picks what to show for a request. Subclasses implement ``rank``."""

    name = "selector"

    def __init__(self, config: SelectorConfig | None = None):
        self.config = SelectorConfig() if config is None else config

    @abstractmethod
    def rank(self, graph: CodeGraph, seeds: Sequence[str]) -> list[tuple[str, int]]:
        """Reachable symbols as ``(id, hops from the nearest seed)``, best
        first. Seeds come first, in the given order, at distance 0. Each id
        appears once. The order must not depend on anything but the graph's
        contents, the seeds and the config."""

    def select(self, graph: CodeGraph, seeds: Sequence[str], budget: int) -> Selection:
        """Rank from ``seeds`` and fill ``budget`` tokens."""
        seeds = tuple(dict.fromkeys(seeds))
        if not seeds:
            raise ValueError("need at least one seed")
        for sid in seeds:
            if sid not in graph:
                raise KeyError(sid)
        if budget < 0:
            raise ValueError("budget must be >= 0")
        return fill(graph, seeds, self.rank(graph, seeds), budget, self.config)

    def __repr__(self) -> str:
        return f"{type(self).__name__}({self.config!r})"


def fill(
    graph: CodeGraph,
    seeds: Sequence[str],
    ranked: Sequence[tuple[str, int]],
    budget: int,
    config: SelectorConfig,
) -> Selection:
    """Choose a detail level per ranked symbol under ``budget`` (see ``Strategy``)."""
    distance = dict(ranked)
    seed_set = set(seeds)
    chosen: dict[str, Detail] = {}  # insertion order is rank order
    left = budget
    parents: dict[str, list[str]] = {}

    def ancestors_of(sid: str) -> list[str]:
        if sid not in parents:
            parents[sid] = ancestors(graph, sid)
        return parents[sid]

    def cost(sid: str, detail: Detail) -> int:
        return symbol_cost(graph, sid, detail)

    def upgradable(sid: str) -> bool:
        return sid in seed_set or graph.symbol(sid).kind in config.upgrade_kinds

    def covered(sid: str) -> bool:
        return any(chosen.get(a) is Detail.FULL for a in ancestors_of(sid))

    def try_full(sid: str) -> bool:
        """Show ``sid`` in full if it fits, absorbing its selected descendants."""
        nonlocal left
        kids = [k for k in chosen if k != sid and sid in ancestors_of(k)]
        extra = cost(sid, Detail.FULL) - sum(cost(k, chosen[k]) for k in kids)
        if sid in chosen:
            extra -= cost(sid, chosen[sid])
        if extra > left:
            return False
        for k in kids:
            del chosen[k]
        chosen[sid] = Detail.FULL
        left -= extra
        return True

    def try_signature(sid: str) -> bool:
        nonlocal left
        c = cost(sid, Detail.SIGNATURE)
        if c > left:
            return False
        chosen[sid] = Detail.SIGNATURE
        left -= c
        return True

    if config.seeds_full:
        for sid in seeds:
            if covered(sid):  # a seed inside another seed
                continue
            if not try_full(sid):
                try_signature(sid)

    if config.strategy is Strategy.FULL_FIRST:
        for sid, _ in ranked:
            if sid in chosen or covered(sid):
                continue
            if not (upgradable(sid) and try_full(sid)):
                try_signature(sid)
    else:
        for sid, _ in ranked:
            if sid not in chosen and not covered(sid):
                try_signature(sid)
        if config.strategy is Strategy.SIGNATURES_FIRST:
            for sid in list(chosen):
                if sid in chosen and upgradable(sid) and not covered(sid):
                    try_full(sid)

    items = [SelectionItem(sid, detail, distance[sid]) for sid, detail in chosen.items()]
    return Selection(seeds=tuple(seeds), budget=budget, items=items, tokens_used=budget - left)
