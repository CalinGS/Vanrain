"""Python parser built on the standard ast module.

What it reports for one file:

* a ``Symbol`` for the module and for every class and function, at any depth;
* a ``CONTAINS`` edge from each definition's parent;
* a ``Binding`` for every name an import binds, with relative imports already
  made absolute;
* a ``Reference`` for every other use of a name: calls, bases, annotations,
  decorators, names used as values.

References keep the dotted text as written (``util.round_money``) with two
normalisations the resolver relies on:

* the first parameter of a method (``self``, ``cls``, ``me``...) is written
  ``self``, and ``super().m`` is written ``super().m``;
* when the receiver is a local variable whose type the parser can guess (an
  annotation, ``x = Cls()``, iterating over a ``list[Cls]``, a ``self.attr``
  annotated or assigned in the class), the receiver is replaced by that type
  and the reference is marked ``inferred``: ``order.add`` becomes
  ``Order.add``.

Uses of other local variables are dropped here, since they can never become
edges between symbols.
"""

from __future__ import annotations

import ast
import io
import tokenize
from collections.abc import Iterable
from dataclasses import dataclass, field

from vanrain.model import (
    Binding,
    Edge,
    EdgeKind,
    NodeKind,
    ParseResult,
    Reference,
    Symbol,
)
from vanrain.parsers.base import Parser
from vanrain.tokens import estimate_tokens

_FUNCS = (ast.FunctionDef, ast.AsyncFunctionDef)
_DEFS = (*_FUNCS, ast.ClassDef)
_COMPS = (ast.ListComp, ast.SetComp, ast.GeneratorExp, ast.DictComp)

# Generic types whose first argument is what iterating over them yields.
_CONTAINERS = frozenset(
    {
        "list", "List", "set", "Set", "frozenset", "FrozenSet", "tuple", "Tuple",
        "dict", "Dict", "Mapping", "MutableMapping", "defaultdict", "OrderedDict",
        "Sequence", "MutableSequence", "Iterable", "Iterator", "Collection",
        "Generator", "AsyncIterable", "AsyncIterator", "deque", "Deque",
    }
)
# Wrappers whose first argument is the real type.
_WRAPPERS = frozenset(
    {"Optional", "Final", "ClassVar", "Annotated", "Required", "NotRequired", "ReadOnly"}
)


@dataclass(frozen=True)
class _Type:
    """A guessed type: a dotted name as written, and what iterating yields."""

    name: str | None = None
    elem: _Type | None = None
    is_self: bool = False


_SELF = _Type(is_self=True)


@dataclass
class _Scope:
    id: str
    kind: NodeKind
    locals: set[str] = field(default_factory=set)  # names that are local variables
    env: dict[str, _Type] = field(default_factory=dict)  # guessed types of names
    attrs: dict[str, _Type] = field(default_factory=dict)  # types of self.<attr>

    @property
    def is_function(self) -> bool:
        return self.kind in (NodeKind.FUNCTION, NodeKind.METHOD)

    def nested(self, names: Iterable[str] = ()) -> _Scope:
        """Same symbol, extra local names: lambdas and comprehensions."""
        names = set(names)
        env = {k: v for k, v in self.env.items() if k not in names}
        return _Scope(self.id, self.kind, self.locals | names, env, self.attrs)


def _dotted(node: ast.AST) -> list[str] | None:
    """``a.b.c`` -> ``["a", "b", "c"]``; None if not a pure name chain."""
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
        return parts[::-1]
    return None


def _is_super_call(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "super"
    )


def _parse_string_annotation(node: ast.Constant) -> ast.expr | None:
    try:
        parsed = ast.parse(node.value.strip(), mode="eval").body
    except SyntaxError:
        return None
    for sub in ast.walk(parsed):
        if hasattr(sub, "lineno"):
            sub.lineno = node.lineno
    return parsed


def _annotation_type(node: ast.AST | None) -> _Type | None:
    """Best-effort type of an annotation expression."""
    if node is None:
        return None
    if isinstance(node, ast.Constant):
        if isinstance(node.value, str):
            return _annotation_type(_parse_string_annotation(node))
        return None
    parts = _dotted(node)
    if parts:
        return _Type(".".join(parts))
    if isinstance(node, ast.Subscript):
        parts = _dotted(node.value)
        if not parts:
            return None
        base, last = ".".join(parts), parts[-1]
        sl = node.slice
        args = list(sl.elts) if isinstance(sl, ast.Tuple) else [sl]
        if last in _WRAPPERS:
            return _annotation_type(args[0])
        if last == "Union":
            for a in args:
                t = _annotation_type(a)
                if t:
                    return t
            return None
        if last in _CONTAINERS:
            return _Type(base, elem=_annotation_type(args[0]))
        return _Type(base)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
        return _annotation_type(node.left) or _annotation_type(node.right)
    return None


def _all_args(args: ast.arguments) -> list[ast.arg]:
    out = [*args.posonlyargs, *args.args]
    if args.vararg:
        out.append(args.vararg)
    out.extend(args.kwonlyargs)
    if args.kwarg:
        out.append(args.kwarg)
    return out


def _is_staticmethod(node: ast.AST) -> bool:
    for d in node.decorator_list:
        parts = _dotted(d)
        if parts and parts[-1] == "staticmethod":
            return True
    return False


def _receiver(node: ast.AST) -> str | None:
    """Name of a method's first parameter (``self``/``cls``), if it has one."""
    if _is_staticmethod(node):
        return None
    positional = [*node.args.posonlyargs, *node.args.args]
    return positional[0].arg if positional else None


def _local_names(fn: ast.AST) -> set[str]:
    """Names bound inside a function body (not nested scopes, not imports)."""
    names = {a.arg for a in _all_args(fn.args)}
    declared: set[str] = set()

    def visit(node: ast.AST) -> None:
        if isinstance(node, (*_DEFS, ast.Lambda, *_COMPS)):
            return  # their own scopes; a def's name resolves to its symbol
        if isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del)):
            names.add(node.id)
        elif isinstance(node, (ast.Global, ast.Nonlocal)):
            declared.update(node.names)
        elif isinstance(node, ast.ExceptHandler) and node.name:
            names.add(node.name)
        else:
            for attr in ("name", "rest"):  # match patterns
                value = getattr(node, attr, None)
                if isinstance(value, str) and isinstance(node, ast.pattern):
                    names.add(value)
        for child in ast.iter_child_nodes(node):
            visit(child)

    for stmt in fn.body:
        visit(stmt)
    return names - declared


def _class_attr_types(node: ast.ClassDef) -> dict[str, _Type]:
    """Types of ``self.<attr>``: class annotations, then assignments in methods."""
    annotated: dict[str, _Type] = {}
    assigned: dict[str, _Type] = {}
    for stmt in node.body:
        if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
            t = _annotation_type(stmt.annotation)
            if t:
                annotated[stmt.target.id] = t
    for stmt in node.body:
        if not isinstance(stmt, _FUNCS):
            continue
        me = _receiver(stmt)
        if me is None:
            continue
        params = {
            a.arg: _annotation_type(a.annotation)
            for a in _all_args(stmt.args)
            if a.annotation is not None
        }

        def own_attr(target: ast.AST) -> str | None:
            if (
                isinstance(target, ast.Attribute)
                and isinstance(target.value, ast.Name)
                and target.value.id == me
            ):
                return target.attr
            return None

        for sub in ast.walk(stmt):
            if isinstance(sub, ast.AnnAssign) and own_attr(sub.target):
                t = _annotation_type(sub.annotation)
                if t:
                    annotated[own_attr(sub.target)] = t
            elif isinstance(sub, ast.Assign):
                t = None
                value = sub.value
                if isinstance(value, ast.Call):
                    parts = _dotted(value.func)
                    if parts and parts[0] != me and parts[0] not in params:
                        t = _Type(".".join(parts))
                elif isinstance(value, ast.Name):
                    t = params.get(value.id)
                if t:
                    for target in sub.targets:
                        attr = own_attr(target)
                        if attr:
                            assigned.setdefault(attr, t)
    return {**assigned, **annotated}


class _FileParser:
    def __init__(self, path: str, module: str, source: str):
        self.path = path
        self.module = module
        self.source = source
        self.lines = source.splitlines()
        is_package = path.rsplit("/", 1)[-1].startswith("__init__.")
        self.package = module if is_package else module.rpartition(".")[0]
        self.symbols: list[Symbol] = []
        self.refs: list[Reference] = []
        self.edges: list[Edge] = []
        self.bindings: list[Binding] = []
        self._counts: dict[str, dict[str, int]] = {}

    # -- results -----------------------------------------------------------

    def module_symbol(self, tree: ast.Module | None) -> Symbol:
        doc = ast.get_docstring(tree) if tree is not None else None
        first = doc.strip().splitlines()[0] if doc and doc.strip() else ""
        sig = f'"""{first}"""' if first else ""
        return Symbol(
            id=self.module,
            kind=NodeKind.MODULE,
            file=self.path,
            span=(1, max(1, len(self.lines))),
            signature=sig,
            tokens_full=estimate_tokens(self.source),
            tokens_sig=estimate_tokens(sig),
        )

    def result(self) -> ParseResult:
        return ParseResult(
            file=self.path,
            module=self.module,
            symbols=tuple(self.symbols),
            references=tuple(self.refs),
            edges=tuple(self.edges),
            bindings=tuple(self.bindings),
        )

    def run(self, tree: ast.Module) -> None:
        self.symbols.append(self.module_symbol(tree))
        self.stmts(tree.body, _Scope(self.module, NodeKind.MODULE))

    # -- symbols -----------------------------------------------------------

    def define(self, node: ast.AST, parent: str, kind: NodeKind) -> str:
        counts = self._counts.setdefault(parent, {})
        n = counts.get(node.name, 0) + 1
        counts[node.name] = n
        sid = f"{parent}.{node.name}" + (f"#{n}" if n > 1 else "")
        start = min([node.lineno] + [d.lineno for d in node.decorator_list])
        end = node.end_lineno or node.lineno
        sig = self.signature(node)
        full = "\n".join(self.lines[start - 1 : end])
        self.symbols.append(
            Symbol(
                id=sid,
                kind=kind,
                file=self.path,
                span=(start, end),
                signature=sig,
                tokens_full=estimate_tokens(full),
                tokens_sig=estimate_tokens(sig),
            )
        )
        self.edges.append(Edge(parent, sid, EdgeKind.CONTAINS))
        return sid

    def signature(self, node: ast.AST) -> str:
        """Header from ``def``/``class`` to its colon, plus the docstring's first line."""
        first = node.lineno - 1
        col = node.col_offset
        lines = self.lines[first : (node.body[0].lineno if node.body else node.end_lineno)]
        lines = [lines[0][col:]] + [
            ln[col:] if ln[:col].strip() == "" else ln.lstrip() for ln in lines[1:]
        ]
        header = lines[0]
        try:
            depth = 0
            tokens = tokenize.generate_tokens(io.StringIO("\n".join(lines) + "\n").readline)
            for tok in tokens:
                if tok.type != tokenize.OP:
                    continue
                if tok.string in "([{":
                    depth += 1
                elif tok.string in ")]}":
                    depth -= 1
                elif tok.string == ":" and depth == 0:
                    row, end_col = tok.end
                    header = "\n".join(lines[: row - 1] + [lines[row - 1][:end_col]])
                    break
        except (tokenize.TokenError, SyntaxError, IndentationError):
            pass
        doc = ast.get_docstring(node)
        if doc and doc.strip():
            header += f'\n    """{doc.strip().splitlines()[0]}"""'
        return header

    # -- statements --------------------------------------------------------

    def stmts(self, body: list[ast.stmt], scope: _Scope) -> None:
        for node in body:
            self.stmt(node, scope)

    def stmt(self, node: ast.stmt, scope: _Scope) -> None:
        if isinstance(node, _FUNCS):
            self.function(node, scope)
        elif isinstance(node, ast.ClassDef):
            self.klass(node, scope)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            self.imports(node, scope)
        elif isinstance(node, ast.Assign):
            self.expr(node.value, scope)
            t = self.infer(node.value, scope)
            for target in node.targets:
                self.target(target, scope)
                self.bind_type(target, t, scope)
        elif isinstance(node, ast.AnnAssign):
            self.annotation(node.annotation, scope)
            self.expr(node.value, scope)
            self.target(node.target, scope)
            t = _annotation_type(node.annotation) or self.infer(node.value, scope)
            self.bind_type(node.target, t, scope)
        elif isinstance(node, (ast.For, ast.AsyncFor)):
            self.expr(node.iter, scope)
            t = self.infer(node.iter, scope)
            self.target(node.target, scope)
            self.bind_type(node.target, t.elem if t else None, scope)
            self.stmts(node.body, scope)
            self.stmts(node.orelse, scope)
        elif isinstance(node, (ast.With, ast.AsyncWith)):
            for item in node.items:
                self.expr(item.context_expr, scope)
                if item.optional_vars is not None:
                    self.target(item.optional_vars, scope)
                    self.bind_type(item.optional_vars, None, scope)
            self.stmts(node.body, scope)
        else:
            self.generic(node, scope)

    def generic(self, node: ast.AST, scope: _Scope) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.stmt):
                self.stmt(child, scope)
            elif isinstance(child, ast.expr):
                self.expr(child, scope)
            else:
                self.generic(child, scope)

    def function(self, node: ast.AST, scope: _Scope) -> None:
        kind = NodeKind.METHOD if scope.kind is NodeKind.CLASS else NodeKind.FUNCTION
        sid = self.define(node, scope.id, kind)
        # Decorators, defaults and annotations run in the enclosing scope but
        # belong to the function.
        for d in node.decorator_list:
            self.expr(d, scope, sid)
        for d in [*node.args.defaults, *node.args.kw_defaults]:
            if d is not None:
                self.expr(d, scope, sid)
        args = _all_args(node.args)
        for a in args:
            self.annotation(a.annotation, scope, sid)
        self.annotation(node.returns, scope, sid)

        own = _local_names(node)
        inherited = scope.is_function
        env = {k: v for k, v in scope.env.items() if k not in own} if inherited else {}
        if kind is NodeKind.METHOD:
            me = _receiver(node)
            if me:
                env[me] = _SELF
        for a in args:
            if a.arg not in env:
                t = _annotation_type(a.annotation)
                if t:
                    env[a.arg] = t
        names = own | scope.locals if inherited else own
        inner = _Scope(sid, kind, set(names), env, scope.attrs)
        self.stmts(node.body, inner)

    def klass(self, node: ast.ClassDef, scope: _Scope) -> None:
        sid = self.define(node, scope.id, NodeKind.CLASS)
        for d in node.decorator_list:
            self.expr(d, scope, sid)
        for base in node.bases:
            target = base.value if isinstance(base, ast.Subscript) else base
            parts = _dotted(target)
            if parts and parts[0] not in scope.locals and parts[0] not in scope.env:
                self.ref(sid, ".".join(parts), EdgeKind.INHERITS, base.lineno)
                if isinstance(base, ast.Subscript):
                    self.expr(base.slice, scope, sid)
            else:
                self.expr(base, scope, sid)
        for kw in node.keywords:
            self.expr(kw.value, scope, sid)
        inner = _Scope(sid, NodeKind.CLASS, attrs=_class_attr_types(node))
        self.stmts(node.body, inner)

    def imports(self, node: ast.Import | ast.ImportFrom, scope: _Scope) -> None:
        line = node.lineno
        if isinstance(node, ast.Import):
            for a in node.names:
                self.ref(self.module, a.name, EdgeKind.IMPORTS, line)
                if a.asname:
                    self.bind(scope.id, a.asname, a.name)
                else:
                    head = a.name.split(".")[0]
                    self.bind(scope.id, head, head)
            return
        if node.level:
            pkg = self.package.split(".") if self.package else []
            up = node.level - 1
            if up > len(pkg):
                return
            parts = pkg[: len(pkg) - up]
            if node.module:
                parts += node.module.split(".")
            base = ".".join(parts)
        else:
            base = node.module or ""
        if not base:
            return
        for a in node.names:
            if a.name == "*":
                self.ref(self.module, base, EdgeKind.IMPORTS, line)
                self.bind(scope.id, "*", base)
            else:
                target = f"{base}.{a.name}"
                self.ref(self.module, target, EdgeKind.IMPORTS, line)
                self.bind(scope.id, a.asname or a.name, target)

    # -- expressions -------------------------------------------------------

    def expr(self, node: ast.AST | None, scope: _Scope, src: str | None = None) -> None:
        if node is None:
            return
        src = src or scope.id
        if isinstance(node, ast.Call):
            self.chain(node.func, scope, src, EdgeKind.CALLS)
            for a in node.args:
                self.expr(a, scope, src)
            for kw in node.keywords:
                self.expr(kw.value, scope, src)
        elif isinstance(node, (ast.Name, ast.Attribute)):
            if isinstance(node.ctx, ast.Load):
                self.chain(node, scope, src, EdgeKind.REFERENCES)
            else:
                self.target(node, scope, src)
        elif isinstance(node, _COMPS):
            self.comprehension(node, scope, src)
        elif isinstance(node, ast.Lambda):
            for d in [*node.args.defaults, *node.args.kw_defaults]:
                self.expr(d, scope, src)
            inner = scope.nested(a.arg for a in _all_args(node.args))
            self.expr(node.body, inner, src)
        elif isinstance(node, ast.NamedExpr):
            self.expr(node.value, scope, src)
            self.bind_type(node.target, self.infer(node.value, scope), scope)
        else:
            for child in ast.iter_child_nodes(node):
                if isinstance(child, ast.expr):
                    self.expr(child, scope, src)

    def comprehension(self, node: ast.AST, scope: _Scope, src: str) -> None:
        inner = scope.nested()
        for gen in node.generators:
            self.expr(gen.iter, inner, src)
            t = self.infer(gen.iter, inner)
            inner.locals |= {
                n.id for n in ast.walk(gen.target) if isinstance(n, ast.Name)
            }
            self.bind_type(gen.target, t.elem if t else None, inner)
            for cond in gen.ifs:
                self.expr(cond, inner, src)
        if isinstance(node, ast.DictComp):
            self.expr(node.key, inner, src)
            self.expr(node.value, inner, src)
        else:
            self.expr(node.elt, inner, src)

    def annotation(self, node: ast.AST | None, scope: _Scope, src: str | None = None) -> None:
        if node is None:
            return
        if isinstance(node, ast.Constant):
            if isinstance(node.value, str):
                self.annotation(_parse_string_annotation(node), scope, src)
        elif isinstance(node, ast.Subscript):
            self.annotation(node.value, scope, src)
            parts = _dotted(node.value)
            if not (parts and parts[-1] == "Literal"):
                self.annotation(node.slice, scope, src)
        elif isinstance(node, (ast.Tuple, ast.List)):
            for elt in node.elts:
                self.annotation(elt, scope, src)
        elif isinstance(node, ast.BinOp):
            self.annotation(node.left, scope, src)
            self.annotation(node.right, scope, src)
        else:
            self.expr(node, scope, src)

    def target(self, node: ast.AST, scope: _Scope, src: str | None = None) -> None:
        """An assignment target: only the expressions inside it are uses."""
        if isinstance(node, ast.Attribute):
            if _dotted(node) is None:
                self.expr(node.value, scope, src)
        elif isinstance(node, ast.Subscript):
            self.expr(node.value, scope, src)
            self.expr(node.slice, scope, src)
        elif isinstance(node, (ast.Tuple, ast.List)):
            for elt in node.elts:
                self.target(elt, scope, src)
        elif isinstance(node, ast.Starred):
            self.target(node.value, scope, src)

    def chain(self, node: ast.AST, scope: _Scope, src: str, kind: EdgeKind) -> None:
        """Report one reference for a whole ``a.b.c`` chain."""
        parts: list[str] = []
        base = node
        while isinstance(base, ast.Attribute):
            parts.append(base.attr)
            base = base.value
        parts.reverse()
        line = node.lineno
        if isinstance(base, ast.Name):
            head = base.id
            t = scope.env.get(head)
            if t is not None and t.is_self:
                if not parts:
                    return
                attr_type = scope.attrs.get(parts[0])
                if len(parts) >= 2 and attr_type and attr_type.name:
                    name = ".".join([attr_type.name, *parts[1:]])
                    self.ref(src, name, kind, line, inferred=True)
                else:
                    self.ref(src, ".".join(["self", *parts]), kind, line)
            elif t is not None:
                if parts and t.name:
                    self.ref(src, ".".join([t.name, *parts]), kind, line, inferred=True)
            elif head not in scope.locals:
                self.ref(src, ".".join([head, *parts]), kind, line)
        elif _is_super_call(base):
            if parts:
                self.ref(src, ".".join(["super()", *parts]), kind, line)
        else:
            self.expr(base, scope, src)
            t = self.infer(base, scope) if parts else None
            if t and t.name:
                self.ref(src, ".".join([t.name, *parts]), kind, line, inferred=True)

    def infer(self, node: ast.AST | None, scope: _Scope) -> _Type | None:
        """Best-effort type of an expression."""
        if isinstance(node, ast.Name):
            return scope.env.get(node.id)
        if isinstance(node, ast.Attribute):
            base = node.value
            if isinstance(base, ast.Name):
                t = scope.env.get(base.id)
                if t is not None and t.is_self:
                    return scope.attrs.get(node.attr)
            return None
        if isinstance(node, ast.Call):
            if _is_super_call(node):
                return None
            parts = _dotted(node.func)
            if not parts or parts[0] in scope.env or parts[0] in scope.locals:
                return None
            return _Type(".".join(parts))
        if isinstance(node, ast.Subscript):
            t = self.infer(node.value, scope)
            return t.elem if t else None
        return None

    def bind_type(self, target: ast.AST, t: _Type | None, scope: _Scope) -> None:
        if isinstance(target, ast.Name):
            if t is not None:
                scope.env[target.id] = t
            else:
                scope.env.pop(target.id, None)
        elif isinstance(target, (ast.Tuple, ast.List)):
            for elt in target.elts:
                self.bind_type(elt, None, scope)
        elif isinstance(target, ast.Starred):
            self.bind_type(target.value, None, scope)

    # -- output ------------------------------------------------------------

    def ref(self, src: str, name: str, kind: EdgeKind, line: int, inferred: bool = False) -> None:
        self.refs.append(Reference(src, name, kind, line, inferred))

    def bind(self, scope: str, name: str, target: str) -> None:
        self.bindings.append(Binding(scope, name, target))


class PythonParser(Parser):
    """Parses Python source with the standard ``ast`` module."""

    extensions = (".py", ".pyi")

    def module_id(self, path: str) -> str:
        stem = path.rsplit(".", 1)[0] if path.endswith(self.extensions) else path
        parts = [p for p in stem.split("/") if p]
        if parts and parts[-1] == "__init__":
            parts.pop()
        return ".".join(parts)

    def parse(self, path: str, source: str) -> ParseResult:
        module = self.module_id(path)
        fp = _FileParser(path, module, source)
        try:
            tree = ast.parse(source, filename=path)
        except (SyntaxError, ValueError, RecursionError, MemoryError):
            return ParseResult(path, module, (fp.module_symbol(None),))
        try:
            fp.run(tree)
        except RecursionError:
            fp = _FileParser(path, module, source)
            return ParseResult(path, module, (fp.module_symbol(tree),))
        return fp.result()
