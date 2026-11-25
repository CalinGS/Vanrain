"""src/ layouts: module ids start below the source root, and imports between
files resolve. Also ``@overload``: one symbol per overloaded function."""

import shutil
from pathlib import Path

import pytest

from test_fixture import ROOT as TINY_ROOT
from vanrain import api
from vanrain.graph import _default_parsers, _fingerprint
from vanrain.model import EdgeKind, NodeKind
from vanrain.parsers.base import iter_source_files, parse_repo
from vanrain.parsers.python_ast import PythonParser
from vanrain.resolver import resolve

ROOT = Path(__file__).parent / "fixtures" / "src_repo"


@pytest.fixture(scope="module")
def results():
    return parse_repo(ROOT)


@pytest.fixture(scope="module")
def edges(results):
    return {(e.src, e.kind, e.dst) for e in resolve(results)}


def roots(*files):
    return PythonParser().source_roots(files)


def test_fixture_source_root_is_src():
    assert PythonParser().source_roots(iter_source_files(ROOT, (".py", ".pyi"))) == ("src",)
    assert PythonParser().source_roots(iter_source_files(TINY_ROOT, (".py",))) == ()


@pytest.mark.parametrize(
    "files, want",
    [
        (["src/pkg/__init__.py", "src/pkg/a.py"], ("src",)),
        (["lib/pkg/__init__.py"], ("lib",)),
        (["code/pkg/__init__.py"], ("code",)),  # any top-level non-package
        (["packages/foo/src/foo/__init__.py"], ("packages/foo/src",)),
        (["packages/foo/other/foo/__init__.py"], ()),  # nested: only src/lib
        (["tests/test_a.py", "tests/unit/__init__.py"], ()),  # holds files itself
        (["pkg/__init__.py", "pkg/src/sub/__init__.py"], ()),  # inside a package
        (["src/__init__.py", "src/sub/__init__.py"], ()),  # src is a package
        (["src/script.py"], ()),  # no packages under it
        (["setup.py", "pkg/__init__.py"], ()),  # flat layout
    ],
)
def test_source_roots(files, want):
    assert roots(*files) == want


@pytest.mark.parametrize(
    "path, module",
    [
        ("src/acme/__init__.py", "acme"),
        ("src/acme/core.py", "acme.core"),
        ("tests/test_core.py", "tests.test_core"),
        ("srcx/acme/core.py", "srcx.acme.core"),
    ],
)
def test_module_id_strips_the_source_root(path, module):
    assert PythonParser().module_id(path, ("src",)) == module


def test_symbol_ids_have_no_src_prefix(results):
    ids = {s.id for r in results for s in r.symbols}
    assert ids == {
        "acme",
        "acme.core",
        "acme.core.run",
        "acme.helpers",
        "acme.helpers.clean",
        "acme.helpers.shout",
        "acme.helpers.parse",
        "acme.fast",
        "acme.fast.speed",
        "tests.test_core",
        "tests.test_core.test_run",
    }


def test_imports_and_calls_resolve_across_files(edges):
    for edge in [
        ("acme.core.run", EdgeKind.CALLS, "acme.helpers.clean"),
        ("acme.core.run", EdgeKind.CALLS, "acme.helpers.shout"),  # relative import
        ("acme.core.run", EdgeKind.CALLS, "acme.helpers.parse"),
        ("acme.helpers.parse", EdgeKind.CALLS, "acme.helpers.clean"),
        ("acme.core", EdgeKind.IMPORTS, "acme.helpers.clean"),
        ("acme", EdgeKind.IMPORTS, "acme.core.run"),
        # through the re-export in acme/__init__.py
        ("tests.test_core.test_run", EdgeKind.CALLS, "acme.core.run"),
    ]:
        assert edge in edges


def test_overloads_share_one_symbol(results):
    (parse,) = [s for r in results for s in r.symbols if s.id.startswith("acme.helpers.parse")]
    assert parse.kind is NodeKind.FUNCTION
    assert parse.span == (14, 24)  # from the first @overload to the implementation's end
    assert parse.signature.startswith("def parse(value):")


def test_overloads_without_implementation_become_one_symbol(results):
    (speed,) = [s for r in results for s in r.symbols if s.id.startswith("acme.fast.speed")]
    assert speed.span == (3, 6)
    assert "x: int" in speed.signature and "x: float" in speed.signature


def test_get_context_includes_callees_from_other_files(tmp_path):
    repo = tmp_path / "repo"
    shutil.copytree(ROOT, repo)
    ctx = api.get_context(repo, "acme.core.run", budget=500)
    ids = {item.symbol for item in ctx.selection.items}
    assert {"acme.helpers.clean", "acme.helpers.shout", "acme.helpers.parse"} <= ids
    assert "src." not in ctx.text


def test_layout_change_discards_the_cache():
    parsers = _default_parsers()
    assert _fingerprint(parsers, ["src"]) != _fingerprint(parsers)
