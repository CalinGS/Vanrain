"""Breadth-first ranking: nearest symbols first, edges in both directions."""

from __future__ import annotations

from collections import deque
from collections.abc import Sequence

from vanrain.graph import CodeGraph
from vanrain.selector.base import Selector, steps


class BFSSelector(Selector):
    """Rank by hop count from the nearest seed.

    Follows every edge the config allows (any kind, both directions, at or
    above ``min_confidence``, weight not infinite) and ignores the weights'
    values: one hop is one hop. Ties keep discovery order, which follows
    ``CodeGraph.neighbours`` order, so the ranking is deterministic.
    """

    name = "bfs"

    def rank(self, graph: CodeGraph, seeds: Sequence[str]) -> list[tuple[str, int]]:
        limit = self.config.max_distance
        dist: dict[str, int] = {}
        for sid in seeds:
            dist.setdefault(sid, 0)
        queue = deque(dist)
        while queue:
            sid = queue.popleft()
            d = dist[sid]
            if limit is not None and d >= limit:
                continue
            for step in steps(graph, sid, self.config):
                if step.to not in dist:
                    dist[step.to] = d + 1
                    queue.append(step.to)
        return list(dist.items())
