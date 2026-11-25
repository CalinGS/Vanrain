"""Guards the fixture repo's documented graph against drift.

The expected files are the ground truth for milestone 2 onward, so this test
checks them against the fixture source with the standard ast module.
"""

import ast
from pathlib import Path

import pytest

from vanrain.model import EdgeKind, NodeKind

ROOT = Path(__file__).parent / "fixtures" / "tiny_repo"


def rows(name):
    for line in (ROOT / name).read_text().splitlines():
        if line.strip() and not line.startswith("#"):
            yield line.split("\t")


def expected_symbols():
    return {
        sid: (NodeKind(kind), file, (int(start), int(end)))
        for sid, kind, file, start, end in rows("expected_symbols.tsv")
    }


def expected_edges():
    return [
        (src, EdgeKind(kind), dst, conf)
        for src, kind, dst, conf, _why in rows("expected_edges.tsv")
    ]


def actual_symbols():
    found = {}
    for path in sorted((ROOT / "shop").glob("*.py")):
        rel = path.relative_to(ROOT).as_posix()
        mod = "shop" if path.name == "__init__.py" else f"shop.{path.stem}"
        src = path.read_text()
        found[mod] = (NodeKind.MODULE, rel, (1, len(src.splitlines())))

        def walk(node, prefix, in_class):
            for child in node.body:
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    if isinstance(child, ast.ClassDef):
                        kind = NodeKind.CLASS
                    else:
                        kind = NodeKind.METHOD if in_class else NodeKind.FUNCTION
                    sid = f"{prefix}.{child.name}"
                    start = min([child.lineno] + [d.lineno for d in child.decorator_list])
                    found[sid] = (kind, rel, (start, child.end_lineno))
                    walk(child, sid, isinstance(child, ast.ClassDef))

        walk(ast.parse(src), mod, False)
    return found


def test_expected_symbols_match_source():
    assert expected_symbols() == actual_symbols()


def test_edges_join_known_symbols():
    symbols = expected_symbols()
    for src, _kind, dst, _conf in expected_edges():
        assert src in symbols, src
        assert dst in symbols, dst


def test_edges_are_unique_and_well_formed():
    edges = expected_edges()
    keys = [(s, k, d) for s, k, d, _ in edges]
    assert len(keys) == len(set(keys))
    assert {c for *_, c in edges} <= {"exact", "heuristic"}
    assert len(edges) == 42


def test_contains_edges_match_nesting():
    symbols = expected_symbols()
    contains = {(s, d) for s, k, d, _ in expected_edges() if k is EdgeKind.CONTAINS}
    implied = set()
    for sid, (kind, _f, _s) in symbols.items():
        if kind is not NodeKind.MODULE:
            implied.add((sid.rsplit(".", 1)[0], sid))
    assert contains == implied


@pytest.mark.parametrize("kind", list(EdgeKind))
def test_every_edge_kind_is_exercised(kind):
    assert any(k is kind for _s, k, _d, _c in expected_edges())
