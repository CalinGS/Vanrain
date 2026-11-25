"""Render: Selection -> markdown the LLM reads."""

from pathlib import Path

import pytest

from test_fixture import ROOT
from vanrain.graph import index
from vanrain.model import Detail, Selection, SelectionItem
from vanrain.render import render
from vanrain.selector import BFSSelector, SelectorConfig, Strategy

SEED = "shop.checkout.checkout"
GOLDEN = Path(__file__).parent / "golden"


@pytest.fixture(scope="module")
def graph():
    return index(ROOT, cache=None).graph


def context(graph, budget, seeds=(SEED,), **config):
    sel = BFSSelector(SelectorConfig(**config)).select(graph, list(seeds), budget)
    return sel, render(sel, graph, ROOT)


def test_golden_checkout_250(graph):
    """The whole output for one request, checked by eye once and frozen."""
    _, text = context(graph, 250)
    assert text == (GOLDEN / "checkout_250.md").read_text(encoding="utf-8")


def test_full_items_show_their_source(graph):
    _, text = context(graph, 250)
    assert "def checkout(items: list[Item], discount: float = 0.0) -> float:\n" in text
    assert "    return util.round_money(with_tax(order.total()))\n" in text


def test_signature_items_hide_their_body(graph):
    _, text = context(graph, 100, strategy=Strategy.SIGNATURES_ONLY, seeds_full=False)
    assert "def checkout(items: list[Item], discount: float = 0.0) -> float: ...\n" in text
    assert "order.add(it)" not in text


def test_methods_are_dedented(graph):
    _, text = context(graph, 100_000, seeds=["shop.models.Order.total"], upgrade_kinds=frozenset())
    assert "\ndef total(self) -> float:\n    return sum(" in text


def test_files_in_order_of_nearest_item_and_symbols_in_line_order(graph):
    sel, text = context(graph, 100_000)
    heads = [line[3:] for line in text.splitlines() if line.startswith("## ")]
    assert heads[0] == "shop/checkout.py"
    assert sorted(heads) == sorted(set(heads))
    models = text.split("## shop/models.py")[1].split("## ")[0]
    lines = [int(l.split(" L")[1].split("-")[0]) for l in models.splitlines() if l.startswith("# shop.")]
    assert lines == sorted(lines)


def test_children_of_a_full_item_are_not_repeated(graph):
    sel = Selection(
        seeds=("shop.models.Order",),
        budget=1000,
        items=[
            SelectionItem("shop.models.Order", Detail.FULL, 0),
            SelectionItem("shop.models.Order.add", Detail.SIGNATURE, 1),
            SelectionItem("shop.models.Item", Detail.SIGNATURE, 1),
        ],
    )
    text = render(sel, graph, ROOT)
    assert text.count("def add(self, item: Item) -> None:") == 1
    assert "# shop.models.Order.add" not in text
    assert "# shop.models.Item L5-15" in text


def test_header_counts(graph):
    sel, text = context(graph, 250)
    full = sum(i.detail is Detail.FULL for i in sel.items)
    sigs = len(sel.items) - full
    first = text.splitlines()[0]
    assert first == f"# Context for {SEED}"
    assert f"{len(sel.items)} symbols ({full} full, {sigs} signatures)" in text
    assert f"{sel.tokens_used} of 250 tokens" in text


def test_empty_selection(graph):
    sel, text = context(graph, 0)
    assert sel.items == []
    assert "Nothing fits" in text


def test_missing_file_falls_back_to_signature(graph, tmp_path):
    sel, _ = context(graph, 250)
    text = render(sel, graph, tmp_path)  # no source files here
    assert "def checkout(items: list[Item], discount: float = 0.0) -> float: ...\n" in text
    assert "source not found" in text


def test_render_is_deterministic(graph):
    assert context(graph, 400)[1] == context(graph, 400)[1]
