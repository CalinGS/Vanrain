"""The task set: which SWE-bench instances we run, pinned so reruns match.

A task is one SWE-bench instance. We never ship the dataset; ``load_instances``
reads a local JSONL export of it (one instance per line, the fields below), and
``select_pilot`` picks the pilot subset deterministically from it.

Export once with the ``datasets`` library, pinning the dataset revision::

    from datasets import load_dataset
    ds = load_dataset("princeton-nlp/SWE-bench_Lite", split="test", revision=REV)
    ds.to_json("eval/data/swebench_lite.jsonl")

and record ``REV`` in ``eval/tasks/pilot.json`` (``write_task_file`` does it).
"""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import asdict, dataclass, field
from pathlib import Path

#: Repos with small codebases first; the pilot draws from these (DESIGN.md, section 1).
PILOT_REPOS = (
    "psf/requests",
    "pallets/flask",
    "mwaskom/seaborn",
    "pytest-dev/pytest",
    "pylint-dev/pylint",
    "pydata/xarray",
    "sphinx-doc/sphinx",
    "astropy/astropy",
)


@dataclass(frozen=True)
class Task:
    """What the harness needs from one SWE-bench instance."""

    instance_id: str
    repo: str  # "owner/name"
    base_commit: str
    problem_statement: str  # the issue text: the only thing the agent is told
    patch: str  # gold fix; never shown to the agent, used for coverage scoring
    test_patch: str  # tests that check the fix; applied only at evaluation
    fail_to_pass: tuple[str, ...] = ()
    pass_to_pass: tuple[str, ...] = ()
    version: str = ""
    extra: dict = field(default_factory=dict, compare=False)

    @classmethod
    def from_instance(cls, row: dict) -> Task:
        def tests(key: str) -> tuple[str, ...]:
            value = row.get(key) or []
            return tuple(json.loads(value) if isinstance(value, str) else value)

        return cls(
            instance_id=row["instance_id"],
            repo=row["repo"],
            base_commit=row["base_commit"],
            problem_statement=row["problem_statement"],
            patch=row.get("patch", ""),
            test_patch=row.get("test_patch", ""),
            fail_to_pass=tests("FAIL_TO_PASS"),
            pass_to_pass=tests("PASS_TO_PASS"),
            version=str(row.get("version", "")),
        )


def load_instances(path: str | Path) -> list[Task]:
    """Tasks from a JSONL export of the dataset."""
    with open(path, encoding="utf-8") as f:
        return [Task.from_instance(json.loads(line)) for line in f if line.strip()]


def _rank(instance_id: str, seed: str) -> str:
    """A stable pseudo-random order that does not depend on Python's hash seed."""
    return hashlib.sha256(f"{seed}:{instance_id}".encode()).hexdigest()


def select_pilot(
    tasks: Iterable[Task],
    size: int = 25,
    repos: Iterable[str] = PILOT_REPOS,
    per_repo_cap: int = 5,
    seed: str = "vanrain-pilot-1",
    exclude: Iterable[str] = (),
) -> list[Task]:
    """Pick ``size`` tasks from ``repos``, at most ``per_repo_cap`` per repo.

    Round-robin over repos (in the order given) so no single repo dominates,
    each repo's tasks in a seeded hash order. Same inputs, same pick.
    """
    repos = list(repos)
    skip = set(exclude)
    by_repo: dict[str, list[Task]] = defaultdict(list)
    for t in tasks:
        if t.repo in repos and t.instance_id not in skip:
            by_repo[t.repo].append(t)
    for repo in by_repo:
        by_repo[repo].sort(key=lambda t: _rank(t.instance_id, seed))

    picked: list[Task] = []
    taken = defaultdict(int)
    while len(picked) < size:
        progressed = False
        for repo in repos:
            if len(picked) >= size:
                break
            queue = by_repo.get(repo, [])
            if queue and taken[repo] < per_repo_cap:
                picked.append(queue.pop(0))
                taken[repo] += 1
                progressed = True
        if not progressed:
            break
    return picked


def write_task_file(
    tasks: Iterable[Task], path: str | Path, dataset: str, revision: str, seed: str
) -> None:
    """Pin the chosen ids (and where they came from) in a small JSON file."""
    data = {
        "dataset": dataset,
        "revision": revision,
        "seed": seed,
        "instances": [{"instance_id": t.instance_id, "repo": t.repo,
                       "base_commit": t.base_commit} for t in tasks],
    }
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def read_task_file(path: str | Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def task_dict(task: Task) -> dict:
    return asdict(task)
