"""Command line for the parts of the harness that cost nothing to run.

    python -m harness select DATA.jsonl --out tasks/pilot.json --revision REV
    python -m harness context REPO ISSUE.md --condition vanrain_sig_first --budget 2000
    python -m harness coverage DATA.jsonl tasks/pilot.json --workdir W --budget 2000

Run from the eval/ folder (or put it on PYTHONPATH). Agent runs are not wired
up yet: they wait for the agent decision (DESIGN.md, section 4).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from harness import conditions, tasks
from harness.metrics import gold_file_coverage


def _select(args: argparse.Namespace) -> int:
    pool = tasks.load_instances(args.data)
    picked = tasks.select_pilot(pool, size=args.size, seed=args.seed)
    tasks.write_task_file(picked, args.out, "princeton-nlp/SWE-bench_Lite",
                          args.revision, args.seed)
    for t in picked:
        print(t.instance_id)
    print(f"{len(picked)} tasks -> {args.out}", file=sys.stderr)
    return 0


def _context(args: argparse.Namespace) -> int:
    issue = Path(args.issue).read_text(encoding="utf-8")
    out = conditions.build(args.condition, args.repo, issue, args.budget)
    print(out.text or "(no context)")
    print(f"\n-- {out.condition}: {out.tokens} tokens, seeds {list(out.seeds)}, "
          f"index {out.index_seconds:.2f}s, select {out.select_seconds:.2f}s "
          f"{'; '.join(out.notes)}", file=sys.stderr)
    return 0


def _coverage(args: argparse.Namespace) -> int:
    from harness.checkout import checkout

    pool = {t.instance_id: t for t in tasks.load_instances(args.data)}
    ids = [i["instance_id"] for i in tasks.read_task_file(args.tasks)["instances"]]
    for iid in ids:
        task = pool[iid]
        repo = checkout(task, args.workdir)
        row = {"instance_id": iid}
        for name in args.conditions:
            inj = conditions.build(name, repo, task.problem_statement, args.budget)
            row[name] = {"tokens": inj.tokens,
                         "gold_files": gold_file_coverage(inj.text, task.patch)}
        print(json.dumps(row))
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m harness")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("select", help="pick and pin the pilot tasks")
    s.add_argument("data")
    s.add_argument("--out", default="tasks/pilot.json")
    s.add_argument("--size", type=int, default=25)
    s.add_argument("--seed", default="vanrain-pilot-1")
    s.add_argument("--revision", required=True, help="dataset revision (commit sha)")
    s.set_defaults(fn=_select)

    c = sub.add_parser("context", help="print one condition's context for an issue")
    c.add_argument("repo")
    c.add_argument("issue", help="file with the issue text")
    c.add_argument("--condition", default="vanrain_sig_first", choices=list(conditions.CONDITIONS))
    c.add_argument("--budget", type=int, default=2000)
    c.set_defaults(fn=_context)

    v = sub.add_parser("coverage", help="offline: share of gold-patch files each context names")
    v.add_argument("data")
    v.add_argument("tasks")
    v.add_argument("--workdir", default="work")
    v.add_argument("--budget", type=int, default=2000)
    v.add_argument("--conditions", nargs="+",
                   default=[c for c in conditions.PILOT_CONDITIONS if c != "none"])
    v.set_defaults(fn=_coverage)

    args = p.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
