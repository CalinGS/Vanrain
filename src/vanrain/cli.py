"""Command-line interface. Parses arguments, calls ``vanrain.api``, prints.

    vanrain index                         build or refresh the cache in .vanrain/
    vanrain context SYMBOL... [--budget N] [--strategy S]
    vanrain find NAME                     symbols a name could mean
    vanrain stats                         size and shape of the graph

Every command takes ``--root DIR`` (default: the current directory) and
``--no-cache``. Exit codes: 0 ok, 1 a symbol was not found or is ambiguous,
2 a usage error (bad option, missing directory).
"""

from __future__ import annotations

import argparse
import sys

from vanrain import __version__, api

_SEED_HINT = "Use a longer dotted name or a full id; `vanrain find NAME` lists candidates."


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    try:
        args = parser.parse_args(sys.argv[1:] if argv is None else argv)
    except SystemExit as e:  # --help, --version and usage errors
        return e.code if isinstance(e.code, int) else 2
    if args.command is None:
        parser.print_help()
        return 2
    try:
        return args.handler(args)
    except NotADirectoryError as e:
        return _fail(str(e), 2)
    except api.SeedError as e:
        lines = [str(e)] if not e.candidates else [f"{e.name!r} is ambiguous; it matches:"]
        lines += [f"  {c}" for c in e.candidates]
        return _fail("\n".join(lines + [_SEED_HINT]), 1)


def _index(args) -> int:
    run = api.open_repo(args.root, cache=not args.no_cache)
    st = api.repo_stats(run)
    cache = f"cache {st.cache}" if st.cache else "cache off"
    print(
        f"{st.files} files ({st.parsed} parsed, {st.reused} reused), "
        f"{st.symbols} symbols, {st.edges} edges in {st.seconds:.2f}s; {cache}"
    )
    return 0


def _context(args) -> int:
    ctx = api.get_context(
        args.root, args.symbols, budget=args.budget, strategy=args.strategy, cache=not args.no_cache
    )
    sys.stdout.write(ctx.text)
    return 0


def _find(args) -> int:
    graph = api.open_repo(args.root, cache=not args.no_cache).graph
    found = api.find_symbols(graph, args.name)
    if not found:
        raise api.SeedError(args.name)
    width = max(len(s.id) for s in found)
    for s in found:
        print(f"{s.id:<{width}}  {s.kind.value:<8}  {s.file}:{s.span[0]}-{s.span[1]}")
    if len(found) == 1:
        s = found[0]
        print(f"\n{s.signature}")
        print(f"tokens: {s.tokens_full} full, {s.tokens_sig} signature")
        for link in api.links(graph, s.id):
            arrow = "->" if link.direction == "out" else "<-"
            print(f"  {arrow} {link.kind.value:<10} {link.other}  ({link.confidence:.2f})")
    return 0


def _stats(args) -> int:
    st = api.repo_stats(api.open_repo(args.root, cache=not args.no_cache), top=args.top)
    non_contains = st.edges - st.edges_by_kind.get(api.EdgeKind.CONTAINS, 0)
    rows = [
        ("files", f"{st.files}  ({st.parsed} parsed, {st.reused} reused, {st.seconds:.2f}s)"),
        ("symbols", f"{st.symbols}  {_counts(st.symbols_by_kind)}"),
        ("edges", f"{st.edges}  {_counts(st.edges_by_kind)}"),
        ("heuristic", f"{st.heuristic_edges} of {non_contains} non-contains edges have confidence < 1"),
        ("cache", str(st.cache) if st.cache else "off"),
    ]
    for label, value in rows:
        print(f"{label:<10} {value}")
    for title, pairs in (("most-called", st.most_called), ("largest (tokens)", st.largest)):
        print(f"\n{title}:")
        for sid, n in pairs:
            print(f"  {n:6d}  {sid}")
    return 0


def _counts(counter) -> str:
    return ", ".join(f"{k.value} {n}" for k, n in sorted(counter.items(), key=lambda p: -p[1]))


def _fail(message: str, code: int) -> int:
    print(f"vanrain: error: {message}", file=sys.stderr)
    return code


def _positive(text: str) -> int:
    try:
        n = int(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"not a number: {text!r}") from None
    if n < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return n


def _parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--root", default=".", help="repository to read (default: current directory)")
    common.add_argument(
        "--no-cache", action="store_true", help="index from scratch and write nothing to .vanrain/"
    )

    parser = argparse.ArgumentParser(
        prog="vanrain",
        description="Budgeted, graph-based context selection for coding agents.",
    )
    parser.add_argument("-V", "--version", action="version", version=f"vanrain {__version__}")
    sub = parser.add_subparsers(dest="command", metavar="COMMAND")

    p = sub.add_parser("index", parents=[common], help="build or refresh the graph cache")
    p.set_defaults(handler=_index)

    p = sub.add_parser(
        "context",
        parents=[common],
        help="print the code connected to symbols, within a token budget",
        description="Print markdown context for SYMBOL: a full id (shop.models.Order.total) "
        "or its trailing dotted parts (Order.total, total).",
    )
    p.add_argument("symbols", nargs="+", metavar="SYMBOL")
    p.add_argument(
        "--budget", type=_positive, default=api.DEFAULT_BUDGET, help="token budget (default: %(default)s)"
    )
    p.add_argument(
        "--strategy",
        choices=api.STRATEGIES,
        default=api.DEFAULT_STRATEGY.value,
        help="how to spend the budget (default: %(default)s)",
    )
    p.set_defaults(handler=_context)

    p = sub.add_parser("find", parents=[common], help="list the symbols a name could mean")
    p.add_argument("name")
    p.set_defaults(handler=_find)

    p = sub.add_parser("stats", parents=[common], help="size and shape of the graph")
    p.add_argument("--top", type=_positive, default=10, help="rows in each top list (default: 10)")
    p.set_defaults(handler=_stats)
    return parser


if __name__ == "__main__":
    raise SystemExit(main())
