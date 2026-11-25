"""Smoke test for Vanrain milestone 2 on any real Python repo.

Usage (from the Vanrain repo root, with the package installed or PYTHONPATH=src):
    python smoke_graph.py PATH/TO/REPO [SYMBOL_ID ...]

Prints parse/resolve time, symbol and edge counts, how many references were
resolved, the most-called symbols, and the 1-hop neighbours of each SYMBOL_ID.
"""
from __future__ import annotations

import sys
import time
from collections import Counter
from pathlib import Path

from vanrain.parsers.base import parse_repo
from vanrain.resolver import resolve


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    root = Path(sys.argv[1])
    t0 = time.perf_counter()
    results = parse_repo(root)
    t1 = time.perf_counter()
    edges = resolve(results)
    t2 = time.perf_counter()

    symbols = {s.id: s for r in results for s in r.symbols}
    refs = [ref for r in results for ref in r.references]
    failed = [r.file for r in results if len(r.symbols) <= 1 and r.references == ()]
    kinds = Counter(e.kind.value for e in edges)
    non_contains = [e for e in edges if e.kind.value != "contains"]
    low_conf = sum(1 for e in non_contains if e.confidence < 1.0)

    print(f"repo            {root}")
    print(f"files           {len(results)}  (parse {t1 - t0:.2f}s, resolve {t2 - t1:.2f}s)")
    print(f"symbols         {len(symbols)}  {dict(Counter(s.kind.value for s in symbols.values()))}")
    print(f"edges           {len(edges)}  {dict(kinds)}")
    print(f"references      {len(refs)}; non-CONTAINS edges {len(non_contains)} "
          f"(~{len(non_contains) / max(len(refs), 1):.0%} of references became edges; "
          f"{low_conf} heuristic, confidence < 1)")
    print(f"files w/o refs  {len(failed)} (empty or unparsable)")

    called = Counter(e.dst for e in edges if e.kind.value == "calls")
    print("\nmost-called symbols:")
    for sid, n in called.most_common(10):
        print(f"  {n:5d}  {sid}")

    for target in sys.argv[2:]:
        if target not in symbols:
            close = [s for s in symbols if s.endswith(target)][:5]
            print(f"\n{target}: not found. Did you mean: {close}")
            continue
        s = symbols[target]
        print(f"\n{target}  [{s.kind.value}] {s.file}:{s.span[0]}-{s.span[1]}")
        print(f"  signature: {s.signature}")
        print(f"  tokens: full {s.tokens_full}, signature {s.tokens_sig}")
        for e in edges:
            if e.src == target and e.kind.value != "contains":
                print(f"  -> {e.kind.value:10s} {e.dst}  ({e.confidence:.2f})")
            elif e.dst == target and e.kind.value != "contains":
                print(f"  <- {e.kind.value:10s} {e.src}  ({e.confidence:.2f})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
