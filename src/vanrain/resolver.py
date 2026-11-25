"""Turn unresolved references into typed edges.

Input: the ``ParseResult`` of every file. Output: a sorted list of ``Edge``s
between known symbols, at most one per ``(src, dst, kind)``.

How a reference name is resolved
--------------------------------
The first part of the name is looked up in the scopes around ``src``, inner to
outer, the way Python does it: the symbol's own scope, then enclosing
functions, then the module. A class's scope is only visible from the class
body itself, not from its methods. In each scope a name can be a symbol
defined there or a name bound by an import (followed through re-exports, with
a depth limit against cycles). Each further part is an attribute: a child
symbol, a class member found along the base classes, or a name a module binds.

Python's own two receivers are handled here, as the parser normalises them:

* ``super().m``: ``m`` on the base classes of the enclosing class (exact);
* ``self.m``: ``m`` on the enclosing class and its bases (``SELF_CONFIDENCE``,
  since a subclass may override it).

References the parser marked ``inferred`` (``order.add`` rewritten as
``Order.add``) must resolve through a class, and get ``INFERRED_CONFIDENCE``.

Anything that does not resolve to a symbol (builtins, the standard library,
third-party code, module-level variables, attributes set at runtime) is
dropped, as are self-loops. When the same edge is found with several confidences, the highest
one is kept.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable

from vanrain.model import Edge, EdgeKind, NodeKind, ParseResult, Reference, Symbol

#: Confidence for a call or reference through ``self``.
SELF_CONFIDENCE = 0.9
#: Confidence for a reference whose receiver type the parser guessed.
INFERRED_CONFIDENCE = 0.7

_MAX_DEPTH = 16


def _parent(sid: str) -> str:
    return sid.rpartition(".")[0]


class Resolver:
    """Symbol table for a set of parsed files, and the lookups over it."""

    def __init__(self, results: Iterable[ParseResult]):
        self.results = sorted(results, key=lambda r: r.file)
        self.symbols: dict[str, Symbol] = {}
        for r in self.results:
            for s in r.symbols:
                self.symbols.setdefault(s.id, s)
        self.bindings: dict[tuple[str, str], str] = {}
        self.stars: dict[str, list[str]] = defaultdict(list)
        for r in self.results:
            for b in r.bindings:
                if b.name == "*":
                    self.stars[b.scope].append(b.target)
                else:
                    self.bindings.setdefault((b.scope, b.name), b.target)
        self.bases: dict[str, list[str]] = {}

    # -- edges ---------------------------------------------------------------

    def edges(self) -> list[Edge]:
        best: dict[tuple[str, str, EdgeKind], float] = {}

        def add(src: str, dst: str, kind: EdgeKind, conf: float) -> None:
            if src not in self.symbols or dst not in self.symbols or src == dst:
                return
            key = (src, dst, kind)
            if conf > best.get(key, 0.0):
                best[key] = conf

        for r in self.results:
            for e in r.edges:
                add(e.src, e.dst, e.kind, e.confidence)

        refs = [ref for r in self.results for ref in r.references]
        # Base classes first: attribute lookups below walk them.
        for ref in refs:
            if ref.kind is EdgeKind.INHERITS:
                found = self.resolve(ref)
                if found and self.symbols[found[0]].kind is NodeKind.CLASS:
                    dst, conf = found
                    bases = self.bases.setdefault(ref.src, [])
                    if dst not in bases and dst != ref.src:
                        bases.append(dst)
                    add(ref.src, dst, ref.kind, conf)
        for ref in refs:
            if ref.kind is not EdgeKind.INHERITS:
                found = self.resolve(ref)
                if found:
                    add(ref.src, found[0], ref.kind, found[1])

        return [
            Edge(src, dst, kind, conf)
            for (src, dst, kind), conf in sorted(
                best.items(), key=lambda item: (item[0][0], item[0][2].value, item[0][1])
            )
        ]

    # -- references ----------------------------------------------------------

    def resolve(self, ref: Reference) -> tuple[str, float] | None:
        """The symbol ``ref`` points to, and how sure we are."""
        if ref.src not in self.symbols:
            return None
        if ref.kind is EdgeKind.IMPORTS:
            dst = self.absolute(ref.name)
            return (dst, 1.0) if dst else None

        head, *rest = ref.name.split(".")
        conf = 1.0
        if head == "super()":
            cls = self.enclosing_class(ref.src)
            if cls is None or not rest:
                return None
            cur = self.member(cls, rest[0], skip_own=True)
            rest = rest[1:]
        elif head == "self":
            cls = self.enclosing_class(ref.src)
            if cls is None or not rest:
                return None
            cur = cls
            conf = SELF_CONFIDENCE
        else:
            start = _parent(ref.src) if ref.kind is EdgeKind.INHERITS else ref.src
            cur = self.lookup(start, head)

        if ref.inferred:
            if not rest:
                return None
            conf = min(conf, INFERRED_CONFIDENCE)
        for i, attr in enumerate(rest):
            if cur is None:
                return None
            if ref.inferred and i == len(rest) - 1:
                if self.symbols[cur].kind is not NodeKind.CLASS:
                    return None
            cur = self.attr(cur, attr)
        return (cur, conf) if cur else None

    def lookup(self, scope: str, name: str) -> str | None:
        """Resolve a bare name used in ``scope``, walking outwards."""
        first = True
        while scope in self.symbols:
            kind = self.symbols[scope].kind
            if first or kind is not NodeKind.CLASS:
                found = self.in_scope(scope, name)
                if found:
                    return found
            if kind is NodeKind.MODULE:
                return None
            first = False
            scope = _parent(scope)
        return None

    def in_scope(self, scope: str, name: str, depth: int = 0) -> str | None:
        """A name defined in or imported into ``scope`` itself."""
        if depth > _MAX_DEPTH:
            return None
        sid = f"{scope}.{name}"
        if sid in self.symbols:
            return sid
        target = self.bindings.get((scope, name))
        if target is not None:
            return self.absolute(target, depth + 1)
        for star in self.stars.get(scope, ()):
            module = self.absolute(star, depth + 1)
            if module and self.symbols[module].kind is NodeKind.MODULE:
                found = self.in_scope(module, name, depth + 1)
                if found:
                    return found
        return None

    def attr(self, target: str, name: str, depth: int = 0) -> str | None:
        """``target.name``: a child, an inherited member, or a module binding."""
        kind = self.symbols[target].kind
        if kind is NodeKind.CLASS:
            return self.member(target, name)
        if kind is NodeKind.MODULE:
            return self.in_scope(target, name, depth)
        sid = f"{target}.{name}"
        return sid if sid in self.symbols else None

    def absolute(self, name: str, depth: int = 0) -> str | None:
        """Resolve an absolute dotted name, following re-exports."""
        if depth > _MAX_DEPTH:
            return None
        parts = name.split(".")
        for i in range(len(parts), 0, -1):
            cur: str | None = ".".join(parts[:i])
            if cur in self.symbols:
                for attr in parts[i:]:
                    cur = self.attr(cur, attr, depth + 1)
                    if cur is None:
                        return None
                return cur
        return None

    # -- classes -------------------------------------------------------------

    def enclosing_class(self, sid: str) -> str | None:
        while sid in self.symbols:
            kind = self.symbols[sid].kind
            if kind is NodeKind.CLASS:
                return sid
            if kind is NodeKind.MODULE:
                return None
            sid = _parent(sid)
        return None

    def mro(self, cls: str) -> list[str]:
        """The class and its bases, depth first, each once (not full C3)."""
        out: list[str] = []
        seen: set[str] = set()
        stack = [cls]
        while stack:
            c = stack.pop()
            if c in seen:
                continue
            seen.add(c)
            out.append(c)
            stack.extend(reversed(self.bases.get(c, ())))
        return out

    def member(self, cls: str, name: str, skip_own: bool = False) -> str | None:
        for c in self.mro(cls)[1 if skip_own else 0 :]:
            sid = f"{c}.{name}"
            if sid in self.symbols:
                return sid
        return None


def resolve(results: Iterable[ParseResult]) -> list[Edge]:
    """All edges for a set of parsed files: CONTAINS plus resolved references."""
    return Resolver(results).edges()
