from pathlib import Path

import pytest

from vanrain import api
from vanrain.text_seeds import is_test_file, mentions, score_seeds, seeds_from_text

TINY = Path(__file__).parent / "fixtures" / "tiny_repo"


@pytest.fixture(scope="module")
def graph():
    return api.open_repo(TINY, cache=False).graph


def test_mentions_order_and_options():
    text = (
        "Checkout is wrong with `--round-money`\n"
        'File "shop/checkout.py", line 14, in checkout\n'
        'File "shop/pricing.py", line 13, in with_tax\n'
        "see shop.models.Order and DiscountedOrder at https://example.com/x.html\n"
    )
    m = mentions(text)
    assert m.identifiers[:2] == ("with_tax", "checkout")
    assert "shop.models.Order" in m.identifiers and "DiscountedOrder" in m.identifiers
    assert "round_money" in m.identifiers  # --round-money as an option name
    assert m.paths == ("shop/pricing.py", "shop/checkout.py")
    assert m.words[0] == "checkout"  # title words first


def test_traceback_frames_win(graph):
    text = 'Traceback:\n  File "shop/pricing.py", line 13, in with_tax\nsee Order.total'
    assert seeds_from_text(graph, TINY, text)[0] == "shop.pricing.with_tax"


def test_foreign_prefix_is_dropped_only_when_what_is_left_is_specific(graph):
    assert seeds_from_text(graph, TINY, "`xr.DiscountedOrder` breaks") == \
        ["shop.models.DiscountedOrder"]
    assert seeds_from_text(graph, TINY, "calling np.add fails") == []


def test_names_only_in_code_are_found_by_text_search(graph):
    # TAX_RATE is a module constant, not a symbol: the function using it scores.
    assert seeds_from_text(graph, TINY, "`TAX_RATE` should be 0.25") == \
        ["shop.pricing.with_tax"]


def test_plain_words_are_the_last_resort(graph):
    assert seeds_from_text(graph, TINY, "Discounts get applied twice") == \
        ["shop.pricing.apply_discount"]
    assert seeds_from_text(graph, TINY, "Something is slow, please help.") == []


def test_top_level_package_and_common_names_are_not_seeds(graph):
    scores = score_seeds(graph, TINY, "the `shop` package: `open` and `print` misbehave")
    assert "shop" not in scores
    assert not any(s.endswith((".open", ".print")) for s in scores)


def test_max_seeds_and_min_share(graph):
    text = "`checkout` `with_tax` `apply_discount` `round_money` `Order.add` `Item.price`"
    seeds = seeds_from_text(graph, TINY, text, max_seeds=3)
    assert len(seeds) == 3
    assert seeds_from_text(graph, TINY, text, max_seeds=3, min_share=1.0) == seeds[:1]


@pytest.mark.parametrize("path, expected", [
    ("tests/test_a.py", True), ("src/pkg/testing/x.py", True), ("pkg/conftest.py", True),
    ("pkg/a_test.py", True), ("src/_pytest/python.py", False), ("pkg/contest.py", False),
])
def test_is_test_file(path, expected):
    assert is_test_file(path) is expected


def test_api_exposes_seeds_from_text(graph):
    assert api.seeds_from_text(graph, TINY, "`with_tax`") == ["shop.pricing.with_tax"]
