"""Resolver: ParseResults -> Edges. The fixture's expected edges are the spec."""

import textwrap

import pytest

from test_fixture import ROOT, expected_edges
from vanrain.model import Edge, EdgeKind
from vanrain.parsers.base import parse_repo
from vanrain.parsers.python_ast import PythonParser
from vanrain.resolver import INFERRED_CONFIDENCE, SELF_CONFIDENCE, resolve


@pytest.fixture(scope="module")
def fixture_edges():
    return resolve(parse_repo(ROOT))


def test_fixture_produces_exactly_the_expected_edges(fixture_edges):
    got = {(e.src, e.kind, e.dst) for e in fixture_edges}
    want = {(s, k, d) for s, k, d, _ in expected_edges()}
    assert sorted(got - want) == [], "unexpected edges"
    assert sorted(want - got) == [], "missing edges"
    assert len(fixture_edges) == 42  # one edge per (src, dst, kind)


def test_fixture_confidences(fixture_edges):
    conf = {(e.src, e.kind, e.dst): e.confidence for e in fixture_edges}
    for src, kind, dst, label in expected_edges():
        c = conf[(src, kind, dst)]
        if label == "exact":
            assert c == 1.0, (src, kind, dst)
        else:
            assert 0.0 < c < 1.0, (src, kind, dst)
    assert sum(1 for c in conf.values() if c < 1.0) == 3


def test_resolve_is_deterministic():
    a = resolve(parse_repo(ROOT))
    b = resolve(reversed(parse_repo(ROOT)))
    assert a == b


# --- small repos ---------------------------------------------------------------


def parsed(files):
    """Parse {"pkg/mod.py": source, ...} without touching disk."""
    p = PythonParser()
    return [p.parse(path, textwrap.dedent(src)) for path, src in files.items()]


def edges_of(files):
    return {(e.src, e.kind, e.dst, e.confidence) for e in resolve(parsed(files))}


def test_external_and_unknown_names_are_dropped():
    edges = edges_of({"m.py": "import os\n\ndef f():\n    os.path.join(print(len([])))\n"})
    assert {(s, k, d) for s, k, d, _ in edges} == {("m", EdgeKind.CONTAINS, "m.f")}


def test_import_alias_and_star_import():
    edges = edges_of(
        {
            "a/__init__.py": "",
            "a/b.py": "def g(): pass\nclass K: pass\n",
            "c.py": "import a.b as ab\nfrom a.b import *\n\ndef f():\n    ab.g()\n    K()\n",
        }
    )
    assert ("c", EdgeKind.IMPORTS, "a.b", 1.0) in edges
    assert ("c.f", EdgeKind.CALLS, "a.b.g", 1.0) in edges
    assert ("c.f", EdgeKind.CALLS, "a.b.K", 1.0) in edges


def test_dotted_module_import():
    edges = edges_of(
        {
            "a/__init__.py": "",
            "a/b.py": "def g(): pass\n",
            "c.py": "import a.b\n\ndef f():\n    a.b.g()\n",
        }
    )
    assert ("c.f", EdgeKind.CALLS, "a.b.g", 1.0) in edges


def test_function_local_import():
    edges = edges_of(
        {
            "a.py": "def g(): pass\n",
            "b.py": "def f():\n    from a import g\n    g()\n",
        }
    )
    assert ("b", EdgeKind.IMPORTS, "a.g", 1.0) in edges
    assert ("b.f", EdgeKind.CALLS, "a.g", 1.0) in edges


def test_cross_module_inheritance_and_super():
    edges = edges_of(
        {
            "base.py": "class A:\n    def m(self): pass\n    def n(self): pass\n",
            "sub.py": (
                "from base import A\n\n"
                "class B(A):\n"
                "    def m(self):\n"
                "        super().m()\n"
                "        self.n()\n"
            ),
        }
    )
    assert ("sub.B", EdgeKind.INHERITS, "base.A", 1.0) in edges
    assert ("sub.B.m", EdgeKind.CALLS, "base.A.m", 1.0) in edges
    assert ("sub.B.m", EdgeKind.CALLS, "base.A.n", SELF_CONFIDENCE) in edges


def test_self_call_prefers_own_override():
    edges = edges_of(
        {"m.py": "class A:\n    def x(self): pass\nclass B(A):\n    def x(self): pass\n    def y(self):\n        self.x()\n"}
    )
    calls = {(s, d) for s, k, d, _ in edges if k is EdgeKind.CALLS}
    assert calls == {("m.B.y", "m.B.x")}


def test_inferred_receiver_must_be_a_class():
    edges = edges_of(
        {
            "m.py": (
                "def make():\n"
                "    def z(): pass\n"
                "class K:\n"
                "    def z(self): pass\n"
                "def f():\n"
                "    a = make()\n"
                "    a.z()\n"
                "    b = K()\n"
                "    b.z()\n"
            )
        }
    )
    calls = {(s, d, c) for s, k, d, c in edges if k is EdgeKind.CALLS}
    assert calls == {
        ("m.f", "m.make", 1.0),
        ("m.f", "m.K", 1.0),
        ("m.f", "m.K.z", INFERRED_CONFIDENCE),
    }


def test_class_scope_is_not_visible_from_methods():
    edges = edges_of(
        {"m.py": "def helper(): pass\nclass C:\n    def helper(self): pass\n    def run(self):\n        helper()\n"}
    )
    assert ("m.C.run", EdgeKind.CALLS, "m.helper", 1.0) in edges
    assert not any(d == "m.C.helper" and k is EdgeKind.CALLS for _s, k, d, _ in edges)


def test_exact_edge_wins_over_heuristic_duplicate():
    edges = edges_of(
        {"m.py": "class K:\n    def z(self): pass\ndef f():\n    k = K()\n    k.z()\n    K.z(k)\n"}
    )
    assert ("m.f", EdgeKind.CALLS, "m.K.z", 1.0) in edges
    assert ("m.f", EdgeKind.CALLS, "m.K.z", INFERRED_CONFIDENCE) not in edges


def test_reexport_cycles_terminate():
    edges = edges_of(
        {
            "a.py": "from b import x\n",
            "b.py": "from a import x\n",
            "c.py": "from a import x\n\ndef f():\n    x()\n",
        }
    )
    assert not any(k is EdgeKind.CALLS for _s, k, _d, _c in edges)


def test_inheritance_cycle_terminates():
    edges = edges_of({"m.py": "class A(B): pass\nclass B(A): pass\ndef f():\n    A().nope()\n"})
    assert ("m.A", EdgeKind.INHERITS, "m.B", 1.0) in edges


def test_confidences_are_ordered():
    assert 0.0 < INFERRED_CONFIDENCE < SELF_CONFIDENCE < 1.0


def test_edges_only_join_known_symbols():
    results = parse_repo(ROOT)
    known = {s.id for r in results for s in r.symbols}
    for e in resolve(results):
        assert isinstance(e, Edge)
        assert e.src in known and e.dst in known
