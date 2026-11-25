# eval

Benchmark: run the same agent on the same SWE-bench tasks with and without
Vanrain (and with Aider's repo map), and compare tokens per task, tool calls,
file reads, tests passed and wall time (plan, section 8).

This folder is kept out of the published package.

- `DESIGN.md`: the milestone 6 design (tasks, conditions, metrics, agent options, cost).
- `harness/`: the harness (`python -m harness --help`, run from this folder).
- `tests/`: offline tests, run with `pytest eval/tests` from the repo root.

Optional dependencies, installed only when needed (see `requirements.txt`).
