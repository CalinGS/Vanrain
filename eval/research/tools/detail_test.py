"""Offline test: does variable detail beat whole-function and signature-only
context at the same token budget?

No LLM is involved. For real single-function commits in a git repo:

* target  = the function the commit changed (in the graph *before* the commit)
* needed  = repo functions/classes whose names appear in the lines the commit
            added, i.e. code the author had to know about to write the change.
            Found by plain name matching, not by Vanrain's resolver, so the
            answer key does not depend on the graph being tested.

Each strategy starts from the target (always shown in full) and walks the same
graph outward by hop distance. They differ only in the level of detail:

* full_only  every neighbour whole, or not at all (what most tools do)
* sig_only   every neighbour as a signature (Aider-style)
* mixed      distance 1 whole if it fits, else signature; further out signature
* mixed2     signatures for everything first, then upgrade distance-1 symbols
             to whole while budget remains

Score at each budget: recall = share of needed symbols the model can see
(signature or whole). "new" restricts to symbols the target did not already
use before the commit, which is the harder case.

Usage: PYTHONPATH=<vanrain>/src python detail_test.py REPO PKG_DIR [MAX_COMMITS]
   e.g. ... detail_test.py repos/requests src/requests 40
"""
from __future__ import annotations

import builtins
import io
import json
import keyword
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
from collections import deque
from pathlib import Path

from vanrain.graph import index
from vanrain.model import EdgeKind, NodeKind

BUDGETS = (500, 1000, 2000, 4000)
STRATEGIES = ("full_only", "sig_only", "mixed", "mixed2")
IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
SKIP_NAMES = set(keyword.kwlist) | set(dir(builtins)) | {"self", "cls"}
CODE_KINDS = (NodeKind.FUNCTION, NodeKind.METHOD, NodeKind.CLASS)


def git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True,
                          text=True, errors="replace", check=True).stdout


def candidate_commits(repo, pkg, limit):
    out = git(repo, "log", "--no-merges", "--format=%H", "--", pkg)
    picked = []
    for sha in out.split():
        files = [f for f in git(repo, "diff", "--name-only", f"{sha}^", sha, "--", pkg).split()
                 if f.endswith(".py")]
        if len(files) != 1:
            continue
        diff = git(repo, "diff", "-U0", f"{sha}^", sha, "--", files[0])
        added = [l[1:] for l in diff.splitlines() if l.startswith("+") and not l.startswith("+++")]
        if not 1 <= len(added) <= 40:
            continue
        old_lines = []
        for m in re.finditer(r"^@@ -(\d+)(?:,(\d+))? \+", diff, re.M):
            start, n = int(m.group(1)), int(m.group(2) or 1)
            old_lines += list(range(start, start + n)) if n else [start]
        picked.append((sha, files[0], added, old_lines))
        if len(picked) >= limit:
            break
    return picked


def extract(repo, sha, pkg, dest):
    """Write the package as it was at ``sha`` into dest, keeping its import path."""
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)
    data = subprocess.run(["git", "-C", str(repo), "archive", sha, pkg],
                          capture_output=True, check=True).stdout
    prefix = str(Path(pkg).parent)  # "src" or "."
    with tarfile.open(fileobj=io.BytesIO(data)) as tar:
        for m in tar.getmembers():
            name = m.name if prefix == "." else m.name[len(prefix) + 1:]
            if not name:
                continue
            m.name = name
            tar.extract(m, dest)


def bfs(graph, seed):
    """Symbols by hop distance from seed over all edge kinds, both directions."""
    dist = {seed: 0}
    order = []
    q = deque([seed])
    while q:
        cur = q.popleft()
        for e in graph.neighbours(cur, direction="both"):
            other = e.dst if e.src == cur else e.src
            if other in dist:
                continue
            dist[other] = dist[cur] + 1
            sym = graph.get(other)
            if sym and sym.kind in CODE_KINDS:
                order.append((dist[other], -e.confidence, other))
            q.append(other)
    order.sort()
    return [(d, sid) for d, _, sid in order]


def select(graph, seed, ranked, budget, strategy):
    target = graph.symbol(seed)
    used = target.tokens_full
    shown = {seed: "full"}
    if strategy == "mixed2":
        for d, sid in ranked:
            s = graph.symbol(sid)
            if used + s.tokens_sig <= budget:
                shown[sid] = "sig"; used += s.tokens_sig
        for d, sid in ranked:
            if d == 1 and shown.get(sid) == "sig":
                s = graph.symbol(sid)
                extra = s.tokens_full - s.tokens_sig
                if used + extra <= budget:
                    shown[sid] = "full"; used += extra
        return shown, used
    for d, sid in ranked:
        s = graph.symbol(sid)
        if strategy == "full_only":
            options = [("full", s.tokens_full)]
        elif strategy == "sig_only":
            options = [("sig", s.tokens_sig)]
        else:  # mixed
            options = [("full", s.tokens_full), ("sig", s.tokens_sig)] if d == 1 else [("sig", s.tokens_sig)]
        for level, cost in options:
            if used + cost <= budget:
                shown[sid] = level; used += cost
                break
    return shown, used


def main():
    repo, pkg = Path(sys.argv[1]), sys.argv[2]
    limit = int(sys.argv[3]) if len(sys.argv) > 3 else 40
    work = Path(tempfile.mkdtemp(prefix="vr-detail-"))
    cache = work / "cache.json"
    rows = []
    for sha, file, added, old_lines in candidate_commits(repo, pkg, limit * 4):
        if len(rows) >= limit:
            break
        root = work / "tree"
        extract(repo, f"{sha}^", pkg, root)
        graph = index(root, cache=cache).graph
        rel = file[len(str(Path(pkg).parent)) + 1:] if str(Path(pkg).parent) != "." else file
        in_file = [graph.symbol(s) for s in graph.symbols_in_file(rel)]
        hits = [s for s in in_file if s.kind in (NodeKind.FUNCTION, NodeKind.METHOD)
                and any(s.span[0] <= ln <= s.span[1] for ln in old_lines)]
        if not hits:
            continue
        target = min(hits, key=lambda s: s.span[1] - s.span[0])
        if any(not (target.span[0] <= ln <= target.span[1]) for ln in old_lines):
            continue  # commit also changed code outside this function
        by_name = {}
        for s in graph.symbols.values():
            if s.kind in CODE_KINDS:
                by_name.setdefault(s.id.rsplit(".", 1)[-1], set()).add(s.id)
        short = target.id.rsplit(".", 1)[-1]
        names = {n for line in added for n in IDENT.findall(line.split("#")[0])}
        needed = {n for n in names if n in by_name and n not in SKIP_NAMES and n != short}
        if not needed:
            continue
        src = (root / rel).read_text(errors="replace").splitlines()
        old_body = "\n".join(src[target.span[0] - 1:target.span[1]])
        new_needed = {n for n in needed if not re.search(rf"\b{n}\b", old_body)}
        file_tokens = sum(len(l) + 1 for l in src) // 4
        ranked = bfs(graph, target.id)
        dist_of = {sid: d for d, sid in ranked}
        row = {"sha": sha[:10], "target": target.id, "needed": sorted(needed),
               "new": sorted(new_needed), "target_tokens": target.tokens_full,
               "file_tokens": file_tokens,
               "needed_dist": {n: min((dist_of.get(i, 99) for i in by_name[n]), default=99)
                               for n in needed},
               "file_recall": sum(1 for n in needed if any(graph.symbol(i).file == rel for i in by_name[n])) / len(needed)}
        for b in BUDGETS:
            for st in STRATEGIES:
                shown, used = select(graph, target.id, ranked, b, st)
                vis = {sid.rsplit(".", 1)[-1] for sid in shown}
                row[f"{st}@{b}"] = {
                    "recall": sum(n in vis for n in needed) / len(needed),
                    "new_recall": (sum(n in vis for n in new_needed) / len(new_needed)) if new_needed else None,
                    "used": used, "n_full": sum(v == "full" for v in shown.values()) - 1,
                    "n_sig": sum(v == "sig" for v in shown.values())}
        rows.append(row)
    shutil.rmtree(work, ignore_errors=True)
    json.dump(rows, sys.stdout, indent=1)


if __name__ == "__main__":
    main()
