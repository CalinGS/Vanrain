"""Shared data types: the contract between every Vanrain module.

This module holds types only, no logic. Parsers produce ``ParseResult``s, the
resolver turns their ``Reference``s into ``Edge``s, the graph stores ``Symbol``s
and ``Edge``s, and selectors return a ``Selection``. Everything downstream of the
parsers is language-neutral.

Conventions (frozen for v0.1)
-----------------------------
Symbol ids
    Fully qualified dotted names: ``pkg.mod``, ``pkg.mod.Class``,
    ``pkg.mod.Class.method``, ``pkg.mod.func``.

    * A package's ``__init__.py`` is the module ``pkg`` itself.
    * Nested functions and classes extend their parent's id:
      ``pkg.mod.outer.inner``.
    * A name defined twice in the same scope (``if/else`` definitions, a
      property getter and setter) keeps the plain id for the first definition;
      later ones get ``#2``, ``#3``... in source order: ``pkg.mod.f#2``.
    * Re-exports create no symbol. ``from .models import Order`` in
      ``pkg/__init__.py`` is an ``IMPORTS`` edge from ``pkg`` to
      ``pkg.models.Order``, and anything importing ``pkg.Order`` resolves to
      ``pkg.models.Order``.

Files and spans
    ``Symbol.file`` is a POSIX path relative to the repository root.
    ``Symbol.span`` is ``(start, end)``, 1-based and inclusive. A definition's
    span starts at its first decorator, if any. A module spans its whole file.

Edges
    Edges only join symbols that exist in the graph. References to the standard
    library, third-party code, builtins and module-level variables are dropped
    in v0.1. There is at most one edge per ``(src, dst, kind)``.
    See ``EdgeKind`` for what each kind means and which end is ``src``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class NodeKind(str, Enum):
    """What a symbol is. String values keep the cache format readable."""

    MODULE = "module"
    CLASS = "class"
    FUNCTION = "function"  # module-level or nested function
    METHOD = "method"  # function defined directly in a class body


class EdgeKind(str, Enum):
    """How two symbols are connected. ``src`` is always the symbol that acts.

    CALLS
        ``src`` calls ``dst``. Calling a class (``Order()``) is a call to the
        class. ``super().m()`` is a call to the parent's ``m``.
    IMPORTS
        Module ``src`` imports ``dst`` (a module or a symbol). The source is
        the module even when the import sits inside a function.
    INHERITS
        Class ``src`` has ``dst`` as a direct base class.
    REFERENCES
        ``src`` uses ``dst`` without calling it: type annotations,
        ``isinstance`` checks, passing a function as a value. A name in call
        position is ``CALLS`` only, never also ``REFERENCES``.
    CONTAINS
        ``dst`` is defined directly inside ``src`` (module -> class or
        function, class -> method, function -> nested function). Packages do
        not contain their submodules.
    """

    CALLS = "calls"
    IMPORTS = "imports"
    INHERITS = "inherits"
    REFERENCES = "references"
    CONTAINS = "contains"
    # Later: TESTED_BY


class Detail(str, Enum):
    """How much of a symbol a selection includes."""

    FULL = "full"  # the whole source span
    SIGNATURE = "signature"  # Symbol.signature only


@dataclass(frozen=True)
class Symbol:
    """A node in the code graph."""

    id: str
    kind: NodeKind
    file: str
    span: tuple[int, int]
    # The full definition header up to its colon (which may span several
    # lines), plus the first line of the docstring if there is one.
    signature: str
    tokens_full: int
    tokens_sig: int


@dataclass(frozen=True)
class Edge:
    """A typed, directed connection between two symbols."""

    src: str  # Symbol.id
    dst: str  # Symbol.id
    kind: EdgeKind
    # 1.0 when the resolution is certain; below 1.0 for heuristic ones such
    # as instance method calls whose receiver type was inferred.
    confidence: float = 1.0


@dataclass(frozen=True)
class Reference:
    """An unresolved use of a name, as a parser sees it.

    Parsers emit these; the resolver turns them into ``Edge``s.
    """

    src: str  # id of the enclosing symbol
    name: str  # dotted text as written, e.g. "util.round_money" or "self.add"
    kind: EdgeKind
    line: int
    # True when the parser replaced the receiver with its guessed type:
    # ``order.add()`` after ``order = Order()`` becomes ``"Order.add"``. The
    # resolver only accepts such a name if its prefix is a class, and gives the
    # edge a confidence below 1.0.
    inferred: bool = False


@dataclass(frozen=True)
class Binding:
    """A name an import statement binds in a scope.

    ``from .models import Order`` in ``pkg/__init__.py`` is
    ``Binding("pkg", "Order", "pkg.models.Order")``; ``import a.b`` binds
    ``a`` to ``"a"``; ``from m import *`` binds ``"*"`` to ``"m"``. The
    target is an absolute dotted name that may not be a symbol yet (it can
    be a re-export); the resolver follows it.
    """

    scope: str  # id of the symbol whose body holds the import
    name: str  # local name
    target: str  # absolute dotted name it refers to


@dataclass(frozen=True)
class ParseResult:
    """Everything a parser extracts from one file."""

    file: str  # POSIX path relative to the repository root
    module: str  # module id, e.g. "pkg.mod"
    symbols: tuple[Symbol, ...] = ()
    references: tuple[Reference, ...] = ()
    # Edges known without resolving anything else (CONTAINS).
    edges: tuple[Edge, ...] = ()
    bindings: tuple[Binding, ...] = ()


@dataclass(frozen=True)
class SelectionItem:
    """One symbol picked for the context, and how much of it to show."""

    symbol: str  # Symbol.id
    detail: Detail
    distance: int  # hops from the nearest seed; seeds are 0


@dataclass
class Selection:
    """What a selector chose for one request."""

    seeds: tuple[str, ...]  # Symbol ids the traversal started from
    budget: int  # token budget the selector was given
    items: list[SelectionItem] = field(default_factory=list)
    tokens_used: int = 0
