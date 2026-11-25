"""CodeGraph storage and queries, the cache, and incremental indexing."""

import os
import shutil
import time

import pytest

from test_fixture import ROOT, expected_edges, expected_symbols
from vanrain.graph import CodeGraph, index
from vanrain.model import Edge, EdgeKind, NodeKind, Symbol
from vanrain.parsers.base import parse_repo
from vanrain.resolver import resolve


@pytest.fixture(scope="module")
def graph():
    results = parse_repo(ROOT)
    return CodeGraph([s for r in results for s in r.symbols], resolve(results))


def ids(edges, end="dst"):
    return [getattr(e, end) for e in edges]


# --- storage --------------------------------------------------------------------


def test_graph_holds_the_fixture(graph):
    assert set(graph.symbols) == set(expected_symbols())
    assert len(graph) == len(expected_symbols())
    got = {(e.src, e.kind, e.dst) for e in graph.edges()}
    assert got == {(s, k, d) for s, k, d, _ in expected_edges()}
    assert graph.edge_count == 42
    assert "shop.models.Order" in graph
    assert graph.symbol("shop.models.Order").kind is NodeKind.CLASS
    assert graph.get("nope") is None
    with pytest.raises(KeyError):
        graph.symbol("nope")


def sym(sid, file="m.py"):
    return Symbol(sid, NodeKind.FUNCTION, file, (1, 1), f"def {sid}():", 3, 3)


def test_one_edge_per_src_dst_kind_keeps_the_highest_confidence():
    g = CodeGraph([sym("a"), sym("b")])
    g.add_edge(Edge("a", "b", EdgeKind.CALLS, 0.7))
    g.add_edge(Edge("a", "b", EdgeKind.CALLS, 0.9))
    g.add_edge(Edge("a", "b", EdgeKind.CALLS, 0.5))
    g.add_edge(Edge("a", "b", EdgeKind.REFERENCES))
    assert g.edge_count == 2
    assert g.callees("a") == [Edge("a", "b", EdgeKind.CALLS, 0.9)]


def test_edges_must_join_known_symbols():
    g = CodeGraph([sym("a")])
    with pytest.raises(KeyError):
        g.add_edge(Edge("a", "missing", EdgeKind.CALLS))
    with pytest.raises(KeyError):
        g.add_edge(Edge("missing", "a", EdgeKind.CALLS))


def test_symbols_in_file(graph):
    assert graph.symbols_in_file("shop/util.py") == [
        "shop.util",
        "shop.util._unused",
        "shop.util.round_money",
    ]
    assert graph.symbols_in_file("nope.py") == []


# --- queries --------------------------------------------------------------------


def test_callers_and_callees(graph):
    assert ids(graph.callers("shop.util.round_money"), "src") == [
        "shop.checkout.checkout",
        "shop.checkout.outer.inner",
    ]
    assert ids(graph.callees("shop.checkout.checkout")) == [
        "shop.models.DiscountedOrder",
        "shop.models.DiscountedOrder.total",
        "shop.models.Order.add",
        "shop.pricing.with_tax",
        "shop.util.round_money",
    ]
    assert graph.callers("shop.util._unused") == []


def test_queries_carry_confidence(graph):
    conf = {e.dst: e.confidence for e in graph.callees("shop.checkout.checkout")}
    assert conf["shop.pricing.with_tax"] == 1.0
    assert 0 < conf["shop.models.Order.add"] < 1
    sure = graph.callees("shop.checkout.checkout", min_confidence=1.0)
    assert ids(sure) == [
        "shop.models.DiscountedOrder",
        "shop.pricing.with_tax",
        "shop.util.round_money",
    ]


def test_neighbours_by_kind_and_direction(graph):
    item = "shop.models.Item"
    assert ids(graph.neighbours(item, kinds=[EdgeKind.REFERENCES], direction="in"), "src") == [
        "shop.checkout.checkout",
        "shop.models.Order.__init__",
        "shop.models.Order.add",
    ]
    assert ids(graph.neighbours(item, kinds=[EdgeKind.CONTAINS])) == [
        "shop.models.Item.__init__",
        "shop.models.Item.price",
    ]
    both = graph.neighbours(item, direction="both")
    # Out: 2 contained methods. In: its module, 3 references and an import.
    assert len(both) == 2 + 1 + 3 + 1
    assert all(item in (e.src, e.dst) for e in both)
    with pytest.raises(ValueError):
        graph.neighbours(item, direction="sideways")


def test_neighbours_of_an_unknown_symbol_are_empty(graph):
    assert graph.neighbours("nope", direction="both") == []
    assert graph.callers("nope") == []


def test_query_order_is_deterministic(graph):
    out = graph.neighbours("shop.checkout", direction="out")
    assert out == sorted(out, key=lambda e: (e.kind.value, e.dst))


# --- save / load ----------------------------------------------------------------


def test_save_and_load_round_trip(graph, tmp_path):
    path = tmp_path / "sub" / "graph.json"
    graph.save(path)
    loaded = CodeGraph.load(path)
    assert loaded == graph
    assert loaded.symbols == graph.symbols
    assert list(loaded.edges()) == list(graph.edges())
    assert loaded.symbol("shop.models.Order").span == graph.symbol("shop.models.Order").span


# --- index: cache and incremental updates ---------------------------------------


@pytest.fixture
def repo(tmp_path):
    dst = tmp_path / "repo"
    shutil.copytree(ROOT / "shop", dst / "shop")
    return dst


def fresh(root):
    return index(root, cache=None).graph


def touch_later(path, text):
    """Write ``text`` and make sure the mtime moves even on coarse clocks."""
    st = path.stat()
    path.write_bytes(text.encode() if isinstance(text, str) else text)
    os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns + 2_000_000_000))


def test_first_run_parses_everything_and_writes_the_cache(repo):
    run = index(repo)
    assert sorted(run.parsed) == [
        "shop/__init__.py",
        "shop/checkout.py",
        "shop/models.py",
        "shop/pricing.py",
        "shop/util.py",
    ]
    assert run.reused == [] and run.removed == [] and run.resolved
    assert (repo / ".vanrain" / "cache.json").is_file()
    assert run.graph.edge_count == 42


def test_second_run_reuses_the_cache(repo):
    first = index(repo).graph
    run = index(repo)
    assert run.parsed == [] and run.removed == []
    assert len(run.reused) == 5
    assert not run.resolved  # nothing changed, so not even the resolver runs
    assert run.graph == first


def test_only_changed_files_are_reparsed(repo):
    index(repo)
    util = repo / "shop" / "util.py"
    touch_later(util, util.read_text() + "\n\ndef added():\n    return round_money(1)\n")
    run = index(repo)
    assert run.parsed == ["shop/util.py"]
    assert len(run.reused) == 4 and run.resolved
    assert "shop.util.added" in run.graph
    assert ids(run.graph.callees("shop.util.added")) == ["shop.util.round_money"]
    assert run.graph == fresh(repo)


def test_edges_from_unchanged_files_follow_a_change(repo):
    """checkout.py is not reparsed, but its edges to a renamed function go."""
    index(repo)
    util = repo / "shop" / "util.py"
    touch_later(util, util.read_text().replace("round_money", "round_cash"))
    run = index(repo)
    assert run.parsed == ["shop/util.py"]
    assert "shop.util.round_money" not in run.graph
    assert "shop.util.round_money" not in ids(run.graph.callees("shop.checkout.checkout"))
    assert run.graph == fresh(repo)


def test_added_and_removed_files(repo):
    index(repo)
    (repo / "shop" / "pricing.py").unlink()
    (repo / "shop" / "extra.py").write_text("from shop.util import round_money\n\ndef f():\n    round_money(2)\n")
    run = index(repo)
    assert run.parsed == ["shop/extra.py"]
    assert run.removed == ["shop/pricing.py"]
    assert "shop.pricing.with_tax" not in run.graph
    assert "shop.extra.f" in ids(run.graph.callers("shop.util.round_money"), "src")
    assert run.graph == fresh(repo)


def test_touched_but_unchanged_file_is_not_reparsed(repo):
    index(repo)
    util = repo / "shop" / "util.py"
    touch_later(util, util.read_bytes())
    run = index(repo)
    assert run.parsed == [] and not run.resolved


def test_corrupt_or_foreign_cache_is_rebuilt(repo):
    index(repo)
    cache = repo / ".vanrain" / "cache.json"
    cache.write_text("{not json")
    run = index(repo)
    assert len(run.parsed) == 5
    assert run.graph == fresh(repo)
    cache.write_text('{"format": -1}')
    assert len(index(repo).parsed) == 5


def test_custom_cache_path(repo, tmp_path):
    path = tmp_path / "elsewhere.json"
    index(repo, cache=path)
    assert path.is_file() and not (repo / ".vanrain").exists()
    assert index(repo, cache=path).parsed == []


def test_second_run_is_much_faster(repo):
    # Enough files that parsing dominates, so the comparison is not noise.
    for i in range(120):
        shutil.copy(repo / "shop" / "checkout.py", repo / "shop" / f"copy{i}.py")
    t0 = time.perf_counter()
    index(repo)
    cold = time.perf_counter() - t0
    # Best of three warm runs, so one slow tick on a shared CI runner does not
    # decide the result.
    warm = float("inf")
    for _ in range(3):
        t0 = time.perf_counter()
        run = index(repo)
        warm = min(warm, time.perf_counter() - t0)
        assert run.parsed == []
    assert warm < cold / 3, (cold, warm)
