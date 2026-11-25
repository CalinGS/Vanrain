"""The command-line interface, run against a copy of the fixture repo.

The CLI only parses arguments and prints what the Python API returns, so these
tests check the wiring: exit codes, where output goes, options reaching the
API, and that errors are readable.
"""

import ast
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from test_fixture import ROOT
from vanrain import cli
from vanrain.cli import main

GOLDEN = Path(__file__).parent / "golden"


@pytest.fixture
def repo(tmp_path):
    """A writable copy of the fixture repo, so the cache never lands in tests/."""
    dst = tmp_path / "repo"
    shutil.copytree(ROOT, dst)
    return dst


def run(capsys, *args):
    code = main([str(a) for a in args])
    out, err = capsys.readouterr()
    return code, out, err


# --- context --------------------------------------------------------------------


def test_context_matches_the_golden_render(repo, capsys):
    code, out, err = run(capsys, "context", "shop.checkout.checkout", "--budget", 250, "--root", repo)
    assert code == 0, err
    assert out == (GOLDEN / "checkout_250.md").read_text(encoding="utf-8")


def test_context_defaults_to_2000_tokens(repo, capsys):
    code, out, _ = run(capsys, "context", "Order.total", "--root", repo)
    assert code == 0
    assert "of 2000 tokens" in out
    assert out.startswith("# Context for shop.models.Order.total\n")


def test_context_takes_a_suffix_name(repo, capsys):
    code, out, _ = run(capsys, "context", "apply_discount", "--root", repo, "--budget", 300)
    assert code == 0
    assert out.startswith("# Context for shop.pricing.apply_discount\n")


def test_context_several_symbols(repo, capsys):
    code, out, _ = run(capsys, "context", "Order.add", "with_tax", "--root", repo)
    assert code == 0
    assert out.startswith("# Context for shop.models.Order.add, shop.pricing.with_tax\n")


def test_context_strategy_option(repo, capsys):
    code, out, _ = run(
        capsys, "context", "shop.checkout.checkout", "--root", repo, "--strategy", "signatures_only"
    )
    assert code == 0
    # only the seed is in full
    assert "(1 full, " in out


def test_context_unknown_strategy_is_a_usage_error(repo, capsys):
    code, _, err = run(capsys, "context", "Order", "--root", repo, "--strategy", "random")
    assert code == 2
    assert "signatures_first" in err


def test_context_unknown_symbol(repo, capsys):
    code, out, err = run(capsys, "context", "nope", "--root", repo)
    assert code == 1
    assert out == ""
    assert "no symbol matches 'nope'" in err
    assert "vanrain find" in err


def test_context_ambiguous_symbol_lists_candidates(repo, capsys):
    code, out, err = run(capsys, "context", "total", "--root", repo)
    assert code == 1
    assert out == ""
    assert "ambiguous" in err
    assert "shop.models.Order.total" in err
    assert "shop.models.DiscountedOrder.total" in err


def test_context_rejects_a_bad_budget(repo, capsys):
    code, _, err = run(capsys, "context", "Order", "--root", repo, "--budget", 0)
    assert code == 2
    assert "at least 1" in err


def test_context_uses_and_writes_the_cache(repo, capsys):
    run(capsys, "context", "Order", "--root", repo)
    assert (repo / ".vanrain" / "cache.json").is_file()


def test_no_cache_writes_nothing(repo, capsys):
    code, _, _ = run(capsys, "context", "Order", "--root", repo, "--no-cache")
    assert code == 0
    assert not (repo / ".vanrain").exists()


# --- index ----------------------------------------------------------------------


def test_index_builds_then_reuses_the_cache(repo, capsys):
    code, out, _ = run(capsys, "index", "--root", repo)
    assert code == 0
    assert (repo / ".vanrain" / "cache.json").is_file()
    assert "5 files" in out and "5 parsed" in out
    assert "23 symbols" in out and "42 edges" in out

    code, out, _ = run(capsys, "index", "--root", repo)
    assert code == 0
    assert "0 parsed" in out and "5 reused" in out


def test_index_no_cache(repo, capsys):
    code, out, _ = run(capsys, "index", "--root", repo, "--no-cache")
    assert code == 0
    assert not (repo / ".vanrain").exists()
    assert "cache off" in out


def test_root_defaults_to_the_current_directory(repo, capsys, monkeypatch):
    monkeypatch.chdir(repo)
    code, out, _ = run(capsys, "index")
    assert code == 0
    assert (repo / ".vanrain" / "cache.json").is_file()


def test_missing_root(tmp_path, capsys):
    code, out, err = run(capsys, "index", "--root", tmp_path / "nowhere")
    assert code == 2
    assert "not a directory" in err


# --- find -----------------------------------------------------------------------


def test_find_lists_matches_with_location(repo, capsys):
    code, out, _ = run(capsys, "find", "total", "--root", repo)
    assert code == 0
    lines = out.splitlines()
    assert any(
        "shop.models.DiscountedOrder.total" in l and "method" in l and "shop/models.py:" in l
        for l in lines
    )
    assert any("shop.models.Order.total" in l for l in lines)


def test_find_one_match_shows_signature_and_neighbours(repo, capsys):
    code, out, _ = run(capsys, "find", "apply_discount", "--root", repo)
    assert code == 0
    assert "shop.pricing.apply_discount" in out
    assert "def apply_discount" in out
    assert "<- calls" in out  # someone calls it
    assert "shop.models.DiscountedOrder.total" in out


def test_find_no_match(repo, capsys):
    code, out, err = run(capsys, "find", "nope", "--root", repo)
    assert code == 1
    assert "no symbol matches 'nope'" in err


# --- stats ----------------------------------------------------------------------


def test_stats(repo, capsys):
    code, out, _ = run(capsys, "stats", "--root", repo)
    assert code == 0
    assert "symbols" in out and "23" in out
    assert "edges" in out and "42" in out
    assert "calls" in out and "contains" in out
    assert "most-called" in out


# --- plumbing -------------------------------------------------------------------


def test_no_command_prints_help(capsys):
    code, out, _ = run(capsys)
    assert code == 2
    assert "context" in out and "index" in out


def test_version(capsys):
    code, out, _ = run(capsys, "--version")
    assert code == 0
    assert "vanrain 0.0.1" in out


def test_python_dash_m(repo):
    proc = subprocess.run(
        [sys.executable, "-m", "vanrain", "find", "Order", "--root", str(repo), "--no-cache"],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr
    assert "shop.models.Order" in proc.stdout


def test_cli_only_talks_to_the_public_api():
    """No logic in the CLI: it imports nothing but ``vanrain.api`` (and the version)."""
    tree = ast.parse(Path(cli.__file__).read_text(encoding="utf-8"))
    modules = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("vanrain"):
            modules.add(node.module)
        elif isinstance(node, ast.Import):
            modules.update(a.name for a in node.names if a.name.startswith("vanrain"))
    assert modules <= {"vanrain", "vanrain.api"}
