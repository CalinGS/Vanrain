"""Seeds: map a symbol name to start nodes."""

import pytest

from test_fixture import ROOT
from vanrain.graph import index
from vanrain.seeds import SeedError, find_seeds, resolve_seed, resolve_seeds


@pytest.fixture(scope="module")
def graph():
    return index(ROOT, cache=None).graph


def test_exact_id_wins(graph):
    assert find_seeds(graph, "shop.models.Order") == ["shop.models.Order"]
    # An exact id wins even when it is also the suffix of another id.
    assert find_seeds(graph, "shop.checkout") == ["shop.checkout"]


@pytest.mark.parametrize(
    "name, expected",
    [
        ("Order", "shop.models.Order"),
        ("Order.total", "shop.models.Order.total"),
        ("models.Order.total", "shop.models.Order.total"),
        ("inner", "shop.checkout.outer.inner"),
        ("outer.inner", "shop.checkout.outer.inner"),
        ("with_tax", "shop.pricing.with_tax"),
        ("util", "shop.util"),
    ],
)
def test_unique_suffix(graph, name, expected):
    assert find_seeds(graph, name) == [expected]
    assert resolve_seed(graph, name) == expected


def test_suffix_matches_whole_name_parts_only(graph):
    # "rder" is the end of "Order" but not a whole dotted part.
    assert find_seeds(graph, "rder") == []
    assert find_seeds(graph, "der.total") == []


def test_ambiguous_suffix_lists_candidates(graph):
    assert find_seeds(graph, "total") == [
        "shop.models.DiscountedOrder.total",
        "shop.models.Order.total",
    ]
    with pytest.raises(SeedError) as err:
        resolve_seed(graph, "total")
    assert err.value.candidates == (
        "shop.models.DiscountedOrder.total",
        "shop.models.Order.total",
    )
    assert "ambiguous" in str(err.value)
    # A module and a function can share a last part.
    assert find_seeds(graph, "checkout") == ["shop.checkout", "shop.checkout.checkout"]
    assert find_seeds(graph, "checkout.checkout") == ["shop.checkout.checkout"]


def test_unknown_name(graph):
    assert find_seeds(graph, "nope") == []
    with pytest.raises(SeedError) as err:
        resolve_seed(graph, "nope")
    assert err.value.candidates == ()
    assert "no symbol" in str(err.value)


def test_blank_name_is_rejected(graph):
    with pytest.raises(SeedError):
        resolve_seed(graph, "  ")


def test_resolve_many_keeps_order_and_drops_repeats(graph):
    assert resolve_seeds(graph, ["with_tax", "Order", "shop.pricing.with_tax"]) == (
        "shop.pricing.with_tax",
        "shop.models.Order",
    )
