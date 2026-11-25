"""Selectors: BFS ranking, greedy fill under a budget, detail levels."""

import math
import random
from collections import deque

import pytest

from test_fixture import ROOT, expected_edges, expected_symbols
from vanrain.graph import CodeGraph, index
from vanrain.model import Detail, EdgeKind, NodeKind, SelectionItem
from vanrain.selector import BFSSelector, Selector, SelectorConfig, Strategy
from vanrain.selector.base import ancestors, item_cost, symbol_cost

SEED = "shop.checkout.checkout"
STRATEGIES = list(Strategy)


@pytest.fixture(scope="module")
def graph():
    return index(ROOT, cache=None).graph


def select(graph, budget, seeds=(SEED,), **config):
    return BFSSelector(SelectorConfig(**config)).select(graph, list(seeds), budget)


def reference_distances(seeds, follow=lambda kind, direction: True):
    """Shortest hop counts over the fixture's documented edges, both directions."""
    adj = {sid: set() for sid in expected_symbols()}
    for src, kind, dst, _ in expected_edges():
        if follow(kind, "out"):
            adj[src].add(dst)
        if follow(kind, "in"):
            adj[dst].add(src)
    dist = {s: 0 for s in seeds}
    queue = deque(seeds)
    while queue:
        sid = queue.popleft()
        for other in adj[sid]:
            if other not in dist:
                dist[other] = dist[sid] + 1
                queue.append(other)
    return dist


def sig_full(graph, sid):
    """What showing ``sid`` costs as (signature, full), header line included."""
    return symbol_cost(graph, sid, Detail.SIGNATURE), symbol_cost(graph, sid, Detail.FULL)


def shown(graph, selection):
    """Every symbol the reader can see: items plus what FULL items contain."""
    full = [i.symbol for i in selection.items if i.detail is Detail.FULL]
    seen = {i.symbol for i in selection.items}
    for sid in graph.symbols:
        if any(a in full for a in ancestors(graph, sid)):
            seen.add(sid)
    return seen


# --- interface -----------------------------------------------------------------


def test_bfs_is_a_selector():
    sel = BFSSelector()
    assert isinstance(sel, Selector)
    assert sel.config == SelectorConfig()
    assert sel.config.strategy is Strategy.SIGNATURES_FIRST


def test_selection_records_the_request(graph):
    s = select(graph, 200)
    assert s.seeds == (SEED,)
    assert s.budget == 200


def test_bad_requests(graph):
    with pytest.raises(KeyError):
        select(graph, 100, seeds=["shop.nope"])
    with pytest.raises(ValueError):
        select(graph, -1)
    with pytest.raises(ValueError):
        select(graph, 100, seeds=[])


# --- ranking -------------------------------------------------------------------


def test_bfs_distances_are_shortest_hops(graph):
    ranked = BFSSelector().rank(graph, [SEED])
    assert ranked[0] == (SEED, 0)
    assert dict(ranked) == reference_distances([SEED])
    assert [d for _, d in ranked] == sorted(d for _, d in ranked)
    assert len({sid for sid, _ in ranked}) == len(ranked)


def test_isolated_node_is_reached_only_through_its_module(graph):
    ranked = BFSSelector().rank(graph, ["shop.util._unused"])
    assert ranked[:2] == [("shop.util._unused", 0), ("shop.util", 1)]
    no_contains = SelectorConfig(
        edge_weights={(EdgeKind.CONTAINS, d): math.inf for d in ("in", "out")}
    )
    assert BFSSelector(no_contains).rank(graph, ["shop.util._unused"]) == [("shop.util._unused", 0)]


def test_first_ring_of_checkout(graph):
    ranked = BFSSelector().rank(graph, [SEED])
    ring = {sid for sid, d in ranked if d == 1}
    assert ring == {
        "shop.checkout",  # contains it
        "shop.models.DiscountedOrder",
        "shop.models.DiscountedOrder.total",
        "shop.models.Order.add",
        "shop.models.Item",
        "shop.pricing.with_tax",
        "shop.util.round_money",
    }


def test_several_seeds_start_together(graph):
    seeds = ["shop.pricing.with_tax", "shop.models.Item"]
    ranked = BFSSelector().rank(graph, seeds)
    assert ranked[:2] == [(seeds[0], 0), (seeds[1], 0)]
    assert dict(ranked) == reference_distances(seeds)


def test_max_distance(graph):
    ranked = BFSSelector(SelectorConfig(max_distance=1)).rank(graph, [SEED])
    assert max(d for _, d in ranked) == 1
    assert len(ranked) == 8


def test_min_confidence_drops_heuristic_edges(graph):
    ranked = dict(BFSSelector(SelectorConfig(min_confidence=1.0)).rank(graph, [SEED]))
    assert ranked["shop.models.DiscountedOrder"] == 1
    # Only reached through a guessed receiver type at distance 1.
    assert ranked["shop.models.Order.add"] > 1


def test_infinite_weight_means_do_not_follow(graph):
    blocked = {(EdgeKind.CONTAINS, "in"), (EdgeKind.CONTAINS, "out")}
    cfg = SelectorConfig(edge_weights={k: math.inf for k in blocked})
    ranked = dict(BFSSelector(cfg).rank(graph, [SEED]))
    assert ranked == reference_distances([SEED], follow=lambda kind, d: (kind, d) not in blocked)
    assert ranked["shop.checkout"] == 2  # now only through what it imports


def test_plain_bfs_ignores_weight_values(graph):
    heavy = {(k, d): w for k in EdgeKind for d, w in (("out", 7.5), ("in", 0.1))}
    assert BFSSelector(SelectorConfig(edge_weights=heavy)).rank(graph, [SEED]) == (
        BFSSelector().rank(graph, [SEED])
    )


def test_config_weights_default_to_one_and_reject_bad_values():
    cfg = SelectorConfig(edge_weights={(EdgeKind.IMPORTS, "in"): 3.0})
    assert cfg.weight(EdgeKind.IMPORTS, "in") == 3.0
    assert cfg.weight(EdgeKind.IMPORTS, "out") == 1.0
    assert cfg.weight(EdgeKind.CALLS, "in") == 1.0
    with pytest.raises(ValueError):
        SelectorConfig(edge_weights={(EdgeKind.CALLS, "sideways"): 1.0})
    with pytest.raises(ValueError):
        SelectorConfig(edge_weights={(EdgeKind.CALLS, "out"): -1.0})
    with pytest.raises(ValueError):
        SelectorConfig(max_distance=-1)
    assert SelectorConfig(strategy="full_first").strategy is Strategy.FULL_FIRST


# --- budget --------------------------------------------------------------------


@pytest.mark.parametrize("strategy", STRATEGIES)
def test_never_over_budget(graph, strategy):
    for budget in range(0, 1300, 7):
        s = select(graph, budget, strategy=strategy)
        assert s.tokens_used <= budget
        assert s.tokens_used == sum(item_cost(graph, i) for i in s.items)


@pytest.mark.parametrize("strategy", STRATEGIES)
def test_zero_budget_selects_nothing(graph, strategy):
    s = select(graph, 0, strategy=strategy)
    assert s.items == []
    assert s.tokens_used == 0


def test_seed_comes_first_in_full_when_it_fits(graph):
    s = select(graph, sig_full(graph, SEED)[1])
    assert [(i.symbol, i.detail, i.distance) for i in s.items] == [(SEED, Detail.FULL, 0)]
    s = select(graph, sig_full(graph, SEED)[0])
    assert [(i.symbol, i.detail, i.distance) for i in s.items] == [(SEED, Detail.SIGNATURE, 0)]
    s = select(graph, sig_full(graph, SEED)[0] - 1)
    assert SEED not in {i.symbol for i in s.items}


def test_seeds_full_can_be_turned_off(graph):
    s = select(graph, sig_full(graph, SEED)[1], seeds_full=False)
    assert s.items[0] == SelectionItem(SEED, Detail.SIGNATURE, 0)


def test_seed_inside_another_seed_is_not_repeated(graph):
    s = select(graph, 1000, seeds=("shop.models.Order", "shop.models.Order.add"))
    assert s.items[0] == SelectionItem("shop.models.Order", Detail.FULL, 0)
    assert "shop.models.Order.add" not in {i.symbol for i in s.items}


def test_items_follow_the_ranking(graph):
    ranked = BFSSelector().rank(graph, [SEED])
    pos = {sid: n for n, (sid, _) in enumerate(ranked)}
    for strategy in STRATEGIES:
        for budget in (50, 150, 400, 5000):
            s = select(graph, budget, strategy=strategy)
            order = [pos[i.symbol] for i in s.items]
            assert order == sorted(order)
            assert all(i.distance == dict(ranked)[i.symbol] for i in s.items)


def test_greedy_fill_skips_what_does_not_fit_and_keeps_going(graph):
    s = select(graph, 100, strategy=Strategy.SIGNATURES_ONLY, seeds_full=False)
    ranked = BFSSelector().rank(graph, [SEED])
    picked = {i.symbol for i in s.items}
    skipped = [sid for sid, _ in ranked if sid not in picked]
    left = s.budget - s.tokens_used
    assert skipped, "the budget should be too small for everything"
    assert all(sig_full(graph, sid)[0] > left for sid in skipped)
    # Later, smaller symbols still got in after a bigger one was skipped.
    first_skip = next(n for n, (sid, _) in enumerate(ranked) if sid not in picked)
    assert any(sid in picked for sid, _ in ranked[first_skip + 1 :])


# --- detail levels ---------------------------------------------------------------


def costs_more_in_full(graph, sid):
    sym = graph.symbol(sid)
    return sym.tokens_full > sym.tokens_sig


def test_signatures_only_shows_bodies_of_seeds_only(graph):
    for budget in (100, 400, 5000):
        s = select(graph, budget, strategy=Strategy.SIGNATURES_ONLY)
        assert [i.symbol for i in s.items if i.detail is Detail.FULL] == [SEED]
        s = select(graph, budget, strategy=Strategy.SIGNATURES_ONLY, seeds_full=False)
        assert {i.detail for i in s.items} == {Detail.SIGNATURE}


def base_budget(graph):
    """Seed in full plus every other reachable signature."""
    ranked = BFSSelector().rank(graph, [SEED])
    return sum(sig_full(graph, sid)[0] for sid, _ in ranked) - sig_full(graph, SEED)[0] + sig_full(graph, SEED)[1]


def test_signatures_first_spends_on_breadth_before_depth(graph):
    ranked = BFSSelector().rank(graph, [SEED])
    base = base_budget(graph)
    s = select(graph, base)
    assert {i.symbol for i in s.items} == {sid for sid, _ in ranked}
    full = [i.symbol for i in s.items if i.detail is Detail.FULL and costs_more_in_full(graph, i.symbol)]
    assert full == [SEED]
    s = select(graph, base - 1)
    assert len(shown(graph, s)) == len(ranked) - 1  # one signature had to go


def test_signatures_first_upgrades_nearest_first(graph):
    # 10 spare tokens. Nearest first, DiscountedOrder (distance 1) costs 6 more
    # in full, because showing the class in full makes its two method
    # signatures redundant and refunds them. That leaves 4, too little for
    # anything else that grows in full.
    s = select(graph, base_budget(graph) + 10)
    full = [i.symbol for i in s.items if i.detail is Detail.FULL and costs_more_in_full(graph, i.symbol)]
    assert full == [SEED, "shop.models.DiscountedOrder"]
    picked = {i.symbol for i in s.items}
    assert "shop.models.DiscountedOrder.total" not in picked  # absorbed
    assert s.budget - s.tokens_used == 4


def test_all_three_levels_appear(graph):
    ranked = BFSSelector().rank(graph, [SEED])
    reachable = {sid for sid, _ in ranked}
    s = select(graph, 250)
    details = {i.detail for i in s.items}
    assert details == {Detail.FULL, Detail.SIGNATURE}
    assert shown(graph, s) < reachable  # some reachable symbols are left out
    assert s.items[0] == SelectionItem(SEED, Detail.FULL, 0)


def test_selection_is_greedy_maximal(graph):
    """Nothing left out would still fit in what is left of the budget."""
    for strategy in STRATEGIES:
        for budget in (40, 120, 250, 600):
            s = select(graph, budget, strategy=strategy)
            left = budget - s.tokens_used
            picked = {i.symbol: i for i in s.items}
            covered = shown(graph, s)
            for sid, _ in BFSSelector().rank(graph, [SEED]):
                if sid not in covered:
                    assert sig_full(graph, sid)[0] > left, (strategy, budget, sid)
            if strategy is Strategy.SIGNATURES_ONLY:
                continue
            for sid, item in picked.items():
                sym = graph.symbol(sid)
                upgradable = sym.kind is not NodeKind.MODULE or sid == SEED
                if item.detail is Detail.SIGNATURE and upgradable:
                    assert sym.tokens_full - sym.tokens_sig > left, (strategy, budget, sid)


def test_modules_are_not_upgraded_unless_seeded(graph):
    s = select(graph, 100_000)
    by_id = {i.symbol: i for i in s.items}
    assert by_id["shop.checkout"].detail is Detail.SIGNATURE
    assert by_id["shop.models"].detail is Detail.SIGNATURE
    s = select(graph, 100_000, seeds=["shop.pricing"])
    assert s.items[0].symbol == "shop.pricing"
    assert s.items[0].detail is Detail.FULL


def test_upgrade_kinds_is_configurable(graph):
    s = select(graph, 100_000, upgrade_kinds=frozenset({NodeKind.FUNCTION}))
    for i in s.items:
        if i.detail is Detail.FULL:
            assert graph.symbol(i.symbol).kind is NodeKind.FUNCTION or i.symbol == SEED


@pytest.mark.parametrize("strategy", STRATEGIES)
def test_full_parent_absorbs_its_children(graph, strategy):
    for budget in (150, 300, 600, 100_000):
        s = select(graph, budget, strategy=strategy, seeds=["shop.models.Order.add"])
        full = {i.symbol for i in s.items if i.detail is Detail.FULL}
        for i in s.items:
            assert not (set(ancestors(graph, i.symbol)) & full), (budget, i.symbol)


def test_huge_budget_shows_everything_reachable(graph):
    ranked = BFSSelector().rank(graph, [SEED])
    for strategy in STRATEGIES:
        s = select(graph, 100_000, strategy=strategy)
        assert shown(graph, s) >= {sid for sid, _ in ranked}


def test_full_first_prefers_depth(graph):
    s = select(graph, 120, strategy=Strategy.FULL_FIRST)
    assert s.items[0].detail is Detail.FULL
    sigs_first = select(graph, 120)
    assert len(shown(graph, sigs_first)) >= len(shown(graph, s))


# --- determinism ------------------------------------------------------------------


def test_same_input_same_output(graph):
    for strategy in STRATEGIES:
        a = select(graph, 333, strategy=strategy)
        b = select(graph, 333, strategy=strategy)
        assert a == b


def test_insertion_order_does_not_matter(graph):
    rng = random.Random(4)
    for _ in range(5):
        symbols = list(graph.symbols.values())
        edges = graph.edges()
        rng.shuffle(symbols)
        rng.shuffle(edges)
        shuffled = CodeGraph(symbols, edges)
        for budget in (90, 333, 5000):
            assert select(shuffled, budget) == select(graph, budget)
