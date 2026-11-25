"""PythonParser: file -> ParseResult (symbols, references, bindings, CONTAINS)."""

import textwrap

import pytest

from test_fixture import ROOT, expected_edges, expected_symbols
from vanrain.model import Binding, Edge, EdgeKind, NodeKind, Reference
from vanrain.parsers.base import Parser, parse_repo
from vanrain.parsers.python_ast import PythonParser


def parse(source, path="pkg/mod.py"):
    return PythonParser().parse(path, textwrap.dedent(source))


def by_id(result):
    return {s.id: s for s in result.symbols}


def refs(result, kind=None):
    return {
        (r.src, r.name, r.inferred)
        for r in result.references
        if kind is None or r.kind is kind
    }


# --- the fixture -------------------------------------------------------------


@pytest.fixture(scope="module")
def results():
    return parse_repo(ROOT)


def test_parser_implements_interface():
    p = PythonParser()
    assert isinstance(p, Parser)
    assert ".py" in p.extensions


@pytest.mark.parametrize(
    "path, module",
    [
        ("shop/__init__.py", "shop"),
        ("shop/models.py", "shop.models"),
        ("a/b/c.py", "a.b.c"),
        ("top.py", "top"),
    ],
)
def test_module_id(path, module):
    assert PythonParser().module_id(path) == module


def test_parse_repo_finds_only_source_files(results):
    assert sorted(r.file for r in results) == [
        "shop/__init__.py",
        "shop/checkout.py",
        "shop/models.py",
        "shop/pricing.py",
        "shop/util.py",
    ]


def test_fixture_symbols_match_expected(results):
    got = {
        s.id: (s.kind, s.file, s.span) for r in results for s in r.symbols
    }
    assert got == expected_symbols()


def test_fixture_contains_edges_come_from_parser(results):
    got = {e for r in results for e in r.edges}
    want = {
        Edge(src, dst, kind)
        for src, kind, dst, _ in expected_edges()
        if kind is EdgeKind.CONTAINS
    }
    assert got == want


def test_fixture_signatures(results):
    syms = {s.id: s for r in results for s in r.symbols}
    assert syms["shop.models.Item.price"].signature == (
        'def price(self) -> float:\n    """Total price for this line."""'
    )
    assert syms["shop.models.DiscountedOrder"].signature == (
        'class DiscountedOrder(Order):\n    """An order with a percentage discount."""'
    )
    assert syms["shop.pricing.with_tax"].signature == (
        "def with_tax(amount: float) -> float:"
    )
    assert syms["shop.util"].signature == '"""Small helpers."""'


def test_fixture_token_counts(results):
    for r in results:
        for s in r.symbols:
            assert 0 < s.tokens_sig <= s.tokens_full, s.id


def test_fixture_imports_are_absolute(results):
    checkout = next(r for r in results if r.module == "shop.checkout")
    assert {r.name for r in checkout.references if r.kind is EdgeKind.IMPORTS} == {
        "shop.Order",
        "shop.util",
        "shop.models.DiscountedOrder",
        "shop.models.Item",
        "shop.pricing.with_tax",
    }
    init = next(r for r in results if r.module == "shop")
    assert Binding("shop", "Order", "shop.models.Order") in init.bindings


def test_fixture_inferred_receivers(results):
    models = next(r for r in results if r.module == "shop.models")
    checkout = next(r for r in results if r.module == "shop.checkout")
    calls = refs(models, EdgeKind.CALLS) | refs(checkout, EdgeKind.CALLS)
    assert ("shop.models.Order.total", "Item.price", True) in calls
    assert ("shop.checkout.checkout", "DiscountedOrder.add", True) in calls
    assert ("shop.checkout.checkout", "DiscountedOrder.total", True) in calls
    assert ("shop.models.DiscountedOrder.total", "super().total", False) in calls


# --- ids, spans, signatures --------------------------------------------------


def test_duplicate_names_get_numbered_ids():
    r = parse(
        """
        class C:
            @property
            def x(self):
                return 1

            @x.setter
            def x(self, v):
                pass

        if True:
            def f():
                def g(): pass
        else:
            def f():
                def g(): pass
        """
    )
    ids = by_id(r)
    assert {"pkg.mod.C.x", "pkg.mod.C.x#2", "pkg.mod.f", "pkg.mod.f#2"} <= ids.keys()
    assert {"pkg.mod.f.g", "pkg.mod.f#2.g"} <= ids.keys()
    assert ids["pkg.mod.C.x"].span == (3, 5)  # starts at the decorator
    assert ids["pkg.mod.C.x#2"].span == (7, 9)


def test_kinds_and_nesting():
    r = parse(
        """
        class Outer:
            class Inner:
                def m(self): pass

        async def run():
            def helper(): pass
        """
    )
    ids = by_id(r)
    assert ids["pkg.mod"].kind is NodeKind.MODULE
    assert ids["pkg.mod.Outer.Inner"].kind is NodeKind.CLASS
    assert ids["pkg.mod.Outer.Inner.m"].kind is NodeKind.METHOD
    assert ids["pkg.mod.run"].kind is NodeKind.FUNCTION
    assert ids["pkg.mod.run.helper"].kind is NodeKind.FUNCTION
    assert Edge("pkg.mod.Outer", "pkg.mod.Outer.Inner", EdgeKind.CONTAINS) in r.edges


def test_multiline_signature_and_async():
    r = parse(
        '''
        async def fetch(
            url: str,
            timeout: float = 1.0,
        ) -> bytes:
            """Fetch a URL.

            More text that is not part of the signature.
            """
            return b""
        '''
    )
    sig = by_id(r)["pkg.mod.fetch"].signature
    assert sig == (
        "async def fetch(\n"
        "    url: str,\n"
        "    timeout: float = 1.0,\n"
        ") -> bytes:\n"
        '    """Fetch a URL."""'
    )


def test_syntax_error_gives_module_only():
    r = parse("def broken(:\n")
    assert [s.id for s in r.symbols] == ["pkg.mod"]
    assert r.references == () and r.edges == ()


# --- references --------------------------------------------------------------


def test_calls_are_never_also_references():
    r = parse(
        """
        import util

        def f():
            util.helper(1)
            return util.other
        """
    )
    assert refs(r, EdgeKind.CALLS) == {("pkg.mod.f", "util.helper", False)}
    assert refs(r, EdgeKind.REFERENCES) == {("pkg.mod.f", "util.other", False)}


def test_untyped_locals_are_not_references():
    r = parse(
        """
        def f(a, b=None):
            c = make()
            a.x(); b.y(); c.z
            for d in range(3):
                d.w()
            return [e.v for e in a]
        """
    )
    names = {n for _s, n, _i in refs(r)}
    # make() is typed as "make", so c.z becomes an inferred guess the resolver
    # will drop unless make is a class.
    assert names == {"make", "range", "make.z"}


def test_self_and_cls_are_normalised():
    r = parse(
        """
        class A:
            def m(me):
                me.n()

            @classmethod
            def build(cls):
                return cls.n()

            @staticmethod
            def s(x):
                x.n()
        """
    )
    calls = refs(r, EdgeKind.CALLS)
    assert ("pkg.mod.A.m", "self.n", False) in calls
    assert ("pkg.mod.A.build", "self.n", False) in calls
    assert not any(src == "pkg.mod.A.s" for src, _n, _i in calls)


def test_attribute_types_from_annotations_and_constructors():
    r = parse(
        """
        class Repo:
            cache: "Cache"

            def __init__(self, db: Database):
                self.db = db
                self.log = Logger()

            def run(self):
                self.db.query()
                self.log.write()
                self.cache.get()
                Repo().run()
        """
    )
    calls = refs(r, EdgeKind.CALLS)
    assert ("pkg.mod.Repo.run", "Database.query", True) in calls
    assert ("pkg.mod.Repo.run", "Logger.write", True) in calls
    assert ("pkg.mod.Repo.run", "Cache.get", True) in calls
    assert ("pkg.mod.Repo.run", "Repo.run", True) in calls
    assert ("pkg.mod.Repo.run", "Repo", False) in calls


def test_annotations_and_string_annotations_are_references():
    r = parse(
        """
        from typing import Optional

        def f(x: "Item", y: Optional[list["Order"]] = None) -> "Result | None":
            z: Thing = x
        """
    )
    names = {n for s, n, _i in refs(r, EdgeKind.REFERENCES) if s == "pkg.mod.f"}
    assert {"Item", "Optional", "list", "Order", "Result", "Thing"} <= names


def test_bases_are_inherits_and_decorators_are_references():
    r = parse(
        """
        @register
        @app.route("/")
        class C(base.Base, Generic[T], metaclass=Meta):
            pass
        """
    )
    assert refs(r, EdgeKind.INHERITS) == {
        ("pkg.mod.C", "base.Base", False),
        ("pkg.mod.C", "Generic", False),
    }
    assert ("pkg.mod.C", "register", False) in refs(r, EdgeKind.REFERENCES)
    assert ("pkg.mod.C", "app.route", False) in refs(r, EdgeKind.CALLS)
    assert ("pkg.mod.C", "Meta", False) in refs(r, EdgeKind.REFERENCES)


def test_imports_and_bindings():
    r = parse(
        """
        import os.path
        import a.b as ab
        from . import sibling
        from ..up import thing as t
        from .star import *

        def f():
            from deep.mod import fn
        """,
        path="pkg/sub/mod.py",
    )
    imports = {(s, n) for s, n, _i in refs(r, EdgeKind.IMPORTS)}
    assert imports == {
        ("pkg.sub.mod", "os.path"),
        ("pkg.sub.mod", "a.b"),
        ("pkg.sub.mod", "pkg.sub.sibling"),
        ("pkg.sub.mod", "pkg.up.thing"),
        ("pkg.sub.mod", "pkg.sub.star"),
        ("pkg.sub.mod", "deep.mod.fn"),  # the module imports, even inside f
    }
    assert set(r.bindings) == {
        Binding("pkg.sub.mod", "os", "os"),
        Binding("pkg.sub.mod", "ab", "a.b"),
        Binding("pkg.sub.mod", "sibling", "pkg.sub.sibling"),
        Binding("pkg.sub.mod", "t", "pkg.up.thing"),
        Binding("pkg.sub.mod", "*", "pkg.sub.star"),
        Binding("pkg.sub.mod.f", "fn", "deep.mod.fn"),
    }


def test_relative_import_in_package_init():
    r = parse("from .models import Order\nfrom . import util\n", path="shop/__init__.py")
    assert set(r.bindings) == {
        Binding("shop", "Order", "shop.models.Order"),
        Binding("shop", "util", "shop.util"),
    }


def test_reference_lines():
    r = parse("import x\n\ndef f():\n    x.y()\n")
    (call,) = [ref for ref in r.references if ref.kind is EdgeKind.CALLS]
    assert call == Reference("pkg.mod.f", "x.y", EdgeKind.CALLS, 4)


def test_empty_subscript_annotation_does_not_crash():
    # ``Generator[()]`` and ``tuple[()]`` have a subscript with no elements.
    result = parse(
        """
        from typing import Generator, Optional

        def gen(x: Optional[()]) -> Generator[()]:
            pass

        def pair(x: tuple[()]) -> None:
            pass
        """
    )
    assert "pkg.mod.gen" in by_id(result)
