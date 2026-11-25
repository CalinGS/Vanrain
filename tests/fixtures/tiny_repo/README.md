# tiny_repo: the fixture with known edges

A hand-made Python package (`shop/`) whose correct code graph is written down in
two files. Every module from milestone 2 on is tested against them.

* `expected_symbols.tsv`: every symbol the parser must produce
  (id, kind, file, 1-based inclusive span).
* `expected_edges.tsv`: every edge the parser + resolver must produce, and no
  others (42 edges). `exact` edges must have confidence 1.0, `heuristic` ones
  below 1.0. The last column says why each edge exists.

The conventions behind both files are in the docstring of `vanrain/model.py`.
If you change anything under `shop/`, update both files;
`tests/test_fixture.py` checks that ids, kinds and spans still match the source.

## What each feature exercises

| Feature | Where |
| --- | --- |
| Relative import and re-export | `shop/__init__.py` re-exports `Order`; `checkout.py` imports it via `shop` |
| Submodule import | `from shop import util` |
| Inheritance and override | `DiscountedOrder(Order)` overrides `total`, inherits `add` |
| `super()` calls | `DiscountedOrder.__init__`, `DiscountedOrder.total` |
| Constructor call | `DiscountedOrder(discount)` |
| Heuristic instance calls | `order.add`, `order.total`, `item.price()` |
| Module attribute call | `util.round_money(...)` |
| Annotations as references | `list[Item]`, `item: Item` |
| `isinstance` as reference | `is_order` |
| Function as a value | `HANDLERS` dict at module level |
| Nested function | `outer.inner` |
| Isolated node | `util._unused` |

## Deliberately not edges (v0.1)

* Builtins and the standard library: `round`, `sum`, `isinstance`, `super`,
  `list.append`.
* Module-level variables: `with_tax` reading `TAX_RATE`, the `HANDLERS` name itself.
* Packages do not contain their submodules (`shop` has no CONTAINS edges).
* `from shop import Order` gives no IMPORTS edge to `shop` itself, only to the
  resolved name.
* Using `util.round_money` gives an edge to the function, not also to `shop.util`.
