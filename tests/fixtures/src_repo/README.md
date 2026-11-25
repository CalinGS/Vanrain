# src_repo

A `src/` layout package for the layout tests (`tests/test_layout.py`).
`src/` is not on any import path, so module ids start below it: `acme.core`,
not `src.acme.core`. `tests/` keeps its name because it holds files directly.
`helpers.parse` is an `@overload`ed function and `fast.pyi` a stub with
overloads only.
