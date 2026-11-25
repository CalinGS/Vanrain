"""Learn per-edge-kind ranking weights from real commits.

Step 1 (build):  python weight_search.py build OUT.pkl REPO PKG [MAX] [REPO PKG [MAX] ...]
    Builds the same tasks as detail_test.py and saves each task's graph,
    target and needed names.
Step 2 (search): python weight_search.py search OUT.pkl TRAIN_REPOS TEST_REPOS [TRIALS]
    e.g. ... search tasks.pkl click,flask httpx,requests,requests_old 3000
    Random-searches edge costs on the train repos (maximising signature
    recall at 2,000 tokens) and reports train and held-out test scores for
    plain BFS (all costs 1) and the best weights found.

Ranking: Dijkstra from the target. Each edge has a cost per (kind, direction),
divided by its confidence. Selection: signatures first, nearest first, until
the budget is spent (the milestone-4 default).
"""
from __future__ import annotations

import heapq
import pickle
import random
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import detail_test as dt  # noqa: E402
from vanrain.graph import index  # noqa: E402
from vanrain.model import EdgeKind  # noqa: E402

KINDS = [k for k in EdgeKind]
KEYS = [(k.value, d) for k in KINDS for d in ("out", "in")]
BUDGETS = (1000, 2000, 4000)


def build(out, specs):
    import shutil, tempfile
    tasks = []
    for repo, pkg, limit in specs:
        name = Path(repo).name + ("_old" if "/" not in pkg and Path(repo).name == "requests" else "")
        work = Path(tempfile.mkdtemp(prefix="vr-w-"))
        n = 0
        for sha, file, added, old_lines in dt.candidate_commits(Path(repo), pkg, limit * 4):
            if n >= limit:
                break
            root = work / "tree"
            dt.extract(Path(repo), f"{sha}^", pkg, root)
            g = index(root, cache=work / "c.json").graph
            parent = str(Path(pkg).parent)
            rel = file if parent == "." else file[len(parent) + 1:]
            in_file = [g.symbol(s) for s in g.symbols_in_file(rel)]
            hits = [s for s in in_file if s.kind.value in ("function", "method")
                    and any(s.span[0] <= ln <= s.span[1] for ln in old_lines)]
            if not hits:
                continue
            t = min(hits, key=lambda s: s.span[1] - s.span[0])
            if any(not (t.span[0] <= ln <= t.span[1]) for ln in old_lines):
                continue
            names = {x for line in added for x in dt.IDENT.findall(line.split("#")[0])}
            code = [s for s in g.symbols.values() if s.kind in dt.CODE_KINDS]
            short_names = {s.id.rsplit(".", 1)[-1] for s in code}
            short = t.id.rsplit(".", 1)[-1]
            needed = {x for x in names if x in short_names and x not in dt.SKIP_NAMES and x != short}
            if not needed:
                continue
            # compact graph: adjacency with (other, kind, dir, conf); per-symbol sig tokens and short name
            adj = {}
            for e in g.edges():
                adj.setdefault(e.src, []).append((e.dst, e.kind.value, "out", e.confidence))
                adj.setdefault(e.dst, []).append((e.src, e.kind.value, "in", e.confidence))
            info = {s.id: (s.id.rsplit(".", 1)[-1], s.tokens_sig, s.kind in dt.CODE_KINDS)
                    for s in g.symbols.values()}
            tasks.append({"repo": name, "sha": sha[:10], "target": t.id,
                          "target_tokens": t.tokens_full, "needed": needed,
                          "adj": adj, "info": info})
            n += 1
        shutil.rmtree(work, ignore_errors=True)
        print(name, n, file=sys.stderr)
    pickle.dump(tasks, open(out, "wb"))


def rank(task, w):
    dist = {task["target"]: 0.0}
    heap = [(0.0, task["target"])]
    order = []
    done = set()
    while heap:
        d, cur = heapq.heappop(heap)
        if cur in done:
            continue
        done.add(cur)
        if cur != task["target"] and task["info"][cur][2]:
            order.append(cur)
        for other, kind, direction, conf in task["adj"].get(cur, ()):
            c = w[(kind, direction)]
            if c >= 50:  # edge kind switched off
                continue
            nd = d + c / max(conf, 0.05)
            if nd < dist.get(other, 1e18):
                dist[other] = nd
                heapq.heappush(heap, (nd, other))
    return order


def score(task, w, budget):
    used = task["target_tokens"]
    seen = set()
    for sid in rank(task, w):
        name, sig, _ = task["info"][sid]
        if used + sig <= budget:
            used += sig
            seen.add(name)
    return sum(n in seen for n in task["needed"]) / len(task["needed"])


def mean(tasks, w, budget=2000):
    return sum(score(t, w, budget) for t in tasks) / len(tasks)


def search(pkl, train_names, test_names, trials):
    tasks = pickle.load(open(pkl, "rb"))
    train = [t for t in tasks if t["repo"] in train_names]
    test = [t for t in tasks if t["repo"] in test_names]
    bfs = {k: 1.0 for k in KEYS}
    rng = random.Random(0)
    grid = [0.5, 1, 1.5, 2, 3, 5, 8, 50]
    best, best_s = bfs, mean(train, bfs)
    for i in range(trials):
        if i < trials // 2:
            w = {k: rng.choice(grid) for k in KEYS}
        else:  # local moves around the best
            w = dict(best)
            for k in rng.sample(KEYS, 2):
                w[k] = rng.choice(grid)
        s = mean(train, w)
        if s > best_s:
            best, best_s = w, s
    print(f"train {sorted(train_names)}: {len(train)} tasks; test {sorted(test_names)}: {len(test)} tasks")
    print("budget  set    BFS    learned")
    for b in BUDGETS:
        for label, ts in (("train", train), ("test", test)):
            print(f"{b:6d}  {label:5s}  {mean(ts, bfs, b):.3f}  {mean(ts, best, b):.3f}")
    print("learned costs (lower = followed first; 50 = ignored):")
    for k in KEYS:
        print(f"  {k[0]:10s} {k[1]:3s} {best[k]}")


if __name__ == "__main__":
    if sys.argv[1] == "build":
        a = sys.argv[3:]
        specs = []
        while a:
            repo, pkg = a[0], a[1]
            lim = int(a[2]) if len(a) > 2 and a[2].isdigit() else 40
            specs.append((repo, pkg, lim))
            a = a[3:] if len(a) > 2 and a[2].isdigit() else a[2:]
        build(sys.argv[2], specs)
    else:
        search(sys.argv[2], set(sys.argv[3].split(",")), set(sys.argv[4].split(",")),
               int(sys.argv[5]) if len(sys.argv) > 5 else 2000)
