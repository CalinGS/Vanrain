# model.py: review of the section 5 draft

Milestone 1 settles the schema every module depends on. This lists what changed
from the draft in the plan and why. The conventions themselves are in the
`vanrain/model.py` docstring.

## Changed or added

1. **`Detail` enum added** (`FULL`, `SIGNATURE`). The draft used it in
   `Selection` without defining it.
2. **Enums are `str` enums with lowercase values** (`EdgeKind.CALLS == "calls"`),
   so the graph cache (milestone 3) serialises them as plain text and old caches
   stay readable if members are reordered.
3. **`Selection.target: str` became `seeds: tuple[str, ...]`.** The seeds module
   returns a list of symbols (a stack trace gives several), so a selection can
   start from more than one node.
4. **`Selection.budget` added.** Without it you cannot tell from a selection how
   close to the budget it came, which the benchmark needs.
5. **`Selection.items` holds `SelectionItem(symbol, detail, distance)`** instead
   of bare `(str, Detail, int)` tuples, so callers use names, not positions.
6. **`Reference` and `ParseResult` added.** Section 3 says parsers return a
   `ParseResult` of symbols plus unresolved references, but the draft never
   defined either. They live in `model.py` because they are the contract between
   parsers and resolver, and they contain nothing Python-specific.
7. **`signature` defined as the full definition header** up to its colon, not
   just the first line, because a multi-line `def` cut at line one is not a
   usable signature. The first docstring line is still appended.

## Decisions written down (section 6 asked for them)

* **Ids:** nested definitions extend the parent id (`pkg.mod.outer.inner`);
  duplicates in one scope get `#2`, `#3`; re-exports create no symbol and
  resolve to the original definition.
* **Paths and spans:** repo-relative POSIX paths; spans 1-based and inclusive,
  starting at the first decorator.
* **Edges only between known symbols.** Builtins, stdlib, third-party code and
  module-level variables are dropped in v0.1; at most one edge per
  `(src, dst, kind)`.
* **Edge direction and meaning** are defined per kind in `EdgeKind`, including
  the cases that were ambiguous: a class call is `CALLS` to the class,
  `super().m()` is `CALLS` to the parent's `m`, a name in call position is never
  also `REFERENCES`, and packages do not `CONTAINS` their submodules.

## Open, deliberately left for later

* **Module-level variables and constants are not nodes.** `with_tax -> TAX_RATE`
  is invisible. Adding a `VARIABLE` node kind is cheap later if the benchmark
  shows the missing context hurts.
* **No validation in the types** (e.g. `0 < confidence <= 1`, `start <= end`),
  per "no logic" in model. Parsers and the resolver are tested instead.
* **Token counts live on `Symbol`**, which ties the graph cache to the token
  estimator. If the tokenizer changes, the cache must be rebuilt. Acceptable for
  v0.1; revisit when a real tokenizer arrives.
