"""Milestone 6 benchmark harness (see eval/DESIGN.md).

Kept outside the installable package: nothing under eval/ ships with vanrain.

Stages, each a module:

- ``tasks``        pick and pin the task set (SWE-bench Lite subset)
- ``checkout``     a clean repo at the task's base commit, with no future history
- ``issue_seeds``  identifiers and paths mentioned in the issue text
- ``conditions``   the context each condition injects into the agent's prompt
- ``agents``       adapters that run one agent on one task (chosen later)
- ``metrics``      tokens, tool calls, file reads, tests, time; one record per run
"""
