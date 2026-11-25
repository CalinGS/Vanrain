"""CodeGraph: nodes, typed edges, neighbour queries, save/load cache.

Two layers live here:

* ``CodeGraph`` stores ``Symbol``s and ``Edge``s and answers neighbour
  queries. It knows nothing about languages, parsing or files on disk beyond
  ``Symbol.file``.
* ``index()`` builds a ``CodeGraph`` for a repository and keeps a cache next
  to it, so a later run only re-parses files whose content changed. Parsing is
  the slow step, so it is the one that is cached per file. Resolution is
  cross-file (renaming a function changes edges from files that did not
  change), so whenever any file changed the resolver runs again over every
  file's cached ``ParseResult``. When nothing changed it does not run at all.

Cache format
------------
One JSON file, ``.vanrain/cache.json`` under the repository root by default::

    {"format": 1, "fingerprint": "...",
     "files": {"pkg/mod.py": {"mtime_ns": .., "size": .., "sha1": "..",
                              "result": <ParseResult>}},
     "edges": [<Edge>, ...]}

``fingerprint`` hashes the code of the parsers, the resolver and the model,
so any change to how the graph is built throws the cache away. A file is
reused when its size and mtime match; if only the mtime moved, its SHA-1
decides. A cache that is missing, unreadable or from another version is
ignored and rewritten.
"""

from __future__ import annotations

import hashlib
import inspect
import json
import os
import sys
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path

from vanrain.model import Binding, Edge, EdgeKind, NodeKind, ParseResult, Reference, Symbol
from vanrain.parsers.base import Parser, iter_source_files

#: Bump when the layout of the cache file changes.
CACHE_FORMAT = 1
#: Where ``index`` keeps its cache, relative to the repository root.
DEFAULT_CACHE = Path(".vanrain") / "cache.json"

_DIRECTIONS = ("out", "in", "both")


class CodeGraph:
    """Symbols and typed, directed edges between them.

    There is at most one edge per ``(src, dst, kind)``; adding it again keeps
    the higher confidence. Both ends of an edge must already be symbols. All
    query results are sorted by edge kind, then by the symbol at the other end,
    so they are deterministic.
    """

    def __init__(self, symbols: Iterable[Symbol] = (), edges: Iterable[Edge] = ()):
        self._symbols: dict[str, Symbol] = {}
        self._out: dict[str, dict[tuple[str, EdgeKind], Edge]] = {}
        self._in: dict[str, dict[tuple[str, EdgeKind], Edge]] = {}
        self._edge_count = 0
        for s in symbols:
            self.add_symbol(s)
        for e in edges:
            self.add_edge(e)

    # -- building ------------------------------------------------------------

    def add_symbol(self, symbol: Symbol) -> None:
        """Add a symbol. The first symbol with a given id wins."""
        if symbol.id not in self._symbols:
            self._symbols[symbol.id] = symbol
            self._out[symbol.id] = {}
            self._in[symbol.id] = {}

    def add_edge(self, edge: Edge) -> None:
        """Add an edge between two known symbols (``KeyError`` otherwise)."""
        out = self._out[edge.src]
        inn = self._in[edge.dst]
        key = (edge.dst, edge.kind)
        old = out.get(key)
        if old is None:
            self._edge_count += 1
        elif old.confidence >= edge.confidence:
            return
        out[key] = edge
        inn[(edge.src, edge.kind)] = edge

    # -- nodes ---------------------------------------------------------------

    @property
    def symbols(self) -> Mapping[str, Symbol]:
        """All symbols by id (read-only view)."""
        return _ReadOnly(self._symbols)

    def symbol(self, sid: str) -> Symbol:
        return self._symbols[sid]

    def get(self, sid: str) -> Symbol | None:
        return self._symbols.get(sid)

    def symbols_in_file(self, file: str) -> list[str]:
        """Ids of the symbols defined in ``file``, sorted."""
        return sorted(sid for sid, s in self._symbols.items() if s.file == file)

    def __contains__(self, sid: object) -> bool:
        return sid in self._symbols

    def __len__(self) -> int:
        return len(self._symbols)

    # -- edges ---------------------------------------------------------------

    @property
    def edge_count(self) -> int:
        return self._edge_count

    def edges(self) -> list[Edge]:
        """Every edge, sorted by ``(src, kind, dst)``."""
        return sorted(
            (e for out in self._out.values() for e in out.values()),
            key=lambda e: (e.src, e.kind.value, e.dst),
        )

    def neighbours(
        self,
        sid: str,
        kinds: Iterable[EdgeKind] | None = None,
        direction: str = "out",
        min_confidence: float = 0.0,
    ) -> list[Edge]:
        """Edges touching ``sid``.

        ``direction`` is ``"out"`` (``sid`` is ``src``), ``"in"`` (``sid`` is
        ``dst``) or ``"both"``. ``kinds`` limits the edge kinds (all when
        ``None``); ``min_confidence`` drops less certain edges. An unknown
        ``sid`` has no neighbours.
        """
        if direction not in _DIRECTIONS:
            raise ValueError(f"direction must be one of {_DIRECTIONS}, not {direction!r}")
        wanted = None if kinds is None else frozenset(kinds)
        found: list[tuple[tuple[str, str, int], Edge]] = []
        for table, other, rank in (
            (self._out, "dst", 0),
            (self._in, "src", 1),
        ):
            if direction != "both" and _DIRECTIONS[rank] != direction:
                continue
            for e in table.get(sid, {}).values():
                if wanted is not None and e.kind not in wanted:
                    continue
                if e.confidence < min_confidence:
                    continue
                found.append(((e.kind.value, getattr(e, other), rank), e))
        found.sort(key=lambda item: item[0])
        return [e for _, e in found]

    def callees(self, sid: str, min_confidence: float = 0.0) -> list[Edge]:
        """``CALLS`` edges out of ``sid``: what it calls."""
        return self.neighbours(sid, [EdgeKind.CALLS], "out", min_confidence)

    def callers(self, sid: str, min_confidence: float = 0.0) -> list[Edge]:
        """``CALLS`` edges into ``sid``: who calls it."""
        return self.neighbours(sid, [EdgeKind.CALLS], "in", min_confidence)

    # -- comparison and persistence ------------------------------------------

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, CodeGraph):
            return NotImplemented
        return self._symbols == other._symbols and self.edges() == other.edges()

    def __repr__(self) -> str:
        return f"CodeGraph({len(self)} symbols, {self.edge_count} edges)"

    def to_dict(self) -> dict:
        return {
            "symbols": [_symbol_row(s) for s in self._symbols.values()],
            "edges": [_edge_row(e) for e in self.edges()],
        }

    @classmethod
    def from_dict(cls, data: Mapping) -> CodeGraph:
        return cls(
            (_symbol(row) for row in data["symbols"]),
            (_edge(row) for row in data["edges"]),
        )

    def save(self, path: str | os.PathLike) -> None:
        """Write the graph to ``path`` as JSON, creating parent directories."""
        _write_json(Path(path), self.to_dict())

    @classmethod
    def load(cls, path: str | os.PathLike) -> CodeGraph:
        return cls.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))


class _ReadOnly(Mapping):
    __slots__ = ("_d",)

    def __init__(self, d: dict):
        self._d = d

    def __getitem__(self, key):
        return self._d[key]

    def __iter__(self):
        return iter(self._d)

    def __len__(self) -> int:
        return len(self._d)

    def __eq__(self, other: object) -> bool:
        return dict(self._d) == (dict(other) if isinstance(other, Mapping) else other)


# --- indexing a repository ---------------------------------------------------


@dataclass
class IndexRun:
    """A built graph, and what ``index`` had to redo to build it."""

    graph: CodeGraph
    parsed: list[str] = field(default_factory=list)  # files parsed this run
    reused: list[str] = field(default_factory=list)  # files taken from the cache
    removed: list[str] = field(default_factory=list)  # cached files now gone
    resolved: bool = False  # whether the resolver ran


def index(
    root: str | os.PathLike,
    cache: str | os.PathLike | None = DEFAULT_CACHE,
    parsers: Iterable[Parser] | None = None,
) -> IndexRun:
    """Build the graph of the repository at ``root``, reusing ``cache``.

    ``cache`` is a path relative to ``root`` (or absolute); ``None`` disables
    caching. Only files whose content changed since the cached run are parsed
    again; the resolver runs only if some file was added, changed or removed.
    """
    from vanrain.resolver import resolve

    root = Path(root)
    parsers = _default_parsers() if parsers is None else list(parsers)
    by_ext: dict[str, Parser] = {}
    for p in parsers:
        for ext in p.extensions:
            by_ext.setdefault(ext, p)
    cache_path = None if cache is None else root / cache
    fingerprint = _fingerprint(parsers)
    old = _read_cache(cache_path, fingerprint) if cache_path else None
    old_files: dict = old["files"] if old else {}

    run = IndexRun(CodeGraph())
    files: dict[str, dict] = {}
    for rel in iter_source_files(root, by_ext):
        path = root / rel
        st = path.stat()
        entry = old_files.get(rel)
        if entry and entry["size"] == st.st_size and entry["mtime_ns"] == st.st_mtime_ns:
            files[rel] = entry
            run.reused.append(rel)
            continue
        digest = hashlib.sha1(path.read_bytes()).hexdigest()
        if entry and entry["sha1"] == digest:
            files[rel] = {**entry, "size": st.st_size, "mtime_ns": st.st_mtime_ns}
            run.reused.append(rel)
            continue
        result = by_ext[path.suffix].parse_file(root, rel)
        files[rel] = {
            "mtime_ns": st.st_mtime_ns,
            "size": st.st_size,
            "sha1": digest,
            "result": _result_row(result),
        }
        run.parsed.append(rel)
    run.removed = sorted(set(old_files) - set(files))

    if old and not run.parsed and not run.removed:
        edge_rows = old["edges"]
    else:
        results = [_result(files[rel]["result"], rel) for rel in sorted(files)]
        edge_rows = [_edge_row(e) for e in resolve(results)]
        run.resolved = True

    run.graph = CodeGraph(
        (_symbol(row) for rel in sorted(files) for row in files[rel]["result"]["symbols"]),
        (_edge(row) for row in edge_rows),
    )
    if cache_path and (run.resolved or files != old_files):
        _write_json(
            cache_path,
            {"format": CACHE_FORMAT, "fingerprint": fingerprint, "files": files, "edges": edge_rows},
        )
    return run


def _default_parsers() -> list[Parser]:
    from vanrain.parsers.python_ast import PythonParser

    return [PythonParser()]


def _fingerprint(parsers: Iterable[Parser]) -> str:
    """Hash of everything that decides what the cached data looks like."""
    import vanrain.model
    import vanrain.resolver

    h = hashlib.sha1(f"{CACHE_FORMAT}".encode())
    modules = [vanrain.model, vanrain.resolver, sys.modules[__name__]]
    modules += [sys.modules[type(p).__module__] for p in parsers]
    for m in modules:
        h.update(m.__name__.encode())
        try:
            h.update(inspect.getsource(m).encode())
        except (OSError, TypeError):
            h.update(b"?")
    return h.hexdigest()


def _read_cache(path: Path, fingerprint: str) -> dict | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if (
        not isinstance(data, dict)
        or data.get("format") != CACHE_FORMAT
        or data.get("fingerprint") != fingerprint
    ):
        return None
    return data


def _write_json(path: Path, data: object) -> None:
    """Write atomically, so a crash never leaves half a file behind."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, separators=(",", ":")), encoding="utf-8")
    os.replace(tmp, path)


# --- compact rows for the model types ----------------------------------------
# Lists instead of dicts keep the cache small and quick to load. Enum lookups
# go through plain dicts, since calling an Enum is slow on large graphs.

_NODE_KINDS = {k.value: k for k in NodeKind}
_EDGE_KINDS = {k.value: k for k in EdgeKind}


def _symbol_row(s: Symbol) -> list:
    return [s.id, s.kind.value, s.file, s.span[0], s.span[1], s.signature, s.tokens_full, s.tokens_sig]


def _symbol(row: list) -> Symbol:
    sid, kind, file, start, end, sig, full, short = row
    return Symbol(sid, _NODE_KINDS[kind], file, (start, end), sig, full, short)


def _edge_row(e: Edge) -> list:
    return [e.src, e.dst, e.kind.value, e.confidence]


def _edge(row: list) -> Edge:
    return Edge(row[0], row[1], _EDGE_KINDS[row[2]], row[3])


def _result_row(r: ParseResult) -> dict:
    return {
        "module": r.module,
        "symbols": [_symbol_row(s) for s in r.symbols],
        "references": [[x.src, x.name, x.kind.value, x.line, int(x.inferred)] for x in r.references],
        "edges": [_edge_row(e) for e in r.edges],
        "bindings": [[b.scope, b.name, b.target] for b in r.bindings],
    }


def _result(row: dict, file: str) -> ParseResult:
    return ParseResult(
        file,
        row["module"],
        tuple(_symbol(s) for s in row["symbols"]),
        tuple(Reference(s, n, _EDGE_KINDS[k], line, bool(i)) for s, n, k, line, i in row["references"]),
        tuple(_edge(e) for e in row["edges"]),
        tuple(Binding(*b) for b in row["bindings"]),
    )
