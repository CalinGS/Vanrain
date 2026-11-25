"""The public Python API in ``vanrain.api`` (what the CLI and later the MCP
server call)."""

import shutil
from pathlib import Path

import pytest

from test_fixture import ROOT
from vanrain import api
from vanrain.model import EdgeKind, NodeKind
from vanrain.selector import Strategy

GOLDEN = Path(__file__).parent / "golden"


@pytest.fixture
def repo(tmp_path):
    dst = tmp_path / "repo"
    shutil.copytree(ROOT, dst)
    return dst


def test_open_repo_indexes_with_cache(repo):
    run = api.open_repo(repo)
    assert len(run.graph) == 23
    assert (repo / ".vanrain" / "cache.json").is_file()
    assert api.open_repo(repo).parsed == []


def test_open_repo_without_cache(repo):
    api.open_repo(repo, cache=False)
    assert not (repo / ".vanrain").exists()


def test_open_repo_rejects_a_missing_root(tmp_path):
    with pytest.raises(NotADirectoryError):
        api.open_repo(tmp_path / "nowhere")


def test_get_context_matches_golden(repo):
    ctx = api.get_context(repo, ["shop.checkout.checkout"], budget=250, cache=False)
    assert ctx.seeds == ("shop.checkout.checkout",)
    assert ctx.selection.tokens_used <= 250
    assert ctx.text == (GOLDEN / "checkout_250.md").read_text(encoding="utf-8")


def test_get_context_accepts_one_name_and_a_strategy_string(repo):
    ctx = api.get_context(repo, "Order.total", strategy="signatures_only", cache=False)
    assert ctx.seeds == ("shop.models.Order.total",)
    assert ctx.selection.budget == api.DEFAULT_BUDGET == 2000
    assert api.DEFAULT_STRATEGY is Strategy.SIGNATURES_FIRST


def test_get_context_reuses_a_graph(repo):
    graph = api.open_repo(repo, cache=False).graph
    ctx = api.get_context(repo, ["Order"], graph=graph)
    assert not (repo / ".vanrain").exists()
    assert ctx.seeds == ("shop.models.Order",)


def test_get_context_errors(repo):
    with pytest.raises(api.SeedError) as exc:
        api.get_context(repo, ["total"], cache=False)
    assert len(exc.value.candidates) == 2
    with pytest.raises(ValueError):
        api.get_context(repo, ["Order"], budget=0, cache=False)
    with pytest.raises(ValueError):
        api.get_context(repo, [], cache=False)


def test_find_symbols(repo):
    graph = api.open_repo(repo, cache=False).graph
    found = api.find_symbols(graph, "total")
    assert [s.id for s in found] == [
        "shop.models.DiscountedOrder.total",
        "shop.models.Order.total",
    ]
    assert api.find_symbols(graph, "nope") == []


def test_links(repo):
    graph = api.open_repo(repo, cache=False).graph
    links = api.links(graph, "shop.pricing.apply_discount")
    assert all(l.kind is not EdgeKind.CONTAINS for l in links)
    assert any(l.direction == "in" and l.kind is EdgeKind.CALLS and l.other == "shop.models.DiscountedOrder.total" for l in links)


def test_repo_stats(repo):
    st = api.repo_stats(api.open_repo(repo, cache=False))
    assert st.files == 5
    assert st.symbols == 23
    assert st.edges == 42
    assert sum(st.symbols_by_kind.values()) == 23
    assert sum(st.edges_by_kind.values()) == 42
    assert st.symbols_by_kind[NodeKind.MODULE] == 5
    assert 0 <= st.heuristic_edges <= st.edges - st.edges_by_kind[EdgeKind.CONTAINS]
    assert st.most_called and st.most_called[0][1] >= st.most_called[-1][1]
